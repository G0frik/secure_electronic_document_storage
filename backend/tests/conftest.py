"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import Generator

import pytest
from flask import Flask
from flask.testing import FlaskClient

from app.app_factory import create_app


@pytest.fixture
def app() -> Generator[Flask, None, None]:
    application = create_app()
    application.config.update(TESTING=True)
    yield application


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    return app.test_client()
