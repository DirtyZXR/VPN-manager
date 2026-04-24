"""SSH Service for executing commands on servers."""

import logging

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
        self.host = server.url.replace("https://", "").replace("http://", "").split(":")[0]
        self.port = server.ssh_port or 22
        self.username = server.ssh_user or "root"

    def get_ssh_password(self) -> str | None:
        """Decrypt and return SSH password."""
        if not self.server.ssh_password_encrypted:
            return None

        from cryptography.fernet import Fernet

        settings = get_settings()
        cipher = Fernet(settings.encryption_key.encode())
        return cipher.decrypt(self.server.ssh_password_encrypted.encode()).decode()

    async def _connect(self) -> asyncssh.SSHClientConnection:
        """Establish SSH connection.

        Returns:
            SSHClientConnection
        """
        password = self.get_ssh_password()

        # Use known_hosts=None for now, to bypass strict host key checking
        # like original script which connects to fresh servers.
        return await asyncssh.connect(
            self.host, port=self.port, username=self.username, password=password, known_hosts=None
        )

    async def run_command(self, command: str) -> str:
        """Run a command on the server via SSH.

        Args:
            command: Command to execute

        Returns:
            Stdout string

        Raises:
            Exception: If command fails
        """
        async with await self._connect() as conn:
            result = await conn.run(command)
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
        """Append content to a file.

        Args:
            filepath: Path to the file
            content: Content to append
        """
        # Escape single quotes and use bash -c with echo -e
        escaped_content = content.replace("'", "'\\''")
        await self.run_command(f"echo -e '{escaped_content}' >> {filepath}")

    async def write_file(self, filepath: str, content: str) -> None:
        """Write content to a file (overwriting).

        Args:
            filepath: Path to the file
            content: Content to write
        """
        escaped_content = content.replace("'", "'\\''")
        await self.run_command(f"echo -e '{escaped_content}' > {filepath}")
