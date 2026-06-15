"""Unit tests for SSH TOFU (Trust On First Use) host-key verification.

All asyncssh I/O is mocked — no real SSH server needed.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import asyncssh
import pytest

from app.database.models.server import Server
from app.services.ssh_service import SSHHostKeyMismatchError, SSHManager

# ── helpers ──────────────────────────────────────────────────────────────────

FAKE_KEY_STRING = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFakeHostKeyForTestingPurposesOnly"


def _make_server(*, host_key: str | None = None) -> MagicMock:
    """Return a mock object that satisfies SSHManager's Server interface."""
    server = MagicMock(spec=Server)
    server.ip_address = "10.0.0.1"
    server.ssh_port = 22
    server.ssh_user = "root"
    server.ssh_password_encrypted = None
    server.ssh_key_encrypted = None
    server.ssh_host_key = host_key
    return server


def _make_mock_conn(key_string: str = FAKE_KEY_STRING) -> MagicMock:
    """Return a mock SSH connection whose get_server_host_key() works."""
    mock_ssh_key = MagicMock()
    mock_ssh_key.export_public_key.return_value = key_string.encode()

    conn = MagicMock()
    conn.get_server_host_key.return_value = mock_ssh_key
    # Support async context manager (used via `async with await asyncssh.connect(...)`)
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    return conn


def _make_mock_session() -> AsyncMock:
    """Return a mock AsyncSession suitable for persist tests."""
    session = AsyncMock()
    session.add = MagicMock()
    return session


# ── tests ─────────────────────────────────────────────────────────────────────


class TestTOFUFirstConnect:
    """First connection: no stored key → accept any key and capture it."""

    @pytest.mark.asyncio
    async def test_first_connect_uses_known_hosts_none(self):
        """_connect() must pass known_hosts=None on the first connection."""
        server = _make_server(host_key=None)
        manager = SSHManager(server)
        mock_conn = _make_mock_conn()

        with (
            patch("asyncssh.connect", new=AsyncMock(return_value=mock_conn)) as mock_connect,
            patch.object(manager, "_auto_persist_host_key", new=AsyncMock()),
        ):
            conn = await manager._connect()

        call_kwargs = mock_connect.call_args.kwargs
        assert call_kwargs.get("known_hosts") is None, (
            "First TOFU connect must pass known_hosts=None"
        )
        assert conn is mock_conn

    @pytest.mark.asyncio
    async def test_first_connect_discovers_and_stores_key(self):
        """After first connection the discovered key is stored in _discovered_host_key."""
        server = _make_server(host_key=None)
        manager = SSHManager(server)
        mock_conn = _make_mock_conn(FAKE_KEY_STRING)

        with (
            patch("asyncssh.connect", new=AsyncMock(return_value=mock_conn)),
            patch.object(manager, "_auto_persist_host_key", new=AsyncMock()),
        ):
            await manager._connect()

        assert manager._discovered_host_key == FAKE_KEY_STRING

    @pytest.mark.asyncio
    async def test_persist_host_key_writes_to_server(self):
        """_persist_host_key() updates server.ssh_host_key and commits."""
        server = _make_server(host_key=None)
        manager = SSHManager(server)
        manager._discovered_host_key = FAKE_KEY_STRING

        mock_session = _make_mock_session()

        await manager._persist_host_key(mock_session)

        assert server.ssh_host_key == FAKE_KEY_STRING
        mock_session.add.assert_called_once_with(server)
        mock_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_persist_noop_when_no_key_discovered(self):
        """_persist_host_key() is a no-op if nothing was discovered."""
        server = _make_server(host_key=None)
        manager = SSHManager(server)
        manager._discovered_host_key = None

        mock_session = _make_mock_session()
        await manager._persist_host_key(mock_session)

        assert server.ssh_host_key is None
        mock_session.add.assert_not_called()
        mock_session.commit.assert_not_awaited()


