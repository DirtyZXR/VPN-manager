"""MTProxy Provider implementation."""

import logging
import secrets
import uuid
from typing import Any

from app.database.models import Inbound, InboundConnection, Server, Subscription
from app.services.ssh_service import SSHManager
from app.services.vpn_providers.base import BaseVPNProvider

logger = logging.getLogger(__name__)


class MTProxyProvider(BaseVPNProvider):
    """Provider for Telegram MTProxy via Docker."""

    def __init__(self, server: Server) -> None:
        """Initialize provider with server and setup SSH."""
        super().__init__(server)
        self.ssh = SSHManager(server)

        self.container_name = "mtproxy"
        self.config_path = "/opt/mtproxy/secrets.txt"
        self.domain = "google.com"  # Fake-TLS domain
        self.port = "443"

    def _generate_secret(self) -> str:
        """Generate a 16-byte Fake-TLS secret.

        Format: 'ee' + 16 random hex bytes (32 chars) + hex-encoded domain.
        Actually, the 'ee' format uses 16 bytes. Let's just generate a standard ee-secret.
        """
        # 16 bytes = 32 hex chars. We need 'ee' + 30 hex chars + domain hex.
        random_hex = secrets.token_hex(15)  # 30 chars
        secret = f"ee{random_hex}"

        # Add domain
        domain_hex = self.domain.encode("utf-8").hex()
        return f"{secret}{domain_hex}"

    async def add_client(
        self,
        inbound: Inbound,
        subscription: Subscription,
        client_uuid: str | None = None,
        email: str | None = None,
    ) -> dict[str, Any]:
        """Add a new secret to MTProxy."""
        secret = self._generate_secret()

        # Add to secrets file
        await self.ssh.append_to_file(self.config_path, secret)

        # Soft restart MTProxy
        await self.ssh.run_command(f"docker restart {self.container_name}")

        return {"uuid": client_uuid or str(uuid.uuid4()), "secret": secret}

    async def remove_client(self, inbound: Inbound, connection: Any) -> bool:
        """Remove a secret from MTProxy."""
        secret = connection.secret

        if not secret:
            return False

        try:
            # Remove from secrets file using sed
            sed_cmd = f"sed -i '/^{secret}$/d' {self.config_path}"
            await self.ssh.run_command(sed_cmd)

            # Restart
            await self.ssh.run_command(f"docker restart {self.container_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to remove MTProxy secret: {e}")
            return False

    async def disable_client(self, inbound: Inbound, connection: InboundConnection) -> bool:
        """Temporarily disable the client by removing their secret from the configuration."""
        # For MTProxy, disabling is effectively the same as removing from the live config
        return await self.remove_client(inbound, connection)

    async def enable_client(self, inbound: Inbound, connection: Any) -> bool:
        """Re-enable a disabled client using their existing secret."""
        secret = connection.secret

        if not secret:
            return False

        try:
            # Add to secrets file
            await self.ssh.append_to_file(self.config_path, secret)

            # Soft restart MTProxy
            await self.ssh.run_command(f"docker restart {self.container_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to enable MTProxy secret: {e}")
            return False

    async def get_client_config(
        self, inbound: Inbound, connection: Any, prefer_json: bool = False
    ) -> dict[str, Any]:
        """Generate tg:// proxy link."""
        secret = connection.secret

        host = self.ssh.host

        link = f"tg://proxy?server={host}&port={self.port}&secret={secret}"

        # MTProxy doesn't usually use QR codes, but Telegram supports them for links
        import base64
        import io

        import qrcode

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
