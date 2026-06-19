from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.vpn_providers.xui_provider import XUIProvider


def _inbound(xui_id, internal_id):
    return SimpleNamespace(id=internal_id, xui_id=xui_id, type="xui_inbound")


def _subscription():
    return SimpleNamespace(
        name="Sub",
        client=SimpleNamespace(name="Alice", telegram_id=111),
        total_gb=10,
        subscription_token="tok_multi",
        expiry_date=datetime.now(UTC) + timedelta(days=30),
    )


def _provider_with_client(get_traffic_side_effect):
    provider = XUIProvider(MagicMock())
    mock_client = AsyncMock()
    mock_client.get_client_traffic = AsyncMock(side_effect=get_traffic_side_effect)
    mock_client.add_client = AsyncMock(return_value=True)
    provider._client = mock_client
    return provider, mock_client


@pytest.mark.asyncio
async def test_add_client_to_inbounds_single_call_all_ids():
    """Один add на панель со ВСЕМИ xui_id и общим subId."""
    inbounds = [_inbound(3, 1), _inbound(5, 2), _inbound(7, 3)]
    sub = _subscription()

    async def probe(email):
        if probe.calls.get(email, 0) == 0:
            probe.calls[email] = 1
            return None
        return {"uuid": "panel-uuid", "email": email}
    probe.calls = {}

    provider, mock_client = _provider_with_client(probe)

    result = await provider.add_client_to_inbounds(inbounds, sub)

    mock_client.add_client.assert_called_once()
    req, inbound_ids = mock_client.add_client.call_args[0]
    assert inbound_ids == [3, 5, 7]
    assert req.subId == "tok_multi"
    assert result["uuid"] == "panel-uuid"
    assert result["email"]


@pytest.mark.asyncio
async def test_add_client_wrapper_maps_to_single_inbound_id():
    """add_client(inbound) делегирует в add_client_to_inbounds с одним xui_id."""
    sub = _subscription()

    async def probe(email):
        if probe.calls.get(email, 0) == 0:
            probe.calls[email] = 1
            return None
        return {"uuid": "panel-uuid", "email": email}
    probe.calls = {}

    provider, mock_client = _provider_with_client(probe)

    await provider.add_client(_inbound(9, 42), sub)

    mock_client.add_client.assert_called_once()
    _req, inbound_ids = mock_client.add_client.call_args[0]
    assert inbound_ids == [9]


