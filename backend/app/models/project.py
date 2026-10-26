from sqlalchemy import String, Text, DateTime, ForeignKey, JSON, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import TYPE_CHECKING, Any
from uuid import uuid4
from datetime import datetime

from app.db.base import Base, utc_now

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.snapshot import Snapshot


class Project(Base):
    """Project model"""
    __tablename__ = "projects"

    project_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.user_id"), nullable=False, index=True
    )
    title: Mapped[str | None] = mapped_column(String(255))
    diagram_type: Mapped[str | None] = mapped_column(String(100), index=True)
    domain_tag: Mapped[str | None] = mapped_column(String(100), index=True)
    canvas_engine: Mapped[str] = mapped_column(String(30), default="excalidraw")
    source_text: Mapped[str | None] = mapped_column(Text)
    source_image: Mapped[str | None] = mapped_column(Text)
    latest_schema: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    thumbnail_url: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now, nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="projects")
    # Lazy "select": snapshot graphs are large, so they load only where a caller
    # explicitly asks for them (see ProjectService for the query-based reads).
    snapshots: Mapped[list["Snapshot"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
