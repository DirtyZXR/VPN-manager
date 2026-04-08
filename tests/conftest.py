"""Pytest configuration and fixtures."""

import asyncio
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database.models.base import Base

# Database URL for tests
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    """Create test database engine."""
    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def test_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Create test database session."""
    async_session_maker = async_sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with async_session_maker() as session:
        yield session
        await session.rollback()


@pytest.fixture
def mock_settings():
    """Mock settings for testing."""
    from unittest.mock import patch

    # Static Fernet key for consistent testing
    static_fernet_key = "SpWH-ifTebQwpAlasE5SvZsgUwi0onGmILmSrm7G1BQ="

    with patch("app.config.get_settings") as mock:
        settings = mock.return_value
        settings.bot_token = "test_token"
        settings.admin_telegram_ids = "123456789"
        settings.database_url = TEST_DATABASE_URL
        settings.encryption_key = static_fernet_key
        settings.log_level = "DEBUG"
        settings.xui_timeout = 30
        settings.admin_ids = {123456789}
        yield settings
