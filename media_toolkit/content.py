"""Content processing tools (URL scraping + prompt application)."""
from __future__ import annotations

import base64
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from flask import (
    Blueprint,
    abort,
    jsonify,
    render_template,
    request,
    send_file,
    session,
    url_for,
    current_app,
)

from .news_tools import (
    PROMPTS,
    ask_model_openai,
    get_prompt_by_id,
    scrap_page,
    synthesize_speech,
)

from .auth import login_required
from .loggers import audiototext_logger, errors_logger

content_bp = Blueprint("content_tools", __name__, url_prefix="/content")
_ALLOWED_ROLES: List[str] = ["admin", "redakcja", "moderator", "tester", "fox"]

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
ENTRY_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def _get_user_output_dir(create: bool = False) -> Path:
    user = session.get("user") or "anonymous"
    user_dir = OUTPUT_DIR / user
    if create:
        user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir

def _sanitize_entry_id(entry_id: str) -> str:
    if not entry_id or not ENTRY_ID_RE.match(entry_id):
        abort(404)
    return entry_id

def _load_entry(entry_id: str) -> Tuple[Dict[str, Any], Path, str]:
    entry_id = _sanitize_entry_id(entry_id)
    user_dir = _get_user_output_dir(create=False)
    if not user_dir.exists():
        abort(404)

    json_path = user_dir / f"{entry_id}.json"
    if not json_path.exists():
        abort(404)

    with json_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return data, user_dir, entry_id


def _with_prefix(path: Optional[str]) -> Optional[str]:
    if not path:
        return path
    prefix = current_app.config.get("MEDIA_TOOLKIT_URL_PREFIX", "")
    if prefix and path.startswith("/") and not path.startswith(prefix + "/"):
        return f"{prefix}{path}"
    return path


@content_bp.route("/summary", methods=["GET"])
@login_required(role=_ALLOWED_ROLES)
def summary_form():
    """Render the simplified summary form."""
    return render_template("content/summary.html", prompts=PROMPTS)


@content_bp.route("/short", methods=["GET"])
@login_required(role=_ALLOWED_ROLES)
def short_mobile():
    """Mobile-friendly summary workflow."""
    return render_template("content/short.html", prompts=PROMPTS)


@content_bp.route("/prompts", methods=["GET"])
@login_required(role=_ALLOWED_ROLES)
def prompts_list():
    items = [{"id": p["id"], "label": p["label"]} for p in PROMPTS]
    return jsonify({"ok": True, "prompts": items})


@content_bp.route("/scrap", methods=["POST"])
@login_required(role=_ALLOWED_ROLES)
def scrap_url():
    print(f'\n\t\tSTART ==> scrap_url()')
    payload = request.get_json(silent=True) or {}
    url = (payload.get("url") or "").strip()
    print('payload, url')
    print(payload, url)

    if not url:
        return jsonify({"ok": False, "error": "Brak pola 'url'"}), 400

    try:
        data = scrap_page(url, language="pl")
        audiototext_logger.info(f'scrap_page({url}, "pl")')
        audiototext_logger.info(f'data: {data}')

    except Exception as exc:  # pragma: no cover - network failures
        errors_logger.error(f'exc==>{exc}')
        return jsonify({"ok": False, "error": str(exc)}), 500

    return jsonify({"ok": True, "payload": data})


