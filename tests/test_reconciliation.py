"""Tests for zombie/phantom reconciliation and transaction boundaries in sync_service."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_server(server_id: int = 1) -> MagicMock:
    server = MagicMock()
    server.id = server_id
    server.name = f"Server-{server_id}"
    server.ip_address = "10.0.0.1"
    server.is_online = True
    server.sync_status = "synced"
    server.sync_error = None
    xui_panel = MagicMock()
    xui_panel.url = "https://panel.example.com"
    xui_panel.username = "admin"
    server.xui_panel = xui_panel
    return server


def _make_xui_connection(
    conn_id: int = 1,
    email: str = "user@vpn",
    sync_status: str = "error",
    subscription_id: int = 10,
    inbound_id: int = 5,
) -> MagicMock:
    conn = MagicMock()
    conn.id = conn_id
    conn.email = email
    conn.sync_status = sync_status
    conn.subscription_id = subscription_id
    conn.inbound_id = inbound_id
    return conn


def _make_sync_service(session: MagicMock) -> MagicMock:
    """Build a real SyncService-like object without importing heavy deps."""
    from app.services.sync_service import SyncService

    svc = SyncService.__new__(SyncService)
    svc.session = session
    svc._is_running = False
    svc._xui_service = MagicMock()
    return svc


def _make_session() -> MagicMock:
    session = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.flush = AsyncMock()
    session.delete = MagicMock()
    return session


def _old_created_at_ms() -> int:
    """createdAt (epoch ms) older than grace-period — zombie should be deleted."""
    return int((time.time() - 20 * 60) * 1000)  # 20 minutes ago


def _fresh_created_at_ms() -> int:
    """createdAt (epoch ms) within grace-period — zombie must NOT be deleted."""
    return int(time.time() * 1000)  # right now


# ---------------------------------------------------------------------------
# 2a. Phantom tests
# ---------------------------------------------------------------------------


class TestPhantomReconciliation:
    """Фантомы БД: sync_status='error', клиента нет на панели → удалить."""

    @pytest.mark.asyncio
    async def test_phantom_deleted_when_absent_from_panel(self, mock_settings):
        """Соединение error + email отсутствует в снимке get_clients() → session.delete вызван."""
        session = _make_session()

        conn = _make_xui_connection(conn_id=42, email="ghost@vpn", sync_status="error")

        from app.services.sync_service import SyncService

        svc = SyncService.__new__(SyncService)
        svc.session = session
        svc._xui_service = MagicMock()

        xui_client = MagicMock()
        # get_clients() snapshot: ghost@vpn is NOT present
        xui_client.get_clients = AsyncMock(return_value=[])

        server = _make_server()

        # Mock session.execute: error_connections, sub_tokens, xui_inbounds, pairs
        execute_results = [
            _make_scalars_result([conn]),
            _make_rows_result([]),
            _make_rows_result([]),
            _make_rows_result([]),
        ]
        session.execute = AsyncMock(side_effect=execute_results)

        await svc._reconcile_xui_server(server, xui_client)

        session.delete.assert_called_once_with(conn)

    @pytest.mark.asyncio
    async def test_phantom_restored_when_present_on_panel(self, mock_settings):
        """Соединение error + email ЕСТЬ в снимке get_clients() → sync_status='synced', не удалён."""
        session = _make_session()

        conn = _make_xui_connection(conn_id=7, email="alive@vpn", sync_status="error")

        from app.services.sync_service import SyncService

        svc = SyncService.__new__(SyncService)
        svc.session = session
        svc._xui_service = MagicMock()

        xui_client = MagicMock()
        # get_clients() snapshot: alive@vpn IS present
        xui_client.get_clients = AsyncMock(
            return_value=[{"email": "alive@vpn", "subId": "", "inboundIds": []}]
        )

        server = _make_server()

        execute_results = [
            _make_scalars_result([conn]),
            _make_rows_result([]),
            _make_rows_result([]),
            _make_rows_result([]),
        ]
        session.execute = AsyncMock(side_effect=execute_results)

        await svc._reconcile_xui_server(server, xui_client)

        session.delete.assert_not_called()
        assert conn.sync_status == "synced"

    @pytest.mark.asyncio
    async def test_get_clients_raises_skips_entire_reconciliation(self, mock_settings):
        """get_clients() бросает → реконсиляция пропущена, ничего не удалено (ни зомби, ни фантомы)."""
        session = _make_session()

        from app.services.sync_service import SyncService

        svc = SyncService.__new__(SyncService)
        svc.session = session
        svc._xui_service = MagicMock()

        xui_client = MagicMock()
        xui_client.get_clients = AsyncMock(side_effect=Exception("connection refused"))

        server = _make_server()
        # execute should NOT be called because we return early
        session.execute = AsyncMock()

        await svc._reconcile_xui_server(server, xui_client)

        session.delete.assert_not_called()
        session.execute.assert_not_called()


# ---------------------------------------------------------------------------
# 2b. XUI zombie tests
# ---------------------------------------------------------------------------


class TestXUIZombieReconciliation:
    """XUI зомби: subId == токен существующей подписки, нет InboundConnection → удалить с панели."""

    @pytest.mark.asyncio
    async def test_zombie_deleted_when_old_enough(self, mock_settings):
        """subId совпадает с подпиской, нет connection, createdAt старый → delete_client вызван."""
        session = _make_session()

        from app.services.sync_service import SyncService

        svc = SyncService.__new__(SyncService)
        svc.session = session
        svc._xui_service = MagicMock()

        bot_token = "bot-token-123"
        panel_client = {
            "email": "zombie@vpn",
            "subId": bot_token,
            "inboundIds": [10],  # xui_id=10
            "createdAt": _old_created_at_ms(),
        }

        xui_client = MagicMock()
        xui_client.get_clients = AsyncMock(return_value=[panel_client])
        xui_client.delete_client = AsyncMock(return_value=True)

        server = _make_server()

        execute_results = [
            # error connections: none
            _make_scalars_result([]),
            # subscription tokens: bot_token → sub_id=99
            _make_rows_result([(bot_token, 99)]),
            # xui inbounds: xui_id=10 → inbound_db_id=5
            _make_rows_result([(10, 5)]),
            # existing pairs: no connection for (99, 5)
            _make_rows_result([]),
        ]
        session.execute = AsyncMock(side_effect=execute_results)

        await svc._reconcile_xui_server(server, xui_client)

        xui_client.delete_client.assert_called_once_with("zombie@vpn")

    @pytest.mark.asyncio
    async def test_zombie_skipped_within_grace_period(self, mock_settings):
        """Зомби моложе grace-period (createdAt=сейчас) → НЕ удалён."""
        session = _make_session()

        from app.services.sync_service import SyncService

        svc = SyncService.__new__(SyncService)
        svc.session = session
        svc._xui_service = MagicMock()

        bot_token = "fresh-token"
        panel_client = {
            "email": "fresh-zombie@vpn",
            "subId": bot_token,
            "inboundIds": [10],
            "createdAt": _fresh_created_at_ms(),  # right now — within grace period
        }

        xui_client = MagicMock()
        xui_client.get_clients = AsyncMock(return_value=[panel_client])
        xui_client.delete_client = AsyncMock(return_value=True)

        server = _make_server()

        execute_results = [
            _make_scalars_result([]),
            _make_rows_result([(bot_token, 99)]),
            _make_rows_result([(10, 5)]),
            _make_rows_result([]),  # no connection → would be zombie IF old enough
        ]
        session.execute = AsyncMock(side_effect=execute_results)

        await svc._reconcile_xui_server(server, xui_client)

        xui_client.delete_client.assert_not_called()

    @pytest.mark.asyncio
    async def test_zombie_without_created_at_not_deleted(self, mock_settings):
        """Клиент без createdAt/0 → не удалён (безопаснее пропустить)."""
        session = _make_session()

        from app.services.sync_service import SyncService

        svc = SyncService.__new__(SyncService)
        svc.session = session
        svc._xui_service = MagicMock()

        bot_token = "no-ts-token"
        # No createdAt field at all
        panel_client = {
            "email": "nots@vpn",
            "subId": bot_token,
            "inboundIds": [10],
        }

        xui_client = MagicMock()
        xui_client.get_clients = AsyncMock(return_value=[panel_client])
        xui_client.delete_client = AsyncMock(return_value=True)

        server = _make_server()

        execute_results = [
            _make_scalars_result([]),
            _make_rows_result([(bot_token, 99)]),
            _make_rows_result([(10, 5)]),
            _make_rows_result([]),
        ]
        session.execute = AsyncMock(side_effect=execute_results)

        await svc._reconcile_xui_server(server, xui_client)

        xui_client.delete_client.assert_not_called()

    @pytest.mark.asyncio
    async def test_zombie_with_zero_created_at_not_deleted(self, mock_settings):
        """Клиент с createdAt=0 → не удалён."""
        session = _make_session()

        from app.services.sync_service import SyncService

        svc = SyncService.__new__(SyncService)
        svc.session = session
        svc._xui_service = MagicMock()

        bot_token = "zero-ts-token"
        panel_client = {
            "email": "zeronts@vpn",
            "subId": bot_token,
            "inboundIds": [10],
            "createdAt": 0,
        }

        xui_client = MagicMock()
        xui_client.get_clients = AsyncMock(return_value=[panel_client])
        xui_client.delete_client = AsyncMock(return_value=True)

        server = _make_server()

        execute_results = [
            _make_scalars_result([]),
            _make_rows_result([(bot_token, 99)]),
            _make_rows_result([(10, 5)]),
            _make_rows_result([]),
        ]
        session.execute = AsyncMock(side_effect=execute_results)

        await svc._reconcile_xui_server(server, xui_client)

        xui_client.delete_client.assert_not_called()

    @pytest.mark.asyncio
    async def test_zombie_empty_email_not_deleted(self, mock_settings):
        """Зомби с пустым email → не удалён."""
        session = _make_session()

        from app.services.sync_service import SyncService

        svc = SyncService.__new__(SyncService)
        svc.session = session
        svc._xui_service = MagicMock()

        bot_token = "bot-token-empty-email"
        panel_client = {
            "email": "",  # пустой email
            "subId": bot_token,
            "inboundIds": [10],
            "createdAt": _old_created_at_ms(),
        }

        xui_client = MagicMock()
        xui_client.get_clients = AsyncMock(return_value=[panel_client])
        xui_client.delete_client = AsyncMock(return_value=True)

        server = _make_server()

        execute_results = [
            _make_scalars_result([]),
            _make_rows_result([(bot_token, 99)]),
            _make_rows_result([(10, 5)]),
            _make_rows_result([]),
        ]
        session.execute = AsyncMock(side_effect=execute_results)

        await svc._reconcile_xui_server(server, xui_client)

        xui_client.delete_client.assert_not_called()

    @pytest.mark.asyncio
    async def test_unknown_sub_id_not_deleted(self, mock_settings):
        """subId НЕ совпадает ни с одной подпиской → НЕ удалён, warning залогирован."""
        session = _make_session()

        from app.services.sync_service import SyncService

        svc = SyncService.__new__(SyncService)
        svc.session = session
        svc._xui_service = MagicMock()

        panel_client = {
            "email": "manual@vpn",
            "subId": "unknown-token-xyz",
            "inboundIds": [10],
            "createdAt": _old_created_at_ms(),
        }

        xui_client = MagicMock()
        xui_client.get_clients = AsyncMock(return_value=[panel_client])
        xui_client.delete_client = AsyncMock()

        server = _make_server()

        execute_results = [
            _make_scalars_result([]),       # no error connections
            _make_rows_result([("other-token", 1)]),  # DB has different token
            _make_rows_result([(10, 5)]),
            _make_rows_result([]),
        ]
        session.execute = AsyncMock(side_effect=execute_results)

        with patch("app.services.sync_service.logger") as mock_logger:
            await svc._reconcile_xui_server(server, xui_client)

            xui_client.delete_client.assert_not_called()
            # Warning должен быть залогирован
            warning_calls = [str(c) for c in mock_logger.warning.call_args_list]
            assert any("unknown-token-xyz" in w or "manual@vpn" in w for w in warning_calls)

    @pytest.mark.asyncio
    async def test_client_without_sub_id_not_deleted(self, mock_settings):
        """Клиент без subId → не трогать (debug-лог, не удалять)."""
        session = _make_session()

        from app.services.sync_service import SyncService

        svc = SyncService.__new__(SyncService)
        svc.session = session
        svc._xui_service = MagicMock()

        panel_client = {
            "email": "nosub@vpn",
            "subId": "",  # пустой subId
            "inboundIds": [10],
            "createdAt": _old_created_at_ms(),
        }

        xui_client = MagicMock()
        xui_client.get_clients = AsyncMock(return_value=[panel_client])
        xui_client.delete_client = AsyncMock()

        server = _make_server()

        execute_results = [
            _make_scalars_result([]),
            _make_rows_result([("some-token", 1)]),
            _make_rows_result([(10, 5)]),
            _make_rows_result([]),
        ]
        session.execute = AsyncMock(side_effect=execute_results)

        await svc._reconcile_xui_server(server, xui_client)

        xui_client.delete_client.assert_not_called()

    @pytest.mark.asyncio
    async def test_connected_client_not_deleted(self, mock_settings):
        """subId совпадает с подпиской И есть InboundConnection → клиент не удаляется."""
        session = _make_session()

        from app.services.sync_service import SyncService

        svc = SyncService.__new__(SyncService)
        svc.session = session
        svc._xui_service = MagicMock()

        bot_token = "connected-token"
        panel_client = {
            "email": "connected@vpn",
            "subId": bot_token,
            "inboundIds": [10],
            "createdAt": _old_created_at_ms(),
        }

        xui_client = MagicMock()
        xui_client.get_clients = AsyncMock(return_value=[panel_client])
        xui_client.delete_client = AsyncMock()

        server = _make_server()

        execute_results = [
            _make_scalars_result([]),
            _make_rows_result([(bot_token, 99)]),  # sub_id=99
            _make_rows_result([(10, 5)]),           # xui_id=10 → inbound_db_id=5
            _make_rows_result([(99, 5)]),           # pair (99,5) exists → NOT zombie
        ]
        session.execute = AsyncMock(side_effect=execute_results)

        await svc._reconcile_xui_server(server, xui_client)

        xui_client.delete_client.assert_not_called()


# ---------------------------------------------------------------------------
# C5. Transaction boundary tests
# ---------------------------------------------------------------------------


class TestTransactionBoundaries:
    """C5: при исключении в sync_server → rollback, не commit."""

    @pytest.mark.asyncio
    async def test_exception_triggers_rollback_not_commit(self, mock_settings):
        """Исключение в _sync_server_inbounds → rollback вызван, commit НЕ вызван."""
        session = _make_session()

        from app.services.sync_service import SyncService

        svc = SyncService.__new__(SyncService)
        svc.session = session
        svc._is_running = False
        svc._xui_service = MagicMock()
        import asyncio
        svc._sync_lock = asyncio.Lock()

        server = _make_server()
        server.last_sync_at = None
        server.sync_status = "error"  # needs sync

        # Patch _save_server_error_status to a no-op so we don't need a full DB
        with (
            patch.object(svc, "_needs_sync", return_value=True),
            patch.object(
                svc,
                "_sync_server_inbounds",
                new=AsyncMock(side_effect=RuntimeError("boom")),
            ),
            patch.object(svc, "_save_server_error_status", new=AsyncMock()),
            patch("app.services.server_monitor.ServerMonitor.ping", new=AsyncMock(return_value=True)),
        ):
            # Мокируем session.execute для запроса inbounds
            session.execute = AsyncMock(return_value=_make_scalars_result([]))

            result = await svc.sync_server(server, force=True)

        assert result is False
        session.rollback.assert_called_once()
        session.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_success_triggers_single_commit_no_rollback(self, mock_settings):
        """Успешная синхронизация → ровно один commit, rollback не вызван."""
        session = _make_session()

        from app.services.sync_service import SyncService

        svc = SyncService.__new__(SyncService)
        svc.session = session
        svc._is_running = False
        svc._xui_service = MagicMock()
        svc._xui_service._get_client = AsyncMock(return_value=MagicMock())
        import asyncio
        svc._sync_lock = asyncio.Lock()

        server = _make_server()
        server.last_sync_at = None
        server.sync_status = "synced"

        reconcile_mock = AsyncMock()

        with (
            patch.object(svc, "_needs_sync", return_value=True),
            patch.object(svc, "_sync_server_inbounds", new=AsyncMock()),
            patch.object(svc, "_reconcile_xui_server", new=reconcile_mock),
            patch("app.services.server_monitor.ServerMonitor.ping", new=AsyncMock(return_value=True)),
        ):
            session.execute = AsyncMock(return_value=_make_scalars_result([]))

            result = await svc.sync_server(server, force=True)

        assert result is True
        session.commit.assert_called_once()
        session.rollback.assert_not_called()

    @pytest.mark.asyncio
    async def test_error_status_saved_after_rollback(self, mock_settings):
        """При ошибке sync_server: rollback → _save_server_error_status вызван с нужными аргументами."""
        from app.xui_client import XUIError

        session = _make_session()

        from app.services.sync_service import SyncService

        svc = SyncService.__new__(SyncService)
        svc.session = session
        svc._is_running = False
        svc._xui_service = MagicMock()
        svc._xui_service._get_client = AsyncMock(return_value=MagicMock())
        import asyncio
        svc._sync_lock = asyncio.Lock()

        server = _make_server()
        server.last_sync_at = None
        server.sync_status = "synced"

        save_status_mock = AsyncMock()

        with (
            patch.object(svc, "_needs_sync", return_value=True),
            patch.object(
                svc,
                "_sync_server_inbounds",
                new=AsyncMock(side_effect=XUIError("panel error")),
            ),
            patch.object(svc, "_save_server_error_status", new=save_status_mock),
            patch("app.services.server_monitor.ServerMonitor.ping", new=AsyncMock(return_value=True)),
        ):
            session.execute = AsyncMock(return_value=_make_scalars_result([]))

            result = await svc.sync_server(server, force=True)

        assert result is False
        session.rollback.assert_called_once()
        # _save_server_error_status должен быть вызван ПОСЛЕ rollback
        save_status_mock.assert_awaited_once()
        call_args = save_status_mock.await_args
        assert call_args.args[0] == server.id  # server_id
        assert call_args.args[1] == "error"    # sync_status


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------


def _make_scalars_result(objects: list) -> MagicMock:
    """Return a mock that mimics session.execute().scalars().all()."""
    result = MagicMock()
    scalars_mock = MagicMock()
    scalars_mock.all = MagicMock(return_value=objects)
    result.scalars = MagicMock(return_value=scalars_mock)
    return result


def _make_rows_result(rows: list) -> MagicMock:
    """Return a mock that mimics session.execute().all() (for row queries)."""
    result = MagicMock()
    result.all = MagicMock(return_value=rows)
    result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=rows)))
    return result
