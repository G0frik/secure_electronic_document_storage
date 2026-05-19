"""Pydantic schemas for /api/files endpoints.

Response payloads built directly in `api/files.py::_file_payload` to keep
the SQLAlchemy → JSON shaping explicit (same pattern as auth.py).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class FileListParams(BaseModel):
    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=50, ge=1, le=200)
