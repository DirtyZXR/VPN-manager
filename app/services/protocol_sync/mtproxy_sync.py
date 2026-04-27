"""MTProxy protocol sync service (stub)."""

from typing import TYPE_CHECKING

from loguru import logger

from app.services.protocol_sync import ProtocolSyncBase, register

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.database.models import Inbound, InboundConnection
    from app.services.xui_service import XUIService


class MTProxyProtocolSync(ProtocolSyncBase):
    """Stub for MTProxy client synchronization.

    TODO: Implement MTProxy sync when MTProxy management API is available.
    """

    async def sync_clients(
        self,
        session: "AsyncSession",
        inbound: "Inbound",
        xui_service: "XUIService | None" = None,
    ) -> int:
        logger.debug(f"[SYNC] MTProxy sync: not implemented, skipping inbound {inbound.id}")
        return 0

    async def verify_connection(
        self,
        session: "AsyncSession",
        connection: "InboundConnection",
        xui_service: "XUIService | None" = None,
    ) -> bool:
        return True


register("mtproxy_inbound", MTProxyProtocolSync())
