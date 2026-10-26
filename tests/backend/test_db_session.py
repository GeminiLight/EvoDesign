from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError

from app.db import session as db_session


class _FakeSession:
    def __init__(self, *, commit_error: Exception | None = None):
        self.commit_error = commit_error
        self.commits = 0
        self.rollbacks = 0
        self.closes = 0

    async def commit(self):
        self.commits += 1
        if self.commit_error:
            raise self.commit_error

    async def rollback(self):
        self.rollbacks += 1

    async def close(self):
        self.closes += 1


class _FakeSessionContext:
    def __init__(self, session: _FakeSession):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class _RecordingLogger:
    def __init__(self):
        self.debug_messages: list[tuple[str, tuple[object, ...]]] = []
        self.error_messages: list[tuple[str, tuple[object, ...]]] = []
        self.exceptions: list[object] = []

    def opt(self, *, exception=None, **kwargs):
        self.exceptions.append(exception)
        return self

    def debug(self, message: str, *args):
        self.debug_messages.append((message, args))

    def error(self, message: str, *args):
        self.error_messages.append((message, args))


async def _open_dependency(monkeypatch, session: _FakeSession):
    monkeypatch.setattr(
        db_session,
        "create_db_session",
        lambda: _FakeSessionContext(session),
    )
    generator = db_session.get_db()
    yielded_session = await generator.__anext__()
    assert yielded_session is session
    return generator


@pytest.mark.asyncio
async def test_init_db_delegates_schema_bootstrap(monkeypatch):
    engine = object()
    calls = []

    async def initialize_database_schema(received_engine):
        calls.append(received_engine)

    monkeypatch.setattr(db_session, "get_engine", lambda: engine)
    monkeypatch.setattr(
        db_session,
        "initialize_database_schema",
        initialize_database_schema,
    )

    await db_session.init_db()

    assert calls == [engine]


@pytest.mark.asyncio
async def test_get_db_commits_and_closes_after_success(monkeypatch):
    session = _FakeSession()
    generator = await _open_dependency(monkeypatch, session)

    with pytest.raises(StopAsyncIteration):
        await generator.__anext__()

    assert session.commits == 1
    assert session.rollbacks == 0
    assert session.closes == 1


@pytest.mark.asyncio
async def test_get_db_rolls_back_http_exceptions_without_database_error_log(
    monkeypatch,
):
    session = _FakeSession()
    logger = _RecordingLogger()
    generator = await _open_dependency(monkeypatch, session)
    monkeypatch.setattr(db_session, "logger", logger)

    with pytest.raises(HTTPException) as exc_info:
        await generator.athrow(HTTPException(status_code=404, detail="missing"))

    assert exc_info.value.status_code == 404
    assert session.commits == 0
    assert session.rollbacks == 1
    assert session.closes == 1
    assert logger.error_messages == []


@pytest.mark.asyncio
async def test_get_db_logs_sqlalchemy_errors_as_database_failures(monkeypatch):
    session = _FakeSession()
    logger = _RecordingLogger()
    generator = await _open_dependency(monkeypatch, session)
    monkeypatch.setattr(db_session, "logger", logger)

    with pytest.raises(SQLAlchemyError):
        await generator.athrow(SQLAlchemyError("statement failed"))

    assert session.commits == 0
    assert session.rollbacks == 1
    assert session.closes == 1
    assert logger.error_messages == [("Database transaction failed", ())]
    assert len(logger.exceptions) == 1


@pytest.mark.asyncio
async def test_get_db_rolls_back_downstream_non_database_exceptions(monkeypatch):
    session = _FakeSession()
    logger = _RecordingLogger()
    generator = await _open_dependency(monkeypatch, session)
    monkeypatch.setattr(db_session, "logger", logger)

    with pytest.raises(ValueError, match="handler failed"):
        await generator.athrow(ValueError("handler failed"))

    assert session.commits == 0
    assert session.rollbacks == 1
    assert session.closes == 1
    assert logger.error_messages == []
    assert logger.debug_messages == [
        (
            "Rolling back database session after downstream exception: {}",
            ("ValueError",),
        )
    ]
    assert logger.exceptions == []


@pytest.mark.asyncio
async def test_get_db_rolls_back_and_logs_commit_failures(monkeypatch):
    session = _FakeSession(commit_error=SQLAlchemyError("commit failed"))
    logger = _RecordingLogger()
    generator = await _open_dependency(monkeypatch, session)
    monkeypatch.setattr(db_session, "logger", logger)

    with pytest.raises(SQLAlchemyError):
        await generator.__anext__()

    assert session.commits == 1
    assert session.rollbacks == 1
    assert session.closes == 1
    assert logger.error_messages == [("Database commit failed", ())]
    assert len(logger.exceptions) == 1


@pytest.mark.asyncio
async def test_get_db_rolls_back_and_logs_unexpected_commit_failures(monkeypatch):
    error = RuntimeError("driver commit failed")
    session = _FakeSession(commit_error=error)
    logger = _RecordingLogger()
    generator = await _open_dependency(monkeypatch, session)
    monkeypatch.setattr(db_session, "logger", logger)

    with pytest.raises(RuntimeError, match="driver commit failed"):
        await generator.__anext__()

    assert session.commits == 1
    assert session.rollbacks == 1
    assert session.closes == 1
    assert logger.error_messages == [("Unexpected database commit failure", ())]
    assert logger.exceptions == [error]
