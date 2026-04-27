"""AWG protocol sync service (stub)."""

from typing import TYPE_CHECKING

from loguru import logger

from app.services.protocol_sync import ProtocolSyncBase, register

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.database.models import Inbound, InboundConnection
    from app.services.xui_service import XUIService


class AWGProtocolSync(ProtocolSyncBase):
    """Stub for AmneziaWG client synchronization.

    TODO: Implement AWG sync when AWG management API is available.
    Possible approaches:
    - Read awg0.conf via SSH and parse peer configs
    - Parse traffic stats from wg show
    """

    async def sync_clients(
        self,
        session: "AsyncSession",
        inbound: "Inbound",
        xui_service: "XUIService | None" = None,
    ) -> int:
        logger.debug(f"[SYNC] AWG sync: not implemented, skipping inbound {inbound.id}")
        return 0

    async def verify_connection(
        self,
        session: "AsyncSession",
        connection: "InboundConnection",
        xui_service: "XUIService | None" = None,
    ) -> bool:
        return True


register("awg_inbound", AWGProtocolSync())
