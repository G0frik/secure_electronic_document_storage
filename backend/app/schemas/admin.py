"""Pydantic schemas for /api/admin/* endpoints (Phase 13)."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

from app.models.user import Role, UserStatus


class UserUpdateRequest(BaseModel):
    """All fields optional — only the provided ones are applied. `clear_department`
    nulls the department FK (Pydantic v2 can't distinguish "absent" from "null"
    on `department_id: uuid | None`).
    """

    role: Role | None = None
    department_id: uuid.UUID | None = None
    clear_department: bool = False
    quota_bytes: int | None = Field(default=None, ge=0)
    status: UserStatus | None = None
    is_manager: bool | None = None


class DepartmentCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)


class DepartmentRenameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)


class GroupCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=256)


class GroupUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=256)
    clear_description: bool = False
