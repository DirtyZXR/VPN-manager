"""Protocol-specific sync services registry."""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.database.models import Inbound, InboundConnection
    from app.services.xui_service import XUIService


class ProtocolSyncBase(ABC):
    """Base class for protocol-specific client synchronization."""

    @abstractmethod
    async def sync_clients(
        self,
        session: "AsyncSession",
        inbound: "Inbound",
        xui_service: "XUIService | None" = None,
    ) -> int:
        """Synchronize clients for a specific inbound.

        Args:
            session: Async database session.
            inbound: Inbound model instance.
            xui_service: XUI service instance (only for XUI protocol).

        Returns:
            Number of synchronized clients.
        """

    @abstractmethod
    async def verify_connection(
        self,
        session: "AsyncSession",
        connection: "InboundConnection",
        xui_service: "XUIService | None" = None,
    ) -> bool:
        """Verify a single connection integrity against the remote service.

        Args:
            session: Async database session.
            connection: InboundConnection model instance.
            xui_service: XUI service instance (only for XUI protocol).

        Returns:
            True if connection is valid, False if problem detected.
        """


_REGISTRY: dict[str, ProtocolSyncBase] = {}
_LOADED = False


def _ensure_loaded() -> None:
    global _LOADED
    if _LOADED:
        return
    _LOADED = True
    import app.services.protocol_sync.awg_sync  # noqa: F401
    import app.services.protocol_sync.mtproxy_sync  # noqa: F401
    import app.services.protocol_sync.xui_sync  # noqa: F401


def register(inbound_type: str, sync_service: ProtocolSyncBase) -> None:
    _REGISTRY[inbound_type] = sync_service
    logger.debug(f"[protocol_sync] Registered sync for '{inbound_type}': {sync_service.__class__.__name__}")


def for_inbound(inbound: "Inbound") -> ProtocolSyncBase | None:
    _ensure_loaded()
    return _REGISTRY.get(inbound.type)


def for_type(inbound_type: str) -> ProtocolSyncBase | None:
    _ensure_loaded()
    return _REGISTRY.get(inbound_type)