@pytest.mark.asyncio
async def test_add_xui_inbounds_creates_shared_connections(test_session, mock_settings):
    from unittest.mock import patch

    from sqlalchemy import select as sa_select

    from app.database.models import (
        Client,
        Server,
        Subscription,
        XUIInbound,
        XUIInboundConnection,
    )
    from app.services.new_subscription_service import NewSubscriptionService

    # БД для тестов общая (session-scoped in-memory), поэтому PK не задаём
    # вручную, а используем автоинкремент; имя/почта/токен — уникальные, чтобы
    # не конфликтовать со строками из других тестов.
    server = Server(name="S-multi", ip_address="1.2.3.4", is_active=True)
    test_session.add(server)
    await test_session.flush()
    ib1 = XUIInbound(
        server_id=server.id, xui_id=3, remark="r1", protocol="vless",
        port=443, settings_json="{}", client_count=0, is_active=True,
    )
    ib2 = XUIInbound(
        server_id=server.id, xui_id=5, remark="r2", protocol="vless",
        port=444, settings_json="{}", client_count=0, is_active=True,
    )
    test_session.add_all([ib1, ib2])
    client = Client(name="Alice-multi", email="alice-multi@a.com", telegram_id=900111, is_active=True)
    test_session.add(client)
    await test_session.flush()
    sub = Subscription(
        client_id=client.id, name="Sub", subscription_token="tok_multi",
        total_gb=10, expiry_date=datetime.now(UTC) + timedelta(days=30), is_active=True,
    )
    test_session.add(sub)
    await test_session.flush()

    inbound_ids = [ib1.id, ib2.id]

    svc = NewSubscriptionService(test_session)
    mock_provider = AsyncMock()
    mock_provider.add_client_to_inbounds = AsyncMock(
        return_value={"uuid": "panel-uuid", "email": "Sub-Alice", "xui_client_id": "panel-uuid"}
    )

    with patch.object(svc, "_get_provider", AsyncMock(return_value=mock_provider)):
        conns = await svc.add_xui_inbounds_to_subscription(sub.id, inbound_ids)

    # один вызов провайдера на всю пачку, оба inbound'а переданы вместе
    mock_provider.add_client_to_inbounds.assert_awaited_once()
    passed_inbounds = mock_provider.add_client_to_inbounds.call_args[0][0]
    assert {ib.id for ib in passed_inbounds} == set(inbound_ids)

    # созданы 2 строки с общими uuid/email
    assert len(conns) == 2
    assert {c.inbound_id for c in conns} == set(inbound_ids)
    assert all(c.uuid == "panel-uuid" and c.email == "Sub-Alice" for c in conns)

    # реально сохранены в БД
    rows = (
        await test_session.execute(
            sa_select(XUIInboundConnection).where(XUIInboundConnection.subscription_id == sub.id)
        )
    ).scalars().all()
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_add_xui_inbounds_compensates_on_db_failure(monkeypatch):
    """При ошибке сохранения в БД создаётся откат: клиент снимается с панели один
    раз (общий email), наружу летит XUIError."""
    from unittest.mock import patch

    from app.services.new_subscription_service import NewSubscriptionService

    sub = SimpleNamespace(
        id=1, name="Sub",
        client=SimpleNamespace(name="Alice", telegram_id=111),
        total_gb=10, subscription_token="tok_multi",
        expiry_date=datetime.now(UTC) + timedelta(days=30),
    )
    ib1 = SimpleNamespace(id=10, xui_id=3, server_id=1, server=SimpleNamespace(id=1), client_count=0)
    ib2 = SimpleNamespace(id=11, xui_id=5, server_id=1, server=SimpleNamespace(id=1), client_count=0)

    # execute(): 1) запрос существующих связей → пусто; 2) загрузка inbound'ов → ib1, ib2;
    # 3) поиск клиента подписки на панели → None (создаём нового клиента).
    empty = MagicMock()
    empty.scalars.return_value.all.return_value = []
    loaded = MagicMock()
    loaded.scalars.return_value.all.return_value = [ib1, ib2]
    no_existing = MagicMock()
    no_existing.scalar_one_or_none.return_value = None

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=[empty, loaded, no_existing])
    nested = AsyncMock()
    nested.__aenter__ = AsyncMock(return_value=nested)
    nested.__aexit__ = AsyncMock(return_value=False)
    mock_session.begin_nested = MagicMock(return_value=nested)
    mock_session.add = MagicMock()
    # Падение при сохранении в БД → срабатывает ветка saga-компенсации.
    mock_session.flush = AsyncMock(side_effect=RuntimeError("boom"))

    svc = NewSubscriptionService(mock_session)
    monkeypatch.setattr(svc, "get_subscription", AsyncMock(return_value=sub))

    mock_provider = AsyncMock()
    mock_provider.add_client_to_inbounds = AsyncMock(
        return_value={"uuid": "panel-uuid", "email": "Sub-Alice", "xui_client_id": "panel-uuid"}
    )
    mock_provider.remove_client = AsyncMock(return_value=True)

    from app.xui_client.exceptions import XUIError

    with (
        patch.object(svc, "_get_provider", AsyncMock(return_value=mock_provider)),
        pytest.raises(XUIError),
    ):
        await svc.add_xui_inbounds_to_subscription(1, [10, 11])

    # компенсация ровно один раз
    assert mock_provider.remove_client.await_count == 1


