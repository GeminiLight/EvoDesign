from __future__ import annotations

from datetime import datetime, timezone

from app.db.base import utc_now


def test_utc_now_returns_naive_utc_timestamp():
    before = datetime.now(timezone.utc).replace(tzinfo=None)
    value = utc_now()
    after = datetime.now(timezone.utc).replace(tzinfo=None)

    assert value.tzinfo is None
    assert before <= value <= after
