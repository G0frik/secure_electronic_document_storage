"""API blueprint registration."""

from __future__ import annotations

from flask import Flask

from app.api.health import bp as health_bp


def register_blueprints(app: Flask) -> None:
    """Register all blueprints on the app."""
    app.register_blueprint(health_bp)
