from sqlalchemy import String, Text, DateTime, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import TYPE_CHECKING, Any
from uuid import uuid4
from datetime import datetime

from app.db.base import Base, utc_now

if TYPE_CHECKING:
    from app.models.project import Project


class Snapshot(Base):
    """Version snapshot and diagnostic record"""
    __tablename__ = "snapshots"

    snapshot_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.project_id"), nullable=False, index=True
    )
    parent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("snapshots.snapshot_id", ondelete="SET NULL"), index=True
    )
    schema_blob: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    edit_source: Mapped[str] = mapped_column(String(20), nullable=False)
    thought_trace: Mapped[str | None] = mapped_column(Text)
    metrics_scores: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False, index=True)

    project: Mapped["Project"] = relationship(back_populates="snapshots")
