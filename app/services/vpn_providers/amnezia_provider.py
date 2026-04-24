"""Amnezia VPN Provider implementation."""

from datetime import datetime
from typing import Any

from loguru import logger

from app.amnezia_client import AmneziaClient, AmneziaError
from app.database.models import Inbound, InboundConnection, Server, Subscription
from app.services.vpn_providers.base import BaseVPNProvider


class AmneziaProvider(BaseVPNProvider):
    """Provider for Amnezia PHP panel."""

    def __init__(self, server: Server) -> None:
        super().__init__(server)
        self._client: AmneziaClient | None = None

    async def _get_client(self) -> AmneziaClient:
        """Get or initialize Amnezia HTTP client."""
        if not self._client:
            payload = self.server.provider_payload or {}

            # Using server host and port to build API URL, or getting from payload
            api_url = payload.get("api_url")
            if not api_url:
                api_url = self.server.url
                if not api_url.startswith("http://") and not api_url.startswith("https://"):
                    api_url = f"https://{api_url}"
                if not api_url.endswith("/api"):
                    api_url = api_url.rstrip("/") + "/api"
            else:
                # ensure it ends with /api
                if not api_url.endswith("/api"):
                    api_url = api_url.rstrip("/") + "/api"

            self._client = AmneziaClient(
                base_url=api_url,
                email=self.server.username,
                password=self.get_server_password(),
                verify_ssl=payload.get("verify_ssl", self.server.verify_ssl),
            )
            await self._client.__aenter__()
            await self._client.login()
        return self._client

    async def add_client(
        self,
        inbound: Inbound,
        subscription: Subscription,
        client_uuid: str | None = None,
        email: str | None = None,
    ) -> dict[str, Any]:
        client = await self._get_client()

        # Amnezia creates clients per server. Our "Inbound" in Amnezia represents a protocol?
        # Actually Amnezia API create_client uses server_id. We assume inbound.amnezia_server_id or payload.server_id
        # Let's extract server_id from payload, defaulting to 1
        ib_payload = inbound.provider_payload or {}
        amnezia_server_id = ib_payload.get("amnezia_server_id", 1)
        amnezia_protocol_id = ib_payload.get("amnezia_protocol_id")

        # Determine expiry
        expires_in_days = 0
        if subscription.expiry_date:
            from datetime import UTC

            now = datetime.now(UTC) if subscription.expiry_date.tzinfo else datetime.utcnow()
            delta = subscription.expiry_date - now
            expires_in_days = max(1, delta.days)

        try:
            resp = await client.create_client(
                server_id=amnezia_server_id,
                name=subscription.name or "VPN User",
                expires_in_days=expires_in_days if expires_in_days > 0 else None,
                protocol_id=amnezia_protocol_id,
            )

            amnezia_client_id = resp.client.id

            # Set traffic limit if needed
            if subscription.total_gb > 0:
                limit_bytes = subscription.total_gb * 1024 * 1024 * 1024
                await client.set_traffic_limit(amnezia_client_id, limit_bytes)

            return {
                "amnezia_client_id": amnezia_client_id,
                "config": resp.client.config,
                # Do NOT store qr_code in DB to prevent bloat
            }

        except AmneziaError as e:
            logger.error("Failed to create Amnezia client: {}", e)
            raise ValueError(f"Failed to create Amnezia client: {e}") from e

    async def update_client(
        self,
        inbound: Inbound,
        connection: InboundConnection,
        new_total_gb: int,
        new_expiry_date: Any,
    ) -> bool:
        client = await self._get_client()
        payload = connection.provider_payload or {}
        amnezia_client_id = payload.get("amnezia_client_id")

        if not amnezia_client_id:
            raise ValueError("Missing amnezia_client_id for update")

        try:
            # Update expiry
            if new_expiry_date:
                # Amnezia expects Y-m-d H:i:s
                date_str = new_expiry_date.strftime("%Y-%m-%d %H:%M:%S")
                await client.set_expiration(amnezia_client_id, date_str)
            else:
                # Null means unlimited (never expires)
                await client.set_expiration(amnezia_client_id, None)

            # Update traffic limit
            limit_bytes = new_total_gb * 1024 * 1024 * 1024 if new_total_gb > 0 else None
            await client.set_traffic_limit(amnezia_client_id, limit_bytes)

            # Update enabled status
            details = await client.get_client_details(amnezia_client_id)
            current_status = details.status

            if connection.is_enabled and current_status != "active":
                await client.restore_client(amnezia_client_id)
            elif not connection.is_enabled and current_status == "active":
                await client.revoke_client(amnezia_client_id)

            return True
        except AmneziaError as e:
            logger.error("Failed to update Amnezia client limits: {}", e)
            return False

    async def remove_client(self, inbound: Inbound, connection: InboundConnection) -> bool:
        client = await self._get_client()
        payload = connection.provider_payload or {}
        amnezia_client_id = payload.get("amnezia_client_id")

        if not amnezia_client_id:
            return False

        try:
            return await client.delete_client(amnezia_client_id)
        except AmneziaError as e:
            logger.error("Failed to delete Amnezia client: {}", e)
            return False

    async def reset_client_traffic(self, inbound: Inbound, connection: InboundConnection) -> bool:
        client = await self._get_client()
        payload = connection.provider_payload or {}
        amnezia_client_id = payload.get("amnezia_client_id")

        if not amnezia_client_id:
            return False

        try:
            # Amnezia API does not expose a dedicated reset traffic endpoint.
            # Workaround: remove traffic limit, then restore it.
            await client.set_traffic_limit(amnezia_client_id, None)

            # If the connection had a limit, restore it
            if connection.total_gb > 0:
                limit_bytes = connection.total_gb * 1024 * 1024 * 1024
                await client.set_traffic_limit(amnezia_client_id, limit_bytes)

            return True
        except AmneziaError as e:
            logger.error("Failed to reset Amnezia client traffic: {}", e)
            return False

    async def get_client_config(
        self, inbound: Inbound, connection: InboundConnection, prefer_json: bool = False
    ) -> dict[str, Any]:
        payload = connection.provider_payload or {}
        config_data = payload.get("config", "")

        if not config_data:
            config_type = "empty"
        elif (
            config_data.startswith("tg://")
            or config_data.startswith("vless://")
            or "t.me" in config_data
        ):
            config_type = "link"
        else:
            config_type = "file"

        return {
            "config_type": config_type,
            "config_data": config_data,
        }

    async def close(self) -> None:
        if self._client:
            await self._client.__aexit__(None, None, None)
            self._client = None
