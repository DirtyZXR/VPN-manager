"""MTProxy Provider implementation.

Supports two implementations:
- mtg (single secret): one shared secret for all users, no SSH for CRUD
- mtg-multi (per-user secrets): named secrets in [secrets] TOML section, SSH required
"""

import base64
import io
import logging
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

    mtg (single):
      - All users share one default_secret from MTProxyService
      - add/remove/enable/disable are no-SSH (DB only)
      - get_client_config always returns the same link

    mtg-multi:
      - Each user gets a named secret in [secrets] section
      - Every config change restarts the container
      - No per-user traffic or expiry tracking
    """

    def __init__(self, server: Server) -> None:
        super().__init__(server)
        self.ssh = SSHManager(server)
        self.container_name = "vpnbot-mtproxy"
        self.config_path = "/opt/vpnbot/mtproxy/config.toml"

        svc = server.mtproxy_service
        if svc:
            self.implementation = svc.implementation or "mtg-multi"
            self.port = svc.port or 443
            self.domain = svc.domain or "google.com"
            self.default_secret = svc.default_secret
        else:
            self.implementation = "mtg-multi"
            self.port = 443
            self.domain = "google.com"
            self.default_secret = None

    @property
    def is_single(self) -> bool:
        return self.implementation == "mtg"

    async def _restart_container(self) -> None:
        await self.ssh.run_command(f"docker restart {self.container_name}")

    # ── CRUD ──────────────────────────────────────────────────────────

    async def add_client(
        self,
        inbound: Inbound,
        subscription: Subscription,
        client_uuid: str | None = None,
        email: str | None = None,
        domain: str | None = None,
    ) -> dict[str, Any]:
        if self.is_single:
            return {
                "uuid": client_uuid or str(uuid.uuid4()),
                "secret": self.default_secret,
                "domain": self.domain,
            }

        secret_domain = domain or self.domain
        name = f"user_{subscription.id}_{inbound.id}"
        secret = (await self.ssh.run_command(
            f"docker run --rm ghcr.io/dolonet/mtg-multi:latest generate-secret {secret_domain}"
        )).strip()
        await self.ssh.run_command(
            f"sed -i '/\\[secrets\\]/a {name} = \"{secret}\"' {self.config_path}"
        )
        await self._restart_container()
        return {"uuid": client_uuid or str(uuid.uuid4()), "secret": secret, "domain": secret_domain}

    async def remove_client(self, inbound: Inbound, connection: InboundConnection) -> bool:
        if self.is_single:
            return True

        secret = connection.secret
        if not secret:
            return False

        try:
            await self.ssh.run_command(
                f"sed -i '/{secret}/d' {self.config_path}"
            )
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
        if self.is_single:
            return True

        secret = connection.secret
        if not secret:
            return False

        try:
            name = f"user_{connection.subscription_id}_{inbound.id}"
            await self.ssh.run_command(
                f"sed -i '/\\[secrets\\]/a {name} = \"{secret}\"' {self.config_path}"
            )
            await self._restart_container()
            return True
        except Exception as e:
            logger.error(f"Failed to enable MTProxy secret: {e}")
            return False

    async def disable_client(self, inbound: Inbound, connection: InboundConnection) -> bool:
        if self.is_single:
            return True

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
        secret = connection.secret if not self.is_single else self.default_secret
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
