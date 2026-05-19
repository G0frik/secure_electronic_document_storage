"""Flask extension instances. Imported by the app factory and other modules."""

from __future__ import annotations

from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_migrate import Migrate
from flask_session import Session
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    """Base class for all ORM models."""


db: SQLAlchemy = SQLAlchemy(model_class=Base)
migrate: Migrate = Migrate()
session_ext: Session = Session()
cors: CORS = CORS()

limiter: Limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=settings.redis_url,
    default_limits=[],
    headers_enabled=True,
)
