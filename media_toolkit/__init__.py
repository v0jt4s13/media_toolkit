# __init__.py - v1.2
"""Media Toolkit Flask application factory."""
from __future__ import annotations

import os
from pathlib import Path
from flask import Flask, redirect, render_template, request, session, url_for, current_app
from werkzeug.middleware.proxy_fix import ProxyFix

from .config import get_config
from .auth import build_users, login_required, log_entry_access
from .loggers import audiototext_routes_logger

# Ensure environment variables are ready before importing blueprints that rely on them.
get_config()

from .audiototext.routes import audiototext_bp  # noqa: E402  (import after config)
from .content_tools.routes import content_bp  # noqa: E402

_PACKAGE_ROOT = Path(__file__).resolve().parent
_TEMPLATES_DIR = _PACKAGE_ROOT / "templates"
_STATIC_DIR = _PACKAGE_ROOT / "static"
_ALLOWED_ROLES = ["admin", "redakcja", "moderator", "tester", "fox"]


def create_app(config_overrides: dict | None = None) -> Flask:
    app = Flask(
        "media_toolkit",
        template_folder=str(_TEMPLATES_DIR),
        static_folder=str(_STATIC_DIR),
    )
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)
    app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024
    app.secret_key = os.getenv("FLASK_SECRET_KEY", "change-me-why-you-ask")

    app.register_blueprint(audiototext_bp)
    app.register_blueprint(content_bp)

    app.config["MEDIA_TOOLKIT_URL_PREFIX"] = os.getenv("MEDIA_TOOLKIT_URL_PREFIX", "").rstrip("/")

    users = build_users()

    @app.route("/")
    @login_required(role=_ALLOWED_ROLES)
    def index():
        log_entry_access("/")
        prefix = current_app.config.get("MEDIA_TOOLKIT_URL_PREFIX", "")
        audiototext_routes_logger.info(f'\n\t\tSTART ==> index() ==> prefix:{prefix}')
        
        target = url_for("content_tools.short_mobile")
        audiototext_routes_logger.info(f"[create_app] {prefix}{target}")
        if prefix:
            target = f"{prefix}{target}"
        return redirect(target)

    @app.route("/login", methods=["GET", "POST"])
    def login():
        audiototext_routes_logger.info(f'\n\t\tSTART ==> login()')
        log_entry_access("/login")
        if session.get("user"):
            prefix = current_app.config.get("MEDIA_TOOLKIT_URL_PREFIX", "")
            target = url_for("content_tools.short_mobile")
            audiototext_routes_logger.info(f"[create_app][login] {prefix}{target}")
            if prefix:
                target = f"{prefix}{target}"
            return redirect(target)

        if request.method == "POST":
            user = request.form.get("username")
            pwd = request.form.get("password")
            user_data = users.get(user)
            audiototext_routes_logger.info(f'Proba logowania: {user_data} <===> {users}\n if user_data and {user_data["password"]} == {pwd}')

            if user_data and user_data["password"] == pwd:

                try:
                    session["user"] = user
                    session["role"] = user_data["role"]
                    audiototext_routes_logger.info(f'[create_app][login] user={user}; user_data["role"]={user_data["role"]}')
                except Exception as err:
                    audiototext_routes_logger.info(f'[create_app][login] err: {err}')

                prefix = current_app.config.get("MEDIA_TOOLKIT_URL_PREFIX", "")
                audiototext_routes_logger.info(f'[create_app][login] prefix={prefix}')
                target = url_for("content_tools.short_mobile")
                audiototext_routes_logger.info(f'[create_app][login] target={target}')

                audiototext_routes_logger.info(f"[create_app][login] {prefix}{target}")
                if prefix:
                    target = f"{prefix}{target}"
                    audiototext_routes_logger.info(f"{prefix}{target}")
                return redirect(target)
            return render_template("login.html", error="Nieprawidłowe dane logowania")

        return render_template("login.html")

    @app.route("/logout")
    @login_required()
    def logout():
        audiototext_routes_logger.info(f'\n\t\tSTART ==> logout()')
        session.pop("user", None)
        session.pop("role", None)
        prefix = current_app.config.get("MEDIA_TOOLKIT_URL_PREFIX", "")
        target = url_for("login")
        audiototext_routes_logger.info(f"[create_app][logout] {prefix}{target}")
        if prefix:
            target = f"{prefix}{target}"
        return redirect(target)

    @app.route("/transkrypt", methods=["GET"])
    @login_required(role=_ALLOWED_ROLES)
    def transcripts_view():
        audiototext_routes_logger.info(f'\n\t\tSTART ==> transcripts_view()')
        return render_template("transkrypt.html")

    @app.route("/audiototext/summary", methods=["GET"])
    @login_required(role=_ALLOWED_ROLES)
    def legacy_summary_alias():
        audiototext_routes_logger.info(f'\n\t\tSTART ==> legacy_summary_alias()')
        return redirect(url_for("content_tools.summary_form"))

    @app.route("/audiototext/short", methods=["GET"])
    @login_required(role=_ALLOWED_ROLES)
    def legacy_short_alias():
        audiototext_routes_logger.info(f'\n\t\tSTART ==> legacy_short_alias() ==> {url_for("content_tools.short_mobile")}')
        return redirect(url_for("content_tools.short_mobile"))

    @app.errorhandler(403)
    def forbidden(error):  # pragma: no cover - simple render path
        return render_template("403.html"), 403

    @app.errorhandler(500)
    def internal_error(error):  # pragma: no cover - simple render path
        return render_template("500.html"), 500

    if config_overrides:
        app.config.update(config_overrides)

    return app


__all__ = ["create_app"]
