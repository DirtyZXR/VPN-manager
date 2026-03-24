"""Test sync service functionality."""

import pytest
from datetime import datetime, timedelta, timezone

from app.database.models import Server, Inbound, InboundConnection, Subscription, Client
from app.services.sync_service import SyncService


@pytest.mark.asyncio
async def test_sync_service_initialization(test_session, mock_settings):
    """Test that SyncService initializes correctly."""
    service = SyncService(test_session)
    assert service.session == test_session
    assert service._is_running is False


@pytest.mark.asyncio
async def test_needs_sync_new_model(test_session, mock_settings):
    """Test that new models need sync."""
    service = SyncService(test_session)

    # Create server without sync fields
    server = Server(
        name="TestServer",
        url="https://test.com",
        username="admin",
        password_encrypted="encrypted",
        is_active=True,
    )
    test_session.add(server)
    await test_session.flush()

    # Should need sync (last_sync_at is None)
    assert service._needs_sync(server) is True


@pytest.mark.asyncio
async def test_needs_sync_recent_sync(test_session, mock_settings):
    """Test that recently synced models don't need sync."""
    service = SyncService(test_session)

    # Create server with recent sync
    server = Server(
        name="TestServer",
        url="https://test.com",
        username="admin",
        password_encrypted="encrypted",
        is_active=True,
        last_sync_at=datetime.now(timezone.utc),
        sync_status="synced",
    )
    test_session.add(server)
    await test_session.flush()

    # Should not need sync (sync was recent)
    assert service._needs_sync(server) is False


@pytest.mark.asyncio
async def test_needs_sync_stale_sync(test_session, mock_settings):
    """Test that stale models need sync."""
    service = SyncService(test_session)

    # Create server with old sync
    old_sync_time = datetime.now(timezone.utc) - timedelta(minutes=10)
    server = Server(
        name="TestServer",
        url="https://test.com",
        username="admin",
        password_encrypted="encrypted",
        is_active=True,
        last_sync_at=old_sync_time,
        sync_status="synced",
    )
    test_session.add(server)
    await test_session.flush()

    # Should need sync (sync was more than 5 minutes ago)
    assert service._needs_sync(server) is True


@pytest.mark.asyncio
async def test_needs_sync_error_status(test_session, mock_settings):
    """Test that models with error status need sync."""
    service = SyncService(test_session)

    # Create server with error status
    server = Server(
        name="TestServer",
        url="https://test.com",
        username="admin",
        password_encrypted="encrypted",
        is_active=True,
        last_sync_at=datetime.now(timezone.utc),
        sync_status="error",
        sync_error="Previous error",
    )
    test_session.add(server)
    await test_session.flush()

    # Should need sync (status is error)
    assert service._needs_sync(server) is True


@pytest.mark.asyncio
async def test_needs_sync_offline_status(test_session, mock_settings):
    """Test that offline models need sync."""
    service = SyncService(test_session)

    # Create server with offline status
    server = Server(
        name="TestServer",
        url="https://test.com",
        username="admin",
        password_encrypted="encrypted",
        is_active=True,
        last_sync_at=datetime.now(timezone.utc),
        sync_status="offline",
        sync_error="Connection failed",
    )
    test_session.add(server)
    await test_session.flush()

    # Should need sync (status is offline)
    assert service._needs_sync(server) is True


@pytest.mark.asyncio
async def test_manual_sync_connection(test_session, mock_settings):
    """Test manual sync for connection."""
    service = SyncService(test_session)

    # Create inbound connection
    inbound = Inbound(
        id=1,
        server_id=1,
        xui_id=1,
        remark="TestInbound",
        protocol="vless",
        port=443,
        settings_json='{}',
        client_count=0,
        is_active=True,
    )
    test_session.add(inbound)

    from app.database.models import InboundConnection, Subscription, Client

    client = Client(
        id=1,
        name="TestClient",
        email="test@client.com",
        telegram_id=123456789,
        is_admin=False,
        is_active=True,
    )
    test_session.add(client)

    subscription = Subscription(
        id=1,
        client_id=1,
        name="TestSub",
        subscription_token="test_token",
        total_gb=100,
        expiry_date=datetime.now(timezone.utc) + timedelta(days=30),
        is_active=True,
    )
    test_session.add(subscription)

    connection = InboundConnection(
        id=1,
        subscription_id=1,
        inbound_id=1,
        xui_client_id="uuid-1",
        email="test@vpn.local",
        uuid="uuid-1",
        is_enabled=True,
    )
    test_session.add(connection)
    await test_session.flush()

    # Manual sync should update sync status
    results = await service.manual_sync("connection", connection.id)
    assert results["synced"] == 1
    assert results["errors"] == 0


@pytest.mark.asyncio
async def test_manual_sync_all(test_session, mock_settings):
    """Test manual sync for all entities."""
    service = SyncService(test_session)

    # Create test server
    server = Server(
        name="TestServer",
        url="https://test.com",
        username="admin",
        password_encrypted="encrypted",
        is_active=True,
    )
    test_session.add(server)
    await test_session.flush()

    # Manual sync should work (though may not actually sync anything)
    results = await service.manual_sync("all")
    assert "synced" in results
    assert "errors" in results
