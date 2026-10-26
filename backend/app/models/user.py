from datetime import datetime
from sqlalchemy import String, Text, DateTime, Index, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import TYPE_CHECKING, List, Optional
from uuid import uuid4

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.subscription import Subscription
    from app.models.project import Project


class User(Base, TimestampMixin):
    """Application user account."""

    __tablename__ = "users"
    __table_args__ = (
        Index(
            "uq_users_auth_provider_external_id",
            "auth_provider",
            "external_id",
            unique=True,
            sqlite_where=text("external_id IS NOT NULL"),
            postgresql_where=text("external_id IS NOT NULL"),
        ),
    )

    user_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    username: Mapped[str | None] = mapped_column(String(255))
    avatar_url: Mapped[str | None] = mapped_column(Text)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    auth_provider: Mapped[str] = mapped_column(String(50), default="email")
    external_id: Mapped[str | None] = mapped_column(String(255))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Relationships
    subscription: Mapped[Optional["Subscription"]] = relationship(
        back_populates="user", uselist=False, lazy="selectin"
    )
    # Lazy "select": eager loading here cascaded into Project.snapshots and pulled
    # every snapshot blob into memory on each bearer-token request.
    projects: Mapped[List["Project"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