class TestTOFUAutoPersist:
    """Auto-persist on first connect: session provided / not provided / repeat connect."""

    @pytest.mark.asyncio
    async def test_first_connect_with_session_auto_persists(self):
        """First connect with session=<mock> must call _persist_host_key and set server.ssh_host_key."""
        server = _make_server(host_key=None)
        mock_session = _make_mock_session()
        manager = SSHManager(server, session=mock_session)
        mock_conn = _make_mock_conn(FAKE_KEY_STRING)

        with patch("asyncssh.connect", new=AsyncMock(return_value=mock_conn)):
            await manager._connect()

        # Key must be captured
        assert manager._discovered_host_key == FAKE_KEY_STRING
        # Key must be persisted on the server object
        assert server.ssh_host_key == FAKE_KEY_STRING
        # Session.add and commit must have been called
        mock_session.add.assert_called_once_with(server)
        mock_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_first_connect_without_session_opens_own_session(self):
        """First connect with session=None must call _persist_host_key via own session."""
        server = _make_server(host_key=None)
        manager = SSHManager(server)  # no session
        mock_conn = _make_mock_conn(FAKE_KEY_STRING)

        mock_session = _make_mock_session()
        mock_session_factory_ctx = AsyncMock()
        mock_session_factory_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_factory_ctx.__aexit__ = AsyncMock(return_value=False)

        # async_session_factory is imported lazily inside _auto_persist_host_key from
        # app.database, so we patch the name at that location.
        with (
            patch("asyncssh.connect", new=AsyncMock(return_value=mock_conn)),
            patch(
                "app.database.async_session_factory",
                return_value=mock_session_factory_ctx,
            ),
        ):
            await manager._connect()

        assert manager._discovered_host_key == FAKE_KEY_STRING
        assert server.ssh_host_key == FAKE_KEY_STRING

    @pytest.mark.asyncio
    async def test_first_connect_no_session_db_error_does_not_raise(self):
        """If the DB session fails when no session was provided, _connect() must NOT raise."""
        server = _make_server(host_key=None)
        manager = SSHManager(server)
        mock_conn = _make_mock_conn(FAKE_KEY_STRING)

        with (
            patch("asyncssh.connect", new=AsyncMock(return_value=mock_conn)),
            patch(
                "app.database.async_session_factory",
                side_effect=Exception("DB unavailable"),
            ),
        ):
            # Should complete without raising
            conn = await manager._connect()

        assert conn is mock_conn
        # Key is still captured in memory even if persist failed
        assert manager._discovered_host_key == FAKE_KEY_STRING

    @pytest.mark.asyncio
    async def test_subsequent_connect_with_session_does_not_persist_again(self):
        """Second connect (key already in DB) must NOT call session.add/commit."""
        server = _make_server(host_key=FAKE_KEY_STRING)
        mock_session = _make_mock_session()
        manager = SSHManager(server, session=mock_session)
        mock_conn = _make_mock_conn()

        fake_known = MagicMock()
        with (
            patch("asyncssh.import_known_hosts", return_value=fake_known),
            patch("asyncssh.connect", new=AsyncMock(return_value=mock_conn)),
        ):
            await manager._connect()

        # _discovered_host_key must be None (no new discovery)
        assert manager._discovered_host_key is None
        # Nothing should have been persisted
        mock_session.add.assert_not_called()
        mock_session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_subsequent_connect_without_session_does_not_persist(self):
        """Second connect with session=None must not attempt to open a DB session."""
        server = _make_server(host_key=FAKE_KEY_STRING)
        manager = SSHManager(server)  # no session
        mock_conn = _make_mock_conn()

        fake_known = MagicMock()
        with (
            patch("asyncssh.import_known_hosts", return_value=fake_known),
            patch("asyncssh.connect", new=AsyncMock(return_value=mock_conn)),
            patch("app.database.async_session_factory") as mock_factory,
        ):
            await manager._connect()

        # DB session factory must NOT have been called
        mock_factory.assert_not_called()


class TestTOFUSubsequentConnect:
    """Subsequent connections: stored key exists → verify strictly."""

    @pytest.mark.asyncio
    async def test_subsequent_connect_passes_known_hosts_object(self):
        """_connect() must pass a non-None known_hosts on subsequent connections."""
        server = _make_server(host_key=FAKE_KEY_STRING)
        manager = SSHManager(server)
        mock_conn = _make_mock_conn()

        fake_known = MagicMock()
        with (
            patch("asyncssh.import_known_hosts", return_value=fake_known) as mock_import,
            patch("asyncssh.connect", new=AsyncMock(return_value=mock_conn)) as mock_connect,
        ):
            await manager._connect()

        # import_known_hosts must be called with the stored key line
        mock_import.assert_called_once()
        call_arg = mock_import.call_args.args[0]
        assert FAKE_KEY_STRING in call_arg, "Stored key must appear in known_hosts line"
        assert "10.0.0.1" in call_arg, "Host IP must appear in known_hosts line"

        # The known_hosts kwarg to connect() must be the parsed object
        connect_kwargs = mock_connect.call_args.kwargs
        assert connect_kwargs.get("known_hosts") is fake_known

    @pytest.mark.asyncio
    async def test_subsequent_connect_no_new_key_discovery(self):
        """_discovered_host_key should be None when key was already stored."""
        server = _make_server(host_key=FAKE_KEY_STRING)
        manager = SSHManager(server)
        mock_conn = _make_mock_conn()

        fake_known = MagicMock()
        with (
            patch("asyncssh.import_known_hosts", return_value=fake_known),
            patch("asyncssh.connect", new=AsyncMock(return_value=mock_conn)),
        ):
            await manager._connect()

        assert manager._discovered_host_key is None


