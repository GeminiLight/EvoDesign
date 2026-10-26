from typing import AsyncGenerator

from fastapi import HTTPException
from loguru import logger
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings
from app.db.bootstrap import initialize_database_schema

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Return the lazily configured async database engine."""
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            echo=settings.debug,
            future=True,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the lazily configured async session factory."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )
    return _session_factory


def create_db_session() -> AsyncSession:
    """Create an async DB session outside FastAPI dependency injection."""
    return get_session_factory()()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield a database session and commit only after successful request handling."""
    async with create_db_session() as session:
        try:
            yield session
        except HTTPException:
            await session.rollback()
            raise
        except SQLAlchemyError as exc:
            await session.rollback()
            logger.opt(exception=exc).error("Database transaction failed")
            raise
        except Exception as exc:
            # Non-database handler errors still need explicit transaction cleanup.
            await session.rollback()
            logger.debug(
                "Rolling back database session after downstream exception: {}",
                type(exc).__name__,
            )
            raise
        else:
            try:
                await session.commit()
            except SQLAlchemyError as exc:
                await session.rollback()
                logger.opt(exception=exc).error("Database commit failed")
                raise
            except Exception as exc:
                # Preserve unusual commit failures while keeping rollback deterministic.
                await session.rollback()
                logger.opt(exception=exc).error("Unexpected database commit failure")
                raise
        finally:
            await session.close()


async def init_db() -> None:
    """Initialize database schema using the configured engine."""
    await initialize_database_schema(get_engine())


async def close_db() -> None:
    """Close database connection."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
        logger.info("Database connection closed")
