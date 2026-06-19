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
        from app.database.models import AWGInboundConnection, InboundConnection, Subscription
        from app.services.vpn_providers.factory import get_vpn_provider

        conn_poly = with_polymorphic(InboundConnection, "*")
        result = await session.execute(
            select(conn_poly)
            .where(conn_poly.inbound_id == inbound.id)
            .options(
                selectinload(conn_poly.subscription).selectinload(Subscription.client),
            )
        )
        connections = result.scalars().all()

        if not connections:
            return 0

        server = inbound.server
        try:
            provider = get_vpn_provider(server, inbound_type="awg_inbound")
        except ValueError:
            logger.warning("AWG sync: нет провайдера для сервера {}", server.id)
            return 0

        synced = 0
        now = datetime.now(UTC)

        for conn in connections:
            try:
                if not isinstance(conn, AWGInboundConnection):
                    continue

                sub = conn.subscription
                client_name = sub.client.name if sub and sub.client else "—"

                expiry = conn.expiry_date
                if expiry and expiry.tzinfo is None:
                    expiry = expiry.replace(tzinfo=UTC)

                should_be_enabled = sub.is_active if sub else True
                if expiry and now > expiry:
                    should_be_enabled = False

                if conn.is_enabled and not should_be_enabled:
                    if await provider.disable_client(inbound, conn):
                        conn.is_enabled = False
                        conn.sync_status = "synced"
                        conn.last_sync_at = now
                        logger.info(
                            "AWG: подключение {} ({}) отключено (истёк срок)",
                            conn.id, client_name,
                        )
                        synced += 1
                    else:
                        logger.warning(
                            "AWG: не удалось отключить подключение {} ({}) на сервере — "
                            "оставляю включённым (повтор в следующем цикле)",
                            conn.id, client_name,
                        )

                elif not conn.is_enabled and should_be_enabled:
                    if await provider.enable_client(inbound, conn):
                        conn.is_enabled = True
                        conn.sync_status = "synced"
                        conn.last_sync_at = now
                        logger.info(
                            "AWG: подключение {} ({}) включено (подписка возобновлена)",
                            conn.id, client_name,
                        )
                        synced += 1
                    else:
                        logger.warning(
                            "AWG: не удалось включить подключение {} ({}) на сервере "
                            "(повтор в следующем цикле)",
                            conn.id, client_name,
                        )

            except Exception as e:
                logger.warning("AWG sync: ошибка обработки подключения {}: {}", conn.id, e)

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
