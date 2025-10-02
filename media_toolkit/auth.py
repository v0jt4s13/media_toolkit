"""Lightweight authentication helpers for the Media Toolkit app."""
from __future__ import annotations

from .loggers import audiototext_logger
import os
from functools import wraps
from typing import Dict

from flask import abort, redirect, request, session, url_for, has_request_context

# logger = logging.getLogger("media_toolkit.auth")
_ALWAYS_ALLOWED_ROLES = {"fox" "tester"}


def build_users() -> Dict[str, Dict[str, str]]:
    """Return a mapping of allowed users loaded from environment variables."""
    return {
        "admin": {"password": os.getenv("ADMIN_PASSWORD"), "role": "admin"},
        "redakcja": {"password": os.getenv("REDAKCJA_PASSWORD", "red!!!akcja"), "role": "redakcja"},
        "ads": {"password": os.getenv("ADS_PASSWORD", "mod!!!2025"), "role": "moderator"},
        "tester": {"password": os.getenv("TESTER_PASSWORD", "test!n-tv!2025"), "role": "tester"},
        # "fox": {"password": os.getenv("FOX_PASSWORD", "!!!fox!n-tv!2025"), "role": "fox"},
        "fox": {"password": os.getenv("FOX_PASSWORD", "!!!fox123"), "role": "tester"},
        "test": {"password": os.getenv("TEST_PASSWORD", "test"), "role": "tester"},
    }


def login_required(redirect_to: str = "login", role=None):
    """Decorator ensuring the user is logged in and optionally has a required role."""

    def decorator(view_func):
        @wraps(view_func)
        def wrapper(*args, **kwargs):
            user = session.get("user")
            user_role = session.get("role")
            if not user:
                return redirect(url_for(redirect_to))

            if role:
                if isinstance(role, list):
                    allowed = set(role) | _ALWAYS_ALLOWED_ROLES
                    if user_role not in allowed:
                        abort(403)
                else:
                    if user_role not in ({role} | _ALWAYS_ALLOWED_ROLES):
                        abort(403)

            log_entry_access()
            return view_func(*args, **kwargs)

        return wrapper

    return decorator


def log_entry_access(page: str | None = None) -> None:
    """Log access to secured pages for audit purposes."""
    if not has_request_context():
        audiototext_logger.info("Access | system | %s | %s", page or "-", "system")
        return

    ip = request.remote_addr or "unknown_ip"
    user = session.get("user", "guest")
    current_page = page or request.path
    agent = request.headers.get("User-Agent", "unknown_agent")
    audiototext_logger.info("Access | %s | %s | %s | %s", ip, current_page, user, agent)
