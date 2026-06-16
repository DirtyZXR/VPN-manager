"""Tests for NotificationService lazy singleton Bot."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.services.notification_service as ns_module
from app.services.notification_service import (
    NotificationService,
    _get_shared_bot,
    close_shared_bot,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_bot() -> MagicMock:
    """Return a mock that looks enough like aiogram.Bot for our tests."""
    bot = MagicMock()
    session = MagicMock()
    session.close = AsyncMock()
    bot.session = session
    bot.send_message = AsyncMock()
    return bot


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_singleton():
    """Ensure _shared_bot is None before and after each test."""
    ns_module._shared_bot = None
    yield
    ns_module._shared_bot = None


@pytest.fixture
def mock_settings():
    with patch("app.services.notification_service.get_settings") as m:
        m.return_value.bot_token = "test_token_123"
        yield m


# ---------------------------------------------------------------------------
# 1. Singleton — same instance returned on repeated calls
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_shared_bot_returns_same_instance(mock_settings):
    """_get_shared_bot() must return the exact same Bot object every time."""
    created: list = []

    def fake_bot(token):
        bot = _make_mock_bot()
        created.append(bot)
        return bot

    with patch("app.services.notification_service.Bot", side_effect=fake_bot):
        bot1 = await _get_shared_bot()
        bot2 = await _get_shared_bot()
        bot3 = await _get_shared_bot()

    assert bot1 is bot2 is bot3, "Must return the same instance"
    assert len(created) == 1, f"Bot must be created only once, got {len(created)}"


@pytest.mark.asyncio
async def test_get_bot_method_returns_singleton(mock_settings):
    """NotificationService._get_bot() delegates to the shared singleton."""
    created: list = []

    def fake_bot(token):
        bot = _make_mock_bot()
        created.append(bot)
        return bot

    with patch("app.services.notification_service.Bot", side_effect=fake_bot):
        session = MagicMock()
        svc1 = NotificationService(session)
        svc2 = NotificationService(session)

        b1 = await svc1._get_bot()
        b2 = await svc2._get_bot()
        b3 = await svc1._get_bot()

    assert b1 is b2 is b3
    assert len(created) == 1


# ---------------------------------------------------------------------------
# 2. No per-call session.close after send_message
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_notify_does_not_close_bot_session(mock_settings):
    """send-methods must NOT close the bot session after each notification."""
    mock_bot = _make_mock_bot()

    with patch("app.services.notification_service.Bot", return_value=mock_bot):
        session = MagicMock()
        svc = NotificationService(session)

        client = MagicMock()
        client.telegram_id = 111
        client.name = "Test"

        await svc.notify_subscription_deleted(client, "Sub1")
        await svc.notify_subscription_deleted(client, "Sub2")

    # session.close must NOT have been called by the notify methods
    mock_bot.session.close.assert_not_awaited()


@pytest.mark.asyncio
async def test_singleton_reused_across_two_notifications(mock_settings):
    """Bot is not recreated between consecutive notification calls."""
    created: list = []

    def fake_bot(token):
        bot = _make_mock_bot()
        created.append(bot)
        return bot

    with patch("app.services.notification_service.Bot", side_effect=fake_bot):
        session = MagicMock()
        svc = NotificationService(session)

        client = MagicMock()
        client.telegram_id = 222
        client.name = "User"

        await svc.notify_subscription_deleted(client, "Sub A")
        await svc.notify_subscription_deleted(client, "Sub B")

    assert len(created) == 1, "Bot must be created only once across two notifications"


# ---------------------------------------------------------------------------
# 3. close_shared_bot closes session and resets the cache
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_close_shared_bot_closes_session_and_resets(mock_settings):
    """close_shared_bot() must close the HTTP session and reset _shared_bot to None."""
    mock_bot = _make_mock_bot()

    with patch("app.services.notification_service.Bot", return_value=mock_bot):
        # Create the singleton
        await _get_shared_bot()
        assert ns_module._shared_bot is mock_bot

        # Close it
        await close_shared_bot()

    # Session must have been closed
    mock_bot.session.close.assert_awaited_once()
    # Cache must be reset
    assert ns_module._shared_bot is None


@pytest.mark.asyncio
async def test_close_then_get_creates_new_instance(mock_settings):
    """After close_shared_bot(), the next _get_shared_bot() creates a fresh Bot."""
    first_bot = _make_mock_bot()
    second_bot = _make_mock_bot()
    bots = iter([first_bot, second_bot])

    with patch("app.services.notification_service.Bot", side_effect=lambda token: next(bots)):
        b1 = await _get_shared_bot()
        await close_shared_bot()
        b2 = await _get_shared_bot()

    assert b1 is not b2, "After close, a new Bot instance must be created"
    assert ns_module._shared_bot is second_bot


@pytest.mark.asyncio
async def test_close_shared_bot_noop_when_none(mock_settings):
    """close_shared_bot() is safe to call when no singleton has been created yet."""
    assert ns_module._shared_bot is None
    # Must not raise
    await close_shared_bot()
    assert ns_module._shared_bot is None
