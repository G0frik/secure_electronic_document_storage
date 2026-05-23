"""Flask app factory."""

from __future__ import annotations

from datetime import timedelta

import redis
from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

from app.api import register_blueprints
from app.api.errors import register_error_handlers
from app.cli import register_cli
from app.config import settings
from app.extensions import cors, db, limiter, migrate, session_ext
from app.logging_config import configure_logging, get_logger
from app.services.vault import read_secret


def _resolve_secret_key() -> str:
    """Load SECRET_KEY from Vault, falling back to env var / default."""
    vault_val = read_secret("docstore/config", "secret_key")
    if vault_val:
        return vault_val
    return settings.secret_key


def create_app() -> Flask:
    """Build and return a configured Flask application."""
    configure_logging(settings.log_level)
    log = get_logger(__name__)

    app = Flask(__name__)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
    app.config.update(
        SECRET_KEY=_resolve_secret_key(),
        SQLALCHEMY_DATABASE_URI=settings.database_url,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        # --- Uploads (Phase 2) ---
        MAX_CONTENT_LENGTH=settings.max_upload_size_mb * 1024 * 1024,
        # --- Sessions (Phase 1) ---
        SESSION_TYPE="redis",
        SESSION_REDIS=redis.from_url(settings.redis_url),
        SESSION_PERMANENT=True,
        SESSION_KEY_PREFIX="docstore:session:",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=settings.session_lifetime_hours),
        SESSION_COOKIE_NAME="docstore_session",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=True,
    )

    # Extensions
    db.init_app(app)
    migrate.init_app(app, db)
    session_ext.init_app(app)
    limiter.init_app(app)
    cors.init_app(
        app,
        resources={r"/api/*": {"origins": _cors_origins()}, r"/healthz": {"origins": "*"}},
        supports_credentials=True,
        expose_headers=["X-CSRF-Token"],
    )

    # Error handlers
    register_error_handlers(app)

    # Blueprints
    register_blueprints(app)

    # CLI commands
    register_cli(app)

    log.info(
        "app.created",
        env=settings.flask_env,
        debug=app.debug,
        public_registration=settings.registration_open_to_public,
    )
    return app


def _cors_origins() -> list[str]:
    if settings.is_development:
        return [
            "https://localhost",
            "https://127.0.0.1",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
    # Production CORS allow-list comes via env in later phases.
    return []
