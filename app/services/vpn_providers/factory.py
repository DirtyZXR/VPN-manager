"""Factory for getting the appropriate VPN Provider."""

from app.database.models import Server
from app.services.vpn_providers.base import BaseVPNProvider
from app.services.vpn_providers.xui_provider import XUIProvider


def get_vpn_provider(server: Server) -> BaseVPNProvider:
    """Get the appropriate VPN provider instance based on server panel_type.

    Args:
        server: Server model instance

    Returns:
        Provider instance implementing BaseVPNProvider

    Raises:
        ValueError: If panel_type is unknown
    """
    panel_type = server.panel_type or "xui"

    if panel_type == "xui":
        return XUIProvider(server)
    else:
        raise ValueError(f"Unknown panel_type: {panel_type} for server {server.id}")
