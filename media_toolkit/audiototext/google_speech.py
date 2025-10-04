# google_speech.py - v1.5
"""Helpers for building Google Speech API requests."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from google.cloud import speech_v1p1beta1 as speech


def build_config(
    language_code: str = "pl-PL",
    enable_automatic_punctuation: bool = True,
    enable_word_time_offsets: bool = False,
    diarization_speaker_count: Optional[int] = None,
    model: Optional[str] = None,
    use_enhanced: Optional[bool] = None,
    additional_hints: Optional[List[str]] = None,
) -> speech.RecognitionConfig:
    diarization_config = None
    if diarization_speaker_count:
        diarization_config = speech.SpeakerDiarizationConfig(
            enable_speaker_diarization=True,
            min_speaker_count=max(2, diarization_speaker_count),
            max_speaker_count=diarization_speaker_count,
        )

    speech_contexts = []
    if additional_hints:
        speech_contexts.append(speech.SpeechContext(phrases=additional_hints))

    config = speech.RecognitionConfig(
        language_code=language_code,
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=16000,
        enable_automatic_punctuation=enable_automatic_punctuation,
        enable_word_time_offsets=enable_word_time_offsets,
        diarization_config=diarization_config,
        speech_contexts=speech_contexts or None,
        model=model or "",
        use_enhanced=use_enhanced if use_enhanced is not None else False,
    )
    return config


def extract_transcript(response: speech.RecognizeResponse) -> Dict[str, Any]:
    transcript_chunks: List[str] = []
    alternatives: List[Dict[str, Any]] = []

    for result in response.results:
        if not result.alternatives:
            continue
        best = result.alternatives[0]
        transcript_chunks.append(best.transcript.strip())
        alternatives.append(
            {
                "transcript": best.transcript.strip(),
                "confidence": float(best.confidence or 0.0),
            }
        )

    transcript = " ".join([chunk for chunk in transcript_chunks if chunk])

    out: Dict[str, Any] = {
        "transcript": transcript,
        "alternatives": alternatives,
    }

    if response.results:
        last = response.results[-1]
        if last.alternatives and last.alternatives[0].words:
            diarization = []
            for word in last.alternatives[0].words:
                diarization.append(
                    {
                        "word": word.word,
                        "start_time": word.start_time.total_seconds() if word.start_time else None,
                        "end_time": word.end_time.total_seconds() if word.end_time else None,
                        "speaker_tag": getattr(word, "speaker_tag", None),
                    }
                )
            out["diarization_words"] = diarization

    return out
