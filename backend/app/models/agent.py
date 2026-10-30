"""Project-scoped connections and durable, immutable edit candidates."""

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utc_now


class AgentConnection(Base):
    __tablename__ = 'agent_connections'

    connection_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str | None] = mapped_column(String(36), index=True)
    project_id: Mapped[str | None] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(100), default='Agent CLI')
    status: Mapped[str] = mapped_column(String(20), default='pending')
    user_code: Mapped[str] = mapped_column(String(20))
    device_hash: Mapped[str] = mapped_column(String(64))
    token_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    can_commit: Mapped[bool] = mapped_column(default=False)
    expires_at: Mapped[float] = mapped_column(Float)
    context_version: Mapped[int] = mapped_column(Integer, default=0)
    context_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class AgentProposal(Base):
    __tablename__ = 'agent_proposals'
    __table_args__ = (UniqueConstraint('project_id', 'operation_id', name='uq_agent_project_operation'),)

    proposal_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey('projects.project_id'), index=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    connection_id: Mapped[str | None] = mapped_column(String(36))
    author_kind: Mapped[str] = mapped_column(String(20), default='AGENT')
    operation_id: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    base_version: Mapped[int] = mapped_column(Integer)
    context_version: Mapped[int | None] = mapped_column(Integer)
    base_schema: Mapped[dict[str, Any]] = mapped_column(JSON)
    constraints_hash: Mapped[str] = mapped_column(String(80))
    candidate_schema: Mapped[dict[str, Any]] = mapped_column(JSON)
    changed_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default='queued')
    report: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    preview_path: Mapped[str | None] = mapped_column(Text)
    lease_id: Mapped[str | None] = mapped_column(String(36))
    lease_until: Mapped[float] = mapped_column(Float, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[float] = mapped_column(Float)
    committed_version: Mapped[int | None] = mapped_column(Integer)
    committed_snapshot_id: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
