# tasks.py - v1.5
"""Background job manager for audio transcription."""
from __future__ import annotations

import json
import os
import queue
import re
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..loggers import audiototext_logger, logger
from .google_stt import stt_google_from_file, stt_google_from_gcs
from .gcs import A2T_GCS_BUCKET, upload_to_gcs

RESULTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "results"))
UPLOADS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "uploads"))
JOBS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "jobs"))
os.makedirs(RESULTS_DIR, exist_ok=True)
os.makedirs(UPLOADS_DIR, exist_ok=True)
os.makedirs(JOBS_DIR, exist_ok=True)

from google.cloud import storage  # NEW
A2T_GCS_BUCKET = os.getenv("A2T_GCS_BUCKET")  # NEW

def _upload_to_gcs_depr(local_path: str, prefix: str = "audiototext/") -> str:  # NEW
    if not A2T_GCS_BUCKET:
        raise RuntimeError("Brak env A2T_GCS_BUCKET – ustaw nazwę bucketu GCS.")
    client = storage.Client()
    ext = os.path.splitext(local_path)[1] or ".wav"
    name = f"{prefix}{uuid.uuid4().hex}{ext}"
    blob = client.bucket(A2T_GCS_BUCKET).blob(name)
    blob.upload_from_filename(local_path)
    return f"gs://{A2T_GCS_BUCKET}/{name}"


@dataclass
class Job:
    job_id: str
    file_path: Optional[str] = None
    gcs_uri: Optional[str] = None
    youtube_url: Optional[str] = None
    params: Dict[str, Any] = field(default_factory=dict)
    status: str = "queued"
    result_path: Optional[str] = None
    error: Optional[str] = None


def _job_state_path(job_id: str) -> str:
    return os.path.join(JOBS_DIR, f"{job_id}.json")


def _job_to_state(job: Job) -> Dict[str, Any]:
    return {
        "job_id": job.job_id,
        "file_path": job.file_path,
        "gcs_uri": job.gcs_uri,
        "params": job.params,
        "status": job.status,
        "result_path": job.result_path,
        "error": job.error,
        "updated_at": int(time.time()),
    }


def _atomic_write_json(path: str, payload: Dict[str, Any]) -> None:
    fd, tmp = tempfile.mkstemp(prefix="job_", suffix=".json", dir=JOBS_DIR)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def _download_youtube_audio(url: str, out_dir: str) -> str:
    """Download best audio from YouTube via yt-dlp."""
    try:
        import yt_dlp
        from yt_dlp.utils import DownloadError
    except Exception as exc:  # pragma: no cover - dependency guard
        raise RuntimeError("Brak pakietu yt-dlp. Zainstaluj: pip install -U yt-dlp") from exc

    os.makedirs(out_dir, exist_ok=True)

    default_ua = os.getenv(
        "YTDLP_USER_AGENT",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    )
    accept_lang = os.getenv("YTDLP_ACCEPT_LANGUAGE", "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7")

    ydl_opts = {
        "format": "bestaudio/best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "outtmpl": os.path.join(out_dir, "%(id)s.%(ext)s"),
        "paths": {"home": out_dir},
        "overwrites": True,
        "concurrent_fragment_downloads": 1,
        "geo_bypass": True,
        "extractor_args": {"youtube": {"player_client": ["android"]}},
        "http_headers": {"User-Agent": default_ua, "Accept-Language": accept_lang},
    }

    cookies_file = os.getenv("YTDLP_COOKIES_FILE")
    if cookies_file and os.path.isfile(cookies_file):
        ydl_opts["cookiefile"] = cookies_file
    else:
        spec = os.getenv("YTDLP_COOKIES_FROM_BROWSER", "").strip()
        if spec:
            parts = spec.split(":", 1)
            browser = parts[0]
            profile = parts[1] if len(parts) > 1 else None
            ydl_opts["cookiesfrombrowser"] = (browser, profile, None, True)

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            return ydl.prepare_filename(info)
    except DownloadError as exc:
        hint = (
            "YouTube odrzucił pobieranie bez zalogowania. Skonfiguruj cookies: "
            "ustaw YTDLP_COOKIES_FILE lub YTDLP_COOKIES_FROM_BROWSER i spróbuj ponownie."
        )
        audiototext_logger.error("❌ Błąd pobierania YouTube: %s", hint)
        raise RuntimeError(f"yt-dlp DownloadError: {exc}. {hint}") from exc


def save_job_state(job: Job) -> None:
    _atomic_write_json(_job_state_path(job.job_id), _job_to_state(job))


def load_job_state(job_id: str) -> Optional[Dict[str, Any]]:
    path = _job_state_path(job_id)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return None


