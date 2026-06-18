"""Регресс: при создании подписки XUI-inbound'ы одной панели объединяются в один клиент.

3x-ui v3.2.5+ отвергает повторное использование subId, поэтому несколько XUI-inbound'ов
одного сервера должны создаваться ОДНИМ вызовом ``add_xui_inbounds_to_subscription``
(через ``inboundIds``). AWG/MTProxy создаются по одному через ``add_inbound_to_subscription``.
"""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_inbound(ib_id: int, ib_type: str, server_id: int, server_name: str):
    server = SimpleNamespace(name=server_name, panel_type="xui")
    return SimpleNamespace(
        id=ib_id,
        type=ib_type,
        server_id=server_id,
        remark=f"inbound-{ib_id}",
        server=server,
    )


@pytest.mark.asyncio
async def test_create_subscription_groups_xui_inbounds_per_server(monkeypatch):
    import app.bot.handlers.admin.subscriptions as subs

    mock_session = AsyncMock()

    @asynccontextmanager
    async def fake_factory():
        yield mock_session

    monkeypatch.setattr(subs, "async_session_factory", fake_factory)

    # Два XUI-inbound'а на сервере 1 + один AWG-inbound на сервере 2.
    xui_1 = _make_inbound(11, "xui_inbound", 1, "Server-1")
    xui_2 = _make_inbound(12, "xui_inbound", 1, "Server-1")
    awg_1 = _make_inbound(21, "awg_inbound", 2, "Server-2")

    inbounds_by_server = {1: [xui_1, xui_2], 2: [awg_1]}

    mock_xui = MagicMock()
    mock_xui.get_server_inbounds = AsyncMock(
        side_effect=lambda s_id: inbounds_by_server.get(s_id, [])
    )
    mock_xui.close_all_clients = AsyncMock()
    monkeypatch.setattr(subs, "XUIService", MagicMock(return_value=mock_xui))

    mock_client_service = MagicMock()
    mock_client_service.get_client_by_id = AsyncMock(
        return_value=SimpleNamespace(name="Client")
    )
    monkeypatch.setattr(subs, "ClientService", MagicMock(return_value=mock_client_service))

    subscription = SimpleNamespace(
        id=7,
        name="Sub",
        subscription_token="tok",
        client=SimpleNamespace(name="Client"),
    )

    mock_sub_service = MagicMock()
    mock_sub_service.create_subscription = AsyncMock(return_value=(subscription, None))
    mock_sub_service.add_xui_inbounds_to_subscription = AsyncMock(
        return_value=[MagicMock(), MagicMock()]
    )
    mock_sub_service.add_inbound_to_subscription = AsyncMock(return_value=MagicMock())
    mock_sub_service.close_all_clients = AsyncMock()
    monkeypatch.setattr(
        "app.services.new_subscription_service.NewSubscriptionService",
        MagicMock(return_value=mock_sub_service),
    )

    mock_notification = MagicMock()
    mock_notification.notify_subscription_created = AsyncMock()
    monkeypatch.setattr(
        "app.services.notification_service.NotificationService",
        MagicMock(return_value=mock_notification),
    )

    callback = AsyncMock()
    callback.message = AsyncMock()
    state = AsyncMock()
    state.get_data = AsyncMock(
        return_value={
            "client_id": 1,
            "subscription_name": "Sub",
            "total_gb": 10,
            "expiry_days": 30,
            "server_ids": {1, 2},
            "selected_inbounds": {11, 12, 21},
        }
    )

    await subs.create_subscription(callback, state)

    # XUI-inbound'ы сервера 1 — ровно один батч-вызов с обоими id.
    mock_sub_service.add_xui_inbounds_to_subscription.assert_awaited_once_with(7, [11, 12])
    # AWG-inbound — отдельный одиночный вызов.
    mock_sub_service.add_inbound_to_subscription.assert_awaited_once_with(7, 21)


@pytest.mark.asyncio
async def test_create_subscription_groups_xui_inbounds_across_servers(monkeypatch):
    import app.bot.handlers.admin.subscriptions as subs

    mock_session = AsyncMock()

    @asynccontextmanager
    async def fake_factory():
        yield mock_session

    monkeypatch.setattr(subs, "async_session_factory", fake_factory)

    # По два XUI-inbound'а на каждом из двух серверов.
    xui_s1_a = _make_inbound(11, "xui_inbound", 1, "Server-1")
    xui_s1_b = _make_inbound(12, "xui_inbound", 1, "Server-1")
    xui_s2_a = _make_inbound(21, "xui_inbound", 2, "Server-2")
    xui_s2_b = _make_inbound(22, "xui_inbound", 2, "Server-2")

    inbounds_by_server = {1: [xui_s1_a, xui_s1_b], 2: [xui_s2_a, xui_s2_b]}

    mock_xui = MagicMock()
    mock_xui.get_server_inbounds = AsyncMock(
        side_effect=lambda s_id: inbounds_by_server.get(s_id, [])
    )
    mock_xui.close_all_clients = AsyncMock()
    monkeypatch.setattr(subs, "XUIService", MagicMock(return_value=mock_xui))

    mock_client_service = MagicMock()
    mock_client_service.get_client_by_id = AsyncMock(
        return_value=SimpleNamespace(name="Client")
    )
    monkeypatch.setattr(subs, "ClientService", MagicMock(return_value=mock_client_service))

    subscription = SimpleNamespace(
        id=7,
        name="Sub",
        subscription_token="tok",
        client=SimpleNamespace(name="Client"),
    )

    mock_sub_service = MagicMock()
    mock_sub_service.create_subscription = AsyncMock(return_value=(subscription, None))
    mock_sub_service.add_xui_inbounds_to_subscription = AsyncMock(
        return_value=[MagicMock(), MagicMock()]
    )
    mock_sub_service.add_inbound_to_subscription = AsyncMock(return_value=MagicMock())
    mock_sub_service.close_all_clients = AsyncMock()
    monkeypatch.setattr(
        "app.services.new_subscription_service.NewSubscriptionService",
        MagicMock(return_value=mock_sub_service),
    )

    mock_notification = MagicMock()
    mock_notification.notify_subscription_created = AsyncMock()
    monkeypatch.setattr(
        "app.services.notification_service.NotificationService",
        MagicMock(return_value=mock_notification),
    )

    callback = AsyncMock()
    callback.message = AsyncMock()
    state = AsyncMock()
    state.get_data = AsyncMock(
        return_value={
            "client_id": 1,
            "subscription_name": "Sub",
            "total_gb": 10,
            "expiry_days": 30,
            "server_ids": {1, 2},
            "selected_inbounds": {11, 12, 21, 22},
        }
    )

    await subs.create_subscription(callback, state)

    # Каждый сервер — отдельный батч-вызов со своим набором id (всего два вызова).
    assert mock_sub_service.add_xui_inbounds_to_subscription.await_count == 2
    actual_calls = {
        (call.args[0], tuple(call.args[1]))
        for call in mock_sub_service.add_xui_inbounds_to_subscription.await_args_list
    }
    assert actual_calls == {(7, (11, 12)), (7, (21, 22))}
    # Не-XUI inbound'ов нет — одиночные вызовы не выполняются.
    mock_sub_service.add_inbound_to_subscription.assert_not_awaited()
