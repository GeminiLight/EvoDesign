"""Durable per-day generation quota for unauthenticated guest clients.

Counts live in the database rather than process memory so a restart or a
second worker cannot reset a guest's daily allowance. Client IPs are stored
only as keyed hashes.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import PublicErrorMixin
from app.models.guest_usage import GuestGenerationUsage

DEFAULT_GUEST_DAILY_GENERATION_LIMIT = 10


class GuestQuotaExceededError(PublicErrorMixin, RuntimeError):
    """Raised when a guest client has used its daily generation allowance."""

    default_public_detail = "Guest generation limit reached for today. Sign in to keep generating."

    def __init__(self, limit: int):
        self.limit = limit
        super().__init__(
            f"guest daily quota of {limit} exhausted",
            public_detail=(
                f"Guests can run {limit} diagram generations per day. "
                "Sign in to keep generating, or try again tomorrow (UTC)."
            ) if limit else "Guest generation is disabled. Sign in to generate diagrams.",
        )


def _utc_day(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d")


def hash_client(client_ip: str, secret: str) -> str:
    """Return a keyed hash so raw guest IPs never reach the database."""
    return hmac.new(secret.encode("utf-8"), client_ip.encode("utf-8"), hashlib.sha256).hexdigest()


async def consume_guest_generation(
    db: AsyncSession,
    *,
    client_ip: str,
    limit: int,
    secret: str,
    clock: Callable[[], datetime] | None = None,
) -> int:
    """Atomically count one guest generation and return the new daily total.

    Raises GuestQuotaExceededError without counting when the allowance is used.
    The caller commits the transaction.
    """
    if limit <= 0:
        raise GuestQuotaExceededError(limit)
    day = _utc_day(clock() if clock else None)
    client_hash = hash_client(client_ip, secret)
    # Earlier days can never be consulted again; keep the table to one day.
    await db.execute(delete(GuestGenerationUsage).where(GuestGenerationUsage.day < day))

    for _ in range(2):
        # The guarded UPDATE is the atomic check-and-increment on both SQLite
        # and Postgres; concurrent guests cannot both pass the last slot.
        bumped = await db.execute(
            update(GuestGenerationUsage)
            .where(
                GuestGenerationUsage.client_hash == client_hash,
                GuestGenerationUsage.day == day,
                GuestGenerationUsage.count < limit,
            )
            .values(count=GuestGenerationUsage.count + 1)
            .returning(GuestGenerationUsage.count)
        )
        count = bumped.scalar_one_or_none()
        if count is not None:
            return count
        existing = await db.scalar(select(GuestGenerationUsage.count).where(
            GuestGenerationUsage.client_hash == client_hash, GuestGenerationUsage.day == day))
        if existing is not None:
            break  # The row exists, so the guarded UPDATE failed on the limit.
        try:
            async with db.begin_nested():
                db.add(GuestGenerationUsage(client_hash=client_hash, day=day, count=1))
            return 1
        except IntegrityError:
            continue  # A concurrent first request created the row; retry the UPDATE.
    raise GuestQuotaExceededError(limit)


class GuestQuota:
    """Dependency-injectable facade over consume_guest_generation."""

    async def consume(self, db: AsyncSession, *, client_ip: str, limit: int, secret: str) -> int:
        """Count one guest generation or raise GuestQuotaExceededError."""
        return await consume_guest_generation(db, client_ip=client_ip, limit=limit, secret=secret)
