from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class GuestGenerationUsage(Base):
    """Per-day generation counter for one guest client (keyed by a hashed IP)."""

    __tablename__ = "guest_generation_usage"

    client_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    day: Mapped[str] = mapped_column(String(10), primary_key=True)  # UTC YYYY-MM-DD
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
