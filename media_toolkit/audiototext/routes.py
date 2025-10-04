# routes.py - v1.5
"""Routes for audio transcription utilities."""
from __future__ import annotations

import json
import os

from flask import Blueprint, current_app, jsonify, render_template, request, send_file, url_for
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge
from werkzeug.utils import secure_filename

from ..auth import login_required
from ..loggers import audiototext_routes_logger
from .gcs import gcs_selftest
from .service import TranscriptionService
from .tasks import RESULTS_DIR, UPLOADS_DIR, get_manager, load_job_state

manager = get_manager()
_service = TranscriptionService(default_language="pl-PL")
audiototext_bp = Blueprint("audiototext", __name__, url_prefix="/audiototext")


@audiototext_bp.route("/", methods=["GET"])
@login_required(role=["admin", "redakcja", "moderator", "tester", "fox"])
def upload_form():
    return render_template("audiototext/upload.html")


@audiototext_bp.route("/transcribe", methods=["POST"])
@login_required(role=["admin", "redakcja", "moderator", "tester", "fox"])
def transcribe_audio():
    """Start asynchronous transcription for a local file or GCS URI."""
    try:
        payload = request.get_json(force=True, silent=False)
    except Exception as exc:  # pragma: no cover - defensive
        audiototext_routes_logger.error("❌ Błędny JSON: %s", exc)
        return jsonify({"ok": False, "error": "Invalid JSON"}), 400

    try:
        language_code = payload.get("language_code") or "pl-PL"
        diarization_speaker_count = payload.get("diarization_speaker_count")
        model = payload.get("model")
        use_enhanced = payload.get("use_enhanced")
        additional_hints = payload.get("additional_hints")
        enable_word_time_offsets = bool(payload.get("enable_word_time_offsets", False))

        if "file_path" in payload:
            result = _service.transcribe_local_file(
                file_path=payload["file_path"],
                language_code=language_code,
                diarization_speaker_count=diarization_speaker_count,
                model=model,
                use_enhanced=use_enhanced,
                additional_hints=additional_hints,
                enable_word_time_offsets=enable_word_time_offsets,
            )
        elif "gcs_uri" in payload:
            result = _service.transcribe_gcs(
                gcs_uri=payload["gcs_uri"],
                language_code=language_code,
                diarization_speaker_count=diarization_speaker_count,
                model=model,
                use_enhanced=use_enhanced,
                additional_hints=additional_hints,
                enable_word_time_offsets=enable_word_time_offsets,
            )
        else:
            return jsonify({"ok": False, "error": "Provide 'file_path' or 'gcs_uri'"}), 400

        return jsonify({"ok": True, "result": result}), 200

    except FileNotFoundError as exc:
        audiototext_routes_logger.error("❌ Plik nie znaleziony: %s", exc)
        return jsonify({"ok": False, "error": str(exc)}), 404
    except Exception as exc:  # pragma: no cover - defensive
        audiototext_routes_logger.error("❌ Błąd transkrypcji: %s", exc)
        return jsonify({"ok": False, "error": "Transcription failed"}), 500


@audiototext_bp.route("/youtube/start", methods=["POST"])
@login_required(role=["admin", "redakcja", "moderator", "tester", "fox"])
def youtube_start():
    audiototext_routes_logger.info("START youtube_start()")
    try:
        data = request.get_json(silent=True) or request.form
        url = (data.get("youtube_url") or "").strip()
        audiototext_routes_logger.info("🔗 youtube_url ==> %s", url)

        if not url:
            audiototext_routes_logger.error("❌ Error: brak parametru youtube_url")
            return jsonify({"ok": False, "error": "Brak parametru youtube_url"}), 400

        language_code = (data.get("language_code") or "pl-PL").strip()

        diarization_speaker_count = data.get("diarization_speaker_count")
        try:
            diarization_speaker_count = (
                int(diarization_speaker_count)
                if diarization_speaker_count not in (None, "", "0")
                else None
            )
        except Exception:  # pragma: no cover - fallback
            diarization_speaker_count = None

        enable_word_time_offsets = str(data.get("enable_word_time_offsets")).lower() in (
            "1",
            "true",
            "yes",
            "on",
        )

        params = {
            "language_code": language_code,
            "diarization_speaker_count": diarization_speaker_count,
            "enable_word_time_offsets": enable_word_time_offsets,
        }
        manager = get_manager()
        job_id = manager.enqueue(file_path=None, params=params, gcs_uri=None, youtube_url=url)

        return jsonify(
            {
                "ok": True,
                "job_id": job_id,
                "status_url": url_for("audiototext.job_status", job_id=job_id),
            }
        )
    except Exception as exc:  # pragma: no cover - defensive
        audiototext_routes_logger.error("❌ Error2: %s", exc)
        return jsonify({"ok": False, "error": str(exc)}), 500


