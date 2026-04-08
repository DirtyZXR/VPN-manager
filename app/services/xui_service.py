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
from app.database.models import Inbound, Server
from app.xui_client import XUIClient, XUIError


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
        """
        return self._cipher.decrypt(encrypted.encode()).decode()

    async def _get_client(self, server: Server) -> XUIClient:
        """Get or create XUI client for server.

        Args:
            server: Server model

        Returns:
            XUI client instance
        """
        if server.id in self._clients:
            return self._clients[server.id]

        password = self._decrypt_password(server.password_encrypted)
        # Use verify_ssl from server model, default to True for existing servers
        verify_ssl = getattr(server, 'verify_ssl', True)

        # Build full URL for API requests using server URL + panel path
        panel_path = getattr(server, 'panel_path', '/')
        from urllib.parse import urljoin
        base_url = urljoin(server.url, panel_path)

        # Try to load saved cookies
        saved_cookies = None
        if server.session_cookies_encrypted:
            try:
                saved_cookies = json.loads(self._decrypt_password(server.session_cookies_encrypted))
                logger.debug(f"Loaded saved cookies for server {server.id}")
            except Exception as e:
                logger.warning(f"Failed to load saved cookies for server {server.id}: {e}")

        client = XUIClient(
            base_url=base_url,
            username=server.username,
            password=password,
            timeout=self._timeout,
            verify_ssl=verify_ssl,
            saved_cookies=saved_cookies,
        )
        await client.connect()

        # Save cookies after successful connection
        self._save_session_cookies(server, client)

        self._clients[server.id] = client
        return client

    def _save_session_cookies(self, server: Server, client: XUIClient) -> None:
        """Save session cookies to server.

        Args:
            server: Server model
            client: XUI client instance
        """
        try:
            cookies = client.get_session_cookies()
            if cookies:
                from datetime import datetime
                cookies_json = json.dumps(cookies)
                server.session_cookies_encrypted = self._encrypt_password(cookies_json)
                server.session_created_at = datetime.now(UTC)
                logger.debug(f"Saved session cookies for server {server.id}")
        except Exception as e:
            logger.warning(f"Failed to save session cookies for server {server.id}: {e}")

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
                logger.warning(f"Error closing XUI client for server {server_id}: {e}")
            finally:
                self._clients.pop(server_id, None)

    async def close_all_clients(self) -> None:
        """Close all XUI clients properly."""
        for server_id in list(self._clients.keys()):
            try:
                await self.close_client(server_id)
            except Exception as e:
                logger.warning(f"Error closing client for server {server_id}: {e}")

    # Server management

    async def get_all_servers(self) -> Sequence[Server]:
        """Get all servers.

        Returns:
            List of all servers
        """
        result = await self.session.execute(
            select(Server).order_by(Server.name)
        )
        return result.scalars().all()

    async def get_active_servers(self) -> Sequence[Server]:
        """Get all active servers.

        Returns:
            List of active servers
        """
        result = await self.session.execute(
            select(Server).where(Server.is_active).order_by(Server.name)
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
            select(Server).where(Server.id == server_id)
        )
        return result.scalar_one_or_none()

    async def create_server(
        self,
        name: str,
        url: str,
        username: str,
        password: str,
        verify_ssl: bool = True,
        panel_path: str = "/",
        subscription_path: str = "/sub/",
        subscription_json_path: str = "/subjson/",
    ) -> Server:
        """Create a new server.

        Args:
            name: Server name
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
        encrypted_password = self._encrypt_password(password)
        server = Server(
            name=name,
            url=url,
            username=username,
            password_encrypted=encrypted_password,
            is_active=True,
            verify_ssl=verify_ssl,
            panel_path=panel_path,
            subscription_path=subscription_path,
            subscription_json_path=subscription_json_path,
        )
        self.session.add(server)
        await self.session.flush()
        return server

    async def update_server(
        self,
        server_id: int,
        name: str | None = None,
        url: str | None = None,
        username: str | None = None,
        password: str | None = None,
        is_active: bool | None = None,
        verify_ssl: bool | None = None,
        panel_path: str | None = None,
        subscription_path: str | None = None,
        subscription_json_path: str | None = None,
    ) -> Server | None:
        """Update server.

        Args:
            server_id: Server ID
            name: New name (optional)
            url: New URL (optional)
            username: New username (optional)
            password: New password (optional)
            is_active: New active status (optional)
            verify_ssl: New SSL verification status (optional)
            panel_path: New panel path (optional)
            subscription_path: New subscription path (optional)
            subscription_json_path: New JSON subscription path (optional)

        Returns:
            Updated server or None if not found
        """
        server = await self.get_server_by_id(server_id)
        if not server:
            return None

        if name is not None:
            server.name = name
        if url is not None:
            server.url = url
        if username is not None:
            server.username = username
        if password is not None:
            server.password_encrypted = self._encrypt_password(password)
            # Clear saved cookies when password changes
            server.session_cookies_encrypted = None
            server.session_created_at = None
        if is_active is not None:
            server.is_active = is_active
        if verify_ssl is not None:
            server.verify_ssl = verify_ssl
        if panel_path is not None:
            server.panel_path = panel_path
        if subscription_path is not None:
            server.subscription_path = subscription_path
        if subscription_json_path is not None:
            server.subscription_json_path = subscription_json_path

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
        result = await self.session.execute(
            select(Inbound).where(Inbound.server_id == server_id)
        )
        existing = {i.xui_id: i for i in result.scalars().all()}

        synced = 0
        for xui_inbound in xui_inbounds:
            if xui_inbound.id in existing:
                # Update existing
                inbound = existing[xui_inbound.id]
                inbound.remark = xui_inbound.remark
                inbound.protocol = xui_inbound.protocol
                inbound.port = xui_inbound.port
                inbound.settings_json = xui_inbound.settings or "{}"
                inbound.is_active = xui_inbound.enable
            else:
                # Create new
                inbound = Inbound(
                    server_id=server_id,
                    xui_id=xui_inbound.id,
                    remark=xui_inbound.remark,
                    protocol=xui_inbound.protocol,
                    port=xui_inbound.port,
                    settings_json=xui_inbound.settings or "{}",
                    is_active=xui_inbound.enable,
                )
                self.session.add(inbound)
            synced += 1

        server.last_sync_at = datetime.now(UTC)
        server.sync_status = "synced"
        await self.session.flush()

        logger.info(f"Synced {synced} inbounds from server {server.name}")
        return synced

    async def get_server_inbounds(self, server_id: int) -> Sequence[Inbound]:
        """Get inbounds for server from database.

        Args:
            server_id: Server ID

        Returns:
            List of inbounds
        """
        result = await self.session.execute(
            select(Inbound)
            .where(Inbound.server_id == server_id, Inbound.is_active)
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
            select(Inbound)
            .options(selectinload(Inbound.server))
            .where(Inbound.id == inbound_id)
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
            "clients": []
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

            stats["clients"].append({
                "email": client.get("email", "N/A"),
                "uuid": client.get("id", "N/A"),
                "enabled": is_enabled,
                "used_gb": used_gb / (1024**3),
                "total_gb": client.get("totalGB", 0) / (1024**3) if client.get("totalGB") else 0,
                "expiry_time": client.get("expiryTime", 0),
            })

        return stats
