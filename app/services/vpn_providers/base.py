"""Base VPN Provider interface."""

from abc import ABC, abstractmethod
from typing import Any

from app.database.models import Inbound, InboundConnection, Server, Subscription


class BaseVPNProvider(ABC):
    """Abstract base class for all VPN Panel providers."""

    def __init__(self, server: Server) -> None:
        """Initialize provider with server.

        Args:
            server: Server model instance
        """
        self.server = server

    @abstractmethod
    async def add_client(
        self,
        inbound: Inbound,
        subscription: Subscription,
        client_uuid: str | None = None,
        email: str | None = None,
    ) -> dict[str, Any]:
        """Add a new client to the VPN panel.

        Args:
            inbound: The inbound/protocol to add the client to
            subscription: The subscription details (limits, expiry, etc.)
            client_uuid: Optional UUID to force (for rebuilds)
            email: Optional email to force

        Returns:
            Dictionary to be stored in InboundConnection.provider_payload
        """
        pass

    @abstractmethod
    async def get_client_config(
        self, inbound: Inbound, connection: InboundConnection, prefer_json: bool = False
    ) -> dict[str, Any]:
        """Get client configuration (links, files, QR codes).

        Args:
            inbound: The inbound/protocol
            connection: The inbound connection
            prefer_json: Whether to return config as JSON

        Returns:
            Dictionary containing config data, e.g.:
            {
                "config_type": "link", # or "file"
                "config_data": "vless://...", # or raw file content for .conf
                "qr_code_base64": "...", # optional
            }
        """
        pass

    @abstractmethod
    async def remove_client(self, inbound: Inbound, connection: InboundConnection) -> bool:
        """Remove a client's access (delete/revoke).

        Args:
            inbound: The inbound/protocol
            connection: The inbound connection to remove

        Returns:
            True if successfully removed, False otherwise
        """
        pass

    @abstractmethod
    async def disable_client(self, inbound: Inbound, connection: InboundConnection) -> bool:
        """Temporarily disable a client without removing them.

        Args:
            inbound: The inbound/protocol
            connection: The inbound connection to disable

        Returns:
            True if successfully disabled, False otherwise
        """
        pass

    @abstractmethod
    async def enable_client(self, inbound: Inbound, connection: InboundConnection) -> bool:
        """Re-enable a previously disabled client.

        Args:
            inbound: The inbound/protocol
            connection: The inbound connection to enable

        Returns:
            True if successfully enabled, False otherwise
        """
        pass

    @abstractmethod
    async def close(self) -> None:
        """Close any open HTTP sessions."""
        pass
