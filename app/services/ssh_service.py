"""SSH Service for executing commands on servers."""

import logging
from urllib.parse import urlparse

import asyncssh

from app.config import get_settings
from app.database.models import Server

logger = logging.getLogger(__name__)


class SSHManager:
    """Manages SSH connections to servers."""

    def __init__(self, server: Server) -> None:
        """Initialize SSH Manager with server credentials.

        Args:
            server: Server model instance containing ssh details
        """
        self.server = server

        if server.ip_address:
            self.host = server.ip_address
        elif server.url:
            parsed = urlparse(server.url)
            if parsed.hostname:
                self.host = parsed.hostname
            else:
                self.host = server.url.split(":")[0]
        else:
            self.host = "127.0.0.1"

        self.port = server.ssh_port or 22
        self.username = server.ssh_user or "root"

    def _decrypt(self, encrypted_data: str | None) -> str | None:
        if not encrypted_data:
            return None
        from cryptography.fernet import Fernet

        settings = get_settings()
        cipher = Fernet(settings.encryption_key.encode())
        return cipher.decrypt(encrypted_data.encode()).decode()

    def get_ssh_password(self) -> str | None:
        """Decrypt and return SSH password."""
        return self._decrypt(self.server.ssh_password_encrypted)

    def get_ssh_key(self) -> str | None:
        """Decrypt and return SSH private key."""
        return self._decrypt(self.server.ssh_key_encrypted)

    async def _connect(
        self, override_password: str | None = None, override_key: str | None = None
    ) -> asyncssh.SSHClientConnection:
        """Establish SSH connection.

        Args:
            override_password: Use this password instead of the one in DB
            override_key: Use this private key instead of the one in DB

        Returns:
            SSHClientConnection
        """
        password = override_password or self.get_ssh_password()
        key_data = override_key or self.get_ssh_key()

        client_keys = None
        if key_data:
            # Load the private key from string
            client_keys = [asyncssh.import_private_key(key_data)]

        # Use known_hosts=None for now, to bypass strict host key checking
        # like original script which connects to fresh servers.
        return await asyncssh.connect(
            self.host,
            port=self.port,
            username=self.username,
            password=password,
            client_keys=client_keys,
            known_hosts=None,
        )

    async def test_connection(self, password: str | None = None, key: str | None = None) -> bool:
        """Test SSH connection without executing a command.

        Args:
            password: Password to test (overrides DB)
            key: Private key string to test (overrides DB)

        Returns:
            True if connection is successful, False otherwise
        """
        try:
            async with await self._connect(override_password=password, override_key=key):
                return True
        except Exception as e:
            logger.error(f"SSH test connection failed: {e}")
            return False

    async def run_command(self, command: str, input_data: str | None = None) -> str:
        """Run a command on the server via SSH.

        Args:
            command: Command to execute
            input_data: Optional string to pipe to the command's stdin

        Returns:
            Stdout string

        Raises:
            Exception: If command fails
        """
        async with await self._connect() as conn:
            result = await conn.run(command, input=input_data)
            if result.exit_status != 0:
                logger.error(f"Command failed: {command}\nStderr: {result.stderr}")
                raise Exception(
                    f"Command failed with exit status {result.exit_status}: {result.stderr}"
                )

            return str(result.stdout).strip()

    async def read_file(self, filepath: str) -> str:
        """Read a file from the server.

        Args:
            filepath: Path to the file on the server

        Returns:
            File content
        """
        return await self.run_command(f"cat {filepath}")

    async def append_to_file(self, filepath: str, content: str) -> None:
        """Append content to a file via stdin to avoid bash escaping hell.

        Args:
            filepath: Path to the file
            content: Content to append
        """
        if not content.endswith("\n"):
            content += "\n"
        await self.run_command(f"cat >> {filepath}", input_data=content)

    async def write_file(self, filepath: str, content: str) -> None:
        """Write content to a file via stdin (overwriting).

        Args:
            filepath: Path to the file
            content: Content to write
        """
        await self.run_command(f"cat > {filepath}", input_data=content)
