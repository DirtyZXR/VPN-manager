"""MTProxy protocol sync service.

mtg: no per-user management, sync is a no-op.
mtg-multi: expiry-based enable/disable (same pattern as AWG).
"""

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


class MTProxyProtocolSync(ProtocolSyncBase):
    async def sync_clients(
        self,
        session: "AsyncSession",
        inbound: "Inbound",
        xui_service: "XUIService | None" = None,
    ) -> int:
        from app.database.models import MTProxyInboundConnection
        from app.services.vpn_providers.factory import get_vpn_provider

        server = inbound.server
        svc = server.mtproxy_service if hasattr(server, "mtproxy_service") else None

        if not svc or svc.implementation == "mtg":
            return 0

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

        try:
            provider = get_vpn_provider(server, inbound_type="mtproxy_inbound")
        except ValueError:
            logger.warning("MTProxy sync: нет провайдера для сервера {}", server.id)
            return 0

        synced = 0
        now = datetime.now(UTC)

        for conn in connections:
            try:
                if not isinstance(conn, MTProxyInboundConnection):
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
                    logger.info("MTProxy: подключение {} отключено (истёк срок)", conn.id)
                    synced += 1

                elif not conn.is_enabled and should_be_enabled:
                    await provider.enable_client(inbound, conn)
                    conn.is_enabled = True
                    conn.sync_status = "synced"
                    conn.last_sync_at = now
                    logger.info("MTProxy: подключение {} включено (подписка возобновлена)", conn.id)
                    synced += 1

            except Exception as e:
                logger.warning("MTProxy sync: ошибка обработки подключения {}: {}", conn.id, e)

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


register("mtproxy_inbound", MTProxyProtocolSync())
