"""Database schema bootstrap and compatibility repair helpers."""

from loguru import logger
from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.sql.elements import TextClause


USER_PROVIDER_IDENTITY_INDEX = "uq_users_auth_provider_external_id"


async def initialize_database_schema(engine: AsyncEngine) -> None:
    """Create ORM tables and apply startup schema compatibility repairs."""
    from app.db.base import Base
    from app.models import (  # noqa: F401
        DnaRule,
        OAuthCode,
        Project,
        Snapshot,
        Subscription,
        User,
    )

    # Inspect BEFORE create_all: a database that already has tables but no
    # alembic_version was built by this legacy startup path, not by migrations.
    preexisting_tables = await _inspect_table_names(engine)
    if preexisting_tables and "alembic_version" not in preexisting_tables:
        logger.info(
            "Database has {} table(s) but no alembic_version; it was created "
            "by create_all, not by migrations. Run `alembic stamp head` from "
            "backend/ to bring it under migration control (not done "
            "automatically because stamping an out-of-sync schema is unsafe).",
            len(preexisting_tables),
        )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    await ensure_project_version_column(engine)
    await ensure_agent_document_columns(engine)
    await ensure_user_provider_identity_index(engine)

    logger.info("Database tables created")


async def _inspect_table_names(engine: AsyncEngine) -> set[str]:
    """Return the set of table names currently present in the database."""
    async with engine.connect() as conn:
        return await conn.run_sync(lambda sync_conn: set(inspect(sync_conn).get_table_names()))


async def ensure_project_version_column(engine: AsyncEngine) -> None:
    """Ensure databases created before project versioning have projects.version."""
    async with engine.begin() as conn:
        has_version = await conn.run_sync(_has_table_column, "projects", "version")
        if not has_version:
            logger.info("Adding 'version' column to projects table")
            await conn.execute(
                text("ALTER TABLE projects ADD COLUMN version INTEGER NOT NULL DEFAULT 1")
            )


async def ensure_user_provider_identity_index(engine: AsyncEngine) -> None:
    """Ensure OAuth provider identities are unique in existing databases."""
    async with engine.begin() as conn:
        duplicate = (
            await conn.execute(
                text(
                    """
                    SELECT auth_provider, external_id, COUNT(*) AS duplicate_count
                    FROM users
                    WHERE external_id IS NOT NULL
                    GROUP BY auth_provider, external_id
                    HAVING COUNT(*) > 1
                    LIMIT 1
                    """
                )
            )
        ).first()
        if duplicate is not None:
            row = duplicate._mapping
            raise RuntimeError(
                "Cannot create OAuth identity uniqueness index while duplicate "
                f"users exist for auth_provider={row['auth_provider']!r} "
                f"(count={row['duplicate_count']})."
            )

        has_index = await conn.run_sync(
            _has_table_index,
            "users",
            USER_PROVIDER_IDENTITY_INDEX,
        )
        if has_index:
            return

        logger.info("Creating OAuth identity uniqueness index")
        await conn.execute(_create_user_provider_identity_index_sql(conn.dialect.name))


def _create_user_provider_identity_index_sql(dialect_name: str) -> TextClause:
    """Return dialect-specific SQL for the OAuth identity uniqueness index."""
    if dialect_name in {"postgresql", "sqlite"}:
        return text(
            f"CREATE UNIQUE INDEX IF NOT EXISTS {USER_PROVIDER_IDENTITY_INDEX} "
            "ON users (auth_provider, external_id) "
            "WHERE external_id IS NOT NULL"
        )
    return text(
        f"CREATE UNIQUE INDEX {USER_PROVIDER_IDENTITY_INDEX} "
        "ON users (auth_provider, external_id)"
    )


def _has_table_column(
    sync_conn: Connection,
    table_name: str,
    column_name: str,
) -> bool:
    """Return whether a table contains a column using SQLAlchemy inspection."""
    inspector = inspect(sync_conn)
    return any(
        column["name"] == column_name for column in inspector.get_columns(table_name)
    )


def _has_table_index(
    sync_conn: Connection,
    table_name: str,
    index_name: str,
) -> bool:
    """Return whether a table contains an index using SQLAlchemy inspection."""
    inspector = inspect(sync_conn)
    return any(
        index["name"] == index_name for index in inspector.get_indexes(table_name)
    )


async def ensure_agent_document_columns(engine: AsyncEngine) -> None:
    """Repair additive document columns in databases created before Agent CLI."""
    async with engine.begin() as conn:
        if not await conn.run_sync(_has_table_column, "projects", "current_snapshot_id"):
            await conn.execute(text("ALTER TABLE projects ADD COLUMN current_snapshot_id VARCHAR(36)"))
        if not await conn.run_sync(_has_table_column, "snapshots", "is_checkpoint"):
            await conn.execute(text("ALTER TABLE snapshots ADD COLUMN is_checkpoint BOOLEAN NOT NULL DEFAULT FALSE"))
            await conn.execute(text("UPDATE snapshots SET is_checkpoint = TRUE WHERE edit_source = 'AI_GEN'"))
        if await conn.run_sync(_has_table_column, 'projects', 'latest_schema'):
            await conn.run_sync(backfill_document_heads)


def backfill_document_heads(conn: Connection) -> None:
    """Only associate a historical snapshot when its content matches the head."""
    from sqlalchemy import insert, select, update
    from uuid import uuid4
    from app.db.base import utc_now
    from app.models.project import Project
    from app.models.snapshot import Snapshot

    projects = conn.execute(select(Project.project_id, Project.latest_schema).where(
        Project.current_snapshot_id.is_(None), Project.latest_schema.is_not(None))).all()
    for project_id, schema in projects:
        snapshots = conn.execute(select(Snapshot.snapshot_id, Snapshot.schema_blob).where(
            Snapshot.project_id == project_id).order_by(Snapshot.timestamp.desc(), Snapshot.snapshot_id.desc())).all()
        snapshot_id = next((sid for sid, candidate in snapshots if candidate == schema), None)
        if snapshot_id is None:
            snapshot_id = str(uuid4())
            conn.execute(insert(Snapshot).values(snapshot_id=snapshot_id, project_id=project_id,
                schema_blob=schema, edit_source='HUMAN', is_checkpoint=False, timestamp=utc_now()))
        conn.execute(update(Project).where(Project.project_id == project_id,
            Project.current_snapshot_id.is_(None)).values(current_snapshot_id=snapshot_id))
