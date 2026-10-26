"""Alembic environment for the EvoDiagram backend (async engines).

The database URL is resolved from application settings (app.config), so
migrations always target the same database as the running service. Both
sqlite (aiosqlite) and postgres (asyncpg) URLs are async, so migrations run
through an async engine wrapped in run_sync.
"""

from __future__ import annotations

import asyncio
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config, create_async_engine

from alembic import context

# Make `app` (backend/) and `evo_diagram` (repo root) importable no matter
# which directory alembic was invoked from. app.config transitively imports
# evo_diagram.utils.env_loader.
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = _BACKEND_ROOT.parent
for _path in (str(_BACKEND_ROOT), str(_REPO_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from app.config import get_settings  # noqa: E402
from app.db.base import Base  # noqa: E402
import app.models  # noqa: E402,F401  (register every mapper on Base.metadata)

# Alembic Config object (provides access to values within the .ini file).
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Resolved once per run from application settings instead of the ini file so
# secrets/URLs never live in alembic.ini and `%` characters are safe.
DATABASE_URL = get_settings().database_url

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL to stdout, no DBAPI)."""
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # Batch mode keeps future ALTER operations workable on sqlite.
        render_as_batch=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # Batch mode keeps future ALTER operations workable on sqlite.
        render_as_batch=True,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine and run migrations through a sync connection."""
    connectable = create_async_engine(DATABASE_URL, poolclass=pool.NullPool)

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode against the configured database."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
