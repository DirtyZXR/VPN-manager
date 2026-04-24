"""Factory for getting the appropriate VPN Provider."""

from app.database.models import Server
from app.services.vpn_providers.amnezia_awg import AmneziaAWGProvider
from app.services.vpn_providers.base import BaseVPNProvider
from app.services.vpn_providers.mtproxy import MTProxyProvider
from app.services.vpn_providers.xui_provider import XUIProvider


def get_vpn_provider(server: Server) -> BaseVPNProvider:
    """Get the appropriate VPN provider instance based on server panel/service.

    Args:
        server: Server model instance

    Returns:
        Provider instance implementing BaseVPNProvider

    Raises:
        ValueError: If no known panel/service is configured for the server
    """
    if server.xui_panel:
        return XUIProvider(server)
    elif server.awg_service:
        return AmneziaAWGProvider(server)
    elif server.mtproxy_service:
        return MTProxyProvider(server)
    else:
        raise ValueError(f"Unknown or missing panel/service for server {server.id}")
