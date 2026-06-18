"""Tests for bug fixes C2, C7, C9."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.database.models.notification_log import NotificationLevel, NotificationType
from app.services import ClientService

# ---------------------------------------------------------------------------
# C2: _build_expiry_message — корректный выбор time_text по notification_type
# ---------------------------------------------------------------------------

class TestBuildExpiryMessage:
    """Unit tests for NotificationChecker._build_expiry_message (C2 fix)."""

    def _make_checker(self):
        """Create a NotificationChecker with a mocked session (no DB needed)."""
        from app.services.notification_checker import NotificationChecker

        mock_session = MagicMock()
        with patch("app.services.notification_checker.NotificationService"):
            checker = NotificationChecker(mock_session)
        return checker

    def _make_subscription(self, name="Sub", expiry_date=None):
        """Return a minimal mock Subscription."""
        sub = MagicMock()
        sub.id = 1
        sub.name = name
        sub.expiry_date = expiry_date
        sub.inbound_connections = []
        return sub

    def test_expiry_24h_message_contains_correct_time_text(self):
        """_build_expiry_message with EXPIRY_24H should say 'через 24 часа'."""
        checker = self._make_checker()
        sub = self._make_subscription()

        msg = checker._build_expiry_message(
            notification_type=NotificationType.EXPIRY_24H.value,
            subscriptions=[sub],
            level=NotificationLevel.SUBSCRIPTION.value,
        )

        assert "через 24 часа" in msg

    def test_expiry_12h_message_contains_correct_time_text(self):
        """_build_expiry_message with EXPIRY_12H should say 'через 12 часов'."""
        checker = self._make_checker()
        sub = self._make_subscription()

        msg = checker._build_expiry_message(
            notification_type=NotificationType.EXPIRY_12H.value,
            subscriptions=[sub],
            level=NotificationLevel.SUBSCRIPTION.value,
        )

        assert "через 12 часов" in msg

    def test_expiry_1h_message_contains_correct_time_text(self):
        """_build_expiry_message with EXPIRY_1H should say 'через 1 час'."""
        checker = self._make_checker()
        sub = self._make_subscription()

        msg = checker._build_expiry_message(
            notification_type=NotificationType.EXPIRY_1H.value,
            subscriptions=[sub],
            level=NotificationLevel.SUBSCRIPTION.value,
        )

        assert "через 1 час" in msg

    def test_expiry_24h_does_not_say_1h(self):
        """Regression: before the fix EXPIRY_24H fell through to '1 час'."""
        checker = self._make_checker()
        sub = self._make_subscription()

        msg = checker._build_expiry_message(
            notification_type=NotificationType.EXPIRY_24H.value,
            subscriptions=[sub],
            level=NotificationLevel.SUBSCRIPTION.value,
        )

        assert "через 1 час" not in msg


# ---------------------------------------------------------------------------
# C7: search_clients_all_fields — клиент без подписок находится по имени
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_finds_client_without_subscriptions(test_session):
    """Clients with no subscriptions must appear in search results (C7 fix)."""
    service = ClientService(test_session)

    # Create a client with no subscriptions
    client = await service.create_client(
        name="NoSubsClient",
        email="nosubs@example.com",
    )
    await test_session.flush()

    results = await service.search_clients_all_fields("NoSubsClient")

    ids = [c.id for c in results]
    assert client.id in ids, (
        "search_clients_all_fields должен находить клиентов без подписок"
    )


@pytest.mark.asyncio
async def test_search_finds_client_without_subscriptions_by_email(test_session):
    """Clients with no subscriptions found by email fragment (C7 fix)."""
    service = ClientService(test_session)

    client = await service.create_client(
        name="AnotherNoSubs",
        email="uniquefragment@example.com",
    )
    await test_session.flush()

    results = await service.search_clients_all_fields("uniquefragment")

    ids = [c.id for c in results]
    assert client.id in ids


# ---------------------------------------------------------------------------
# C9: delete_client_all_connections — orphan InboundConnection удаляются из БД
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_client_all_connections_deletes_db_records(test_session):
    """After delete_client_all_connections each InboundConnection is passed
    to session.delete(), preventing orphan rows (C9 fix).

    We mock the VPN provider and spy on session.delete to verify the call
    without requiring a live panel.
    """
    from unittest.mock import patch

    from app.services.new_subscription_service import NewSubscriptionService

    # Build a mock connection
    mock_connection = MagicMock()
    mock_connection.inbound = MagicMock()
    mock_connection.inbound.server = MagicMock()

    # Build a mock subscription containing that connection
    mock_sub = MagicMock()
    mock_sub.inbound_connections = [mock_connection]

    # Mock the DB query so it returns our fake subscription
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_sub]

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.delete = AsyncMock()
    mock_session.flush = AsyncMock()

    svc = NewSubscriptionService(mock_session)

    # Mock provider so remove_client doesn't fail
    mock_provider = AsyncMock()
    mock_provider.remove_client = AsyncMock()

    with patch.object(svc, "_get_provider", return_value=mock_provider):
        count = await svc.delete_client_all_connections(client_id=1)

    # The fix: session.delete must have been called for the connection
    mock_session.delete.assert_awaited_once_with(mock_connection)
    mock_session.flush.assert_awaited_once()
    assert count == 1


@pytest.mark.asyncio
async def test_delete_client_all_connections_deletes_multiple_records(test_session):
    """All connections across multiple subscriptions are deleted from DB."""
    from unittest.mock import patch

    from app.services.new_subscription_service import NewSubscriptionService

    conn1, conn2 = MagicMock(), MagicMock()
    for conn in (conn1, conn2):
        conn.inbound = MagicMock()
        conn.inbound.server = MagicMock()

    sub1, sub2 = MagicMock(), MagicMock()
    sub1.inbound_connections = [conn1]
    sub2.inbound_connections = [conn2]

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [sub1, sub2]

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.delete = AsyncMock()
    mock_session.flush = AsyncMock()

    svc = NewSubscriptionService(mock_session)

    mock_provider = AsyncMock()
    mock_provider.remove_client = AsyncMock()

    with patch.object(svc, "_get_provider", return_value=mock_provider):
        count = await svc.delete_client_all_connections(client_id=42)

    assert mock_session.delete.await_count == 2
    mock_session.flush.assert_awaited_once()
    assert count == 2
