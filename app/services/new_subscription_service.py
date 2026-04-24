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
from app.services.vpn_providers import BaseVPNProvider, get_vpn_provider
from app.utils import generate_subscription_token
from app.xui_client.exceptions import XUIError


class NewSubscriptionService:
    """Service for subscription management with new architecture."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize service with database session.

        Args:
            session: Async database session
        """
        self.session = session
        self._providers: dict[int, BaseVPNProvider] = {}

    async def __aenter__(self):
        """Enter async context."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Exit async context and close all clients."""
        await self.close_all_clients()

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

    async def rebuild_subscription(
        self,
        subscription_id: int,
        new_name: str,
        new_total_gb: int,
        new_expiry_days: int | None,
        new_inbound_ids: list[int],
        template_id: int | None = None,
        notes: str | None = None,
    ) -> tuple[Subscription, list[InboundConnection]]:
        """Rebuild subscription with new configuration while keeping token/UUID.

        Args:
            subscription_id: ID of the existing subscription
            new_name: New subscription name
            new_total_gb: New traffic limit in GB (0 = unlimited)
            new_expiry_days: New expiry days
            new_inbound_ids: New list of inbound IDs
            template_id: Optional template ID if rebuilt from template
            notes: Optional notes

        Returns:
            A tuple containing the updated subscription and list of connections.
        """
        subscription = await self.get_subscription(subscription_id)
        if not subscription:
            raise XUIError("Subscription not found")

        current_connections = subscription.inbound_connections
        current_inbound_ids = {c.inbound_id for c in current_connections}
        new_inbound_ids_set = set(new_inbound_ids)

        # Capture old UUID if possible
        client_uuid = None
        if current_connections:
            client_uuid = current_connections[0].uuid
        else:
            import uuid

            client_uuid = str(uuid.uuid4())

        # Update subscription properties
        subscription.name = new_name
        subscription.total_gb = new_total_gb
        subscription.template_id = template_id
        if notes is not None:
            subscription.notes = notes

        expiry_date = None
        if new_expiry_days:
            expiry_date = datetime.now(UTC) + timedelta(days=new_expiry_days)
        subscription.expiry_date = expiry_date

        await self.session.flush()

        # Determine removed, added, and kept inbounds
        removed_ids = current_inbound_ids - new_inbound_ids_set
        added_ids = new_inbound_ids_set - current_inbound_ids
        kept_ids = current_inbound_ids & new_inbound_ids_set

        # Process removed
        for ib_id in removed_ids:
            await self.remove_inbound_from_subscription(subscription_id, ib_id)

        # Process kept (reset traffic, update limits and expiry)
        for conn in current_connections:
            if conn.inbound_id in kept_ids:
                conn.total_gb = new_total_gb
                conn.expiry_date = expiry_date

                # Update in XUI and reset traffic
                try:
                    inbound_result = await self.session.execute(
                        select(Inbound)
                        .where(Inbound.id == conn.inbound_id)
                        .options(selectinload(Inbound.server))
                    )
                    inbound = inbound_result.scalar_one()
                    provider = await self._get_provider(inbound.server)

                    # First, reset the traffic so it starts from 0 for the new period
                    await provider.reset_client_traffic(inbound, conn)

                    # Update limits
                    conn.is_enabled = True
                    await provider.update_client(inbound, conn, new_total_gb, expiry_date)
                except Exception as e:
                    logger.error(
                        f"Failed to update kept inbound {conn.inbound_id} for sub {subscription_id}: {e}"
                    )

        # Process added
        for ib_id in added_ids:
            await self.add_inbound_to_subscription(subscription_id, ib_id, client_uuid=client_uuid)

        await self.session.flush()

        # Reload to get fresh connections
        reloaded_subscription = await self.get_subscription(subscription.id)
        return reloaded_subscription, list(reloaded_subscription.inbound_connections)

    # Inbound Connection methods

    async def add_inbound_to_subscription(
        self,
        subscription_id: int,
        inbound_id: int,
        client_uuid: str | None = None,
    ) -> InboundConnection:
        """Add inbound connection to subscription.

        Args:
            subscription_id: Subscription ID
            inbound_id: Inbound ID
            client_uuid: Optional UUID to use (for rebuilding subscriptions)

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

        # Generate UUID if not provided
        import uuid

        client_uuid = client_uuid or str(uuid.uuid4())
        client_email = None

        try:
            provider = await self._get_provider(inbound.server)
        except Exception as e:
            await self.session.rollback()
            raise XUIError(f"Failed to get VPN provider: {e}") from e

        try:
            # Create client in provider
            client_data = await provider.add_client(
                inbound=inbound,
                subscription=subscription,
                client_uuid=client_uuid,
                email=None,  # Let provider generate/handle unique email
            )
            client_uuid = client_data.get("uuid", client_uuid)
            client_email = client_data.get("email")
            provider_payload = client_data
        except Exception as e:
            await self.session.rollback()
            logger.error(f"Failed to create client in VPN panel: {e}", exc_info=True)
            raise XUIError(f"Failed to create client in VPN panel: {str(e)}") from e

        try:
            # Create inbound connection with per-connection traffic and expiry
            connection = InboundConnection(
                subscription_id=subscription_id,
                inbound_id=inbound_id,
                is_enabled=True,
                total_gb=subscription.total_gb,  # Store per-connection traffic
                expiry_date=subscription.expiry_date,  # Store per-connection expiry
                provider_payload=provider_payload,
                uuid=provider_payload.get("uuid", client_uuid),
                email=provider_payload.get("email", client_email),
                xui_client_id=provider_payload.get("xui_client_id", client_uuid),
                sync_status="synced",
                last_sync_at=datetime.now(UTC),
            )
            self.session.add(connection)
            await self.session.flush()

            # Update inbound client count
            inbound.client_count += 1

            return connection

        except Exception as e:
            # Rollback on database error
            await self.session.rollback()
            logger.error(f"Failed to save inbound connection: {e}", exc_info=True)
            raise XUIError(f"Failed to save inbound connection: {str(e)}") from e

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

        # Delete from provider
        if inbound and inbound.server:
            provider = await self._get_provider(inbound.server)
            await provider.remove_client(inbound, connection)
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

        # Update in provider
        inbound = connection.inbound
        connection.is_enabled = enable  # Update flag before calling provider
        provider = await self._get_provider(inbound.server)
        await provider.update_client(
            inbound, connection, connection.total_gb, connection.expiry_date
        )

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
                # Update in provider
                inbound = connection.inbound
                connection.is_enabled = enable
                provider = await self._get_provider(inbound.server)
                await provider.update_client(
                    inbound, connection, connection.total_gb, connection.expiry_date
                )

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
                # Delete from provider
                inbound = connection.inbound
                try:
                    provider = await self._get_provider(inbound.server)
                    await provider.remove_client(inbound, connection)
                    deleted_count += 1
                except Exception as e:
                    logger.warning(f"Failed to delete client from provider: {e}")

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

        for subscription in subscriptions:
            for connection in subscription.inbound_connections:
                # Update tg_id in provider
                inbound = connection.inbound
                try:
                    provider = await self._get_provider(inbound.server)
                    # For XUI this works because it pulls latest from subscription.client.telegram_id
                    await provider.update_client(
                        inbound, connection, connection.total_gb, connection.expiry_date
                    )
                    updated_count += 1
                    logger.info(
                        f"✅ Updated Telegram ID for client {client_id} in inbound {inbound.id}"
                    )

                except Exception as e:
                    logger.warning(f"Failed to update Telegram ID for client {client_id}: {e}")

        return updated_count

    # Helper methods

    async def _get_provider(self, server: Any) -> BaseVPNProvider:
        """Get or create VPN provider for server.

        Args:
            server: Server model

        Returns:
            VPN provider instance
        """
        if server.id not in self._providers:
            self._providers[server.id] = get_vpn_provider(server)
        return self._providers[server.id]

    async def close_all_clients(self) -> None:
        """Close all VPN providers properly."""
        for server_id in list(self._providers.keys()):
            provider = self._providers[server_id]
            try:
                await provider.close()
            except Exception as e:
                logger.warning(f"Error closing VPN provider {server_id}: {e}")
            finally:
                self._providers.pop(server_id, None)

    # Subscription URLs

    async def get_subscription_urls(self, client_id: int) -> list[dict[str, Any]]:
        """Get all subscription URLs for client.

        Args:
            client_id: Client ID

        Returns:
            List of subscription info dicts
        """
        try:
            subscriptions = await self.get_client_subscriptions(client_id)

            urls = []
            for sub in subscriptions:
                seen_configs = set()
                for conn in sub.inbound_connections:
                    if not conn.is_enabled:
                        continue
                    try:
                        provider = await self._get_provider(conn.inbound.server)
                        config = await provider.get_client_config(conn.inbound, conn)
                        config_data = config.get("config_data")
                        config_type = config.get("config_type")

                        if config_data and config_data not in seen_configs:
                            seen_configs.add(config_data)

                            # Only return links here, files are handled differently in UI
                            if config_type == "link":
                                urls.append(
                                    {
                                        "subscription_id": sub.id,
                                        "subscription_name": sub.name,
                                        "server_name": conn.inbound.server.name,
                                        "url": config_data,
                                        "token": sub.subscription_token,
                                        "type": "standard",
                                    }
                                )
                    except Exception as e:
                        from loguru import logger

                        logger.warning(f"Error getting config for conn {conn.id}: {e}")

            return urls
        finally:
            await self.close_all_clients()

    async def get_subscription_json_urls(self, client_id: int) -> list[dict[str, Any]]:
        """Get all subscription JSON URLs for client."""
        try:
            subscriptions = await self.get_client_subscriptions(client_id)

            urls = []
            for sub in subscriptions:
                seen_configs = set()
                for conn in sub.inbound_connections:
                    if not conn.is_enabled:
                        continue
                    try:
                        provider = await self._get_provider(conn.inbound.server)
                        config = await provider.get_client_config(
                            conn.inbound, conn, prefer_json=True
                        )
                        config_data = config.get("config_data")
                        config_type = config.get("config_type")

                        if config_data and config_data not in seen_configs:
                            seen_configs.add(config_data)

                            if config_type == "link":
                                urls.append(
                                    {
                                        "subscription_id": sub.id,
                                        "subscription_name": sub.name,
                                        "server_name": conn.inbound.server.name,
                                        "url": config_data,
                                        "token": sub.subscription_token,
                                        "type": "json",
                                    }
                                )
                    except Exception as e:
                        from loguru import logger

                        logger.warning(f"Error getting json config for conn {conn.id}: {e}")

            return urls
        finally:
            await self.close_all_clients()

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
                    provider = await self._get_provider(connection.inbound.server)

                    connection.is_enabled = subscription.is_active
                    await provider.update_client(
                        connection.inbound,
                        connection,
                        subscription.total_gb,
                        subscription.expiry_date,
                    )

                    # Update per-connection settings
                    connection.total_gb = subscription.total_gb
                    connection.expiry_date = subscription.expiry_date
                    connection.sync_status = "synced"
                    connection.last_sync_at = datetime.now(UTC)
                except Exception as e:
                    logger.warning(
                        f"Failed to update VPN client for connection {connection.id}: {e}"
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
                provider = await self._get_provider(connection.inbound.server)
                await provider.update_client(
                    connection.inbound, connection, subscription.total_gb, subscription.expiry_date
                )
                connection.expiry_date = subscription.expiry_date
                connection.sync_status = "synced"
                connection.last_sync_at = now
            except Exception as e:
                logger.warning(f"Failed to update VPN client for connection {connection.id}: {e}")
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
                provider = await self._get_provider(connection.inbound.server)

                if base_days > 0:
                    await provider.update_client(
                        connection.inbound,
                        connection,
                        subscription.total_gb,
                        subscription.expiry_date,
                    )

                    # Update local connection expiry
                    connection.expiry_date = subscription.expiry_date
                    connection.sync_status = "synced"
                    connection.last_sync_at = now

                # Reset traffic
                await provider.reset_client_traffic(connection.inbound, connection)
            except Exception as e:
                logger.warning(
                    f"Failed to reset VPN client traffic for connection {connection.id}: {e}"
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
                    provider = await self._get_provider(inbound.server)
                    await provider.remove_client(inbound, connection)
                    inbound.client_count -= 1
            except Exception as e:
                logger.warning(f"Failed to delete VPN client for connection {connection.id}: {e}")

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
