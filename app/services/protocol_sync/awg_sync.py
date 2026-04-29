"""AWG protocol sync service — expiry-based enable/disable."""

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import selectinload, with_polymorphic

from app.services.protocol_sync import ProtocolSyncBase, register

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.database.models import Inbound, InboundConnection
    from app.services.xui_service import XUIService


class AWGProtocolSync(ProtocolSyncBase):
    """Sync service for AmneziaWG.

    AWG has no REST API. The bot manages expiry by:
    1. Checking connection.expiry_date against current time
    2. Disabling expired connections (removes peer from kernel, preserves config/IP)
    3. Enabling renewed connections (re-adds peer with same keys/IP)
    """

    async def sync_clients(
        self,
        session: "AsyncSession",
        inbound: "Inbound",
        xui_service: "XUIService | None" = None,
    ) -> int:
        from app.database.models import AWGInboundConnection, InboundConnection
        from app.services.vpn_providers.factory import get_vpn_provider

        conn_poly = with_polymorphic(InboundConnection, "*")
        result = await session.execute(
            select(conn_poly)
            .where(conn_poly.inbound_id == inbound.id)
            .options(
                selectinload(conn_poly.subscription),
            )
        )
        connections = result.scalars().all()

        if not connections:
            return 0

        server = inbound.server
        try:
            provider = get_vpn_provider(server, inbound_type="awg_inbound")
        except ValueError:
            logger.warning(f"[AWG SYNC] No provider for server {server.id}")
            return 0

        synced = 0
        now = datetime.now(UTC)

        for conn in connections:
            try:
                if not isinstance(conn, AWGInboundConnection):
                    continue

                expiry = conn.expiry_date
                if expiry and expiry.tzinfo is None:
                    expiry = expiry.replace(tzinfo=UTC)

                should_be_enabled = conn.subscription.is_active if conn.subscription else True
                if expiry and now > expiry:
                    should_be_enabled = False

                if conn.is_enabled and not should_be_enabled:
                    await provider.disable_client(inbound, conn)
                    conn.is_enabled = False
                    conn.sync_status = "synced"
                    conn.last_sync_at = now
                    logger.info(f"[AWG SYNC] Disabled expired connection {conn.id}")
                    synced += 1

                elif not conn.is_enabled and should_be_enabled:
                    await provider.enable_client(inbound, conn)
                    conn.is_enabled = True
                    conn.sync_status = "synced"
                    conn.last_sync_at = now
                    logger.info(f"[AWG SYNC] Enabled renewed connection {conn.id}")
                    synced += 1

            except Exception as e:
                logger.error(f"[AWG SYNC] Error syncing connection {conn.id}: {e}")

        await provider.close()
        await session.flush()
        return synced

    async def verify_connection(
        self,
        session: "AsyncSession",
        connection: "InboundConnection",
        xui_service: "XUIService | None" = None,
    ) -> bool:
        return True


register("awg_inbound", AWGProtocolSync())
