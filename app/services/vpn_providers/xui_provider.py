"""XUI VPN Provider implementation."""

import uuid
from typing import Any

from app.database.models import Inbound, InboundConnection, Server, Subscription
from app.services.vpn_providers.base import BaseVPNProvider
from app.xui_client import XUIAddClientRequest, XUIClient, XUIError


class XUIProvider(BaseVPNProvider):
    """Provider for 3x-ui panel."""

    def __init__(self, server: Server) -> None:
        super().__init__(server)
        self._client: XUIClient | None = None

    async def _get_client(self) -> XUIClient:
        """Get or initialize XUI HTTP client."""
        if not self._client:
            payload = self.server.provider_payload or {}

            from urllib.parse import urlparse

            parsed = urlparse(self.server.url)
            host = f"{parsed.scheme}://{parsed.hostname}" if parsed.scheme else self.server.url
            port = parsed.port if parsed.port else (443 if parsed.scheme == "https" else 80)

            # Extract base path from url if it exists, otherwise use payload or default
            base_url = (
                parsed.path if parsed.path and parsed.path != "/" else payload.get("base_url", "/")
            )

            self._client = XUIClient(
                host=host,
                port=port,
                username=self.server.username,
                password=self.get_server_password(),
                base_path=base_url,
                verify_ssl=payload.get("verify_ssl", self.server.verify_ssl),
            )
            await self._client.__aenter__()
        return self._client

    async def add_client(
        self,
        inbound: Inbound,
        subscription: Subscription,
        client_uuid: str | None = None,
        email: str | None = None,
    ) -> dict[str, Any]:
        client = await self._get_client()

        client_uuid = client_uuid or str(uuid.uuid4())
        base_email = email or f"{subscription.name}-{subscription.client.name}"

        # Calculate expiry
        expiry_time = 0
        if subscription.expiry_date:
            expiry_time = int(subscription.expiry_date.timestamp() * 1000)

        tg_id = int(subscription.client.telegram_id) if subscription.client.telegram_id else 0

        final_email = base_email
        for i in range(100):
            if i > 0:
                final_email = f"{base_email}-{i}"

            req = XUIAddClientRequest(
                id=client_uuid,
                email=final_email,
                enable=True,
                flow="xtls-rprx-vision",
                totalGB=subscription.total_gb * 1024 * 1024 * 1024,
                expiryTime=expiry_time,
                subId=subscription.subscription_token,
                tgId=tg_id,
            )
            try:
                # XUI inbound_id can be in inbound.xui_id or payload
                # wait, currently DB has inbound.xui_id? No, inbound.id is internal, inbound.xui_id is for XUI
                # let's assume inbound has xui_id (legacy)
                # check if inbound has xui_id attribute
                x_id = getattr(inbound, "xui_id", inbound.id)

                await client.add_client(x_id, req)
                break
            except XUIError as e:
                error_msg = str(e).lower()
                if "duplicate" in error_msg and "email" in error_msg:
                    continue
                raise ValueError(f"Failed to create XUI client: {str(e)}") from e
        else:
            raise ValueError(
                f"Unable to find an email accepted by XUI panel for inbound {inbound.id}"
            )

        return {"uuid": client_uuid, "email": final_email, "xui_client_id": client_uuid}

    async def update_client(
        self,
        inbound: Inbound,
        connection: InboundConnection,
        new_total_gb: int,
        new_expiry_date: Any,
    ) -> bool:
        client = await self._get_client()

        # Extract UUID and email (handle legacy connection fields or provider_payload)
        payload = connection.provider_payload or {}
        c_uuid = connection.uuid or payload.get("uuid")
        c_email = connection.email or payload.get("email")

        if not c_uuid or not c_email:
            raise ValueError("Missing UUID or email for XUI connection update")

        expiry_time_ms = int(new_expiry_date.timestamp() * 1000) if new_expiry_date else 0
        total_bytes = new_total_gb * 1024 * 1024 * 1024

        req = XUIAddClientRequest(
            id=c_uuid,
            enable=connection.is_enabled,
            email=c_email,
            flow="xtls-rprx-vision",
            totalGB=total_bytes,
            expiryTime=expiry_time_ms,
            subId=connection.subscription.subscription_token,
            tgId=int(connection.subscription.client.telegram_id)
            if connection.subscription.client.telegram_id
            else 0,
        )

        x_id = getattr(inbound, "xui_id", inbound.id)
        await client.update_client(x_id, req)
        return True

    async def remove_client(self, inbound: Inbound, connection: InboundConnection) -> bool:
        client = await self._get_client()
        payload = connection.provider_payload or {}
        c_uuid = connection.uuid or payload.get("uuid")

        if not c_uuid:
            return False

        x_id = getattr(inbound, "xui_id", inbound.id)
        await client.delete_client(x_id, c_uuid)
        return True

    async def reset_client_traffic(self, inbound: Inbound, connection: InboundConnection) -> bool:
        client = await self._get_client()
        payload = connection.provider_payload or {}
        c_email = connection.email or payload.get("email")

        if not c_email:
            return False

        x_id = getattr(inbound, "xui_id", inbound.id)
        await client.reset_client_traffic(x_id, c_email)
        return True

    async def get_client_config(
        self, inbound: Inbound, connection: InboundConnection, prefer_json: bool = False
    ) -> dict[str, Any]:
        # For XUI, the config is returned as a link generated by the server base URL
        try:
            sub = connection.subscription
            token = sub.subscription_token
        except Exception:
            # Fallback if subscription is detached or not loaded
            token = (
                connection.provider_payload.get("subId", "")
                if isinstance(connection.provider_payload, dict)
                else ""
            )

        server = inbound.server

        payload = server.provider_payload
        if not isinstance(payload, dict):
            payload = {}

        subscription_path = None
        if prefer_json:
            subscription_path = server.subscription_json_path or payload.get(
                "subscription_json_path"
            )

        if not subscription_path:
            subscription_path = server.subscription_path or payload.get(
                "subscription_path", "/sub/"
            )

        # To maintain compatibility with previous manual concatenation
        # which users might have relied on
        url = f"{server.url}{subscription_path}{token}"

        return {"config_type": "link", "config_data": url}

    async def close(self) -> None:
        if self._client:
            await self._client.__aexit__(None, None, None)
            self._client = None
