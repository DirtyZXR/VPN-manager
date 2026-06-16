"""SSH Service for executing commands on servers."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import asyncssh
from loguru import logger

from app.config import get_settings
from app.database.models import Server

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# Timeout for establishing the TCP+SSH handshake (seconds).
SSH_CONNECT_TIMEOUT = 30
# Timeout for a single remote command to complete (seconds).
# Long-running ops (Docker pull, curl install) can take several minutes.
SSH_COMMAND_TIMEOUT = 600


class SSHHostKeyMismatchError(Exception):
    """Raised when the server host key does not match the stored (trusted) key.

    This is a potential MITM-attack indicator; the caller must NOT continue
    the connection and should alert the administrator.
    """

    def __init__(self, host: str, message: str) -> None:
        self.host = host
        super().__init__(f"SSH host-key mismatch for {host}: {message}")


# Backward-compatible alias so external code / tests can import either name.
SSHHostKeyMismatch = SSHHostKeyMismatchError


class SSHManager:
    """Manages SSH connections to servers."""

    def __init__(self, server: Server, session: AsyncSession | None = None) -> None:
        """Initialize SSH Manager with server credentials.

        Args:
            server: Server model instance containing ssh details
            session: Optional AsyncSession for auto-persisting the TOFU host key
                on first connect.  When provided and a key is discovered for the
                first time, it is committed immediately.  When omitted a new
                short-lived session is opened just for that commit.
        """
        self.server = server
        self._session = session

        if server.ip_address:
            self.host = server.ip_address
        else:
            self.host = "127.0.0.1"

        self.port = server.ssh_port or 22
        self.username = server.ssh_user or "root"

        # Persistent connection — set by __aenter__, cleared by __aexit__.
        self._conn: asyncssh.SSHClientConnection | None = None
        # Re-entrancy counter for nested ``async with self.ssh:`` blocks.
        self._conn_depth: int = 0

    def _decrypt(self, encrypted_data: str | None) -> str | None:
        if not encrypted_data:
            return None
        from cryptography.fernet import Fernet

        settings = get_settings()
        cipher = Fernet(settings.encryption_key.encode())
        try:
            return cipher.decrypt(encrypted_data.encode()).decode()
        except Exception as e:
            logger.error(f"Failed to decrypt SSH credential: {e}")
            return None

    def get_ssh_password(self) -> str | None:
        """Decrypt and return SSH password."""
        return self._decrypt(self.server.ssh_password_encrypted)

    def get_ssh_key(self) -> str | None:
        """Decrypt and return SSH private key."""
        return self._decrypt(self.server.ssh_key_encrypted)

    async def _connect(
        self, override_password: str | None = None, override_key: str | None = None
    ) -> asyncssh.SSHClientConnection:
        """Establish SSH connection with TOFU host-key verification.

        On the first connection (no stored key) the server's public host key is
        accepted and returned via ``self._discovered_host_key`` so the caller can
        persist it.  On subsequent connections only the previously stored key is
        trusted; a mismatch raises :class:`SSHHostKeyMismatch`.

        Args:
            override_password: Use this password instead of the one in DB
            override_key: Use this private key instead of the one in DB

        Returns:
            SSHClientConnection

        Raises:
            SSHHostKeyMismatch: When the server presents a different key than stored.
        """
        password = override_password or self.get_ssh_password()
        key_data = override_key or self.get_ssh_key()

        client_keys = None
        if key_data:
            client_keys = [asyncssh.import_private_key(key_data)]

        stored_key: str | None = self.server.ssh_host_key

        if stored_key:
            # Verify: accept ONLY the stored key (TOFU enforcement)
            try:
                known = asyncssh.import_known_hosts(f"{self.host} {stored_key}\n")
            except Exception as exc:
                raise SSHHostKeyMismatchError(
                    self.host, f"stored key is unparseable: {exc}"
                ) from exc

            try:
                conn = await asyncssh.connect(
                    self.host,
                    port=self.port,
                    username=self.username,
                    password=password,
                    client_keys=client_keys,
                    known_hosts=known,
                    connect_timeout=SSH_CONNECT_TIMEOUT,
                )
            except (asyncssh.HostKeyNotVerifiable, asyncssh.PermissionDenied) as exc:
                logger.warning(
                    f"SSH host-key mismatch on {self.host}:{self.port} — possible MITM. "
                    "Admin action required."
                )
                raise SSHHostKeyMismatchError(self.host, str(exc)) from exc

            self._discovered_host_key: str | None = None
            return conn

        else:
            # First connection (TOFU): trust and capture the key
            conn = await asyncssh.connect(
                self.host,
                port=self.port,
                username=self.username,
                password=password,
                client_keys=client_keys,
                known_hosts=None,
                connect_timeout=SSH_CONNECT_TIMEOUT,
            )
            host_key = conn.get_server_host_key()
            if host_key is not None:
                discovered = host_key.export_public_key().decode().strip()
                self._discovered_host_key = discovered
                logger.info(
                    "TOFU: captured host key for {} (type={}); persisting.",
                    self.host,
                    discovered.split()[0] if discovered else "unknown",
                )
                # Auto-persist: use provided session or open a short-lived one.
                await self._auto_persist_host_key()
            else:
                self._discovered_host_key = None

            return conn

    async def _auto_persist_host_key(self) -> None:
        """Persist host key using the stored session or a fresh one.

        Opens its own session when ``self._session`` is *None* so that callers
        that don't have an active session (providers, background tasks) still
        benefit from automatic TOFU persistence.
        """
        if self._session is not None:
            await self._persist_host_key(self._session)
        else:
            from app.database import async_session_factory

            try:
                async with async_session_factory() as session:
                    await self._persist_host_key(session)
            except Exception as exc:
                logger.debug(
                    "TOFU: could not persist host key for {} (no session available): {}",
                    self.host,
                    exc,
                )

    async def _persist_host_key(self, session: AsyncSession) -> None:
        """Persist the discovered host key to the Server row.

        Must be called AFTER :meth:`_connect` while the session is still open.
        No-op if no key was discovered (e.g. on subsequent connections where the
        key was already stored).
        """
        discovered = getattr(self, "_discovered_host_key", None)
        if discovered and not self.server.ssh_host_key:
            self.server.ssh_host_key = discovered
            session.add(self.server)
            await session.commit()
            logger.info("TOFU: host key persisted for {}.", self.host)

    # ── Context-manager (persistent connection) ───────────────────────

    async def __aenter__(self) -> SSHManager:
        """Open a single SSH connection for the duration of the ``async with`` block.

        All ``run_command`` calls inside the block reuse this connection
        instead of opening a new one per command.

        Re-entrant: if a connection is already open (outer ``async with`` block),
        this is a no-op — the outer block owns the connection lifetime.
        """
        if self._conn is None:
            self._conn = await self._connect()
            self._conn_depth = 1
        else:
            self._conn_depth += 1
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Close the persistent connection (only when the outermost block exits)."""
        self._conn_depth -= 1
        if self._conn_depth <= 0 and self._conn is not None:
            self._conn.close()
            self._conn = None
            self._conn_depth = 0

    # ── Internal helper ───────────────────────────────────────────────

    def _process_result(self, result: asyncssh.SSHCompletedProcess, command: str) -> str:
        """Validate exit status and return stdout; raise on non-zero exit."""
        if result.exit_status != 0:
            logger.error(f"Command failed: {command}\nStderr: {result.stderr}")
            raise Exception(
                f"Command failed with exit status {result.exit_status}: {result.stderr}"
            )
        return str(result.stdout).strip()

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
        except SSHHostKeyMismatchError:
            raise
        except Exception as e:
            logger.error(f"SSH test connection failed: {e}")
            return False

    async def run_command(self, command: str, input_data: str | None = None) -> str:
        """Run a command on the server via SSH.

        If called inside an ``async with SSHManager(...)`` block the already-open
        connection is reused; otherwise a fresh connection is opened for this
        single command and closed immediately after.

        Args:
            command: Command to execute
            input_data: Optional string to pipe to the command's stdin

        Returns:
            Stdout string

        Raises:
            SSHHostKeyMismatch: On host key mismatch.
            Exception: If command fails or times out.
        """
        try:
            if self._conn is not None:
                # Persistent connection: reuse it.
                result = await asyncio.wait_for(
                    self._conn.run(command, input=input_data),
                    timeout=SSH_COMMAND_TIMEOUT,
                )
                return self._process_result(result, command)
            else:
                # One-shot: open, run, close.
                async with await self._connect() as conn:
                    result = await asyncio.wait_for(
                        conn.run(command, input=input_data),
                        timeout=SSH_COMMAND_TIMEOUT,
                    )
                    return self._process_result(result, command)
        except TimeoutError:
            raise Exception(
                f"SSH command timed out after {SSH_COMMAND_TIMEOUT}s: {command[:80]}"
            ) from None

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
