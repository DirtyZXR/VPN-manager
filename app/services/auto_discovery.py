"""Service for auto-discovering VPN services installed on a server via SSH.

Uses installer discover_existing() methods to read configuration from
vpnbot-* containers.
"""

import logging
from typing import Any

from app.database.models import Server
from app.services.ssh_service import SSHManager

logger = logging.getLogger(__name__)


class AutoDiscoveryService:
    """Discovers installed VPN services on a remote server."""

    def __init__(self, server: Server) -> None:
        self.server = server
        self.ssh = SSHManager(server)

    async def _vpnbot_containers(self) -> list[str]:
        """List all vpnbot-* container names on the server."""
        try:
            output = await self.ssh.run_command(
                "sudo -n docker ps -a --filter name=vpnbot- --format '{{.Names}}' 2>/dev/null || docker ps -a --filter name=vpnbot- --format '{{.Names}}'"
            )
            return [name.strip() for name in output.strip().split("\n") if name.strip()]
        except Exception:
            return []

    async def discover_all(self) -> dict[str, dict[str, Any]]:
        """Run all discovery checks.

        Uses a single persistent SSH connection for all sub-discovery calls.

        Returns:
            Dict of discovered services and their details:
            {
                "3x-ui": {"domain": ..., "caddy_port": ..., "web_path": ..., ...},
                "amnezia-awg": {"port": ..., "subnet_ip": ..., ...},
                "mtproxy": {"port": ..., "implementation": ..., ...}
            }
        """
        async with self.ssh:
            containers = await self._vpnbot_containers()
            if not containers:
                return {}

            discovered: dict[str, dict[str, Any]] = {}

            if "vpnbot-xui" in containers:
                details = await self.discover_xui()
                if details:
                    discovered["3x-ui"] = details

            if "vpnbot-awg" in containers:
                details = await self.discover_amnezia_awg()
                if details:
                    discovered["amnezia-awg"] = details

            if "vpnbot-mtproxy" in containers:
                details = await self.discover_mtproxy()
                if details:
                    discovered["mtproxy"] = details

        return discovered

    async def discover_xui(self) -> dict[str, Any] | None:
        """Discover 3x-ui + Caddy installation via XUIInstaller.discover_existing()."""
        try:
            from app.services.installers.xui_installer import XUIInstaller

            installer = XUIInstaller(self.ssh)
            return await installer.discover_existing()
        except Exception as e:
            logger.debug(f"XUI discovery failed on server {self.server.id}: {e}")
            return None

    async def discover_amnezia_awg(self) -> dict[str, Any] | None:
        """Discover AmneziaWG installation via AWGInstaller.discover_existing()."""
        try:
            from app.services.installers.awg_installer import AWGInstaller

            installer = AWGInstaller(self.ssh)
            return await installer.discover_existing()
        except Exception as e:
            logger.debug(f"AWG discovery failed on server {self.server.id}: {e}")
            return None

    async def discover_mtproxy(self) -> dict[str, Any] | None:
        """Discover MTProxy installation via MTProxyInstaller.discover_existing()."""
        try:
            from app.services.installers.mtproxy_installer import MTProxyInstaller

            installer = MTProxyInstaller(self.ssh)
            return await installer.discover_existing()
        except Exception as e:
            logger.debug(f"MTProxy discovery failed on server {self.server.id}: {e}")
            return None
