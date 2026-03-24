"""Subscription service for managing client subscriptions."""

from datetime import datetime, timedelta, timezone
from typing import Sequence

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import (
    Client,
    Inbound,
    InboundConnection,
    Server,
    Subscription,
)
from app.utils import generate_subscription_token
from app.xui_client import XUIAddClientRequest, XUIClient, XUIError


class NewSubscriptionService:
    """Service for subscription management with new architecture."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize service with database session.

        Args:
            session: Async database session
        """
        self.session = session
        self._xui_clients: dict[int, XUIClient] = {}

    # Client methods

    async def get_client_subscriptions(self, client_id: int) -> Sequence[Subscription]:
        """Get all subscriptions for client.

        Args:
            client_id: Client ID

        Returns:
            List of subscriptions
        """
        result = await self.session.execute(
            select(Subscription)
            .where(Subscription.client_id == client_id)
            .options(
                selectinload(Subscription.client),
                selectinload(Subscription.inbound_connections).selectinload(
                    InboundConnection.inbound
                ),
            )
            .order_by(Subscription.created_at.desc())
        )
        return result.scalars().all()

    # Subscription methods

    async def get_subscription(self, subscription_id: int) -> Subscription | None:
        """Get subscription by ID.

        Args:
            subscription_id: Subscription ID

        Returns:
            Subscription or None
        """
        result = await self.session.execute(
            select(Subscription)
            .where(Subscription.id == subscription_id)
            .options(
                selectinload(Subscription.client),
                selectinload(Subscription.inbound_connections).selectinload(
                    InboundConnection.inbound
                ).selectinload(Inbound.server),
            )
        )
        return result.scalar_one_or_none()

    async def create_subscription(
        self,
        client_id: int,
        name: str,
        total_gb: int = 0,
        expiry_days: int | None = None,
        notes: str | None = None,
    ) -> Subscription:
        """Create a new subscription.

        Args:
            client_id: Client ID
            name: Subscription name
            total_gb: Traffic limit in GB (0 = unlimited)
            expiry_days: Days until expiry (None = never)
            notes: Optional notes

        Returns:
            Created subscription
        """
        # Calculate expiry date
        expiry_date = None
        if expiry_days:
            expiry_date = datetime.now(timezone.utc) + timedelta(days=expiry_days)

        # Generate unique token
        subscription = Subscription(
            client_id=client_id,
            name=name,
            subscription_token=generate_subscription_token(),
            total_gb=total_gb,
            expiry_date=expiry_date,
            notes=notes,
            is_active=True,
        )
        self.session.add(subscription)
        await self.session.flush()

        # Reload with relationships
        return await self.get_subscription(subscription.id)

    # Inbound Connection methods

    async def add_inbound_to_subscription(
        self,
        subscription_id: int,
        inbound_id: int,
    ) -> InboundConnection:
        """Add inbound connection to subscription.

        Args:
            subscription_id: Subscription ID
            inbound_id: Inbound ID

        Returns:
            Created inbound connection

        Raises:
            XUIError: If inbound already exists in subscription
            XUIError: If XUI client creation fails
            XUIError: If email already exists in this inbound
        """
        # Check if inbound already exists in subscription
        existing = await self.session.execute(
            select(InboundConnection).where(
                InboundConnection.subscription_id == subscription_id,
                InboundConnection.inbound_id == inbound_id,
            )
        )
        if existing.scalar_one_or_none():
            raise XUIError("Inbound already exists in this subscription")

        # Get subscription and inbound
        subscription = await self.get_subscription(subscription_id)
        if not subscription:
            raise XUIError("Subscription not found")

        inbound = await self.session.execute(
            select(Inbound)
            .where(Inbound.id == inbound_id)
            .options(selectinload(Inbound.server))
        )
        inbound = inbound.scalar_one_or_none()
        if not inbound:
            raise XUIError("Inbound not found")

        # Generate UUID and email with uniqueness check
        import uuid
        client_uuid = str(uuid.uuid4())

        # Generate unique email for this inbound
        base_email = f"{subscription.client.name}_{subscription.name}_{inbound.remark}@vpn.local"
        client_email = await self._generate_unique_email(inbound_id, base_email)

        # Calculate expiry time for XUI
        expiry_time = 0
        if subscription.expiry_date:
            expiry_time = int(subscription.expiry_date.timestamp() * 1000)

        # Create client in XUI
        client_request = XUIAddClientRequest(
            id=client_uuid,
            email=client_email,
            enable=True,
            flow="xtls-rprx-vision",
            totalGB=subscription.total_gb * 1024 * 1024 * 1024,  # Convert GB to bytes
            expiryTime=expiry_time,
            subId=subscription.subscription_token,
        )

        xui_client = await self._get_xui_client(inbound.server)
        await xui_client.add_client(inbound.xui_id, client_request)

        # Create inbound connection
        connection = InboundConnection(
            subscription_id=subscription_id,
            inbound_id=inbound_id,
            xui_client_id=client_uuid,
            email=client_email,
            uuid=client_uuid,
            is_enabled=True,
        )
        self.session.add(connection)
        await self.session.flush()

        # Update inbound client count
        inbound.client_count += 1

        return connection

    async def remove_inbound_from_subscription(
        self,
        subscription_id: int,
        inbound_id: int,
    ) -> bool:
        """Remove inbound connection from subscription.

        Args:
            subscription_id: Subscription ID
            inbound_id: Inbound ID

        Returns:
            True if removed
        """
        connection = await self.session.execute(
            select(InboundConnection).where(
                InboundConnection.subscription_id == subscription_id,
                InboundConnection.inbound_id == inbound_id,
            )
        )
        connection = connection.scalar_one_or_none()
        if not connection:
            return False

        # Get inbound info
        inbound = await self.session.execute(
            select(Inbound).where(Inbound.id == inbound_id)
        )
        inbound = inbound.scalar_one_or_none()

        # Delete from XUI
        if inbound:
            xui_client = await self._get_xui_client(inbound)
            await xui_client.delete_client(inbound.xui_id, connection.uuid)
            inbound.client_count -= 1

        # Delete from database
        await self.session.delete(connection)
        await self.session.flush()
        return True

    async def toggle_inbound_connection(
        self,
        connection_id: int,
        enable: bool,
    ) -> InboundConnection | None:
        """Enable or disable inbound connection.

        Args:
            connection_id: Connection ID
            enable: True to enable, False to disable

        Returns:
            Updated connection or None
        """
        connection = await self.session.execute(
            select(InboundConnection)
            .where(InboundConnection.id == connection_id)
            .options(selectinload(InboundConnection.inbound))
        )
        connection = connection.scalar_one_or_none()
        if not connection:
            return None

        # Update in XUI
        inbound = connection.inbound
        xui_client = await self._get_xui_client(inbound)
        await xui_client.enable_client(inbound.xui_id, connection.uuid, enable)

        # Update in database
        connection.is_enabled = enable
        await self.session.flush()

        return connection

    async def toggle_client_all_connections(
        self,
        client_id: int,
        enable: bool,
    ) -> int:
        """Enable or disable all inbound connections for a client.

        Args:
            client_id: Client ID
            enable: True to enable, False to disable

        Returns:
            Number of connections toggled
        """
        # Get all subscriptions for client
        result = await self.session.execute(
            select(Subscription)
            .where(Subscription.client_id == client_id)
            .options(
                selectinload(Subscription.inbound_connections)
                .selectinload(InboundConnection.inbound)
                .selectinload(Inbound.server)
            )
        )
        subscriptions = result.scalars().all()

        toggled_count = 0
        for subscription in subscriptions:
            for connection in subscription.inbound_connections:
                # Update in XUI
                inbound = connection.inbound
                xui_client = await self._get_xui_client(inbound.server)
                await xui_client.enable_client(inbound.xui_id, connection.uuid, enable)

                # Update in database
                connection.is_enabled = enable
                toggled_count += 1

        await self.session.flush()
        return toggled_count

    async def delete_client_all_connections(self, client_id: int) -> int:
        """Delete all XUI clients for a client.

        Args:
            client_id: Client ID

        Returns:
            Number of connections deleted from XUI
        """
        # Get all subscriptions for client
        result = await self.session.execute(
            select(Subscription)
            .where(Subscription.client_id == client_id)
            .options(
                selectinload(Subscription.inbound_connections)
                .selectinload(InboundConnection.inbound)
                .selectinload(Inbound.server)
            )
        )
        subscriptions = result.scalars().all()

        deleted_count = 0
        for subscription in subscriptions:
            for connection in subscription.inbound_connections:
                # Delete from XUI
                inbound = connection.inbound
                try:
                    xui_client = await self._get_xui_client(inbound.server)
                    await xui_client.delete_client(inbound.xui_id, connection.uuid)
                    deleted_count += 1
                except Exception as e:
                    logger.warning(f"Failed to delete client from XUI: {e}")

        return deleted_count

    # Helper methods

    async def _generate_unique_email(
        self,
        inbound_id: int,
        base_email: str,
        max_attempts: int = 100,
    ) -> str:
        """Generate unique email for inbound.

        Checks if email already exists in this inbound and adds suffix if needed.

        Args:
            inbound_id: Inbound ID
            base_email: Base email template
            max_attempts: Maximum attempts to find unique email

        Returns:
            Unique email

        Raises:
            XUIError: If unable to generate unique email
        """
        # Split base email into name and domain once
        base_name, domain_part = base_email.rsplit("@", 1)

        for attempt in range(max_attempts):
            if attempt == 0:
                # First attempt, try base email
                email = base_email
            else:
                # Subsequent attempts, add suffix
                email = f"{base_name}_{attempt}@{domain_part}"

            # Check if email exists in this inbound
            existing = await self.session.execute(
                select(InboundConnection).where(
                    InboundConnection.inbound_id == inbound_id,
                    InboundConnection.email == email,
                )
            )

            if not existing.scalar_one_or_none():
                # Email is unique
                return email

        raise XUIError(
            f"Unable to generate unique email for inbound {inbound_id} "
            f"after {max_attempts} attempts"
        )

    async def _get_xui_client(self, server) -> XUIClient:
        """Get or create XUI client for server.

        Args:
            server: Server model

        Returns:
            XUI client instance
        """
        if server.id in self._xui_clients:
            client = self._xui_clients[server.id]
            # Check if client is still active by testing the session
            try:
                # Simple test to check if session is still usable
                if client._session and not client._session.closed:
                    return client
                # Session is closed, remove from cache and create new
                logger.debug(f"Removing stale XUI client for server {server.id}")
                del self._xui_clients[server.id]
            except Exception:
                # If there's any error, also remove from cache and create new
                logger.debug(f"Removing stale XUI client for server {server.id} due to error")
                del self._xui_clients[server.id]

        # Import here to avoid circular dependency
        from app.services.xui_service import XUIService
        from cryptography.fernet import Fernet
        from app.config import get_settings

        xui_service = XUIService(self.session)
        client = await xui_service._get_client(server)
        self._xui_clients[server.id] = client
        return client

    async def close_all_clients(self) -> None:
        """Close all XUI clients properly."""
        for client_id in list(self._xui_clients.keys()):
            client = self._xui_clients[client_id]
            try:
                if client._session and not client._session.closed:
                    await client.close()
            except Exception as e:
                logger.warning(f"Error closing XUI client {client_id}: {e}")
            finally:
                self._xui_clients.pop(client_id, None)

    # Subscription URLs

    async def get_subscription_urls(self, client_id: int) -> list[dict]:
        """Get all subscription URLs for client.

        Args:
            client_id: Client ID

        Returns:
            List of subscription info dicts
        """
        subscriptions = await self.get_client_subscriptions(client_id)

        urls = []
        for sub in subscriptions:
            for connection in sub.inbound_connections:
                if connection.is_enabled:
                    server = connection.inbound.server
                    # Extract host from server URL
                    from urllib.parse import urlparse
                    host = urlparse(server.url).netloc

                    urls.append(
                        {
                            "subscription_name": sub.name,
                            "server_name": server.name,
                            "inbound_name": connection.inbound.remark,
                            "url": f"https://{host}/sub/{sub.subscription_token}",
                            "token": sub.subscription_token,
                        }
                    )

        return urls