"""Pydantic schemas for /api/files endpoints.

Response payloads built directly in `api/files.py::_file_payload` to keep
the SQLAlchemy → JSON shaping explicit (same pattern as auth.py).
"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field


class FileListParams(BaseModel):
    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=50, ge=1, le=200)
    # Phase 7: optional folder scoping. `folder_scope="folder"` filters to
    # files whose `folder_id` matches; `folder_id` may be null for root-level.
    folder_scope: Literal["all", "folder"] = "all"
    folder_id: uuid.UUID | None = None