class JobManager:
    def __init__(self):
        self.q: "queue.Queue[Job]" = queue.Queue()
        self.jobs: Dict[str, Job] = {}
        self._lock = threading.RLock()
        self._started = False
        self._worker: Optional[threading.Thread] = None

    def start(self):
        if not self._started:
            self._worker = threading.Thread(target=self._run, daemon=True, name="stt-worker")
            self._worker.start()
            self._started = True

    def enqueue(
        self,
        file_path: Optional[str],
        params: Dict[str, Any],
        gcs_uri: Optional[str] = None,
        youtube_url: Optional[str] = None,
    ) -> str:
        job_id = uuid.uuid4().hex
        job = Job(job_id=job_id, file_path=file_path, gcs_uri=gcs_uri, youtube_url=youtube_url, params=params)
        with self._lock:
            self.jobs[job_id] = job
        self.q.put(job)
        save_job_state(job)
        logger(
            "Job queued",
            level="info",
            job_id=job_id,
            file_path=file_path,
            gcs_uri=gcs_uri,
            youtube_url=youtube_url,
        )
        self.start()
        return job_id

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self.jobs.get(job_id)

    def _run(self):
        gcs_bucket = os.getenv("A2T_GCS_BUCKET")
        while True:
            job: Job = self.q.get()
            try:
                job.status = "processing"
                save_job_state(job)
                logger("Job processing", level="info", job_id=job.job_id)

                src = job.file_path or job.gcs_uri or job.youtube_url
                if job.youtube_url and not job.file_path and not job.gcs_uri:
                    try:
                        logger(
                            "Downloading YouTube audio",
                            level="info",
                            job_id=job.job_id,
                            youtube_url=job.youtube_url,
                        )
                        if not re.match(r"^https?://(www\.)?(youtube\.com|youtu\.be)/", job.youtube_url, re.I):
                            raise RuntimeError("URL nie wygląda na YouTube")
                        dl_path = _download_youtube_audio(job.youtube_url, UPLOADS_DIR)
                        if not os.path.isfile(dl_path):
                            raise RuntimeError("Pobieranie YouTube nie zwróciło pliku")
                        job.file_path = dl_path
                        save_job_state(job)
                        src = job.file_path
                        job.gcs_uri = upload_to_gcs(job.file_path, gcs_bucket)
                        save_job_state(job)

                        logger(
                            "YouTube audio downloaded",
                            level="info",
                            job_id=job.job_id,
                            file_path=dl_path,
                        )

                    except Exception as exc:
                        logger(
                            "Download YouTube failed",
                            level="error",
                            job_id=job.job_id,
                            error=str(exc),
                        )
                        raise RuntimeError(f"Download YouTube failed: {type(exc).__name__}: {exc}")

                language_code = job.params.get("language_code", "pl-PL")
                diarization_speaker_count = job.params.get("diarization_speaker_count")
                model = job.params.get("model")
                use_enhanced = job.params.get("use_enhanced")
                additional_hints = job.params.get("additional_hints")
                enable_word_time_offsets = bool(job.params.get("enable_word_time_offsets", False))
                if diarization_speaker_count:
                    enable_word_time_offsets = True

                # NEW: jeżeli mamy lokalny plik i brak GCS – wrzuć do GCS
                if job.file_path and not job.gcs_uri:
                    job.gcs_uri = upload_to_gcs(job.file_path, gcs_bucket)
                    save_job_state(job)
                    
                if job.gcs_uri:
                    result = stt_google_from_gcs(
                        gcs_uri=job.gcs_uri,
                        language_code=language_code,
                        additional_hints=additional_hints,
                        diarization_speaker_count=diarization_speaker_count,
                        enable_word_time_offsets=enable_word_time_offsets,
                        use_enhanced=use_enhanced,
                        model=model,
                    )
                else:
                    result = stt_google_from_file(
                        file_path=job.file_path,
                        language_code=language_code,
                        additional_hints=additional_hints,
                        diarization_speaker_count=diarization_speaker_count,
                        enable_word_time_offsets=enable_word_time_offsets,
                        use_enhanced=use_enhanced,
                        model=model,
                    )

                if not result or not result.get("transcript"):
                    raise RuntimeError(
                        "Empty result from Google STT. Possible causes: long audio in sync mode, unsupported codec, silence, or wrong language_code."
                    )

                out_name = f"transcription_{job.job_id}.json"
                out_path = os.path.join(RESULTS_DIR, out_name)
                payload = {
                    "job_id": job.job_id,
                    "source_file": job.file_path or job.gcs_uri,
                    "source_url": job.youtube_url or None,
                    "created_at": int(time.time()),
                    "params": {
                        "language_code": language_code,
                        "diarization_speaker_count": diarization_speaker_count,
                        "enable_word_time_offsets": enable_word_time_offsets,
                        "model": model,
                        "use_enhanced": use_enhanced,
                    },
                    "result": result,
                }
                with open(out_path, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle, ensure_ascii=False, indent=2)

                job.result_path = out_path
                job.status = "done"
                save_job_state(job)
                logger("Job done", level="info", job_id=job.job_id, result_path=out_path)

            except Exception as exc:  # pragma: no cover - worker resilience
                job.status = "error"
                job.error = str(exc)
                save_job_state(job)
                audiototext_logger.error("Job failed: job_id=%s, error=%s", job.job_id, exc)
            finally:
                self.q.task_done()


_manager: Optional[JobManager] = None


def get_manager() -> JobManager:
    global _manager
    if _manager is None:
        _manager = JobManager()
        _manager.start()
    return _manager

__all__ = [
    "Job",
    "JobManager",
    "get_manager",
    "RESULTS_DIR",
    "UPLOADS_DIR",
    "JOBS_DIR",
    "load_job_state",
]