@pytest.mark.asyncio
async def test_delete_subscription_removes_shared_client_once():
    from unittest.mock import patch

    from app.services.new_subscription_service import NewSubscriptionService

    def _conn(inbound_id):
        c = MagicMock()
        c.id = inbound_id
        c.email = "Sub-Alice"  # общий email у всех соединений подписки
        c.inbound_id = inbound_id
        c.inbound = MagicMock()
        c.inbound.server = MagicMock()
        # все соединения — на ОДНОЙ панели, ключ дедупа (server_id, email) совпадает
        c.inbound.server_id = 1
        return c

    sub = MagicMock()
    sub.inbound_connections = [_conn(10), _conn(11), _conn(12)]

    mock_session = AsyncMock()
    mock_session.delete = AsyncMock()
    mock_session.flush = AsyncMock()

    svc = NewSubscriptionService(mock_session)
    provider = AsyncMock()
    provider.remove_client = AsyncMock(return_value=True)

    with patch.object(svc, "_get_provider", AsyncMock(return_value=provider)):
        await svc.delete_subscription(sub)

    # общий панельный клиент снимается ровно один раз
    assert provider.remove_client.await_count == 1


@pytest.mark.asyncio
async def test_delete_subscription_removes_per_panel_when_email_collides():
    """Один email на ДВУХ панелях (разный server_id) — клиент снимается на каждой.

    Email уникален лишь в рамках панели, поэтому при совпадении email на разных
    серверах дедуп не должен пропускать снятие на второй панели (иначе там zombie).
    """
    from unittest.mock import patch

    from app.services.new_subscription_service import NewSubscriptionService

    def _conn(conn_id, server_id):
        c = MagicMock()
        c.id = conn_id
        c.email = "Sub-Alice"  # одинаковый email на обеих панелях
        c.inbound_id = conn_id
        c.inbound = MagicMock()
        c.inbound.server = MagicMock()  # своя панель у каждого соединения
        c.inbound.server_id = server_id
        return c

    sub = MagicMock()
    sub.inbound_connections = [_conn(10, 1), _conn(11, 2)]

    mock_session = AsyncMock()
    mock_session.delete = AsyncMock()
    mock_session.flush = AsyncMock()

    svc = NewSubscriptionService(mock_session)
    provider = AsyncMock()
    provider.remove_client = AsyncMock(return_value=True)

    with patch.object(svc, "_get_provider", AsyncMock(return_value=provider)):
        await svc.delete_subscription(sub)

    # на каждой панели свой клиент — должно быть два снятия
    assert provider.remove_client.await_count == 2


@pytest.mark.asyncio
async def test_delete_client_all_connections_dedups_shared_client_per_panel():
    """Два соединения с общим email на ОДНОЙ панели → один remove_client,
    но обе DB-строки удаляются (дедуп не пропускает удаление строк)."""
    from unittest.mock import patch

    from app.services.new_subscription_service import NewSubscriptionService

    def _conn(conn_id):
        c = MagicMock()
        c.id = conn_id
        c.email = "Sub-Alice"  # общий email
        c.inbound_id = conn_id
        c.inbound = MagicMock()
        c.inbound.server = MagicMock()
        c.inbound.server_id = 1  # одна и та же панель
        return c

    conn1, conn2 = _conn(10), _conn(11)
    mock_sub = MagicMock()
    mock_sub.inbound_connections = [conn1, conn2]

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_sub]

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.delete = AsyncMock()
    mock_session.flush = AsyncMock()

    svc = NewSubscriptionService(mock_session)
    provider = AsyncMock()
    provider.remove_client = AsyncMock(return_value=True)

    with patch.object(svc, "_get_provider", AsyncMock(return_value=provider)):
        await svc.delete_client_all_connections(client_id=1)

    # общий клиент снят один раз, но обе строки удалены из БД
    assert provider.remove_client.await_count == 1
    assert mock_session.delete.await_count == 2
    mock_session.delete.assert_any_await(conn1)
    mock_session.delete.assert_any_await(conn2)


