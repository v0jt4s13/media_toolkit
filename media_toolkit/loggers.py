"""Logging helpers for the Media Toolkit project."""
from __future__ import annotations

import datetime
import os
import json
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Dict

_LOG_DIR = Path(__file__).resolve().parent / "logs"
_LOG_DIR.mkdir(parents=True, exist_ok=True)

_LEVELS: Dict[str, int] = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
}


def _setup_logger(name: str, filename: str, level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger(f"media_toolkit.{name}")
    if logger.handlers:
        return logger

    logger.setLevel(level)
    handler = RotatingFileHandler(_LOG_DIR / filename, maxBytes=1_000_000, backupCount=5)
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    if os.getenv("MEDIA_TOOLKIT_LOG_TO_STDERR", "0") == "1":
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)

    return logger


def logger(msg: str, level: str = "info", **fields):
    """Structured JSON logger used by background workers."""
    level = (level or "info").lower()
    lvl = _LEVELS.get(level, logging.INFO)

    record = {
        "ts": datetime.datetime.utcnow().isoformat() + "Z",
        "level": level,
        "msg": msg,
    }
    record.update(fields)
    payload = json.dumps(record, ensure_ascii=False)

    stream = sys.stderr if level in ("error", "critical") else sys.stdout
    print(payload, file=stream)

    target = audiototext_logger if level not in ("error", "critical") else errors_logger
    target.log(lvl, payload)
    return record


audiototext_logger = _setup_logger("audiototext", "audiototext.log")
audiototext_routes_logger = _setup_logger("audiototext.routes", "audiototext_routes.log")
errors_logger = _setup_logger("errors", "errors.log", level=logging.ERROR)


__all__ = [
    "logger",
    "audiototext_logger",
    "audiototext_routes_logger",
    "errors_logger",
]
