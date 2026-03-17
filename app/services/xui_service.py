"""XUI service for managing 3x-ui panel connections."""

from datetime import datetime
from typing import Sequence

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
        self.session = session
        self._cipher = Fernet(get_settings().encryption_key.encode())
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
        client = XUIClient(
            base_url=server.url,
            username=server.username,
            password=password,
        )
        await client.connect()
        self._clients[server.id] = client
        return client

    async def close_client(self, server_id: int) -> None:
        """Close XUI client for server.

        Args:
            server_id: Server ID
        """
        if server_id in self._clients:
            await self._clients[server_id].close()
            del self._clients[server_id]

    async def close_all_clients(self) -> None:
        """Close all XUI clients."""
        for server_id in list(self._clients.keys()):
            await self.close_client(server_id)

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
            select(Server).where(Server.is_active == True).order_by(Server.name)
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
    ) -> Server:
        """Create a new server.

        Args:
            name: Server name
            url: Panel URL
            username: Panel username
            password: Panel password

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
    ) -> Server | None:
        """Update server.

        Args:
            server_id: Server ID
            name: New name (optional)
            url: New URL (optional)
            username: New username (optional)
            password: New password (optional)
            is_active: New active status (optional)

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
        if is_active is not None:
            server.is_active = is_active

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

        server.last_sync = datetime.utcnow()
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
            .where(Inbound.server_id == server_id, Inbound.is_active == True)
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
            .where(Inbound.is_active == True)
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
