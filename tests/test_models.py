"""Tests for database models."""

import pytest
from datetime import datetime, timezone, timedelta

from app.database.models import Client, Server, Subscription, Inbound, InboundConnection


@pytest.mark.asyncio
async def test_client_model(test_session):
    """Test Client model."""
    client = Client(
        name="Test Client",
        email="test@example.com",
        telegram_id=789012,
        notes="Test notes",
        is_active=True,
        is_admin=False,
    )
    test_session.add(client)
    await test_session.flush()

    assert client.id is not None
    assert isinstance(client.created_at, datetime)
    assert client.is_admin is False
    assert str(client) == "<Client(id=1, name='Test Client', email='test@example.com')>"


@pytest.mark.asyncio
async def test_client_admin_model(test_session):
    """Test Client model with admin status."""
    client = Client(
        name="Admin Client",
        email="admin@example.com",
        telegram_id=123456,
        is_admin=True,
        is_active=True,
    )
    test_session.add(client)
    await test_session.flush()

    assert client.id is not None
    assert client.is_admin is True
    assert client.is_active is True


@pytest.mark.asyncio
async def test_server_model(test_session):
    """Test Server model."""
    server = Server(
        name="Test Server",
        url="https://test.example.com",
        username="admin",
        password_encrypted="encrypted_password",
        is_active=True,
    )
    test_session.add(server)
    await test_session.flush()

    assert server.id is not None
    assert isinstance(server.created_at, datetime)
    assert str(server) == "<Server(id=1, name='Test Server', url='https://test.example.com')>"


@pytest.mark.asyncio
async def test_subscription_model(test_session):
    """Test Subscription model."""
    client = Client(name="Test Client", email="test@example.com")
    test_session.add(client)
    await test_session.flush()

    subscription = Subscription(
        client_id=client.id,
        name="Test Subscription",
        subscription_token="test_token_123",
        total_gb=100,
        expiry_date=datetime.now(timezone.utc) + timedelta(days=30),
        is_active=True,
    )
    test_session.add(subscription)
    await test_session.flush()

    assert subscription.id is not None
    assert subscription.client_id == client.id
    assert subscription.is_unlimited is False
    assert 25 <= subscription.remaining_days <= 30  # Allow for timing differences
    assert subscription.is_expired is False


@pytest.mark.asyncio
async def test_subscription_unlimited(test_session):
    """Test Subscription with unlimited traffic."""
    client = Client(name="Test Client", email="test@example.com")
    test_session.add(client)
    await test_session.flush()

    subscription = Subscription(
        client_id=client.id,
        name="Unlimited Subscription",
        subscription_token="unlimited_token",
        total_gb=0,  # Unlimited
        expiry_date=None,  # Never expires
        is_active=True,
    )
    test_session.add(subscription)
    await test_session.flush()

    assert subscription.is_unlimited is True
    assert subscription.remaining_days is None
    assert subscription.is_expired is False


@pytest.mark.asyncio
async def test_inbound_model(test_session):
    """Test Inbound model."""
    server = Server(
        name="Test Server",
        url="https://test.example.com",
        username="admin",
        password_encrypted="encrypted_password",
    )
    test_session.add(server)
    await test_session.flush()

    inbound = Inbound(
        server_id=server.id,
        xui_id=1,
        remark="Test Inbound",
        protocol="vless",
        port=443,
        settings_json="{}",
        client_count=5,
        is_active=True,
    )
    test_session.add(inbound)
    await test_session.flush()

    assert inbound.id is not None
    assert inbound.server_id == server.id
    assert inbound.client_count == 5
    assert str(inbound) == "<Inbound(id=1, remark='Test Inbound', protocol='vless', clients=5)>"


@pytest.mark.asyncio
async def test_inbound_connection_model(test_session):
    """Test InboundConnection model."""
    client = Client(name="Test Client", email="test@example.com")
    test_session.add(client)
    await test_session.flush()

    subscription = Subscription(
        client_id=client.id,
        name="Test Subscription",
        subscription_token="test_token",
        total_gb=100,
        is_active=True,
    )
    test_session.add(subscription)
    await test_session.flush()

    server = Server(
        name="Test Server",
        url="https://test.example.com",
        username="admin",
        password_encrypted="encrypted_password",
    )
    test_session.add(server)
    await test_session.flush()

    inbound = Inbound(
        server_id=server.id,
        xui_id=1,
        remark="Test Inbound",
        protocol="vless",
        port=443,
        settings_json="{}",
        client_count=0,
        is_active=True,
    )
    test_session.add(inbound)
    await test_session.flush()

    connection = InboundConnection(
        subscription_id=subscription.id,
        inbound_id=inbound.id,
        xui_client_id="test-uuid",
        email="test-connection@example.com",
        uuid="test-uuid-123",
        is_enabled=True,
    )
    test_session.add(connection)
    await test_session.flush()

    assert connection.id is not None
    assert connection.subscription_id == subscription.id
    assert connection.inbound_id == inbound.id
    assert connection.is_enabled is True
    assert str(connection) == "<InboundConnection(id=1, uuid='test-uuid-123', enabled=True)>"


@pytest.mark.asyncio
async def test_subscription_expiry(test_session):
    """Test Subscription expiry logic."""
    client = Client(name="Test Client", email="test@example.com")
    test_session.add(client)
    await test_session.flush()

    # Expired subscription
    expired_sub = Subscription(
        client_id=client.id,
        name="Expired Subscription",
        subscription_token="expired_token",
        total_gb=100,
        expiry_date=datetime.now(timezone.utc) - timedelta(days=1),
        is_active=True,
    )
    test_session.add(expired_sub)
    await test_session.flush()

    assert expired_sub.is_expired is True

    # Active subscription
    active_sub = Subscription(
        client_id=client.id,
        name="Active Subscription",
        subscription_token="active_token",
        total_gb=100,
        expiry_date=datetime.now(timezone.utc) + timedelta(days=30),
        is_active=True,
    )
    test_session.add(active_sub)
    await test_session.flush()

    assert active_sub.is_expired is False
    assert 25 <= active_sub.remaining_days <= 30  # Allow for timing differences

    # Never expires
    never_expires = Subscription(
        client_id=client.id,
        name="Never Expires",
        subscription_token="never_token",
        total_gb=100,
        expiry_date=None,
        is_active=True,
    )
    test_session.add(never_expires)
    await test_session.flush()

    assert never_expires.is_expired is False
    assert never_expires.remaining_days is None