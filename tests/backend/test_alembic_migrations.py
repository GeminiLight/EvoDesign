"""Alembic migration system tests.

These tests shell out to the real alembic CLI (the same entry point developers
use) against throwaway sqlite databases, so they cover alembic.ini, env.py,
and the checked-in revision scripts end to end.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect


ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT / "backend"

EXPECTED_APP_TABLES = {
    "agent_connections",
    "agent_proposals",
    "users",
    "projects",
    "snapshots",
    "subscriptions",
    "oauth_codes",
    "dna_rules",
}


def _alembic_env(tmp_path: Path, db_name: str) -> dict[str, str]:
    """Build a subprocess environment targeting a throwaway sqlite database."""
    env = dict(os.environ)
    env.update(
        {
            "JWT_SECRET": "test-jwt-secret-abcdefghijklmnop",
            "SESSION_SECRET": "test-session-secret-abcdefghij",
            "DB_TYPE": "sqlite",
            # Absolute DB_NAME produces sqlite+aiosqlite:////abs/path.db.
            "DB_NAME": str(tmp_path / db_name),
        }
    )
    # Avoid leaking a developer's local config into the migration run.
    env.pop("DB_HOST", None)
    env.pop("DB_PORT", None)
    env.pop("DB_USER", None)
    env.pop("DB_PASSWORD", None)
    return env


def _run_alembic(tmp_path: Path, db_name: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=str(BACKEND_DIR),
        env=_alembic_env(tmp_path, db_name),
        capture_output=True,
        text=True,
        timeout=180,
    )


def _assert_alembic_succeeded(result: subprocess.CompletedProcess) -> None:
    assert result.returncode == 0, (
        f"alembic failed (rc={result.returncode})\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def _sqlite_tables(db_path: Path) -> set[str]:
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def _sqlite_schema(db_path: Path) -> dict[str, dict[str, object]]:
    """Return {table: {"columns": [...], "indexes": {name: sorted cols}}}."""
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        inspector = inspect(engine)
        schema: dict[str, dict[str, object]] = {}
        for table in sorted(inspector.get_table_names()):
            schema[table] = {
                "columns": sorted(
                    column["name"] for column in inspector.get_columns(table)
                ),
                "indexes": {
                    index["name"]: tuple(sorted(index["column_names"]))
                    for index in inspector.get_indexes(table)
                },
            }
        return schema
    finally:
        engine.dispose()


def test_alembic_upgrade_head_creates_core_tables(tmp_path):
    result = _run_alembic(tmp_path, "upgrade", "upgrade", "head")
    _assert_alembic_succeeded(result)

    db_path = tmp_path / "upgrade.db"
    assert db_path.exists()
    tables = _sqlite_tables(db_path)
    assert EXPECTED_APP_TABLES <= tables
    assert "alembic_version" in tables

    schema = _sqlite_schema(db_path)
    # Spot-check contract-critical columns that the legacy bootstrap used to
    # backfill by hand; migrations must create them directly.
    assert "last_login_at" in schema["users"]["columns"]
    assert "external_id" in schema["users"]["columns"]
    assert "version" in schema["projects"]["columns"]
    # The OAuth identity uniqueness index is part of the initial schema.
    assert (
        "uq_users_auth_provider_external_id"
        in schema["users"]["indexes"]
    )


def test_alembic_check_reports_no_model_drift(tmp_path):
    _assert_alembic_succeeded(_run_alembic(tmp_path, "check", "upgrade", "head"))

    result = _run_alembic(tmp_path, "check", "check")
    _assert_alembic_succeeded(result)
    assert "No new upgrade operations detected" in result.stdout


def test_alembic_schema_matches_create_all_schema(tmp_path):
    """The migration-built schema must equal the create_all startup schema."""
    _assert_alembic_succeeded(_run_alembic(tmp_path, "parity", "upgrade", "head"))
    migrated_db = tmp_path / "parity.db"

    create_all_db = tmp_path / "create_all.db"
    from app.db.base import Base
    from app.models import (  # noqa: F401  (register mappers)
        DnaRule,
        OAuthCode,
        Project,
        Snapshot,
        Subscription,
        User,
    )

    engine = create_engine(f"sqlite:///{create_all_db}")
    try:
        Base.metadata.create_all(engine)
    finally:
        engine.dispose()

    migrated_schema = _sqlite_schema(migrated_db)
    create_all_schema = _sqlite_schema(create_all_db)
    migrated_schema.pop("alembic_version", None)

    assert set(migrated_schema) == set(create_all_schema) == EXPECTED_APP_TABLES
    assert migrated_schema == create_all_schema


def test_alembic_downgrade_base_removes_application_tables(tmp_path):
    _assert_alembic_succeeded(_run_alembic(tmp_path, "downgrade", "upgrade", "head"))
    _assert_alembic_succeeded(_run_alembic(tmp_path, "downgrade", "downgrade", "base"))

    remaining = _sqlite_tables(tmp_path / "downgrade.db")
    assert remaining.isdisjoint(EXPECTED_APP_TABLES)