class TestTOFUMismatch:
    """Host-key mismatch → SSHHostKeyMismatchError raised, connection NOT continued."""

    @pytest.mark.asyncio
    async def test_mismatch_raises_domain_exception(self):
        """HostKeyNotVerifiable from asyncssh must be wrapped in SSHHostKeyMismatchError."""
        server = _make_server(host_key=FAKE_KEY_STRING)
        manager = SSHManager(server)

        fake_known = MagicMock()
        with (
            patch("asyncssh.import_known_hosts", return_value=fake_known),
            patch(
                "asyncssh.connect",
                new=AsyncMock(side_effect=asyncssh.HostKeyNotVerifiable("key mismatch")),
            ),
            pytest.raises(SSHHostKeyMismatchError) as exc_info,
        ):
            await manager._connect()

        assert "10.0.0.1" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_permission_denied_on_host_key_raises_domain_exception(self):
        """asyncssh.PermissionDenied (host key rejection) also raises SSHHostKeyMismatchError."""
        server = _make_server(host_key=FAKE_KEY_STRING)
        manager = SSHManager(server)

        fake_known = MagicMock()
        with (
            patch("asyncssh.import_known_hosts", return_value=fake_known),
            patch(
                "asyncssh.connect",
                new=AsyncMock(side_effect=asyncssh.PermissionDenied("host key")),
            ),
            pytest.raises(SSHHostKeyMismatchError),
        ):
            await manager._connect()

    @pytest.mark.asyncio
    async def test_mismatch_exception_not_swallowed_by_test_connection(self):
        """test_connection() must re-raise SSHHostKeyMismatchError, not return False."""
        server = _make_server(host_key=FAKE_KEY_STRING)
        manager = SSHManager(server)

        fake_known = MagicMock()
        with (
            patch("asyncssh.import_known_hosts", return_value=fake_known),
            patch(
                "asyncssh.connect",
                new=AsyncMock(side_effect=asyncssh.HostKeyNotVerifiable("mismatch")),
            ),
            pytest.raises(SSHHostKeyMismatchError),
        ):
            await manager.test_connection()

    @pytest.mark.asyncio
    async def test_corrupted_stored_key_raises_domain_exception(self):
        """If import_known_hosts itself raises (bad stored key), SSHHostKeyMismatchError raised."""
        server = _make_server(host_key="not-a-valid-key")
        manager = SSHManager(server)

        with (
            patch(
                "asyncssh.import_known_hosts",
                side_effect=ValueError("invalid key format"),
            ),
            pytest.raises(SSHHostKeyMismatchError),
        ):
            await manager._connect()

    @pytest.mark.asyncio
    async def test_mismatch_with_session_does_not_persist(self):
        """On host-key mismatch, session.add/commit must NOT be called."""
        server = _make_server(host_key=FAKE_KEY_STRING)
        mock_session = _make_mock_session()
        manager = SSHManager(server, session=mock_session)

        fake_known = MagicMock()
        with (
            patch("asyncssh.import_known_hosts", return_value=fake_known),
            patch(
                "asyncssh.connect",
                new=AsyncMock(side_effect=asyncssh.HostKeyNotVerifiable("key mismatch")),
            ),
            pytest.raises(SSHHostKeyMismatchError),
        ):
            await manager._connect()

        mock_session.add.assert_not_called()
        mock_session.commit.assert_not_awaited()


class TestSSHHostKeyMismatchException:
    """Sanity checks on the exception itself."""

    def test_host_attribute(self):
        exc = SSHHostKeyMismatchError("192.168.1.1", "wrong key")
        assert exc.host == "192.168.1.1"

    def test_str_contains_host_and_message(self):
        exc = SSHHostKeyMismatchError("192.168.1.1", "wrong key")
        s = str(exc)
        assert "192.168.1.1" in s
        assert "wrong key" in s

    def test_is_exception_subclass(self):
        assert issubclass(SSHHostKeyMismatchError, Exception)
