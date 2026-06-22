"""Режимы обработки расхождений реконсайлером: auto / ask / report / mass-threshold."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from app.database.models import (
    Client,
    PendingDivergence,
    Server,
    Subscription,
    XUIInbound,
)
from app.services.divergence_service import KIND_EXTRA, STATUS_OPEN
from app.services.sync_service import SyncService


def _old_ms() -> int:
    return int((time.time() - 20 * 60) * 1000)  # 20 минут назад — старше grace


async def _setup(session, *, tokens_inbounds):
    """Создать сервер и набор (token, xui_id) подписок/инбаундов без соединений.

    tokens_inbounds: list[(token, xui_id)] — на каждый создаётся подписка и XUIInbound.
    Соединений нет → панельный клиент с таким subId будет «extra»-зомби.
    """
    server = Server(name="S", ip_address="1.2.3.4", is_active=True)
    session.add(server)
    await session.flush()
    client = Client(name="N", email="n@x", telegram_id=1, is_admin=False, is_active=True)
    session.add(client)
    await session.flush()
    for token, xui_id in tokens_inbounds:
        session.add(
            XUIInbound(
                server_id=server.id, remark="r", protocol="vless", is_active=True, xui_id=xui_id
            )
        )
        session.add(
            Subscription(
                client_id=client.id,
                name="sub",
                subscription_token=token,
                total_gb=1,
                expiry_date=None,
                is_active=True,
            )
        )
    await session.flush()
    return server


def _svc(session):
    svc = SyncService.__new__(SyncService)
    svc.session = session
    svc._xui_service = MagicMock()
    return svc


def _panel_zombie(email, token, xui_id):
    return {
        "email": email,
        "subId": token,
        "inboundIds": [xui_id],
        "createdAt": _old_ms(),
        "uuid": "u",
        "totalGB": 0,
        "expiryTime": 0,
        "enable": True,
    }


@pytest.mark.asyncio
async def test_ask_records_pending_no_delete(test_session, mock_settings):
    mock_settings.reconcile_mode = "ask"
    server = await _setup(test_session, tokens_inbounds=[("tok", 10)])
    xui = MagicMock()
    xui.get_clients = AsyncMock(return_value=[_panel_zombie("z@x", "tok", 10)])
    xui.delete_client = AsyncMock()
    xui.detach_client = AsyncMock()

    notify = AsyncMock()
    with patch(
        "app.services.notification_service.NotificationService.notify_admins_divergences",
        new=notify,
        create=True,
    ):
        await _svc(test_session)._reconcile_xui_server(server, xui)

    pendings = (await test_session.execute(select(PendingDivergence))).scalars().all()
    assert len(pendings) == 1
    assert pendings[0].kind == KIND_EXTRA
    assert pendings[0].email == "z@x"
    assert pendings[0].status == STATUS_OPEN
    xui.delete_client.assert_not_called()
    xui.detach_client.assert_not_called()
    notify.assert_awaited_once()


@pytest.mark.asyncio
async def test_auto_deletes_zombie(test_session, mock_settings):
    mock_settings.reconcile_mode = "auto"
    server = await _setup(test_session, tokens_inbounds=[("tok", 10)])
    xui = MagicMock()
    xui.get_clients = AsyncMock(return_value=[_panel_zombie("z@x", "tok", 10)])
    xui.delete_client = AsyncMock(return_value=True)
    xui.detach_client = AsyncMock()

    await _svc(test_session)._reconcile_xui_server(server, xui)

    xui.delete_client.assert_awaited_once_with("z@x")
    pendings = (await test_session.execute(select(PendingDivergence))).scalars().all()
    assert pendings == []


@pytest.mark.asyncio
async def test_report_no_delete_no_pending(test_session, mock_settings):
    mock_settings.reconcile_mode = "report"
    server = await _setup(test_session, tokens_inbounds=[("tok", 10)])
    xui = MagicMock()
    xui.get_clients = AsyncMock(return_value=[_panel_zombie("z@x", "tok", 10)])
    xui.delete_client = AsyncMock()

    report = AsyncMock()
    with patch(
        "app.services.notification_service.NotificationService.notify_admins_divergences_report",
        new=report,
        create=True,
    ):
        await _svc(test_session)._reconcile_xui_server(server, xui)

    xui.delete_client.assert_not_called()
    pendings = (await test_session.execute(select(PendingDivergence))).scalars().all()
    assert pendings == []
    report.assert_awaited_once()


@pytest.mark.asyncio
async def test_mass_threshold_forces_ask(test_session, mock_settings):
    """auto, но расхождений больше порога → принудительно ask (ничего не удаляем)."""
    mock_settings.reconcile_mode = "auto"
    mock_settings.reconcile_mass_threshold = 1
    server = await _setup(test_session, tokens_inbounds=[("t1", 10), ("t2", 20)])
    xui = MagicMock()
    xui.get_clients = AsyncMock(
        return_value=[
            _panel_zombie("z1@x", "t1", 10),
            _panel_zombie("z2@x", "t2", 20),
        ]
    )
    xui.delete_client = AsyncMock()
    xui.detach_client = AsyncMock()

    notify = AsyncMock()
    with patch(
        "app.services.notification_service.NotificationService.notify_admins_divergences",
        new=notify,
        create=True,
    ):
        await _svc(test_session)._reconcile_xui_server(server, xui)

    xui.delete_client.assert_not_called()
    pendings = (await test_session.execute(select(PendingDivergence))).scalars().all()
    assert len(pendings) == 2