@audiototext_bp.route("/upload", methods=["POST"])
@login_required(role=["admin", "redakcja", "moderator", "tester", "fox"])
def upload_audio():
    if "audio_file" not in request.files:
        return jsonify({"ok": False, "error": "Brak pliku w polu 'audio_file'"}), 400

    file_obj = request.files["audio_file"]
    if not file_obj or file_obj.filename == "":
        return jsonify({"ok": False, "error": "Nie wybrano pliku"}), 400

    filename = secure_filename(file_obj.filename)
    save_path = os.path.join(UPLOADS_DIR, filename)
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    file_obj.save(save_path)

    params = {
        "language_code": request.form.get("language_code", "pl-PL"),
        "diarization_speaker_count": (
            int(request.form["diarization_speaker_count"])
            if request.form.get("diarization_speaker_count")
            else None
        ),
        "enable_word_time_offsets": request.form.get("enable_word_time_offsets") == "on",
    }

    job_id = manager.enqueue(save_path, params)
    return (
        jsonify(
            {
                "ok": True,
                "job_id": job_id,
                "status_url": url_for("audiototext.job_status", job_id=job_id, _external=False),
            }
        ),
        202,
    )


@audiototext_bp.route("/job/<job_id>", methods=["GET"])
@login_required(role=["admin", "redakcja", "moderator", "tester", "fox"])
def job_status(job_id):
    mng = get_manager()
    job = mng.get(job_id)

    if job:
        if job.status == "done" and job.result_path and os.path.isfile(job.result_path):
            filename = os.path.basename(job.result_path)
            return jsonify(
                {
                    "ok": True,
                    "status": "done",
                    "result_download": url_for("audiototext.download_result", filename=filename),
                }
            )
        if job.status == "error":
            return jsonify({"ok": True, "status": "error", "error": job.error or "unknown"})
        return jsonify({"ok": True, "status": job.status})

    state = load_job_state(job_id)
    if state:
        status = state.get("status")
        if status == "done":
            result_path = state.get("result_path")
            if result_path and os.path.isfile(result_path):
                filename = os.path.basename(result_path)
                return jsonify(
                    {
                        "ok": True,
                        "status": "done",
                        "result_download": url_for("audiototext.download_result", filename=filename),
                    }
                )
            return jsonify({"ok": True, "status": "done"})
        if status == "error":
            return jsonify({"ok": True, "status": "error", "error": state.get("error")})
        return jsonify({"ok": True, "status": status})

    prefix = f"transcription_{job_id}.json"
    candidate = os.path.join(RESULTS_DIR, prefix)
    if os.path.isfile(candidate):
        filename = os.path.basename(candidate)
        return jsonify(
            {
                "ok": True,
                "status": "done",
                "result_download": url_for("audiototext.download_result", filename=filename),
            }
        )

    return jsonify({"ok": False, "error": "Job not found"}), 404


@audiototext_bp.route("/results/<path:filename>", methods=["GET"])
@login_required(role=["admin", "redakcja", "moderator", "tester", "fox"])
def download_result(filename):
    path = os.path.join(RESULTS_DIR, filename)
    if not os.path.isfile(path):
        return jsonify({"ok": False, "error": "File not found"}), 404
    raw = request.args.get("raw")
    return send_file(
        path,
        as_attachment=False if raw else True,
        download_name=filename,
        mimetype="application/json",
    )


@audiototext_bp.route("/results/browser", methods=["GET"])
@login_required(role=["admin", "redakcja", "moderator", "tester", "fox"])
def results_browser():
    return render_template("audiototext/results_browser.html")


