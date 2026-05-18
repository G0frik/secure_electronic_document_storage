"""WSGI entrypoint. Used by Flask CLI and Gunicorn."""

from app.app_factory import create_app

app = create_app()
