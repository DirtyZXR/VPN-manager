"""Subscription service for managing client subscriptions."""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import (
    Client,
    Inbound,
    InboundConnection,
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
                selectinload(Subscription.inbound_connections)
                .selectinload(InboundConnection.inbound)
                .selectinload(Inbound.server),
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
                selectinload(Subscription.template),
                selectinload(Subscription.inbound_connections)
                .selectinload(InboundConnection.inbound)
                .selectinload(Inbound.server),
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
        template_id: int | None = None,
    ) -> tuple[Subscription, list[InboundConnection]]:
        """Create a new subscription.

        Args:
            client_id: Client ID
            name: Subscription name
            total_gb: Traffic limit in GB (0 = unlimited)
            expiry_days: Days until expiry (None = never)
            notes: Optional notes
            template_id: Optional template ID used to create this subscription

        Returns:
            A tuple containing the created subscription and an empty list of connections.
        """
        # Calculate expiry date
        expiry_date = None
        if expiry_days:
            expiry_date = datetime.now(UTC) + timedelta(days=expiry_days)

        # Generate unique token
        subscription = Subscription(
            client_id=client_id,
            template_id=template_id,
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
        reloaded_subscription = await self.get_subscription(subscription.id)
        assert reloaded_subscription is not None
        if not reloaded_subscription:
            raise XUIError("Subscription not found after creation")

        # Return subscription and an empty list for connections, as they are created later
        return reloaded_subscription, []

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

        inbound_result = await self.session.execute(
            select(Inbound).where(Inbound.id == inbound_id).options(selectinload(Inbound.server))
        )
        inbound = inbound_result.scalar_one_or_none()
        if not inbound:
            raise XUIError("Inbound not found")

        # Generate UUID and email with uniqueness check
        import uuid

        client_uuid = str(uuid.uuid4())

        # Generate unique email for this inbound
        base_email = f"{subscription.name}-{subscription.client.name}"
        client_email = await self._generate_unique_email(inbound_id, base_email)

        # Calculate expiry time for XUI
        expiry_time = 0
        if subscription.expiry_date:
            expiry_time = int(subscription.expiry_date.timestamp() * 1000)

        # Get Telegram ID from client
        tg_id = int(subscription.client.telegram_id) if subscription.client.telegram_id else 0

        # Create client in XUI
        client_request = XUIAddClientRequest(
            id=client_uuid,
            email=client_email,
            enable=True,
            flow="xtls-rprx-vision",
            totalGB=subscription.total_gb * 1024 * 1024 * 1024,  # Convert GB to bytes
            expiryTime=expiry_time,
            subId=subscription.subscription_token,
            tgId=tg_id,  # Pass Telegram ID to XUI
        )

        try:
            xui_client = await self._get_xui_client(inbound.server)
            await xui_client.add_client(inbound.xui_id, client_request)

            # Create inbound connection with per-connection traffic and expiry
            connection = InboundConnection(
                subscription_id=subscription_id,
                inbound_id=inbound_id,
                xui_client_id=client_uuid,
                email=client_email,
                uuid=client_uuid,
                is_enabled=True,
                total_gb=subscription.total_gb,  # Store per-connection traffic
                expiry_date=subscription.expiry_date,  # Store per-connection expiry
                sync_status="synced",
                last_sync_at=datetime.now(UTC),
            )
            self.session.add(connection)
            await self.session.flush()

            # Update inbound client count
            inbound.client_count += 1

            return connection

        except Exception as e:
            # Rollback on XUI error
            await self.session.rollback()
            logger.error(f"Failed to create XUI client: {e}", exc_info=True)
            raise XUIError(f"Failed to create XUI client: {str(e)}") from e

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
        conn_result = await self.session.execute(
            select(InboundConnection).where(
                InboundConnection.subscription_id == subscription_id,
                InboundConnection.inbound_id == inbound_id,
            )
        )
        connection = conn_result.scalar_one_or_none()
        if not connection:
            return False

        # Get inbound info with server relationship
        inbound_result = await self.session.execute(
            select(Inbound).where(Inbound.id == inbound_id).options(selectinload(Inbound.server))
        )
        inbound = inbound_result.scalar_one_or_none()

        # Delete from XUI
        if inbound and inbound.server:
            xui_client = await self._get_xui_client(inbound.server)
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
        conn_result = await self.session.execute(
            select(InboundConnection)
            .where(InboundConnection.id == connection_id)
            .options(selectinload(InboundConnection.inbound).selectinload(Inbound.server))
        )
        connection = conn_result.scalar_one_or_none()
        if not connection:
            return None

        # Update in XUI
        inbound = connection.inbound
        xui_client = await self._get_xui_client(inbound.server)
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

    async def sync_client_telegram_id(self, client_id: int) -> int:
        """Sync Telegram ID to all XUI clients for a client.

        Args:
            client_id: Client ID

        Returns:
            Number of connections updated in XUI
        """
        # Get client

        client = await self.session.get(Client, client_id)
        if not client:
            return 0

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

        updated_count = 0
        tg_id = int(client.telegram_id) if client.telegram_id else 0

        for subscription in subscriptions:
            for connection in subscription.inbound_connections:
                # Update tg_id in XUI
                inbound = connection.inbound
                try:
                    xui_client = await self._get_xui_client(inbound.server)

                    # Create update request with new tg_id
                    from app.xui_client.models import XUIAddClientRequest

                    expiry_time = 0
                    if subscription.expiry_date:
                        expiry_time = int(subscription.expiry_date.timestamp() * 1000)

                    update_request = XUIAddClientRequest(
                        id=connection.uuid,
                        email=connection.email,
                        enable=True,
                        flow="xtls-rprx-vision",
                        totalGB=subscription.total_gb * 1024 * 1024 * 1024,
                        expiryTime=expiry_time,
                        subId=subscription.subscription_token,
                        tgId=tg_id,  # Update Telegram ID
                    )

                    # Use update_client instead of add_client to avoid duplicate email error
                    await xui_client.update_client(inbound.xui_id, update_request)
                    updated_count += 1
                    logger.info(
                        f"✅ Updated Telegram ID for client {client_id} in inbound {inbound.id}"
                    )

                except Exception as e:
                    logger.warning(f"Failed to update Telegram ID for client {client_id}: {e}")

        return updated_count

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
        if "@" in base_email:
            base_name, domain_part = base_email.rsplit("@", 1)
            domain_part = f"@{domain_part}"
        else:
            base_name = base_email
            domain_part = ""

        for attempt in range(max_attempts):
            email = base_email if attempt == 0 else f"{base_name}_{attempt}{domain_part}"

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

    async def _get_xui_client(self, server: Any) -> XUIClient:
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

    async def get_subscription_urls(self, client_id: int) -> list[dict[str, Any]]:
        """Get all subscription URLs for client.

        Prioritizes JSON URLs if available.

        Args:
            client_id: Client ID

        Returns:
            List of subscription info dicts
        """
        subscriptions = await self.get_client_subscriptions(client_id)

        urls = []
        for sub in subscriptions:
            # Create a set of unique servers for this subscription
            servers = {conn.inbound.server for conn in sub.inbound_connections if conn.is_enabled}

            for server in servers:
                # Prioritize JSON URL, fallback to standard URL
                subscription_path = getattr(server, "subscription_json_path", None)
                url_type = "json"
                if not subscription_path:
                    subscription_path = getattr(server, "subscription_path", "/sub/")
                    url_type = "standard"

                from urllib.parse import urljoin

                url = urljoin(server.url, f"{subscription_path}{sub.subscription_token}")

                urls.append(
                    {
                        "subscription_id": sub.id,
                        "subscription_name": sub.name,
                        "server_name": server.name,
                        "url": url,
                        "token": sub.subscription_token,
                        "type": url_type,
                    }
                )

        return urls

    # Subscription management methods

    async def get_all_subscriptions(self) -> Sequence[Subscription]:
        """Get all subscriptions.

        Returns:
            List of all subscriptions
        """
        result = await self.session.execute(
            select(Subscription)
            .options(
                selectinload(Subscription.client),
                selectinload(Subscription.inbound_connections),
            )
            .order_by(Subscription.created_at.desc())
        )
        return result.scalars().all()

    async def update_subscription(
        self,
        subscription_id: int,
        name: str | None = None,
        total_gb: int | None = None,
        expiry_days: float | None = None,
        notes: str | None = None,
        is_active: bool | None = None,
        exact_expiry_date: datetime | None = None,
    ) -> Subscription:
        """Update subscription parameters.

        Args:
            subscription_id: Subscription ID
            name: New subscription name (optional)
            total_gb: New traffic limit in GB (optional)
            expiry_days: New expiry in days (optional, None = no change, 0 = never)
            notes: New notes (optional)
            is_active: New active status (optional)
            exact_expiry_date: Exact expiration date (optional)

        Returns:
            Updated subscription

        Raises:
            XUIError: If subscription not found
        """
        sub_result = await self.session.execute(
            select(Subscription)
            .where(Subscription.id == subscription_id)
            .options(selectinload(Subscription.client))
        )
        subscription = sub_result.scalar_one_or_none()
        if not subscription:
            raise XUIError("Subscription not found")

        # Update fields if provided
        if name is not None:
            subscription.name = name
        if total_gb is not None:
            subscription.total_gb = total_gb
        if exact_expiry_date is not None:
            subscription.expiry_date = exact_expiry_date
        elif expiry_days is not None:
            if expiry_days == 0:
                subscription.expiry_date = None
            else:
                subscription.expiry_date = datetime.now(UTC) + timedelta(days=expiry_days)
        if notes is not None:
            subscription.notes = notes
        if is_active is not None:
            subscription.is_active = is_active

        await self.session.flush()

        # Update XUI clients if parameters changed
        if (
            total_gb is not None
            or expiry_days is not None
            or is_active is not None
            or exact_expiry_date is not None
        ):
            result = await self.session.execute(
                select(InboundConnection)
                .where(InboundConnection.subscription_id == subscription_id)
                .options(selectinload(InboundConnection.inbound).selectinload(Inbound.server))
            )
            connections = result.scalars().all()

            for connection in connections:
                try:
                    xui_client = await self._get_xui_client(connection.inbound.server)

                    # Recalculate expiry time for XUI
                    expiry_time = 0
                    if subscription.expiry_date:
                        expiry_time = int(subscription.expiry_date.timestamp() * 1000)

                    update_request = XUIAddClientRequest(
                        id=connection.uuid,
                        email=connection.email,
                        enable=subscription.is_active,
                        flow="xtls-rprx-vision",
                        totalGB=subscription.total_gb * 1024 * 1024 * 1024,
                        expiryTime=expiry_time,
                        subId=subscription.subscription_token,
                        tgId=int(subscription.client.telegram_id)
                        if subscription.client.telegram_id
                        else 0,
                    )

                    await xui_client.update_client(connection.inbound.xui_id, update_request)
                    # Update per-connection settings
                    connection.total_gb = subscription.total_gb
                    connection.expiry_date = subscription.expiry_date
                    connection.is_enabled = subscription.is_active
                    connection.sync_status = "synced"
                    connection.last_sync_at = datetime.now(UTC)
                except Exception as e:
                    logger.warning(
                        f"Failed to update XUI client for connection {connection.id}: {e}"
                    )
                    connection.sync_status = "error"

            await self.session.flush()

        # Reload with relationships
        updated = await self.get_subscription(subscription_id)
        if updated is None:
            raise XUIError("Subscription not found after update")
        return updated

    async def add_time_to_subscription(self, subscription_id: int, days: int) -> Subscription:
        """Add days to subscription expiry date.

        Args:
            subscription_id: Subscription ID
            days: Days to add

        Returns:
            Updated subscription

        Raises:
            XUIError: If subscription not found
        """
        sub_result = await self.session.execute(
            select(Subscription)
            .where(Subscription.id == subscription_id)
            .options(selectinload(Subscription.client))
        )
        subscription = sub_result.scalar_one_or_none()
        if not subscription:
            raise XUIError("Subscription not found")

        now = datetime.now(UTC)
        expiry = subscription.expiry_date
        if expiry is not None and expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=UTC)

        if expiry is None or expiry < now:
            subscription.expiry_date = now + timedelta(days=days)
        else:
            subscription.expiry_date = expiry + timedelta(days=days)

        await self.session.flush()

        # Update XUI clients
        result = await self.session.execute(
            select(InboundConnection)
            .where(InboundConnection.subscription_id == subscription_id)
            .options(selectinload(InboundConnection.inbound).selectinload(Inbound.server))
        )
        connections = result.scalars().all()

        for connection in connections:
            try:
                xui_client = await self._get_xui_client(connection.inbound.server)

                expiry_time = 0
                if subscription.expiry_date is not None:
                    expiry_time = int(subscription.expiry_date.timestamp() * 1000)

                update_request = XUIAddClientRequest(
                    id=connection.uuid,
                    email=connection.email,
                    enable=connection.is_enabled,
                    flow="xtls-rprx-vision",
                    totalGB=subscription.total_gb * 1024 * 1024 * 1024,
                    expiryTime=expiry_time,
                    subId=subscription.subscription_token,
                    tgId=int(subscription.client.telegram_id)
                    if subscription.client.telegram_id
                    else 0,
                )

                await xui_client.update_client(connection.inbound.xui_id, update_request)
                connection.expiry_date = subscription.expiry_date
                connection.sync_status = "synced"
                connection.last_sync_at = now
            except Exception as e:
                logger.warning(f"Failed to update XUI client for connection {connection.id}: {e}")
                connection.sync_status = "error"

        await self.session.flush()
        updated = await self.get_subscription(subscription_id)
        if updated is None:
            raise XUIError("Subscription not found after update")
        return updated

    async def reset_subscription(self, subscription_id: int) -> bool:
        """Reset traffic for all connections in a subscription.

        Also resets the expiry date based on the template default or originally set duration.

        Args:
            subscription_id: Subscription ID

        Returns:
            True if successful

        Raises:
            XUIError: If subscription not found
        """
        sub_result = await self.session.execute(
            select(Subscription)
            .where(Subscription.id == subscription_id)
            .options(selectinload(Subscription.client), selectinload(Subscription.template))
        )
        subscription = sub_result.scalar_one_or_none()
        if not subscription:
            raise XUIError("Subscription not found")

        now = datetime.now(UTC)

        # Calculate new expiry date
        base_days: int = 0
        if subscription.template_id and subscription.template:
            base_days = int(subscription.template.default_expiry_days or 0)
        else:
            if subscription.expiry_date:
                # Calculate original duration
                expiry = subscription.expiry_date
                if expiry.tzinfo is None:
                    expiry = expiry.replace(tzinfo=UTC)
                created = subscription.created_at
                if created.tzinfo is None:
                    created = created.replace(tzinfo=UTC)

                base_days = (expiry - created).days
                if base_days < 0:
                    base_days = 0

        if base_days > 0:
            subscription.expiry_date = now + timedelta(days=base_days)
            await self.session.flush()

        result = await self.session.execute(
            select(InboundConnection)
            .where(InboundConnection.subscription_id == subscription_id)
            .options(selectinload(InboundConnection.inbound).selectinload(Inbound.server))
        )
        connections = result.scalars().all()

        for connection in connections:
            try:
                xui_client = await self._get_xui_client(connection.inbound.server)

                # Update expiry date in XUI
                if base_days > 0:
                    expiry_time = 0
                    if subscription.expiry_date is not None:
                        expiry = subscription.expiry_date
                        if expiry.tzinfo is None:
                            expiry = expiry.replace(tzinfo=UTC)
                        expiry_time = int(expiry.timestamp() * 1000)

                    update_request = XUIAddClientRequest(
                        id=connection.uuid,
                        email=connection.email,
                        enable=connection.is_enabled,
                        flow="xtls-rprx-vision",
                        totalGB=subscription.total_gb * 1024 * 1024 * 1024,
                        expiryTime=expiry_time,
                        subId=subscription.subscription_token,
                        tgId=int(subscription.client.telegram_id)
                        if subscription.client.telegram_id
                        else 0,
                    )

                    await xui_client.update_client(connection.inbound.xui_id, update_request)

                    # Update local connection expiry
                    connection.expiry_date = subscription.expiry_date
                    connection.sync_status = "synced"
                    connection.last_sync_at = now

                # Reset traffic
                await xui_client.reset_client_traffic(connection.inbound.xui_id, connection.email)
            except Exception as e:
                logger.warning(
                    f"Failed to reset XUI client traffic for connection {connection.id}: {e}"
                )
                if base_days > 0:
                    connection.sync_status = "error"

        if base_days > 0:
            await self.session.flush()

        return True

    async def delete_subscription(self, subscription_id: int) -> bool:
        """Delete subscription and all its inbound connections.

        Args:
            subscription_id: Subscription ID

        Returns:
            True if deleted
        """
        sub_result = await self.session.execute(
            select(Subscription)
            .where(Subscription.id == subscription_id)
            .options(selectinload(Subscription.inbound_connections))
        )
        subscription = sub_result.scalar_one_or_none()
        if not subscription:
            return False

        # Delete all XUI clients
        for connection in subscription.inbound_connections:
            try:
                inbound_result = await self.session.execute(
                    select(Inbound)
                    .where(Inbound.id == connection.inbound_id)
                    .options(selectinload(Inbound.server))
                )
                inbound = inbound_result.scalar_one_or_none()
                if inbound and inbound.server:
                    xui_client = await self._get_xui_client(inbound.server)
                    await xui_client.delete_client(inbound.xui_id, connection.uuid)
                    inbound.client_count -= 1
            except Exception as e:
                logger.warning(f"Failed to delete XUI client for connection {connection.id}: {e}")

        # Delete from database
        await self.session.delete(subscription)
        await self.session.flush()
        return True

    async def get_subscription_inbounds(self, subscription_id: int) -> Sequence[InboundConnection]:
        """Get all inbound connections for subscription.

        Args:
            subscription_id: Subscription ID

        Returns:
            List of inbound connections
        """
        result = await self.session.execute(
            select(InboundConnection)
            .where(InboundConnection.subscription_id == subscription_id)
            .options(selectinload(InboundConnection.inbound).selectinload(Inbound.server))
            .order_by(InboundConnection.created_at.desc())
        )
        return result.scalars().all()

    async def get_subscription_by_id(self, subscription_id: int) -> Subscription | None:
        """Get subscription by ID with full relations.

        Args:
            subscription_id: Subscription ID

        Returns:
            Subscription or None
        """
        return await self.get_subscription(subscription_id)
