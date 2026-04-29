"""Factory for getting the appropriate VPN Provider."""

from app.database.models import Server
from app.services.vpn_providers.amnezia_awg import AmneziaAWGProvider
from app.services.vpn_providers.base import BaseVPNProvider
from app.services.vpn_providers.mtproxy import MTProxyProvider
from app.services.vpn_providers.xui_provider import XUIProvider

_PROVIDER_MAP = {
    "awg_inbound": "awg",
    "mtproxy_inbound": "mtproxy",
    "xui_inbound": "xui",
}


def get_vpn_provider(server: Server, inbound_type: str | None = None) -> BaseVPNProvider:
    """Get the appropriate VPN provider instance based on inbound type or server services.

    Args:
        server: Server model instance
        inbound_type: Inbound polymorphic type (e.g. 'awg_inbound', 'xui_inbound').
                      When provided, selects provider by type. When None, falls back
                      to server-level detection (xui_panel → awg_service → mtproxy_service).

    Returns:
        Provider instance implementing BaseVPNProvider

    Raises:
        ValueError: If no known panel/service is configured for the server
    """
    if inbound_type:
        kind = _PROVIDER_MAP.get(inbound_type)
        if kind == "awg":
            if not server.awg_service:
                raise ValueError(f"Server {server.id} has no AWG service configured")
            return AmneziaAWGProvider(server)
        elif kind == "mtproxy":
            if not server.mtproxy_service:
                raise ValueError(f"Server {server.id} has no MTProxy service configured")
            return MTProxyProvider(server)
        elif kind == "xui":
            if not server.xui_panel:
                raise ValueError(f"Server {server.id} has no XUI panel configured")
            return XUIProvider(server)

    if server.xui_panel:
        return XUIProvider(server)
    elif server.awg_service:
        return AmneziaAWGProvider(server)
    elif server.mtproxy_service:
        return MTProxyProvider(server)
    else:
        raise ValueError(f"Unknown or missing panel/service for server {server.id}")
