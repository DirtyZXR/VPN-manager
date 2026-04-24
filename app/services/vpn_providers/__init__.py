"""VPN Providers package."""

from app.services.vpn_providers.amnezia_provider import AmneziaProvider
from app.services.vpn_providers.base import BaseVPNProvider
from app.services.vpn_providers.factory import get_vpn_provider
from app.services.vpn_providers.xui_provider import XUIProvider

__all__ = ["BaseVPNProvider", "get_vpn_provider", "XUIProvider", "AmneziaProvider"]
