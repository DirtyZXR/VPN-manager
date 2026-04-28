"""MTProxy Provider implementation."""

import base64
import io
import logging
import secrets
import uuid
from datetime import datetime
from typing import Any

import qrcode

from app.database.models import Inbound, InboundConnection, Server, Subscription
from app.services.ssh_service import SSHManager
from app.services.vpn_providers.base import BaseVPNProvider

logger = logging.getLogger(__name__)


class MTProxyProvider(BaseVPNProvider):
    """Provider for Telegram MTProxy via Docker.

    Client lifecycle:
    - add_client: generates secret, appends to config, restarts container
    - enable_client: re-adds secret to config, restarts container
    - disable_client: removes secret from config, restarts container
    - remove_client: same as disable_client (secret stored in DB for re-enable)

    Note: every config change restarts the container, briefly disrupting all users.
    MTProxy has no per-user traffic or expiry tracking.
    """

    def __init__(self, server: Server) -> None:
        super().__init__(server)
        self.ssh = SSHManager(server)
        self.container_name = "vpnbot-mtproxy"
        self.config_path = "/opt/vpnbot/mtproxy/config.toml"
        self.domain = "google.com"
        self.port = "443"

    def _generate_secret(self) -> str:
        random_hex = secrets.token_hex(15)
        secret = f"ee{random_hex}"
        domain_hex = self.domain.encode("utf-8").hex()
        return f"{secret}{domain_hex}"

    async def _restart_container(self) -> None:
        await self.ssh.run_command(f"docker restart {self.container_name}")

    # ── CRUD ──────────────────────────────────────────────────────────

    async def add_client(
        self,
        inbound: Inbound,
        subscription: Subscription,
        client_uuid: str | None = None,
        email: str | None = None,
    ) -> dict[str, Any]:
        secret = self._generate_secret()
        await self.ssh.append_to_file(self.config_path, secret)
        await self._restart_container()
        return {"uuid": client_uuid or str(uuid.uuid4()), "secret": secret}

    async def remove_client(self, inbound: Inbound, connection: InboundConnection) -> bool:
        secret = connection.secret
        if not secret:
            return False

        try:
            sed_cmd = f"sed -i '/^{secret}$/d' {self.config_path}"
            await self.ssh.run_command(sed_cmd)
            await self._restart_container()
            return True
        except Exception as e:
            logger.error(f"Failed to remove MTProxy secret: {e}")
            return False

    async def update_client(
        self,
        inbound: Inbound,
        connection: InboundConnection,
        new_total_gb: int | None = None,
        new_expiry_date: datetime | None = None,
    ) -> bool:
        return True

    async def enable_client(self, inbound: Inbound, connection: InboundConnection) -> bool:
        secret = connection.secret
        if not secret:
            return False

        try:
            await self.ssh.append_to_file(self.config_path, secret)
            await self._restart_container()
            return True
        except Exception as e:
            logger.error(f"Failed to enable MTProxy secret: {e}")
            return False

    async def disable_client(self, inbound: Inbound, connection: InboundConnection) -> bool:
        return await self.remove_client(inbound, connection)

    async def reset_client_traffic(
        self, inbound: Inbound, connection: InboundConnection
    ) -> bool:
        return True

    async def get_client_traffic(
        self, inbound: Inbound, connection: InboundConnection
    ) -> dict[str, Any] | None:
        return None

    # ── Config generation ─────────────────────────────────────────────

    async def get_client_config(
        self, inbound: Inbound, connection: InboundConnection, prefer_json: bool = False
    ) -> dict[str, Any]:
        secret = connection.secret
        host = self.ssh.host
        link = f"tg://proxy?server={host}&port={self.port}&secret={secret}"

        qr = qrcode.QRCode(version=1, box_size=10, border=4)
        qr.add_data(link)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")

        buffered = io.BytesIO()
        img.save(buffered, format="PNG")
        qr_base64 = base64.b64encode(buffered.getvalue()).decode("utf-8")

        return {"config_type": "link", "config_data": link, "qr_code_base64": qr_base64}

    async def close(self) -> None:
        pass
