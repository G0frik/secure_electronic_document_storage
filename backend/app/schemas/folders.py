"""Pydantic schemas for /api/folders/*."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class FolderCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    parent_id: uuid.UUID | None = None
