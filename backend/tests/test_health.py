"""Tests for /healthz and /readyz."""

from __future__ import annotations

from flask.testing import FlaskClient


def test_healthz_returns_ok(client: FlaskClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json == {"status": "ok"}