@pytest.mark.asyncio
async def test_add_xui_inbounds_attaches_to_existing_client(test_session, mock_settings):
    """У подписки уже есть клиент на панели — новый inbound привязывается к нему
    через attach_inbounds (без add_client_to_inbounds, subId не дублируется)."""
    from unittest.mock import patch

    from sqlalchemy import select as sa_select

    from app.database.models import (
        Client,
        Server,
        Subscription,
        XUIInbound,
        XUIInboundConnection,
    )
    from app.services.new_subscription_service import NewSubscriptionService

    server = Server(name="S-attach", ip_address="1.2.3.5", is_active=True)
    test_session.add(server)
    await test_session.flush()
    ib_a = XUIInbound(
        server_id=server.id, xui_id=101, remark="rA", protocol="vless",
        port=443, settings_json="{}", client_count=1, is_active=True,
    )
    ib_b = XUIInbound(
        server_id=server.id, xui_id=102, remark="rB", protocol="vless",
        port=444, settings_json="{}", client_count=0, is_active=True,
    )
    test_session.add_all([ib_a, ib_b])
    client = Client(name="Alice-attach", email="alice-attach@a.com", telegram_id=900222, is_active=True)
    test_session.add(client)
    await test_session.flush()
    sub = Subscription(
        client_id=client.id, name="Sub", subscription_token="tok_attach",
        total_gb=10, expiry_date=datetime.now(UTC) + timedelta(days=30), is_active=True,
    )
    test_session.add(sub)
    await test_session.flush()

    # Существующая связь на inbound A: email E, uuid U.
    conn_a = XUIInboundConnection(
        subscription_id=sub.id, inbound_id=ib_a.id, is_enabled=True,
        total_gb=10, expiry_date=sub.expiry_date, sync_status="synced",
        uuid="U", email="E", xui_client_id="U",
        provider_payload={"uuid": "U", "email": "E", "xui_client_id": "U"},
    )
    test_session.add(conn_a)
    await test_session.flush()

    svc = NewSubscriptionService(test_session)
    mock_provider = AsyncMock()
    mock_provider.attach_inbounds = AsyncMock(return_value=True)
    mock_provider.add_client_to_inbounds = AsyncMock()

    with patch.object(svc, "_get_provider", AsyncMock(return_value=mock_provider)):
        conns = await svc.add_xui_inbounds_to_subscription(sub.id, [ib_b.id])

    mock_provider.attach_inbounds.assert_awaited_once_with("E", [ib_b.xui_id])
    mock_provider.add_client_to_inbounds.assert_not_called()

    assert len(conns) == 1
    assert conns[0].inbound_id == ib_b.id
    assert conns[0].uuid == "U"
    assert conns[0].email == "E"

    rows = (
        await test_session.execute(
            sa_select(XUIInboundConnection).where(
                XUIInboundConnection.subscription_id == sub.id,
                XUIInboundConnection.inbound_id == ib_b.id,
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].uuid == "U" and rows[0].email == "E"


@pytest.mark.asyncio
async def test_add_xui_inbounds_creates_client_when_none_exists(test_session, mock_settings):
    """Нет клиента подписки на панели — создаётся новый через add_client_to_inbounds
    (attach_inbounds не вызывается)."""
    from unittest.mock import patch

    from app.database.models import (
        Client,
        Server,
        Subscription,
        XUIInbound,
    )
    from app.services.new_subscription_service import NewSubscriptionService

    server = Server(name="S-fresh", ip_address="1.2.3.6", is_active=True)
    test_session.add(server)
    await test_session.flush()
    ib_a = XUIInbound(
        server_id=server.id, xui_id=201, remark="rFA", protocol="vless",
        port=443, settings_json="{}", client_count=0, is_active=True,
    )
    test_session.add(ib_a)
    client = Client(name="Alice-fresh", email="alice-fresh@a.com", telegram_id=900333, is_active=True)
    test_session.add(client)
    await test_session.flush()
    sub = Subscription(
        client_id=client.id, name="Sub", subscription_token="tok_fresh",
        total_gb=10, expiry_date=datetime.now(UTC) + timedelta(days=30), is_active=True,
    )
    test_session.add(sub)
    await test_session.flush()

    svc = NewSubscriptionService(test_session)
    mock_provider = AsyncMock()
    mock_provider.attach_inbounds = AsyncMock()
    mock_provider.add_client_to_inbounds = AsyncMock(
        return_value={"uuid": "U2", "email": "E2", "xui_client_id": "U2"}
    )

    with patch.object(svc, "_get_provider", AsyncMock(return_value=mock_provider)):
        conns = await svc.add_xui_inbounds_to_subscription(sub.id, [ib_a.id])

    mock_provider.add_client_to_inbounds.assert_awaited_once()
    mock_provider.attach_inbounds.assert_not_called()

    assert len(conns) == 1
    assert conns[0].uuid == "U2"
    assert conns[0].email == "E2"


@pytest.mark.asyncio
async def test_remove_inbound_detaches_when_sibling_remains(test_session, mock_settings):
    """У подписки два inbound'а с общим email — удаление одного отвязывает его
    (detach_inbounds), клиент остаётся; remove_client не вызывается."""
    from unittest.mock import patch

    from sqlalchemy import select as sa_select

    from app.database.models import (
        Client,
        Server,
        Subscription,
        XUIInbound,
        XUIInboundConnection,
    )
    from app.services.new_subscription_service import NewSubscriptionService

    server = Server(name="S-detach", ip_address="1.2.3.7", is_active=True)
    test_session.add(server)
    await test_session.flush()
    ib_a = XUIInbound(
        server_id=server.id, xui_id=301, remark="rDA", protocol="vless",
        port=443, settings_json="{}", client_count=1, is_active=True,
    )
    ib_b = XUIInbound(
        server_id=server.id, xui_id=302, remark="rDB", protocol="vless",
        port=444, settings_json="{}", client_count=1, is_active=True,
    )
    test_session.add_all([ib_a, ib_b])
    client = Client(name="Alice-detach", email="alice-detach@a.com", telegram_id=900444, is_active=True)
    test_session.add(client)
    await test_session.flush()
    sub = Subscription(
        client_id=client.id, name="Sub", subscription_token="tok_detach",
        total_gb=10, expiry_date=datetime.now(UTC) + timedelta(days=30), is_active=True,
    )
    test_session.add(sub)
    await test_session.flush()

    for ib in (ib_a, ib_b):
        test_session.add(
            XUIInboundConnection(
                subscription_id=sub.id, inbound_id=ib.id, is_enabled=True,
                total_gb=10, expiry_date=sub.expiry_date, sync_status="synced",
                uuid="Ud", email="E", xui_client_id="Ud",
            )
        )
    await test_session.flush()

    svc = NewSubscriptionService(test_session)
    mock_provider = AsyncMock()
    mock_provider.detach_inbounds = AsyncMock(return_value=True)
    mock_provider.remove_client = AsyncMock()

    with patch.object(svc, "_get_provider", AsyncMock(return_value=mock_provider)):
        ok = await svc.remove_inbound_from_subscription(sub.id, ib_a.id)

    assert ok is True
    mock_provider.detach_inbounds.assert_awaited_once_with("E", [ib_a.xui_id])
    mock_provider.remove_client.assert_not_called()

    rows = (
        await test_session.execute(
            sa_select(XUIInboundConnection).where(
                XUIInboundConnection.subscription_id == sub.id,
                XUIInboundConnection.inbound_id == ib_a.id,
            )
        )
    ).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_remove_inbound_deletes_client_when_last(test_session, mock_settings):
    """Единственный inbound с email — удаление снимает клиента целиком
    (remove_client), detach_inbounds не вызывается."""
    from unittest.mock import patch

    from app.database.models import (
        Client,
        Server,
        Subscription,
        XUIInbound,
        XUIInboundConnection,
    )
    from app.services.new_subscription_service import NewSubscriptionService

    server = Server(name="S-last", ip_address="1.2.3.8", is_active=True)
    test_session.add(server)
    await test_session.flush()
    ib_a = XUIInbound(
        server_id=server.id, xui_id=401, remark="rLA", protocol="vless",
        port=443, settings_json="{}", client_count=1, is_active=True,
    )
    test_session.add(ib_a)
    client = Client(name="Alice-last", email="alice-last@a.com", telegram_id=900555, is_active=True)
    test_session.add(client)
    await test_session.flush()
    sub = Subscription(
        client_id=client.id, name="Sub", subscription_token="tok_last",
        total_gb=10, expiry_date=datetime.now(UTC) + timedelta(days=30), is_active=True,
    )
    test_session.add(sub)
    await test_session.flush()

    test_session.add(
        XUIInboundConnection(
            subscription_id=sub.id, inbound_id=ib_a.id, is_enabled=True,
            total_gb=10, expiry_date=sub.expiry_date, sync_status="synced",
            uuid="Ul", email="E", xui_client_id="Ul",
        )
    )
    await test_session.flush()

    svc = NewSubscriptionService(test_session)
    mock_provider = AsyncMock()
    mock_provider.detach_inbounds = AsyncMock()
    mock_provider.remove_client = AsyncMock(return_value=True)

    with patch.object(svc, "_get_provider", AsyncMock(return_value=mock_provider)):
        ok = await svc.remove_inbound_from_subscription(sub.id, ib_a.id)

    assert ok is True
    mock_provider.remove_client.assert_awaited_once()
    mock_provider.detach_inbounds.assert_not_called()


@pytest.mark.asyncio
async def test_attach_client_posts_to_attach_endpoint():
    """attach_client POST'ит на .../attach с inboundIds и возвращает True."""
    from app.xui_client.client import XUIClient

    client = XUIClient(base_url="http://x", api_token="t")
    client._request = AsyncMock(return_value={"success": True})

    result = await client.attach_client("e", [4])

    assert result is True
    method, path = client._request.call_args[0]
    assert method == "POST"
    assert "/attach" in path
    assert client._request.call_args.kwargs["json"] == {"inboundIds": [4]}


@pytest.mark.asyncio
async def test_attach_client_raises_on_failure():
    """attach_client поднимает XUIError при success=False."""
    from app.xui_client.client import XUIClient
    from app.xui_client.exceptions import XUIError

    client = XUIClient(base_url="http://x", api_token="t")
    client._request = AsyncMock(return_value={"success": False, "msg": "nope"})

    with pytest.raises(XUIError):
        await client.attach_client("e", [4])


@pytest.mark.asyncio
async def test_detach_client_posts_to_detach_endpoint():
    """detach_client POST'ит на .../detach с inboundIds и возвращает True."""
    from app.xui_client.client import XUIClient

    client = XUIClient(base_url="http://x", api_token="t")
    client._request = AsyncMock(return_value={"success": True})

    result = await client.detach_client("e", [4])

    assert result is True
    method, path = client._request.call_args[0]
    assert method == "POST"
    assert "/detach" in path
    assert client._request.call_args.kwargs["json"] == {"inboundIds": [4]}


@pytest.mark.asyncio
async def test_detach_client_raises_on_failure():
    """detach_client поднимает XUIError при success=False."""
    from app.xui_client.client import XUIClient
    from app.xui_client.exceptions import XUIError

    client = XUIClient(base_url="http://x", api_token="t")
    client._request = AsyncMock(return_value={"success": False, "msg": "nope"})

    with pytest.raises(XUIError):
        await client.detach_client("e", [4])


@pytest.mark.asyncio
async def test_provider_attach_inbounds_delegates_to_client():
    """attach_inbounds делегирует в client.attach_client."""
    provider = XUIProvider(MagicMock())
    mock_client = AsyncMock()
    mock_client.attach_client = AsyncMock(return_value=True)
    provider._client = mock_client

    result = await provider.attach_inbounds("e", [4])

    assert result is True
    mock_client.attach_client.assert_awaited_once_with("e", [4])


@pytest.mark.asyncio
async def test_provider_detach_inbounds_delegates_to_client():
    """detach_inbounds делегирует в client.detach_client."""
    provider = XUIProvider(MagicMock())
    mock_client = AsyncMock()
    mock_client.detach_client = AsyncMock(return_value=True)
    provider._client = mock_client

    result = await provider.detach_inbounds("e", [4])

    assert result is True
    mock_client.detach_client.assert_awaited_once_with("e", [4])
