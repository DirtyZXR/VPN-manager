"""Client service for managing VPN clients."""

from typing import Sequence
from loguru import logger

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import Client
from app.utils import generate_email


class ClientService:
    """Service for client management."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize service with database session.

        Args:
            session: Async database session
        """
        self.session = session

    async def get_all_clients(self) -> Sequence[Client]:
        """Get all clients.

        Returns:
            List of all clients
        """
        result = await self.session.execute(
            select(Client)
            .options(selectinload(Client.subscriptions))
            .order_by(Client.created_at.desc())
        )
        return result.scalars().all()

    async def get_active_clients(self) -> Sequence[Client]:
        """Get all active clients.

        Returns:
            List of active clients
        """
        result = await self.session.execute(
            select(Client)
            .where(Client.is_active == True)
            .options(selectinload(Client.subscriptions))
            .order_by(Client.created_at.desc())
        )
        return result.scalars().all()

    async def get_client_by_id(self, client_id: int) -> Client | None:
        """Get client by ID.

        Args:
            client_id: Client ID

        Returns:
            Client or None if not found
        """
        result = await self.session.execute(
            select(Client)
            .where(Client.id == client_id)
            .options(selectinload(Client.subscriptions))
        )
        return result.scalar_one_or_none()

    async def get_client_by_email(self, email: str) -> Client | None:
        """Get client by email.

        Args:
            email: Client email

        Returns:
            Client or None if not found
        """
        result = await self.session.execute(
            select(Client).where(Client.email == email)
        )
        return result.scalar_one_or_none()

    async def get_client_by_telegram_id(self, telegram_id: int) -> Client | None:
        """Get client by Telegram ID.

        Args:
            telegram_id: Client Telegram ID

        Returns:
            Client or None if not found
        """
        result = await self.session.execute(
            select(Client).where(Client.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()

    async def create_client(
        self,
        name: str,
        email: str | None = None,
        telegram_id: int | None = None,
        notes: str | None = None,
        is_admin: bool = False,
    ) -> Client:
        """Create a new client.

        Args:
            name: Client name
            email: Client email (generated if not provided)
            telegram_id: Optional Telegram ID
            notes: Optional notes
            is_admin: Whether client is admin

        Returns:
            Created client
        """
        if email is None:
            email = generate_email(name, "vpn", "client")

        client = Client(
            name=name,
            email=email,
            telegram_id=telegram_id,
            notes=notes,
            is_active=True,
            is_admin=is_admin,
        )
        self.session.add(client)
        await self.session.flush()
        return client

    async def update_client(
        self,
        client_id: int,
        name: str | None = None,
        email: str | None = None,
        telegram_id: int | None = None,
        notes: str | None = None,
        is_active: bool | None = None,
        is_admin: bool | None = None,
    ) -> Client | None:
        """Update client.

        Args:
            client_id: Client ID
            name: New name (optional)
            email: New email (optional)
            telegram_id: New Telegram ID (optional)
            notes: New notes (optional)
            is_active: New active status (optional)
            is_admin: New admin status (optional)

        Returns:
            Updated client or None if not found
        """
        client = await self.get_client_by_id(client_id)
        if not client:
            return None

        # Track if Telegram ID is being updated
        telegram_id_changed = False
        if telegram_id is not None and telegram_id != client.telegram_id:
            telegram_id_changed = True

        if name is not None:
            client.name = name
        if email is not None:
            client.email = email
        if telegram_id is not None:
            client.telegram_id = telegram_id
        if notes is not None:
            client.notes = notes
        if is_active is not None:
            client.is_active = is_active
        if is_admin is not None:
            client.is_admin = is_admin

        await self.session.flush()

        # Sync Telegram ID to XUI if changed
        if telegram_id_changed:
            try:
                from app.services.new_subscription_service import NewSubscriptionService
                sub_service = NewSubscriptionService(self.session)
                updated = await sub_service.sync_client_telegram_id(client_id)
                logger.info(f"✅ Synced Telegram ID for client {client_id}, updated {updated} connections in XUI")
                await sub_service.close_all_clients()
            except Exception as e:
                logger.error(f"Failed to sync Telegram ID for client {client_id}: {e}", exc_info=True)

        return client

    async def delete_client(self, client_id: int) -> bool:
        """Delete client.

        Args:
            client_id: Client ID

        Returns:
            True if deleted, False if not found
        """
        client = await self.get_client_by_id(client_id)
        if not client:
            return False

        await self.session.delete(client)
        await self.session.flush()
        return True

    async def set_client_active(self, client_id: int, is_active: bool) -> Client | None:
        """Set client active status.

        Args:
            client_id: Client ID
            is_active: Active status

        Returns:
            Updated client or None if not found
        """
        return await self.update_client(client_id, is_active=is_active)

    async def rename_client(self, client_id: int, new_name: str) -> Client | None:
        """Rename client.

        Args:
            client_id: Client ID
            new_name: New name

        Returns:
            Updated client or None if not found
        """
        return await self.update_client(client_id, name=new_name)

    async def set_client_admin(self, client_id: int, is_admin: bool) -> Client | None:
        """Set client admin status.

        Args:
            client_id: Client ID
            is_admin: Admin status

        Returns:
            Updated client or None if not found
        """
        return await self.update_client(client_id, is_admin=is_admin)