@audiototext_bp.route("/results/list", methods=["GET"])
@login_required(role=["admin", "redakcja", "moderator", "tester", "fox"])
def results_list():
    items = []
    try:
        if not os.path.isdir(RESULTS_DIR):
            return jsonify({"ok": True, "items": []})

        names = [name for name in os.listdir(RESULTS_DIR) if name.endswith(".json")]
        names.sort(key=lambda n: os.path.getmtime(os.path.join(RESULTS_DIR, n)), reverse=True)

        for name in names:
            path = os.path.join(RESULTS_DIR, name)
            meta = {
                "filename": name,
                "size_bytes": None,
                "mtime": None,
                "job_id": None,
                "created_at": None,
                "source_file": None,
                "language_code": None,
                "has_diarization": False,
                "words_count": 0,
                "transcript_chars": 0,
            }
            try:
                stat = os.stat(path)
                meta["size_bytes"] = stat.st_size
                meta["mtime"] = int(stat.st_mtime)
                with open(path, "r", encoding="utf-8") as handler:
                    data = json.load(handler)
                meta["job_id"] = data.get("job_id")
                meta["created_at"] = data.get("created_at")
                meta["source_file"] = data.get("source_file")
                params = data.get("params") or {}
                meta["language_code"] = params.get("language_code")
                result = data.get("result") or {}
                meta["transcript_chars"] = len((result.get("transcript") or ""))
                diarization_words = result.get("diarization_words") or []
                meta["words_count"] = len(diarization_words)
                meta["has_diarization"] = bool(diarization_words)
            except Exception as exc:  # pragma: no cover - keep going
                meta["error"] = str(exc)
            items.append(meta)

        return jsonify({"ok": True, "items": items})
    except Exception as exc:  # pragma: no cover - fallback
        return jsonify({"ok": False, "error": str(exc)}), 500


@audiototext_bp.route("/selftest", methods=["GET"])
@login_required(role=["admin", "redakcja", "moderator", "tester", "fox"])
def gcs_selftest_view():
    bucket = request.args.get("bucket") or None
    prefix = request.args.get("prefix") or None

    result = gcs_selftest(bucket_name=bucket, prefix=prefix)
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


@audiototext_bp.route("/gcstest", methods=["GET"])
@login_required(role=["admin", "redakcja", "moderator", "tester", "fox"])
def gcs_diag():
    import importlib
    import sys

    out = {
        "python": sys.executable,
        "sys_path_head": sys.path[:5],
        "google_file": None,
        "google_path": None,
        "storage_ok": False,
        "storage_error": None,
        "speech_ok": False,
        "speech_error": None,
    }
    try:
        import google

        out["google_file"] = getattr(google, "__file__", None)
        out["google_path"] = list(getattr(google, "__path__", [])) if hasattr(google, "__path__") else None
    except Exception as exc:  # pragma: no cover - diagnostics
        out["google_error"] = str(exc)

    try:
        storage = importlib.import_module("google.cloud.storage")
        out["storage_ok"] = True
        out["storage_version"] = getattr(storage, "__version__", None)
    except Exception as exc:  # pragma: no cover - diagnostics
        out["storage_error"] = str(exc)

    try:
        speech = importlib.import_module("google.cloud.speech")
        out["speech_ok"] = True
        out["speech_version"] = getattr(speech, "__version__", None)
    except Exception as exc:  # pragma: no cover - diagnostics
        out["speech_error"] = str(exc)

    return jsonify(out)


@audiototext_bp.app_errorhandler(RequestEntityTooLarge)
@login_required(role=["admin", "redakcja", "moderator", "tester", "fox"])
def handle_413(error):  # pragma: no cover - simple
    return (
        jsonify({"ok": False, "error": "Plik jest zbyt duży (413). Zwiększ limit lub skompresuj/konwertuj audio."}),
        413,
    )


@audiototext_bp.app_errorhandler(HTTPException)
@login_required(role=["admin", "redakcja", "moderator", "tester", "fox"])
def handle_http_exception(error: HTTPException):  # pragma: no cover - simple
    if request.accept_mimetypes.accept_json:
        return jsonify({"ok": False, "error": f"{error.code} {error.name}"}), error.code
    return error


@audiototext_bp.app_errorhandler(Exception)
@login_required(role=["admin", "redakcja", "moderator", "tester", "fox"])
def handle_unexpected(error):  # pragma: no cover - fallback
    current_app.logger.exception(error)
    if request.accept_mimetypes.accept_json:
        return jsonify({"ok": False, "error": "Błąd serwera (500). Sprawdź logi."}), 500
    return "Internal Server Error", 500
