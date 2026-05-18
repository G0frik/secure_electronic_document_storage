"""Flask app factory."""

from __future__ import annotations

from flask import Flask
from flask_cors import CORS

from app.api import register_blueprints
from app.config import settings
from app.extensions import db, migrate
from app.logging_config import configure_logging, get_logger


def create_app() -> Flask:
    """Build and return a configured Flask application."""
    configure_logging(settings.log_level)
    log = get_logger(__name__)

    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=settings.secret_key,
        SQLALCHEMY_DATABASE_URI=settings.database_url,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )

    # Extensions
    db.init_app(app)
    migrate.init_app(app, db)
    CORS(app, resources={r"/api/*": {"origins": "*"}, r"/healthz": {"origins": "*"}})

    # Blueprints
    register_blueprints(app)

    log.info("app.created", env=settings.flask_env, debug=app.debug)
    return app
