"""XUI protocol sync service."""

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from loguru import logger
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select
from sqlalchemy.orm import selectinload, with_polymorphic

from app.services.protocol_sync import ProtocolSyncBase, register
from app.xui_client.models import ensure_settings_dict

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.database.models import Inbound, InboundConnection
    from app.services.xui_service import XUIService


class XUIProtocolSync(ProtocolSyncBase):
    """Synchronizes XUI inbound clients with the 3x-ui panel."""

    async def sync_clients(
        self,
        session: "AsyncSession",
        inbound: "Inbound",
        xui_service: "XUIService | None" = None,
    ) -> int:
        if xui_service is None:
            logger.warning(f"[SYNC] XUI sync: no xui_service for inbound {inbound.id}")
            return 0

        xui_client = await xui_service._get_client(inbound.server)
        if xui_client is None:
            logger.warning(f"[SYNC] XUI sync: cannot get XUI client for server of inbound {inbound.id}")
            return 0

        logger.info(
            f"[LOG] XUI sync_clients: начало для inbound {inbound.id} "
            f"(xui_id: {inbound.xui_id}, remark: {inbound.remark})"
        )

        xui_inbound = await xui_client.get_inbound(inbound.xui_id)

        if not xui_inbound:
            logger.warning(f"[WARN] Inbound {inbound.xui_id} не найден на панели")
            return 0

        if not xui_inbound.settings:
            logger.warning(f"Inbound {inbound.id} не имеет настроек клиентов")
            return 0

        try:
            settings_dict = ensure_settings_dict(xui_inbound.settings)
            xui_clients = settings_dict.get("clients", [])
        except (json.JSONDecodeError, TypeError) as e:
            logger.error(f"Ошибка парсинга settings для inbound {inbound.id}: {e}")
            return 0

        logger.info(
            f"[LOG] XUI sync_clients: получено {len(xui_clients)} клиентов из inbound {inbound.id} ({inbound.remark})"
        )
        if xui_clients:
            logger.debug(f"Пример данных клиента: {xui_clients[0]}")

        from app.database.models import InboundConnection, Subscription

        conn_poly = with_polymorphic(InboundConnection, "*")
        state = sa_inspect(inbound)
        if "client_connections" in state.unloaded:
            existing_connections_result = await session.execute(
                select(conn_poly)
                .where(conn_poly.inbound_id == inbound.id)
                .options(
                    selectinload(conn_poly.subscription).selectinload(Subscription.client),
                    selectinload(conn_poly.inbound).selectinload(Inbound.server),
                )
            )
            existing_connections = list(existing_connections_result.scalars())
        else:
            existing_connections = list(inbound.client_connections)

        existing_map = {
            getattr(conn, "uuid", None): conn
            for conn in existing_connections
            if getattr(conn, "uuid", None)
        }
        logger.info(
            f"[LOG] XUI sync_clients: в базе найдено {len(existing_map)} подключений для inbound {inbound.id}"
        )

        synced_count = 0
        for xui_client_data in xui_clients:
            xui_uuid = xui_client_data.get("id", "")
            if not xui_uuid:
                logger.warning(f"Клиент без UUID: {xui_client_data}")
                continue

            if xui_uuid in existing_map:
                conn = existing_map[xui_uuid]

                xui_enable = xui_client_data.get("enable", True)
                xui_total_gb = xui_client_data.get("totalGB", 0) // (1024 * 1024 * 1024)
                xui_expiry_time = xui_client_data.get("expiryTime", 0)

                logger.debug(
                    f"Синхронизация клиента {conn.uuid}: enable={xui_enable}, totalGB={xui_total_gb}, expiry={xui_expiry_time}"
                )

                if conn.is_enabled != xui_enable:
                    old_status = conn.is_enabled
                    conn.is_enabled = xui_enable
                    logger.info(
                        f"[SYNC] Подключение {conn.id} ({conn.uuid}): is_enabled={old_status} → {xui_enable}"
                    )

                if conn.total_gb != xui_total_gb:
                    old_gb = conn.total_gb
                    conn.total_gb = xui_total_gb
                    logger.info(
                        f"[SYNC] Подключение {conn.id} ({conn.uuid}): total_gb {old_gb}GB → {xui_total_gb}GB"
                    )

                new_expiry = None
                if xui_expiry_time > 0:
                    new_expiry = datetime.fromtimestamp(xui_expiry_time / 1000, tz=UTC)

                if conn.expiry_date != new_expiry:
                    old_expiry = conn.expiry_date
                    conn.expiry_date = new_expiry
                    logger.info(
                        f"[SYNC] Подключение {conn.id} ({conn.uuid}): expiry {old_expiry} → {new_expiry}"
                    )

                if conn.subscription:
                    subscription = conn.subscription

                    if subscription.total_gb != xui_total_gb:
                        old_gb = subscription.total_gb
                        subscription.total_gb = xui_total_gb
                        logger.info(
                            f"[SYNC] Подписка {subscription.id}: total_gb {old_gb}GB → {xui_total_gb}GB"
                        )

                    if subscription.expiry_date != new_expiry:
                        old_expiry = subscription.expiry_date
                        subscription.expiry_date = new_expiry
                        logger.info(
                            f"[SYNC] Подписка {subscription.id}: expiry {old_expiry} → {new_expiry}"
                        )

                conn.sync_status = "synced"
                conn.last_sync_at = datetime.now(UTC)
                synced_count += 1
            else:
                logger.info(
                    f"[NEW] Клиент {xui_uuid} найден на панели, но не в базе (создан вручную)"
                )

        await session.flush()
        logger.info(f"[OK] Синхронизировано {synced_count} клиентов для inbound {inbound.id}")
        return synced_count

    async def verify_connection(
        self,
        session: "AsyncSession",
        connection: "InboundConnection",
        xui_service: "XUIService | None" = None,
    ) -> bool:
        if xui_service is None:
            return True

        inbound = connection.inbound
        if not inbound or "server" not in getattr(inbound, "__dict__", {}):
            return True

        if not inbound.server.xui_panel:
            return True

        try:
            xui_client = await xui_service._get_client(inbound.server)
            c_email = getattr(connection, "email", None)
            if not c_email and isinstance(getattr(connection, "provider_payload", None), dict):
                c_email = connection.provider_payload.get("email")
            if not c_email:
                # Cannot verify without email; skip silently
                return True
            xui_data = await xui_client.get_client(c_email)

            if not xui_data:
                connection.sync_status = "error"
                connection.sync_error = "Client missing in XUI (deleted manually?)"
                logger.warning(f"[WARN] Клиент {connection.uuid} не найден в XUI")
                return False
        except Exception as e:
            logger.debug(f"Не удалось проверить {connection.uuid}: {e}")

        return True


register("xui_inbound", XUIProtocolSync())
