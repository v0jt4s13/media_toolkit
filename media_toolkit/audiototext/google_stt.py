"""High-level Google STT helpers with YouTube/GCS fallbacks."""
from __future__ import annotations

import os
import subprocess
import tempfile
import wave
from typing import Any, Dict, List, Optional

from google.cloud import speech

from ..loggers import audiototext_logger
from audiototext.gcs import upload_to_gcs

VIDEO_LANGS = {
    "en-US",
    "en-GB",
    "en-AU",
    "fr-FR",
    "de-DE",
    "es-ES",
    "es-US",
    "it-IT",
    "pt-BR",
    "ja-JP",
    "ko-KR",
}


def _inline_duration_limit_err(exc: Exception) -> bool:
    return "inline audio exceeds duration limit" in str(exc).lower()


def _wav_duration_seconds(path: str) -> Optional[float]:
    try:
        with wave.open(path, "rb") as wav:
            frames = wav.getnframes()
            rate = wav.getframerate()
            return frames / float(rate)
    except Exception:
        return None


def _maybe_convert_to_wav_mono16k(src_path: str) -> Optional[str]:
    try:
        subprocess.run(["ffmpeg", "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    except Exception:
        return None

    fd, out = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            src_path,
            "-ac",
            "1",
            "-ar",
            "16000",
            "-acodec",
            "pcm_s16le",
            "-vn",
            out,
        ]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.returncode == 0 and os.path.isfile(out):
            return out
    except Exception:
        pass
    try:
        if os.path.exists(out):
            os.remove(out)
    except Exception:
        pass
    return None


def _extract_transcript(response: speech.RecognizeResponse) -> Dict[str, Any]:
    transcript_chunks: List[str] = []
    alternatives: List[Dict[str, Any]] = []
    diarization_words: List[Dict[str, Any]] = []

    for result in response.results:
        if not result.alternatives:
            continue
        best = result.alternatives[0]
        transcript_chunks.append((best.transcript or "").strip())
        alternatives.append(
            {
                "transcript": (best.transcript or "").strip(),
                "confidence": float(best.confidence or 0.0),
            }
        )
        if getattr(best, "words", None):
            for word in best.words:
                diarization_words.append(
                    {
                        "word": word.word,
                        "start_time": word.start_time.total_seconds() if word.start_time else None,
                        "end_time": word.end_time.total_seconds() if word.end_time else None,
                        "speaker_tag": getattr(word, "speaker_tag", None),
                        "channel_tag": getattr(word, "channel_tag", None),
                    }
                )

    transcript = " ".join([chunk for chunk in transcript_chunks if chunk])
    out: Dict[str, Any] = {
        "transcript": transcript,
        "alternatives": alternatives,
    }
    if diarization_words:
        out["diarization_words"] = diarization_words
    return out


def _attach_meta(
    result: Dict[str, Any],
    meta: Dict[str, Any],
    diarization_config: Optional[speech.SpeakerDiarizationConfig],
    model: str,
    use_enhanced: bool,
) -> Dict[str, Any]:
    if result.get("transcript"):
        result.setdefault("meta", {})
        result["meta"].update(meta)
        result["meta"].update(
            {
                "diarization_enabled": bool(diarization_config),
                "diarization_min": getattr(diarization_config, "min_speaker_count", None)
                if diarization_config
                else None,
                "diarization_max": getattr(diarization_config, "max_speaker_count", None)
                if diarization_config
                else None,
                "model": model,
                "use_enhanced": use_enhanced,
            }
        )
    return result


def stt_google_from_file(
    file_path: str,
    language_code: str = "pl-PL",
    additional_hints: Optional[List[str]] = None,
    diarization_speaker_count: Optional[int] = None,
    enable_word_time_offsets: bool = False,
    use_enhanced: Optional[bool] = None,
    model: Optional[str] = None,
    long_timeout_seconds: int = 3600,
) -> Optional[Dict[str, Any]]:
    if not os.path.isfile(file_path):
        return None

    client = speech.SpeechClient()

    speech_contexts = []
    if additional_hints:
        speech_contexts.append(speech.SpeechContext(phrases=additional_hints))

    diarization_config = None
    if diarization_speaker_count:
        diarization_config = speech.SpeakerDiarizationConfig(
            enable_speaker_diarization=True,
            min_speaker_count=max(2, int(diarization_speaker_count)),
            max_speaker_count=int(diarization_speaker_count),
        )
    elif os.getenv("STT_DIARIZATION_DEFAULT", "0").lower() in ("1", "true", "yes"):
        diarization_config = speech.SpeakerDiarizationConfig(enable_speaker_diarization=True)

    fallbacks = os.getenv("STT_LANG_FALLBACKS", "")
    try_langs = [language_code] + [lang.strip() for lang in fallbacks.split(",") if lang.strip() and lang.strip() != language_code]

    effective_model = model or ""
    effective_use_enhanced = bool(use_enhanced) if use_enhanced is not None else False

    if diarization_config and not model:
        if language_code in VIDEO_LANGS:
            effective_model = "video"
            effective_use_enhanced = True
        else:
            effective_model = ""

    def _via_gcs(src_path: str, lang: str, force_linear16_16k: bool = False) -> Optional[Dict[str, Any]]:
        gcs_bucket = os.getenv("GCS_BUCKET")
        if not gcs_bucket:
            return None
        uri = upload_to_gcs(src_path, gcs_bucket)
        cfg_kwargs = dict(
            language_code=lang,
            enable_automatic_punctuation=True,
            enable_word_time_offsets=enable_word_time_offsets,
            diarization_config=diarization_config,
            speech_contexts=speech_contexts or None,
            model=effective_model,
            use_enhanced=effective_use_enhanced,
        )
        if force_linear16_16k:
            cfg_kwargs.update(
                {
                    "encoding": speech.RecognitionConfig.AudioEncoding.LINEAR16,
                    "sample_rate_hertz": 16000,
                }
            )
        config = speech.RecognitionConfig(**cfg_kwargs)
        audio = speech.RecognitionAudio(uri=uri)
        operation = client.long_running_recognize(config=config, audio=audio)
        response = operation.result(timeout=long_timeout_seconds)
        return _attach_meta(
            _extract_transcript(response),
            {"via": "gcs", "lang": lang, "uri": uri},
            diarization_config,
            effective_model,
            effective_use_enhanced,
        )

    size_bytes = os.path.getsize(file_path)
    max_inline = int(os.getenv("STT_INLINE_MAX_BYTES", 9_000_000))

    tmp_wav = None
    try:
        if size_bytes > max_inline:
            audiototext_logger.info("Plik > %s bajtów, przejście przez GCS", max_inline)
            return _via_gcs(file_path, language_code)

        tmp_wav = _maybe_convert_to_wav_mono16k(file_path)
        use_path = tmp_wav or file_path

        audio_bytes = open(use_path, "rb").read()
        audio = speech.RecognitionAudio(content=audio_bytes)

        best_result = None
        for lang in try_langs:
            config = speech.RecognitionConfig(
                language_code=lang,
                enable_automatic_punctuation=True,
                enable_word_time_offsets=enable_word_time_offsets,
                diarization_config=diarization_config,
                speech_contexts=speech_contexts or None,
                model=effective_model,
                use_enhanced=effective_use_enhanced,
            )
            try:
                response = client.recognize(config=config, audio=audio)
                result = _extract_transcript(response)
                meta = {
                    "via": "sync",
                    "lang": lang,
                    "converted": bool(tmp_wav),
                    "src": use_path,
                }
                result = _attach_meta(result, meta, diarization_config, effective_model, effective_use_enhanced)
                if result.get("transcript"):
                    best_result = result
                    break
            except Exception as exc:
                if _inline_duration_limit_err(exc):
                    audiototext_logger.info("Google: inline audio exceeds duration limit. Przełączam na GCS.")
                    return _via_gcs(use_path, lang, force_linear16_16k=bool(tmp_wav))
                raise

        if best_result:
            return best_result

        return _via_gcs(file_path, language_code)

    finally:
        if tmp_wav and os.path.exists(tmp_wav):
            try:
                os.remove(tmp_wav)
            except OSError:
                pass


def stt_google_from_gcs(
    gcs_uri: str,
    language_code: str = "pl-PL",
    additional_hints: Optional[List[str]] = None,
    diarization_speaker_count: Optional[int] = None,
    enable_word_time_offsets: bool = False,
    use_enhanced: Optional[bool] = None,
    model: Optional[str] = None,
    long_timeout_seconds: int = 3600,
) -> Optional[Dict[str, Any]]:
    client = speech.SpeechClient()

    speech_contexts = []
    if additional_hints:
        speech_contexts.append(speech.SpeechContext(phrases=additional_hints))

    diarization_config = None
    if diarization_speaker_count:
        diarization_config = speech.SpeakerDiarizationConfig(
            enable_speaker_diarization=True,
            min_speaker_count=max(2, int(diarization_speaker_count)),
            max_speaker_count=int(diarization_speaker_count),
        )

    config = speech.RecognitionConfig(
        language_code=language_code,
        enable_automatic_punctuation=True,
        enable_word_time_offsets=enable_word_time_offsets,
        diarization_config=diarization_config,
        speech_contexts=speech_contexts or None,
        model=model or "",
        use_enhanced=bool(use_enhanced) if use_enhanced is not None else False,
    )
    audio = speech.RecognitionAudio(uri=gcs_uri)
    operation = client.long_running_recognize(config=config, audio=audio)
    response = operation.result(timeout=long_timeout_seconds)
    result = _extract_transcript(response)
    return _attach_meta(
        result,
        {"via": "gcs", "lang": language_code, "uri": gcs_uri},
        diarization_config,
        model or "",
        bool(use_enhanced) if use_enhanced is not None else False,
    )


__all__ = [
    "stt_google_from_file",
    "stt_google_from_gcs",
]