@content_bp.route("/apply-prompt", methods=["POST"])
@login_required(role=_ALLOWED_ROLES)
def apply_prompt():
    audiototext_logger.info('AAAAAAAAAAAAa')
    payload = request.get_json(silent=True) or {}
    audiototext_logger.info('BBBBBBBBBBB')
    prompt_id = (payload.get("prompt_id") or "").strip()
    audiototext_logger.info('CCCCCCCCCCCC')
    data = payload.get("data") or {}
    audiototext_logger.info('DDDDDDDDDDDD')
    want_tts = bool(payload.get("text_to_speech"))
    audiototext_logger.info('EEEEEEEEEEE')

    prompt = get_prompt_by_id(prompt_id)
    audiototext_logger.info('FFFFFFFFFFFF')
    if not prompt:
        return jsonify({"ok": False, "error": "Prompt not found"}), 404

    try:
        user_payload = json.dumps(data, ensure_ascii=False, indent=2)
    except Exception:
        user_payload = str(data)

    user_prompt = f"{prompt['user_prefix']}\n{user_payload}"

    try:
        result_text = ask_model_openai(prompt["system"], user_prompt)
    except Exception as exc:  # pragma: no cover - model errors
        return jsonify({"ok": False, "error": str(exc)}), 500

    response: Dict[str, Any] = {"ok": True, "result_text": result_text}
    if prompt_id == "titles5_pl":
        response["result_title"] = None

    audio_bytes: Optional[bytes] = None
    if want_tts and result_text:
        try:
            audio_bytes = synthesize_speech(result_text)
            response["audio_base64"] = base64.b64encode(audio_bytes).decode("ascii")
        except Exception as exc:  # pragma: no cover - dependency issues
            response["audio_error"] = str(exc)
            audio_bytes = None

    user_dir = _get_user_output_dir(create=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    safe_prompt = re.sub(r"[^A-Za-z0-9_-]", "", prompt_id or "prompt") or "prompt"
    safe_prompt = safe_prompt[:32]
    entry_id = f"{timestamp}_{safe_prompt}"
    json_path = user_dir / f"{entry_id}.json"

    counter = 1
    while json_path.exists():
        entry_id = f"{timestamp}_{safe_prompt}_{counter}"
        json_path = user_dir / f"{entry_id}.json"
        counter += 1

    audio_filename: Optional[str] = None
    if audio_bytes:
        audio_filename = f"{entry_id}.mp3"
        audio_path = user_dir / audio_filename
        audio_path.write_bytes(audio_bytes)
        response["audio_url"] = _with_prefix(url_for("content_tools.archive_audio", entry_id=entry_id))

    created_at = datetime.utcnow().isoformat() + "Z"
    metadata = {
        "id": entry_id,
        "prompt_id": prompt_id,
        "title": data.get("title") or "",
        "source_url": data.get("source_url") or "",
        "text": result_text,
        "created_at": created_at,
        "audio_filename": audio_filename,
    }

    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(metadata, handle, ensure_ascii=False, indent=2)

    response["entry_id"] = entry_id
    response["text_url"] = _with_prefix(url_for("content_tools.archive_text", entry_id=entry_id))
    if audio_filename and "audio_url" not in response:
        response["audio_url"] = _with_prefix(url_for("content_tools.archive_audio", entry_id=entry_id))

    audiototext_logger.info(f'response ==> {response}')
    return jsonify(response)


@content_bp.route("/archive", methods=["GET"])
@login_required(role=_ALLOWED_ROLES)
def archive_list():
    """Return metadata for the current user's stored summaries."""
    user_dir = _get_user_output_dir(create=False)
    entries: List[Dict[str, Any]] = []
    if user_dir.exists():
        for json_path in sorted(user_dir.glob("*.json"), reverse=True):
            try:
                with json_path.open("r", encoding="utf-8") as handle:
                    data = json.load(handle)
            except Exception:
                continue
            entry_id = json_path.stem
            entry = {
                "id": entry_id,
                "prompt_id": data.get("prompt_id"),
                "title": data.get("title") or "",
                "created_at": data.get("created_at"),
                "text_url": _with_prefix(url_for("content_tools.archive_text", entry_id=entry_id)),
            }
            if data.get("audio_filename"):
                entry["audio_url"] = _with_prefix(url_for("content_tools.archive_audio", entry_id=entry_id))
            entries.append(entry)

    return jsonify({"ok": True, "entries": entries})


@content_bp.route("/archive/<entry_id>/text", methods=["GET"])
@login_required(role=_ALLOWED_ROLES)
def archive_text(entry_id: str):
    data, _, clean_id = _load_entry(entry_id)
    response: Dict[str, Any] = {
        "ok": True,
        "id": clean_id,
        "prompt_id": data.get("prompt_id"),
        "title": data.get("title"),
        "text": data.get("text"),
        "created_at": data.get("created_at"),
    }
    if data.get("audio_filename"):
        response["audio_url"] = _with_prefix(url_for("content_tools.archive_audio", entry_id=clean_id))
    return jsonify(response)


@content_bp.route("/archive/<entry_id>/audio", methods=["GET"])
@login_required(role=_ALLOWED_ROLES)
def archive_audio(entry_id: str):
    data, user_dir, _ = _load_entry(entry_id)
    audio_filename = data.get("audio_filename")
    if not audio_filename:
        abort(404)
    audio_path = user_dir / audio_filename
    if not audio_path.exists():
        abort(404)

    mimetype = "audio/mpeg"
    if audio_path.suffix.lower() == ".ogg":
        mimetype = "audio/ogg"
    elif audio_path.suffix.lower() == ".wav":
        mimetype = "audio/wav"

    return send_file(audio_path, mimetype=mimetype, download_name=audio_filename, as_attachment=False)


__all__ = ["content_bp"]
