"""Pydantic schemas for /api/files/<id>/tags."""

from __future__ import annotations

from pydantic import BaseModel, Field


class TagAddRequest(BaseModel):
    names: list[str] = Field(min_length=1, max_length=32)
