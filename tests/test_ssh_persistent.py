"""Tests for SSHManager persistent context-manager and command timeouts.

All asyncssh I/O is mocked — no real SSH server needed.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.database.models.server import Server
from app.services.ssh_service import SSH_CONNECT_TIMEOUT, SSHHostKeyMismatchError, SSHManager

# ── helpers ───────────────────────────────────────────────────────────────────

FAKE_KEY_STRING = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFakeHostKeyForTestingPurposesOnly"


def _make_server(*, host_key: str | None = FAKE_KEY_STRING) -> MagicMock:
    """Mock Server object satisfying SSHManager interface."""
    server = MagicMock(spec=Server)
    server.ip_address = "10.0.0.1"
    server.ssh_port = 22
    server.ssh_user = "root"
    server.ssh_password_encrypted = None
    server.ssh_key_encrypted = None
    server.ssh_host_key = host_key
    return server


def _make_mock_conn() -> MagicMock:
    """Return a mock SSHClientConnection with async context manager support."""
    conn = MagicMock()
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    conn.close = MagicMock()

    # .run() returns a successful result by default
    result = MagicMock()
    result.exit_status = 0
    result.stdout = "ok"
    result.stderr = ""
    conn.run = AsyncMock(return_value=result)

    return conn


def _make_known_hosts() -> MagicMock:
    return MagicMock()


# ── Test: persistent connection reuse ─────────────────────────────────────────


class TestPersistentConnection:
    """async with SSHManager(...) should open exactly one connection."""

    @pytest.mark.asyncio
    async def test_context_manager_opens_one_connection_for_multiple_commands(self):
        """asyncssh.connect called once; conn.run called for each command."""
        server = _make_server()
        manager = SSHManager(server)
        mock_conn = _make_mock_conn()
        fake_known = _make_known_hosts()

        with (
            patch("asyncssh.import_known_hosts", return_value=fake_known),
            patch("asyncssh.connect", new=AsyncMock(return_value=mock_conn)) as mock_connect,
        ):
            async with manager as ssh:
                await ssh.run_command("cmd1")
                await ssh.run_command("cmd2")
                await ssh.run_command("cmd3")

        mock_connect.assert_awaited_once()
        assert mock_conn.run.await_count == 3

    @pytest.mark.asyncio
    async def test_context_manager_returns_self(self):
        """__aenter__ must return the SSHManager instance."""
        server = _make_server()
        manager = SSHManager(server)
        mock_conn = _make_mock_conn()
        fake_known = _make_known_hosts()

        with (
            patch("asyncssh.import_known_hosts", return_value=fake_known),
            patch("asyncssh.connect", new=AsyncMock(return_value=mock_conn)),
        ):
            async with manager as ssh:
                assert ssh is manager

    @pytest.mark.asyncio
    async def test_connection_closed_after_context_exit(self):
        """conn.close() must be called after the async with block exits."""
        server = _make_server()
        manager = SSHManager(server)
        mock_conn = _make_mock_conn()
        fake_known = _make_known_hosts()

        with (
            patch("asyncssh.import_known_hosts", return_value=fake_known),
            patch("asyncssh.connect", new=AsyncMock(return_value=mock_conn)),
        ):
            async with manager:
                pass

        mock_conn.close.assert_called_once()
        assert manager._conn is None

    @pytest.mark.asyncio
    async def test_conn_is_none_after_context_exit(self):
        """_conn attribute must be None after exiting the context."""
        server = _make_server()
        manager = SSHManager(server)
        mock_conn = _make_mock_conn()
        fake_known = _make_known_hosts()

        with (
            patch("asyncssh.import_known_hosts", return_value=fake_known),
            patch("asyncssh.connect", new=AsyncMock(return_value=mock_conn)),
        ):
            async with manager:
                assert manager._conn is not None
        assert manager._conn is None


# ── Test: one-shot (no context manager) ──────────────────────────────────────


class TestOneShotCommand:
    """Without async with, each run_command opens+closes its own connection."""

    @pytest.mark.asyncio
    async def test_oneshot_opens_connection_per_command(self):
        """Without context, asyncssh.connect is called for each run_command."""
        server = _make_server()
        manager = SSHManager(server)
        mock_conn = _make_mock_conn()
        fake_known = _make_known_hosts()

        with (
            patch("asyncssh.import_known_hosts", return_value=fake_known),
            patch("asyncssh.connect", new=AsyncMock(return_value=mock_conn)) as mock_connect,
        ):
            await manager.run_command("cmd1")
            await manager.run_command("cmd2")

        assert mock_connect.await_count == 2

    @pytest.mark.asyncio
    async def test_oneshot_conn_is_none_after_command(self):
        """After a one-shot command, _conn must remain None."""
        server = _make_server()
        manager = SSHManager(server)
        mock_conn = _make_mock_conn()
        fake_known = _make_known_hosts()

        with (
            patch("asyncssh.import_known_hosts", return_value=fake_known),
            patch("asyncssh.connect", new=AsyncMock(return_value=mock_conn)),
        ):
            await manager.run_command("cmd")

        assert manager._conn is None


# ── Test: connect_timeout ─────────────────────────────────────────────────────


class TestConnectTimeout:
    """SSH_CONNECT_TIMEOUT must be passed to asyncssh.connect."""

    @pytest.mark.asyncio
    async def test_connect_timeout_passed_on_first_connect(self):
        """TOFU first-connect must include connect_timeout=SSH_CONNECT_TIMEOUT."""
        server = _make_server(host_key=None)
        manager = SSHManager(server)
        mock_conn = _make_mock_conn()

        # Simulate TOFU: set get_server_host_key
        mock_ssh_key = MagicMock()
        mock_ssh_key.export_public_key.return_value = FAKE_KEY_STRING.encode()
        mock_conn.get_server_host_key.return_value = mock_ssh_key

        with (
            patch("asyncssh.connect", new=AsyncMock(return_value=mock_conn)) as mock_connect,
            patch.object(manager, "_auto_persist_host_key", new=AsyncMock()),
        ):
            await manager._connect()

        kwargs = mock_connect.call_args.kwargs
        assert kwargs.get("connect_timeout") == SSH_CONNECT_TIMEOUT

    @pytest.mark.asyncio
    async def test_connect_timeout_passed_on_subsequent_connect(self):
        """Subsequent connect (key stored) must also include connect_timeout."""
        server = _make_server(host_key=FAKE_KEY_STRING)
        manager = SSHManager(server)
        mock_conn = _make_mock_conn()
        fake_known = _make_known_hosts()

        with (
            patch("asyncssh.import_known_hosts", return_value=fake_known),
            patch("asyncssh.connect", new=AsyncMock(return_value=mock_conn)) as mock_connect,
        ):
            await manager._connect()

        kwargs = mock_connect.call_args.kwargs
        assert kwargs.get("connect_timeout") == SSH_CONNECT_TIMEOUT


# ── Test: command timeout ─────────────────────────────────────────────────────


class TestCommandTimeout:
    """Commands that exceed SSH_COMMAND_TIMEOUT must raise a clear exception."""

    @pytest.mark.asyncio
    async def test_timeout_raises_descriptive_exception_in_context(self):
        """When conn.run hangs, a clear exception is raised (persistent mode)."""
        server = _make_server()
        manager = SSHManager(server)
        fake_known = _make_known_hosts()

        async def _hanging_run(*args, **kwargs):
            await asyncio.sleep(9999)

        mock_conn = _make_mock_conn()
        mock_conn.run = _hanging_run

        with (
            patch("asyncssh.import_known_hosts", return_value=fake_known),
            patch("asyncssh.connect", new=AsyncMock(return_value=mock_conn)),
            patch("app.services.ssh_service.SSH_COMMAND_TIMEOUT", 0.01),
        ):
            async with manager:
                with pytest.raises(Exception, match="timed out"):
                    await manager.run_command("sleep 9999")

    @pytest.mark.asyncio
    async def test_timeout_raises_descriptive_exception_oneshot(self):
        """When conn.run hangs in one-shot mode, a clear exception is raised."""
        server = _make_server()
        manager = SSHManager(server)
        fake_known = _make_known_hosts()

        async def _hanging_run(*args, **kwargs):
            await asyncio.sleep(9999)

        mock_conn = _make_mock_conn()
        mock_conn.run = _hanging_run
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("asyncssh.import_known_hosts", return_value=fake_known),
            patch("asyncssh.connect", new=AsyncMock(return_value=mock_conn)),
            patch("app.services.ssh_service.SSH_COMMAND_TIMEOUT", 0.01),
            pytest.raises(Exception, match="timed out"),
        ):
            await manager.run_command("sleep 9999")

    @pytest.mark.asyncio
    async def test_timeout_message_contains_command_prefix(self):
        """Timeout exception message must contain the beginning of the command."""
        server = _make_server()
        manager = SSHManager(server)
        fake_known = _make_known_hosts()

        async def _hanging_run(*args, **kwargs):
            await asyncio.sleep(9999)

        mock_conn = _make_mock_conn()
        mock_conn.run = _hanging_run

        with (
            patch("asyncssh.import_known_hosts", return_value=fake_known),
            patch("asyncssh.connect", new=AsyncMock(return_value=mock_conn)),
            patch("app.services.ssh_service.SSH_COMMAND_TIMEOUT", 0.01),
        ):
            async with manager:
                with pytest.raises(Exception) as exc_info:
                    await manager.run_command("docker build .")
        assert "docker build" in str(exc_info.value)


# ── Test: SSHHostKeyMismatchError propagation ─────────────────────────────────


class TestMismatchPropagation:
    """SSHHostKeyMismatchError from _connect must propagate through the context manager."""

    @pytest.mark.asyncio
    async def test_mismatch_propagates_through_aenter(self):
        """__aenter__ must not swallow SSHHostKeyMismatchError."""
        import asyncssh

        server = _make_server(host_key=FAKE_KEY_STRING)
        manager = SSHManager(server)
        fake_known = _make_known_hosts()

        with (
            patch("asyncssh.import_known_hosts", return_value=fake_known),
            patch(
                "asyncssh.connect",
                new=AsyncMock(side_effect=asyncssh.HostKeyNotVerifiable("mismatch")),
            ),
            pytest.raises(SSHHostKeyMismatchError),
        ):
            async with manager:
                pass  # should never reach here

    @pytest.mark.asyncio
    async def test_mismatch_propagates_through_run_command_oneshot(self):
        """run_command (no context) must propagate SSHHostKeyMismatchError."""
        import asyncssh

        server = _make_server(host_key=FAKE_KEY_STRING)
        manager = SSHManager(server)
        fake_known = _make_known_hosts()

        with (
            patch("asyncssh.import_known_hosts", return_value=fake_known),
            patch(
                "asyncssh.connect",
                new=AsyncMock(side_effect=asyncssh.HostKeyNotVerifiable("mismatch")),
            ),
            pytest.raises(SSHHostKeyMismatchError),
        ):
            await manager.run_command("whoami")


# ── Test: re-entrant context manager ─────────────────────────────────────────


class TestReentrantContext:
    """Nested async with blocks on the same SSHManager must share one connection."""

    @pytest.mark.asyncio
    async def test_nested_context_uses_single_connection(self):
        """Two nested async with blocks → asyncssh.connect called exactly once."""
        server = _make_server()
        manager = SSHManager(server)
        mock_conn = _make_mock_conn()
        fake_known = _make_known_hosts()

        with (
            patch("asyncssh.import_known_hosts", return_value=fake_known),
            patch("asyncssh.connect", new=AsyncMock(return_value=mock_conn)) as mock_connect,
        ):
            async with manager:
                async with manager:
                    await manager.run_command("inner")
                await manager.run_command("outer")

        mock_connect.assert_awaited_once()
        mock_conn.run.assert_awaited()

    @pytest.mark.asyncio
    async def test_connection_closed_only_after_outermost_exit(self):
        """Connection must remain open until the outermost async with exits."""
        server = _make_server()
        manager = SSHManager(server)
        mock_conn = _make_mock_conn()
        fake_known = _make_known_hosts()

        with (
            patch("asyncssh.import_known_hosts", return_value=fake_known),
            patch("asyncssh.connect", new=AsyncMock(return_value=mock_conn)),
        ):
            async with manager:
                async with manager:
                    pass
                # inner block exited — connection should still be open
                assert manager._conn is not None
            # outer block exited — connection must be closed
        assert manager._conn is None
