# utils_audio.py - v1.5
import os, uuid, subprocess, mimetypes
from google.cloud import storage

SPEECH_SAMPLE_RATE = 16000

def to_wav16_mono(src_path: str) -> str:
    """Konwertuj dowolne audio do WAV PCM s16le, 16 kHz, mono."""
    out = os.path.join("/tmp", f"{uuid.uuid4().hex}.16k.wav")
    cmd = [
        "ffmpeg", "-y", "-i", src_path,
        "-ac", "1", "-ar", str(SPEECH_SAMPLE_RATE),
        "-c:a", "pcm_s16le",
        out,
    ]
    subprocess.check_call(cmd)
    return out

