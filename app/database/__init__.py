"""Database connection and session management."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


def _get_engine():
    """Get database engine (lazy loaded)."""
    from app.config import get_settings
    settings = get_settings()
    return create_async_engine(
        settings.database_url,
        echo=settings.log_level == "DEBUG",
    )


def _get_session_factory():
    """Get session factory (lazy loaded)."""
    return async_sessionmaker(
        _get_engine(),
        class_=AsyncSession,
        expire_on_commit=False,
    )


engine = _get_engine()
async_session_factory = _get_session_factory()


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Get async database session."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """Initialize database tables."""
    from app.database.models.base import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
