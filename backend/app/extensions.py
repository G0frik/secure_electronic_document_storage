"""Flask extension instances. Imported by the app factory and other modules."""

from __future__ import annotations

from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all ORM models."""


db: SQLAlchemy = SQLAlchemy(model_class=Base)
migrate: Migrate = Migrate()
