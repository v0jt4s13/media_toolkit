# worker.py - v1.2
from google.cloud import speech_v1p1beta1 as speech
from google.cloud import storage
import subprocess
import shlex
import uuid
import os
import mimetypes
from utils_audio import to_wav16_mono
from .gcs import A2T_GCS_BUCKET, upload_to_gcs

SPEECH_SAMPLE_RATE = 16000  # bezpieczne default
  # ustaw zmienną środowiskową

def resample_any_to_wav16(src_path: str) -> str:
    out = os.path.join("/tmp", f"{uuid.uuid4().hex}.16k.wav")
    cmd = f'ffmpeg -y -i "{src_path}" -ac 1 -ar {SPEECH_SAMPLE_RATE} -c:a pcm_s16le "{out}"'
    subprocess.check_call(cmd, shell=True)
    return out

def resample_if_needed(path_wav: str) -> str:
    out = path_wav.replace(".wav", ".16k.wav")
    cmd = f'ffmpeg -y -i "{path_wav}" -ac 1 -ar {SPEECH_SAMPLE_RATE} -c:a pcm_s16le "{out}"'
    subprocess.check_call(cmd, shell=True)
    return out

def download_youtube_audio(youtube_url: str, out_dir: str) -> str:
    # MP3/M4A też zadziała, ale FLAC/WAV jest najpewniejsze
    # -x: extract audio, --audio-format wav: transcoding do WAV
    cmd = f'yt-dlp -f bestaudio --no-playlist -x --audio-format wav -o "{out_dir}/%(id)s.%(ext)s" {shlex.quote(youtube_url)}'
    subprocess.check_call(cmd, shell=True)
    # znajdź pobrany plik
    for fn in os.listdir(out_dir):
        if fn.endswith(".wav"):
            return os.path.join(out_dir, fn)
    raise RuntimeError("Nie znaleziono pliku WAV po yt-dlp")

def resample_if_needed(path_wav: str) -> str:
    # opcjonalnie sprowadź do mono/16k
    out = path_wav.replace(".wav", ".16k.wav")
    cmd = f'ffmpeg -y -i "{path_wav}" -ac 1 -ar {SPEECH_SAMPLE_RATE} "{out}"'
    subprocess.check_call(cmd, shell=True)
    return out

def upload_to_gcs_depr(local_path: str, bucket_name: str) -> str:
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)

    ext = os.path.splitext(local_path)[1] or ".wav"
    mime = mimetypes.guess_type(local_path)[0] or "application/octet-stream"

    blob_name = f"audiototext/{uuid.uuid4().hex}{ext}"
    blob = bucket.blob(blob_name)
    blob.upload_from_filename(local_path, content_type=mime)
    return f"gs://{bucket_name}/{blob_name}"

def build_config(params: dict) -> speech.RecognitionConfig:
    diar_count = params.get("diarization_speaker_count")
    diarization_config = speech.SpeakerDiarizationConfig(
        enable_speaker_diarization=bool(diar_count),
        min_speaker_count=diar_count or 2,
        max_speaker_count=diar_count or 8,
    )
    return speech.RecognitionConfig(
        language_code=params.get("language_code", "pl-PL"),
        enable_automatic_punctuation=True,
        enable_word_time_offsets=bool(params.get("enable_word_time_offsets")),
        diarization_config=diarization_config,
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=SPEECH_SAMPLE_RATE,
        model="latest_long"  # lub "default", zależnie od projektu
    )

def process_job(file_path, params, gcs_uri, youtube_url):
    client = speech.SpeechClient()

    # 1) ŹRÓDŁO: YouTube → pobranie i upload do GCS
    if youtube_url and not gcs_uri:
        tmpdir = "/tmp/ytaudio"
        os.makedirs(tmpdir, exist_ok=True)
        wav = download_youtube_audio(youtube_url, tmpdir)
        wav16 = resample_if_needed(wav)
        wav16 = to_wav16_mono(wav)     # KONWERSJA
        gcs_uri = upload_to_gcs(wav16, A2T_GCS_BUCKET)

    # 2) ŹRÓDŁO: lokalny plik → dla dłuższych również do GCS (tu na sztywno robimy long-run)
    if file_path and not gcs_uri:
        wav16 = resample_any_to_wav16(file_path)
        gcs_uri = upload_to_gcs(wav16, A2T_GCS_BUCKET)

    config = build_config(params)

    # 3) Long running z URI (rozwiązuje Twój błąd 400)
    operation = client.long_running_recognize(
        config=config,
        audio=speech.RecognitionAudio(uri=gcs_uri),
    )
    # Możesz odpytywać asynchronicznie i zapisać op.name do bazy/kolejki.
    # Jeśli chcesz w workerze poczekać:
    response = operation.result(timeout=3600)

    # 4) Złożenie transkryptu
    transcript = []
    for result in response.results:
        # 'alternatives[0]' = najlepsza hipoteza
        alt = result.alternatives[0]
        transcript.append(alt.transcript)

    return {
        "transcript": "\n".join(transcript).strip(),
        "gcs_uri": gcs_uri,
    }
