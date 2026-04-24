"""Service for auto-discovering VPN panels installed on a server via SSH."""

import logging
import re
from typing import Any

from app.database.models import Server
from app.services.ssh_service import SSHManager

logger = logging.getLogger(__name__)


class AutoDiscoveryService:
    """Discovers installed VPN services on a remote server."""

    def __init__(self, server: Server) -> None:
        self.server = server
        self.ssh = SSHManager(server)

    async def discover_all(self) -> dict[str, dict[str, Any]]:
        """Run all discovery checks.

        Returns:
            Dict of discovered services and their details.
            e.g. {
                "3x-ui": {"port": 2053, "username": "admin", ...},
                "amnezia-awg": {"port": 51820, "public_key": "...", ...},
                "mtproxy": {"port": 443, ...}
            }
        """
        discovered = {}

        awg_details = await self.discover_amnezia_awg()
        if awg_details:
            discovered["amnezia-awg"] = awg_details

        mtproxy_details = await self.discover_mtproxy()
        if mtproxy_details:
            discovered["mtproxy"] = mtproxy_details

        xui_details = await self.discover_xui()
        if xui_details:
            discovered["3x-ui"] = xui_details

        return discovered

    async def discover_amnezia_awg(self) -> dict[str, Any] | None:
        """Check if AmneziaWG is installed and running."""
        try:
            # Check if container exists
            check_cmd = "docker ps -a -q -f name=amnezia-awg"
            container_id = await self.ssh.run_command(check_cmd)
            if not container_id:
                return None

            # Read config
            cat_cmd = "docker exec -i amnezia-awg cat /opt/amnezia/awg/awg0.conf"
            config = await self.ssh.run_command(cat_cmd)

            # Parse details
            port_match = re.search(r"ListenPort\s*=\s*(\d+)", config)
            port = int(port_match.group(1)) if port_match else 51820

            peers = re.findall(r"\[Peer\]", config)

            return {
                "container_name": "amnezia-awg",
                "port": port,
                "peer_count": len(peers),
            }
        except Exception as e:
            logger.debug(f"AWG discovery failed on server {self.server.id}: {e}")
            return None

    async def discover_mtproxy(self) -> dict[str, Any] | None:
        """Check if MTProxy is installed and running."""
        try:
            check_cmd = "docker ps -a -q -f name=mtproxy"
            container_id = await self.ssh.run_command(check_cmd)
            if not container_id:
                return None

            # Get exposed port
            port_cmd = "docker port mtproxy | head -n 1 | awk -F ':' '{print $NF}'"
            port_str = await self.ssh.run_command(port_cmd)
            port = int(port_str) if port_str.isdigit() else 443

            return {
                "container_name": "mtproxy",
                "port": port,
            }
        except Exception as e:
            logger.debug(f"MTProxy discovery failed on server {self.server.id}: {e}")
            return None

    async def discover_xui(self) -> dict[str, Any] | None:
        """Check if 3x-ui is installed and extract settings from its database."""
        try:
            # Check container
            check_cmd = "docker ps -a -q -f name=3x-ui"
            container_id = await self.ssh.run_command(check_cmd)
            if not container_id:
                return None

            # Make sure sqlite3 is installed in the container
            try:
                await self.ssh.run_command("docker exec -i 3x-ui sqlite3 -version")
            except Exception:
                await self.ssh.run_command(
                    "docker exec -i 3x-ui apt-get update && docker exec -i 3x-ui apt-get install -y sqlite3"
                )

            # Extract basic settings
            db_cmd = "docker exec -i 3x-ui sqlite3 /etc/x-ui/x-ui.db"

            port_str = await self.ssh.run_command(
                f"{db_cmd} \"SELECT value FROM settings WHERE key='webPort';\""
            )
            port = int(port_str) if port_str.isdigit() else 2053

            base_path = await self.ssh.run_command(
                f"{db_cmd} \"SELECT value FROM settings WHERE key='webBasePath';\""
            )
            if not base_path:
                base_path = "/"

            sub_path = await self.ssh.run_command(
                f"{db_cmd} \"SELECT value FROM settings WHERE key='subPath';\""
            )

            # Extract user info
            username = await self.ssh.run_command(f'{db_cmd} "SELECT username FROM users LIMIT 1;"')

            return {
                "container_name": "3x-ui",
                "port": port,
                "base_path": base_path,
                "sub_path": sub_path or "/sub/",
                "username": username,
            }
        except Exception as e:
            logger.debug(f"3x-ui discovery failed on server {self.server.id}: {e}")
            return None
