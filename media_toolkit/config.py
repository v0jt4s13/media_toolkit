# config.py - v1.5
"""Configuration helpers for the Media Toolkit project."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Optional

from dotenv import load_dotenv

from .loggers import audiototext_logger

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SETTINGS_DIR = _PROJECT_ROOT / "data_settings"
_DEFAULT_ENV = _SETTINGS_DIR / ".env"
_DEFAULT_TTS = _SETTINGS_DIR / "tts_config.json"

_CONFIG_CACHE: Dict[str, Dict[str, str]] = {}


def _load_dotenv() -> None:
    env_override = os.getenv("MEDIA_TOOLKIT_ENV_FILE")
    env_path = Path(env_override).expanduser() if env_override else _DEFAULT_ENV
    if env_path.is_file():
        load_dotenv(env_path, override=False)


def _load_tts_config() -> Dict[str, str]:
    if not _DEFAULT_TTS.is_file():
        return {}
    try:
        with _DEFAULT_TTS.open("r", encoding="utf-8") as handler:
            return json.load(handler)
    except json.JSONDecodeError:
        return {}


def get_config(key: Optional[str] = None) -> Dict[str, Dict[str, str]]:
    """Load configuration only once and expose selected sections."""
    global _CONFIG_CACHE

    if not _CONFIG_CACHE:
        _load_dotenv()
        env_snapshot = dict(os.environ)

        for var in (
            "GOOGLE_APPLICATION_CREDENTIALS",
            "GOOGLE_CLOUD_PROJECT",
            "GCS_BUCKET",
            "GCS_PREFIX",
            "A2T_GCS_BUCKET",
            "YTDLP_COOKIES_FILE",
            "YTDLP_COOKIES_FROM_BROWSER",
            "MEDIA_TOOLKIT_URL_PREFIX",
            "MEDIA_TOOLKIT_OPENAI_API_KEY",
        ):
            value = env_snapshot.get(var)
            if value:
                os.environ[var] = value

        _CONFIG_CACHE = {
            "env": env_snapshot,
            "tts": _load_tts_config(),
        }

    if key is not None:
        return _CONFIG_CACHE.get(key, {})

    return _CONFIG_CACHE


__all__ = ["get_config"]
