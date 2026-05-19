"""Pydantic schemas for /api/auth endpoints (request validation only).

Response payloads are constructed manually in `api/auth.py::_user_payload`
to keep the SQLAlchemy relationship → string flattening explicit.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, EmailStr, Field

from app.models.user import Role


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=512)


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=512)
    department_id: uuid.UUID | None = None
    role: Role = Role.USER
    is_manager: bool = False


class CsrfResponse(BaseModel):
    csrf_token: str
