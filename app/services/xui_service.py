"""XUI service for managing 3x-ui panel connections."""

import json
from collections.abc import Sequence
from datetime import UTC, datetime

from cryptography.fernet import Fernet
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.database.models import Inbound, Server, XUIInbound
from app.database.models.services import XUIPanel
from app.xui_client import XUIClient, XUIConnectionError, XUIError


def _settings_to_str(val: dict | str | None) -> str:
    if val is None:
        return "{}"
    if isinstance(val, str):
        return val
    return json.dumps(val)


class XUIService:
    """Service for managing 3x-ui panel connections."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize service with database session.

        Args:
            session: Async database session
        """
        settings = get_settings()
        self.session = session
        self._cipher = Fernet(settings.encryption_key.encode())
        self._timeout = settings.xui_timeout
        self._clients: dict[int, XUIClient] = {}
        self._failed_clients: dict[int, datetime] = {}

    def _encrypt_password(self, password: str) -> str:
        """Encrypt password for storage.

        Args:
            password: Plain text password

        Returns:
            Encrypted password string
        """
        return self._cipher.encrypt(password.encode()).decode()

    def _decrypt_password(self, encrypted: str) -> str:
        """Decrypt password from storage.

        Args:
            encrypted: Encrypted password string

        Returns:
            Plain text password

        Raises:
            ValueError: If decryption fails (e.g., plain text stored as encrypted).
        """
        try:
            return self._cipher.decrypt(encrypted.encode()).decode()
        except Exception as e:
            logger.error(f"Failed to decrypt password: {e}")
            raise ValueError(
                f"Password decryption failed — password may be stored as plain text. "
                f"Re-save the panel credentials to fix. Error: {e}"
            ) from e

    async def _get_client(self, server: Server) -> XUIClient:
        """Get or create XUI client for server.

        Args:
            server: Server model

        Returns:
            XUI client instance
        """
        if server.id in self._clients:
            return self._clients[server.id]

        if server.id in self._failed_clients:
            time_since_fail = datetime.now(UTC) - self._failed_clients[server.id]
            if time_since_fail.total_seconds() < 60:
                raise XUIConnectionError(f"Server {server.id} connection recently failed, skipping retry")

        if not server.xui_panel:
            raise XUIError(
                "Server credentials not configured or missing XUI panel. Please setup services first."
            )

        panel = server.xui_panel
        auth_mode = getattr(panel, "auth_mode", "credentials")

        api_token: str | None = None
        if getattr(panel, "api_token_encrypted", None):
            try:
                api_token = self._decrypt_password(panel.api_token_encrypted)
            except Exception as e:
                logger.warning("Failed to decrypt API token for server {}: {}", server.id, e)

        if auth_mode == "token" and not api_token:
            raise XUIError(
                f"Server {server.id} is in token auth mode but no API token is configured."
            )

        password = ""
        two_factor_code: str | None = None
        if auth_mode == "credentials":
            if not panel.username or not panel.password_encrypted:
                raise XUIError(
                    "Server credentials not configured. Please setup services first."
                )
            password = self._decrypt_password(panel.password_encrypted)
            if getattr(panel, "two_factor_code_encrypted", None):
                try:
                    two_factor_code = self._decrypt_password(panel.two_factor_code_encrypted)
                except Exception as e:
                    logger.warning("Failed to decrypt 2FA code for server {}: {}", server.id, e)

        verify_ssl = getattr(panel, "verify_ssl", True)

        panel_path = getattr(panel, "panel_path", "/")
        from urllib.parse import urljoin

        if getattr(panel, "url", None):
            base_url = panel.url
            if not base_url.endswith(panel_path) and panel_path != "/":
                base_url = urljoin(base_url, panel_path)
        else:
            ip = server.ip_address
            url = ip if ip.startswith("http") else f"https://{ip}" if verify_ssl else f"http://{ip}"
            base_url = urljoin(url, panel_path)

        saved_cookies = None
        if auth_mode == "credentials" and getattr(panel, "session_cookies_encrypted", None):
            try:
                saved_cookies = json.loads(
                    self._decrypt_password(panel.session_cookies_encrypted)
                )
                logger.debug("Loaded saved cookies for server {}", server.id)
            except Exception as e:
                logger.warning("Failed to load saved cookies for server {}: {}", server.id, e)

        client = XUIClient(
            base_url=base_url,
            username=panel.username or "",
            password=password,
            timeout=self._timeout,
            verify_ssl=verify_ssl,
            saved_cookies=saved_cookies,
            two_factor_code=two_factor_code,
            api_token=api_token,
        )
        try:
            await client.connect()
        except Exception:
            self._failed_clients[server.id] = datetime.now(UTC)
            raise

        if auth_mode == "credentials":
            self._save_session_cookies(server, client)

        self._clients[server.id] = client
        self._failed_clients.pop(server.id, None)
        return client

    def _save_session_cookies(self, server: Server, client: XUIClient) -> None:
        """Save session cookies to server.

        Args:
            server: Server model
            client: XUI client instance
        """
        try:
            cookies = client.get_session_cookies()
            if cookies and getattr(server, "xui_panel", None):
                from datetime import datetime

                cookies_json = json.dumps(cookies)
                server.xui_panel.session_cookies_encrypted = self._encrypt_password(cookies_json)
                server.xui_panel.session_created_at = datetime.now(UTC)
                logger.debug("Saved session cookies for server {}", server.id)
        except Exception as e:
            logger.warning("Failed to save session cookies for server {}: {}", server.id, e)

    async def create_and_save_api_token(self, server: Server) -> str:
        """Create an API token on the panel and save it to DB.

        Args:
            server: Server with xui_panel configured

        Returns:
            The created token string

        Raises:
            XUIError: If token creation fails
        """
        client = await self._get_client(server)
        token = await client.create_api_token()

        server.xui_panel.api_token_encrypted = self._encrypt_password(token)

        client.api_token = token
        self._save_session_cookies(server, client)

        logger.info("Created and saved API token for server {}", server.id)
        return token

    async def close_client(self, server_id: int) -> None:
        """Close XUI client for server.

        Args:
            server_id: Server ID
        """
        if server_id in self._clients:
            try:
                client = self._clients[server_id]
                if client._session and not client._session.closed:
                    await client.close()
            except Exception as e:
                logger.warning("Error closing XUI client for server {}: {}", server_id, e)
            finally:
                self._clients.pop(server_id, None)

    async def close_all_clients(self) -> None:
        """Close all XUI clients properly."""
        for server_id in list(self._clients.keys()):
            try:
                await self.close_client(server_id)
            except Exception as e:
                logger.warning("Error closing client for server {}: {}", server_id, e)

    # Server management

    async def get_all_servers(self) -> Sequence[Server]:
        """Get all servers.

        Returns:
            List of all servers
        """
        result = await self.session.execute(
            select(Server).options(selectinload(Server.xui_panel)).order_by(Server.name)
        )
        return result.scalars().all()

    async def get_active_servers(self) -> Sequence[Server]:
        """Get all active servers.

        Returns:
            List of active servers
        """
        result = await self.session.execute(
            select(Server)
            .options(selectinload(Server.xui_panel))
            .where(Server.is_active)
            .order_by(Server.name)
        )
        return result.scalars().all()

    async def get_server_by_id(self, server_id: int) -> Server | None:
        """Get server by ID.

        Args:
            server_id: Server ID

        Returns:
            Server or None if not found
        """
        result = await self.session.execute(
            select(Server).options(selectinload(Server.xui_panel)).where(Server.id == server_id)
        )
        return result.scalar_one_or_none()

    async def create_server(
        self,
        name: str,
        ip_address: str | None = None,
        url: str | None = None,
        username: str | None = None,
        password: str | None = None,
        verify_ssl: bool = True,
        panel_path: str = "/",
        subscription_path: str = "/sub/",
        subscription_json_path: str = "/subjson/",
    ) -> Server:
        """Create a new server.

        Args:
            name: Server name
            ip_address: IP Address of the server
            url: Server base URL (e.g., https://example.com)
            username: Panel username
            password: Panel password
            verify_ssl: Whether to verify SSL certificates (default: True)
            panel_path: Path to panel (default: "/")
            subscription_path: Path for subscriptions (default: "/sub")
            subscription_json_path: Path for JSON subscriptions (default: "/subjson")

        Returns:
            Created server
        """
        encrypted_password = self._encrypt_password(password) if password else None

        ip = ip_address or url
        server = Server(
            name=name,
            ip_address=ip,
            is_online=False,  # Wait for monitor to ping it
        )
        self.session.add(server)
        await self.session.flush()

        if username and password:
            xui_panel = XUIPanel(
                server_id=server.id,
                username=username,
                password_encrypted=encrypted_password,
                verify_ssl=verify_ssl,
                panel_path=panel_path,
                subscription_path=subscription_path,
                subscription_json_path=subscription_json_path,
            )
            self.session.add(xui_panel)
            await self.session.flush()
            server.xui_panel = xui_panel

        return server

    async def update_server(
        self,
        server_id: int,
        name: str | None = None,
        ip_address: str | None = None,
        url: str | None = None,
        username: str | None = None,
        password: str | None = None,
        is_online: bool | None = None,
        verify_ssl: bool | None = None,
        panel_path: str | None = None,
        subscription_path: str | None = None,
        subscription_json_path: str | None = None,
        ssh_user: str | None = None,
        ssh_port: int | None = None,
        ssh_password: str | None = None,
        ssh_key: str | None = None,
        auth_mode: str | None = None,
        api_token: str | None = None,
    ) -> Server | None:
        """Update server.

        Args:
            server_id: Server ID
            name: New name (optional)
            ip_address: New IP address (optional)
            url: New URL (optional)
            username: New username (optional)
            password: New password (optional)
            is_online: New online status (optional)
            verify_ssl: New SSL verification status (optional)
            panel_path: New panel path (optional)
            subscription_path: New subscription path (optional)
            subscription_json_path: New JSON subscription path (optional)
            ssh_user: New SSH user (optional)
            ssh_port: New SSH port (optional)
            ssh_password: New SSH password (optional)
            ssh_key: New SSH key (optional)

        Returns:
            Updated server or None if not found
        """
        server = await self.get_server_by_id(server_id)
        if not server:
            return None

        if name is not None:
            server.name = name

        new_ip = ip_address if ip_address is not None else url
        if new_ip is not None:
            server.ip_address = new_ip

        if is_online is not None:
            server.is_online = is_online

        if ssh_user is not None:
            server.ssh_user = ssh_user
        if ssh_port is not None:
            server.ssh_port = ssh_port
        if ssh_password is not None:
            server.ssh_password_encrypted = self._encrypt_password(ssh_password)
        if ssh_key is not None:
            server.ssh_key_encrypted = self._encrypt_password(ssh_key)

        # Handle XUI Panel
        panel_fields = [
            username, password, verify_ssl, panel_path,
            subscription_path, subscription_json_path, auth_mode, api_token,
        ]
        if any(v is not None for v in panel_fields):
            if not getattr(server, "xui_panel", None):
                server.xui_panel = XUIPanel(server_id=server.id)
                self.session.add(server.xui_panel)

            if username is not None:
                server.xui_panel.username = username
            if password is not None:
                server.xui_panel.password_encrypted = self._encrypt_password(password)
                server.xui_panel.session_cookies_encrypted = None
                server.xui_panel.session_created_at = None
            if verify_ssl is not None:
                server.xui_panel.verify_ssl = verify_ssl
            if panel_path is not None:
                server.xui_panel.panel_path = panel_path
            if subscription_path is not None:
                server.xui_panel.subscription_path = subscription_path
            if subscription_json_path is not None:
                server.xui_panel.subscription_json_path = subscription_json_path
            if auth_mode is not None:
                server.xui_panel.auth_mode = auth_mode
            if api_token is not None:
                server.xui_panel.api_token_encrypted = self._encrypt_password(api_token)

        # Close existing client to force reconnection
        await self.close_client(server_id)

        await self.session.flush()
        return server

    async def delete_server(self, server_id: int) -> bool:
        """Delete server.

        Args:
            server_id: Server ID

        Returns:
            True if deleted, False if not found
        """
        server = await self.get_server_by_id(server_id)
        if not server:
            return False

        await self.close_client(server_id)
        await self.session.delete(server)
        await self.session.flush()
        return True

    async def test_server_connection(self, server_id: int) -> tuple[bool, str]:
        """Test connection to server.

        Args:
            server_id: Server ID

        Returns:
            Tuple of (success, message)
        """
        server = await self.get_server_by_id(server_id)
        if not server:
            return False, "Server not found"

        try:
            client = await self._get_client(server)
            inbounds = await client.get_inbounds()
            return True, f"Connected successfully. Found {len(inbounds)} inbounds."
        except XUIError as e:
            return False, f"Connection failed: {e}"
        except Exception as e:
            return False, f"Unexpected error: {e}"

    # Inbound management

    async def sync_server_inbounds(self, server_id: int) -> int:
        """Sync inbounds from server to database.

        Args:
            server_id: Server ID

        Returns:
            Number of inbounds synced

        Raises:
            XUIError: If sync fails
        """
        server = await self.get_server_by_id(server_id)
        if not server:
            raise XUIError("Server not found")

        client = await self._get_client(server)
        xui_inbounds = await client.get_inbounds()

        # Get existing inbounds
        result = await self.session.execute(select(XUIInbound).where(XUIInbound.server_id == server_id))
        existing = {i.xui_id: i for i in result.scalars().all()}

        synced = 0
        for xui_inbound in xui_inbounds:
            if xui_inbound.id in existing:
                # Update existing
                inbound = existing[xui_inbound.id]
                inbound.remark = xui_inbound.remark
                inbound.protocol = xui_inbound.protocol
                inbound.port = xui_inbound.port
                inbound.settings_json = _settings_to_str(xui_inbound.settings)
                inbound.is_active = xui_inbound.enable
            else:
                inbound = XUIInbound(
                    server_id=server_id,
                    xui_id=xui_inbound.id,
                    remark=xui_inbound.remark,
                    protocol=xui_inbound.protocol,
                    port=xui_inbound.port,
                    settings_json=_settings_to_str(xui_inbound.settings),
                    is_active=xui_inbound.enable,
                )
                self.session.add(inbound)
            synced += 1

        # We must mark missing ones as inactive!
        seen_ids = {x.id for x in xui_inbounds}
        for xui_id, db_ib in existing.items():
            if xui_id not in seen_ids:
                db_ib.is_active = False

        server.last_sync_at = datetime.now(UTC)
        server.sync_status = "synced"
        await self.session.flush()

        logger.info("Synced {} inbounds from server {}", synced, server.name)
        return synced

    async def get_server_inbounds(self, server_id: int) -> Sequence[Inbound]:
        """Get active inbounds for server from database.

        Args:
            server_id: Server ID

        Returns:
            List of inbounds
        """
        result = await self.session.execute(
            select(Inbound)
            .options(selectinload(Inbound.server))
            .where(Inbound.server_id == server_id, Inbound.is_active)
            .order_by(Inbound.remark)
        )
        return result.scalars().all()

    async def get_server_inbounds_all_status(self, server_id: int) -> Sequence[Inbound]:
        """Get all inbounds (including inactive) for server from database.

        Args:
            server_id: Server ID

        Returns:
            List of inbounds
        """
        result = await self.session.execute(
            select(Inbound)
            .options(selectinload(Inbound.server))
            .where(Inbound.server_id == server_id)
            .order_by(Inbound.remark)
        )
        return result.scalars().all()

    async def get_all_inbounds(self) -> Sequence[Inbound]:
        """Get all inbounds from all servers.

        Returns:
            List of inbounds with server info
        """
        result = await self.session.execute(
            select(Inbound)
            .options(selectinload(Inbound.server))
            .where(Inbound.is_active)
            .order_by(Inbound.server_id, Inbound.remark)
        )
        return result.scalars().all()

    async def get_inbound_by_id(self, inbound_id: int) -> Inbound | None:
        """Get inbound by ID.

        Args:
            inbound_id: Inbound ID

        Returns:
            Inbound or None if not found
        """
        result = await self.session.execute(
            select(Inbound).options(selectinload(Inbound.server)).where(Inbound.id == inbound_id)
        )
        return result.scalar_one_or_none()

    async def get_inbound_clients(self, inbound_id: int) -> list[dict]:
        """Get clients from XUI panel for specific inbound.

        Args:
            inbound_id: Inbound ID

        Returns:
            List of client information dicts
        """
        inbound = await self.get_inbound_by_id(inbound_id)
        if not inbound:
            return []

        client = await self._get_client(inbound.server)
        clients = await client.get_clients(inbound.xui_id)

        return clients

    async def get_inbound_client_stats(self, inbound_id: int) -> dict:
        """Get statistics for clients in inbound.

        Args:
            inbound_id: Inbound ID

        Returns:
            Dictionary with client statistics
        """
        clients = await self.get_inbound_clients(inbound_id)

        stats = {
            "total_clients": len(clients),
            "enabled_clients": 0,
            "disabled_clients": 0,
            "total_used_gb": 0,
            "clients": [],
        }

        for client in clients:
            is_enabled = client.get("enable", True)
            if is_enabled:
                stats["enabled_clients"] += 1
            else:
                stats["disabled_clients"] += 1

            # Calculate used traffic (convert from bytes to GB)
            used_gb = client.get("up", 0) + client.get("down", 0)
            stats["total_used_gb"] += used_gb / (1024**3)

            stats["clients"].append(
                {
                    "email": client.get("email", "N/A"),
                    "uuid": client.get("id", "N/A"),
                    "enabled": is_enabled,
                    "used_gb": used_gb / (1024**3),
                    "total_gb": client.get("totalGB", 0) / (1024**3)
                    if client.get("totalGB")
                    else 0,
                    "expiry_time": client.get("expiryTime", 0),
                }
            )

        return stats
