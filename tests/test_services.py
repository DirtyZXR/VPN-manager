"""Tests for services."""

import pytest
from sqlalchemy.exc import IntegrityError

from app.services import ClientService


@pytest.mark.asyncio
async def test_client_service_create_client(test_session):
    """Test client creation."""
    service = ClientService(test_session)

    client = await service.create_client(
        name="Test Client",
        email="test@example.com",
        telegram_id=789012,
    )

    assert client.id is not None
    assert client.name == "Test Client"
    assert client.email == "test@example.com"
    assert client.telegram_id == 789012
    assert client.is_active is True
    assert client.is_admin is False


@pytest.mark.asyncio
async def test_client_service_create_admin_client(test_session):
    """Test admin client creation."""
    service = ClientService(test_session)

    client = await service.create_client(
        name="Admin Client",
        email="admin@example.com",
        telegram_id=123456,
        is_admin=True,
    )

    assert client.id is not None
    assert client.name == "Admin Client"
    assert client.is_admin is True


@pytest.mark.asyncio
async def test_client_service_create_client_auto_email(test_session):
    """Test client creation with auto-generated email."""
    service = ClientService(test_session)

    client = await service.create_client(
        name="Auto Client",
        # email=None will generate automatically
    )

    assert client.id is not None
    assert client.name == "Auto Client"
    assert client.email is not None  # Should be auto-generated
    assert "@" in client.email


@pytest.mark.asyncio
async def test_client_service_get_by_id(test_session):
    """Test getting client by ID."""
    service = ClientService(test_session)

    created = await service.create_client(
        name="Test Client",
        email="test@example.com",
    )
    await test_session.flush()

    found = await service.get_client_by_id(created.id)

    assert found is not None
    assert found.id == created.id
    assert found.name == "Test Client"


@pytest.mark.asyncio
async def test_client_service_get_by_email(test_session):
    """Test getting client by email."""
    service = ClientService(test_session)

    created = await service.create_client(
        name="Test Client",
        email="unique@example.com",
    )
    await test_session.flush()

    found = await service.get_client_by_email("unique@example.com")

    assert found is not None
    assert found.id == created.id
    assert found.email == "unique@example.com"


@pytest.mark.asyncio
async def test_client_service_get_by_telegram_id(test_session):
    """Test getting client by Telegram ID."""
    service = ClientService(test_session)

    created = await service.create_client(
        name="Test Client",
        email="test@example.com",
        telegram_id=789012,
    )
    await test_session.flush()

    found = await service.get_client_by_telegram_id(789012)

    assert found is not None
    assert found.id == created.id
    assert found.telegram_id == 789012


@pytest.mark.asyncio
async def test_client_service_get_all_clients(test_session):
    """Test getting all clients."""
    service = ClientService(test_session)

    await service.create_client(name="Client 1", email="client1@example.com")
    await service.create_client(name="Client 2", email="client2@example.com")
    await service.create_client(name="Client 3", email="client3@example.com")
    await test_session.flush()

    clients = await service.get_all_clients()

    assert len(clients) == 3
    assert all(c.name.startswith("Client") for c in clients)


@pytest.mark.asyncio
async def test_client_service_get_active_clients(test_session):
    """Test getting active clients."""
    service = ClientService(test_session)

    await service.create_client(name="Active Client", email="active@example.com")
    await service.create_client(name="Inactive Client", email="inactive@example.com")
    await test_session.flush()

    # Mark one as inactive
    inactive = await service.get_client_by_email("inactive@example.com")
    await service.set_client_active(inactive.id, False)
    await test_session.flush()

    active_clients = await service.get_active_clients()

    assert len(active_clients) == 1
    assert active_clients[0].name == "Active Client"


@pytest.mark.asyncio
async def test_client_service_update_client(test_session):
    """Test client update."""
    service = ClientService(test_session)

    client = await service.create_client(
        name="Old Name",
        email="test@example.com",
    )
    await test_session.flush()

    updated = await service.update_client(
        client.id,
        name="New Name",
        notes="Updated notes",
    )

    assert updated is not None
    assert updated.name == "New Name"
    assert updated.notes == "Updated notes"


@pytest.mark.asyncio
async def test_client_service_set_admin(test_session):
    """Test setting client admin status."""
    service = ClientService(test_session)

    client = await service.create_client(
        name="Regular Client",
        email="regular@example.com",
        is_admin=False,
    )
    await test_session.flush()

    # Make admin
    updated = await service.set_client_admin(client.id, True)
    assert updated is not None
    assert updated.is_admin is True

    # Remove admin
    updated = await service.set_client_admin(client.id, False)
    assert updated is not None
    assert updated.is_admin is False


@pytest.mark.asyncio
async def test_client_service_delete_client(test_session):
    """Test client deletion."""
    service = ClientService(test_session)

    client = await service.create_client(
        name="Test Client",
        email="test@example.com",
    )
    await test_session.flush()

    deleted = await service.delete_client(client.id)

    assert deleted is True

    # Verify client is deleted
    found = await service.get_client_by_id(client.id)
    assert found is None


@pytest.mark.asyncio
async def test_client_service_unique_email(test_session):
    """Test client email uniqueness."""
    service = ClientService(test_session)

    # First client should succeed
    await service.create_client(
        name="Client 1",
        email="same@example.com",
    )
    await test_session.flush()

    # Second client with same email should fail
    with pytest.raises(IntegrityError):
        await service.create_client(
            name="Client 2",
            email="same@example.com",
        )
        await test_session.flush()


@pytest.mark.asyncio
async def test_client_service_unique_telegram_username(test_session):
    """Test client telegram_username uniqueness."""
    service = ClientService(test_session)

    # First client should succeed
    await service.create_client(
        name="Client 1",
        email="client1@example.com",
        telegram_username="@user1",
    )
    await test_session.flush()

    # Second client with same telegram_username should fail
    with pytest.raises(IntegrityError):
        await service.create_client(
            name="Client 2",
            email="client2@example.com",
            telegram_username="@user1",
        )
        await test_session.flush()
