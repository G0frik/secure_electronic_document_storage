"""Admin playground: one input document, an optional attack, several classifier setups side by side.

Only used when the stack runs with PLAYGROUND=1. A run never touches the files, classifications or
access decisions of the service; it keeps its own encrypted copies of the input and attacked document.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import Base


class PlaygroundRun(Base):
    __tablename__ = "playground_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    # text | file | corpus; input_ref = file id or corpus path
    input_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    input_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    attack: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # how the attacked document was made: "adapter", "research-variant", "none"
    attack_source: Mapped[str] = mapped_column(String(32), nullable=False, default="none")
    explain: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    preset: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")

    documents: Mapped[list[PlaygroundDocument]] = relationship(
        back_populates="run", cascade="all, delete-orphan", passive_deletes=True
    )
    rows: Mapped[list[PlaygroundRow]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="PlaygroundRow.position",
    )


class PlaygroundDocument(Base):
    """Input or attacked document; bytes in MinIO under the file envelope encryption."""

    __tablename__ = "playground_documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("playground_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # input | attacked
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    wrapped_dek: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    auth_tag: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    kek_version: Mapped[int] = mapped_column(SmallInteger, nullable=False)

    run: Mapped[PlaygroundRun] = relationship(back_populates="documents")


class PlaygroundRow(Base):
    """One classifier setup applied to the run's attacked document."""

    __tablename__ = "playground_rows"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("playground_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    setup: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    explanation: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    run: Mapped[PlaygroundRun] = relationship(back_populates="rows")


class PlaygroundSetup(Base):
    """A named list of setups (grid rows) to load again later."""

    __tablename__ = "playground_setups"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    rows: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
