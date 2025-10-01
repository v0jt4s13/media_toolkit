"""Google Speech transcription service wrapper."""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from google.cloud import speech

from ..loggers import audiototext_logger
from audiototext.google_speech import build_config, extract_transcript


class TranscriptionService:
    """Thin wrapper around Google Cloud Speech-to-Text."""

    def __init__(self, default_language: str = "pl-PL"):
        if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
            audiototext_logger.error("Brak zmiennej GOOGLE_APPLICATION_CREDENTIALS!")
        self.client = speech.SpeechClient()
        self.default_language = default_language

    def transcribe_local_file(
        self,
        file_path: str,
        language_code: Optional[str] = None,
        diarization_speaker_count: Optional[int] = None,
        model: Optional[str] = None,
        use_enhanced: Optional[bool] = None,
        additional_hints: Optional[List[str]] = None,
        enable_word_time_offsets: bool = False,
    ) -> Dict[str, Any]:
        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"Plik nie istnieje: {file_path}")

        with open(file_path, "rb") as handler:
            content = handler.read()

        audio = speech.RecognitionAudio(content=content)
        config = build_config(
            language_code=language_code or self.default_language,
            diarization_speaker_count=diarization_speaker_count,
            model=model,
            use_enhanced=use_enhanced,
            additional_hints=additional_hints,
            enable_word_time_offsets=enable_word_time_offsets,
        )

        audiototext_logger.info("Start transkrypcji (local) --> file_path=%s", file_path)
        response = self.client.recognize(config=config, audio=audio)
        result = extract_transcript(response)
        audiototext_logger.info(
            "Koniec transkrypcji (local) --> length=%s",
            len(result.get("transcript", "")),
        )
        return result

    def transcribe_gcs(
        self,
        gcs_uri: str,
        language_code: Optional[str] = None,
        diarization_speaker_count: Optional[int] = None,
        model: Optional[str] = None,
        use_enhanced: Optional[bool] = None,
        additional_hints: Optional[List[str]] = None,
        enable_word_time_offsets: bool = False,
    ) -> Dict[str, Any]:
        audio = speech.RecognitionAudio(uri=gcs_uri)
        config = build_config(
            language_code=language_code or self.default_language,
            diarization_speaker_count=diarization_speaker_count,
            model=model,
            use_enhanced=use_enhanced,
            additional_hints=additional_hints,
            enable_word_time_offsets=enable_word_time_offsets,
        )

        audiototext_logger.info("Start transkrypcji (GCS) --> gcs_uri=%s", gcs_uri)
        operation = self.client.long_running_recognize(config=config, audio=audio)
        response = operation.result(timeout=60 * 60)
        result = extract_transcript(response)
        audiototext_logger.info(
            "Koniec transkrypcji (GCS) --> length=%s",
            len(result.get("transcript", "")),
        )
        return result
