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
            xui_panel = self.server.xui_panel
            if not xui_panel:
                raise ValueError("Server has no XUI panel configured")

            payload = xui_panel.provider_payload or {}

            from urllib.parse import urlparse

            parsed = urlparse(xui_panel.url or "")
            scheme = parsed.scheme or "http"
            hostname = parsed.hostname or xui_panel.url or ""
            port = parsed.port
            base_path = xui_panel.panel_path or payload.get("base_url", "/")
            if parsed.path and parsed.path != "/" and not xui_panel.panel_path:
                base_path = parsed.path

            port_part = f":{port}" if port else ""
            base_url = f"{scheme}://{hostname}{port_part}{base_path}"

            from cryptography.fernet import Fernet

            from app.config import get_settings

            settings = get_settings()
            cipher = Fernet(settings.encryption_key.encode())

            password = ""
            if xui_panel.password_encrypted:
                password = cipher.decrypt(xui_panel.password_encrypted.encode()).decode()

            self._client = XUIClient(
                base_url=base_url,
                username=xui_panel.username or "",
                password=password,
                verify_ssl=xui_panel.verify_ssl,
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
        new_total_gb: int | None = None,
        new_expiry_date: Any | None = None,
    ) -> bool:
        client = await self._get_client()

        payload = connection.provider_payload or {}
        c_uuid = connection.uuid or payload.get("uuid")
        c_email = connection.email or payload.get("email")

        if not c_uuid or not c_email:
            raise ValueError("Missing UUID or email for XUI connection update")

        total_gb = new_total_gb if new_total_gb is not None else (connection.subscription.total_gb if connection.subscription else 0)
        expiry_date = new_expiry_date if new_expiry_date is not None else (connection.subscription.expiry_date if connection.subscription else None)
        expiry_time_ms = int(expiry_date.timestamp() * 1000) if expiry_date else 0
        total_bytes = total_gb * 1024 * 1024 * 1024

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

    async def _set_client_enable_status(
        self, inbound: Inbound, connection: InboundConnection, is_enabled: bool
    ) -> bool:
        """Helper to toggle client enable status."""
        client = await self._get_client()

        payload = connection.provider_payload or {}
        c_uuid = connection.uuid or payload.get("uuid")
        c_email = connection.email or payload.get("email")

        if not c_uuid or not c_email:
            raise ValueError("Missing UUID or email for XUI connection update")

        expiry_time_ms = 0
        if connection.subscription and connection.subscription.expiry_date:
            expiry_time_ms = int(connection.subscription.expiry_date.timestamp() * 1000)

        total_bytes = 0
        if connection.subscription and connection.subscription.total_gb:
            total_bytes = connection.subscription.total_gb * 1024 * 1024 * 1024

        req = XUIAddClientRequest(
            id=c_uuid,
            enable=is_enabled,
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

    async def disable_client(self, inbound: Inbound, connection: InboundConnection) -> bool:
        return await self._set_client_enable_status(inbound, connection, False)

    async def enable_client(self, inbound: Inbound, connection: InboundConnection) -> bool:
        return await self._set_client_enable_status(inbound, connection, True)

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

    async def get_client_traffic(
        self, inbound: Inbound, connection: InboundConnection
    ) -> dict[str, Any] | None:
        client = await self._get_client()
        payload = connection.provider_payload or {}
        c_email = connection.email or payload.get("email")

        if not c_email:
            return None

        x_id = getattr(inbound, "xui_id", inbound.id)
        traffic_data = await client.get_client_traffic(x_id, c_email)
        return traffic_data

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
        xui_panel = server.xui_panel
        if not xui_panel:
            raise ValueError("Server has no XUI panel configured")

        payload = xui_panel.provider_payload
        if not isinstance(payload, dict):
            payload = {}

        subscription_path = None
        if prefer_json:
            subscription_path = xui_panel.subscription_json_path or payload.get(
                "subscription_json_path"
            )

        if not subscription_path:
            subscription_path = xui_panel.subscription_path or payload.get(
                "subscription_path", "/sub/"
            )

        # To maintain compatibility with previous manual concatenation
        # which users might have relied on
        url = f"{xui_panel.url or ''}{subscription_path}{token}"

        return {"config_type": "link", "config_data": url}

    async def close(self) -> None:
        if self._client:
            await self._client.__aexit__(None, None, None)
            self._client = None
