"""ManualClientService.import_client / create_import_client / delete_from_panel."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from app.database.models import (
    Client,
    Server,
    Subscription,
    XUIInbound,
    XUIInboundConnection,
)
from app.services.manual_client_service import ManualClientService


def _patched_xui(snapshot, client_mock):
    fake_xui = MagicMock()
    fake_xui._get_client = AsyncMock(return_value=client_mock)
    client_mock.get_clients = AsyncMock(return_value=snapshot)
    return patch("app.services.xui_service.XUIService", return_value=fake_xui)


async def _server_inbound_client(session, xui_id=5):
    server = Server(name="S", ip_address="1.2.3.4", is_active=True)
    session.add(server)
    await session.flush()
    ib = XUIInbound(server_id=server.id, remark="r", protocol="vless", is_active=True, xui_id=xui_id)
    client = Client(name="Owner", email="owner@x", telegram_id=1, is_admin=False, is_active=True)
    session.add_all([ib, client])
    await session.flush()
    return server, ib, client


@pytest.mark.asyncio
async def test_import_reuses_panel_subid(test_session):
    server, ib, owner = await _server_inbound_client(test_session)
    snapshot = [{"email": "ira@x", "id": "ira-uuid", "subId": "irasub",
                 "inboundIds": [5], "expiryTime": 0, "totalGB": 0, "enable": True}]
    panel = MagicMock()
    panel.update_client = AsyncMock()
    svc = ManualClientService(test_session)
    with _patched_xui(snapshot, panel):
        sub = await svc.import_client(server, "ira@x", owner.id)

    assert sub is not None
    assert sub.subscription_token == "irasub"
    panel.update_client.assert_not_called()
    conns = (await test_session.execute(
        select(XUIInboundConnection).where(XUIInboundConnection.subscription_id == sub.id)
    )).scalars().all()
    assert len(conns) == 1
    assert conns[0].email == "ira@x" and conns[0].uuid == "ira-uuid" and conns[0].inbound_id == ib.id


@pytest.mark.asyncio
async def test_import_generates_token_when_subid_empty(test_session):
    server, ib, owner = await _server_inbound_client(test_session)
    snapshot = [{"email": "ira@x", "id": "ira-uuid", "subId": "",
                 "inboundIds": [5], "expiryTime": 0, "totalGB": 0, "enable": True}]
    panel = MagicMock()
    panel.update_client = AsyncMock()
    svc = ManualClientService(test_session)
    with _patched_xui(snapshot, panel):
        sub = await svc.import_client(server, "ira@x", owner.id)

    assert sub.subscription_token
    panel.update_client.assert_awaited_once()


@pytest.mark.asyncio
async def test_import_generates_on_token_collision(test_session):
    server, ib, owner = await _server_inbound_client(test_session)
    test_session.add(Subscription(
        client_id=owner.id, name="x", subscription_token="irasub", total_gb=1,
        expiry_date=None, is_active=True,
    ))
    await test_session.flush()
    snapshot = [{"email": "ira@x", "id": "ira-uuid", "subId": "irasub",
                 "inboundIds": [5], "expiryTime": 0, "totalGB": 0, "enable": True}]
    panel = MagicMock()
    panel.update_client = AsyncMock()
    svc = ManualClientService(test_session)
    with _patched_xui(snapshot, panel):
        sub = await svc.import_client(server, "ira@x", owner.id)

    assert sub.subscription_token != "irasub"
    panel.update_client.assert_awaited_once()


@pytest.mark.asyncio
async def test_import_missing_client_returns_none(test_session):
    server, ib, owner = await _server_inbound_client(test_session)
    panel = MagicMock()
    svc = ManualClientService(test_session)
    with _patched_xui([], panel):
        sub = await svc.import_client(server, "gone@x", owner.id)
    assert sub is None


@pytest.mark.asyncio
async def test_create_import_client_unique_email(test_session):
    svc = ManualClientService(test_session)
    c1 = await svc.create_import_client("Ира")
    c2 = await svc.create_import_client("Ира")
    assert c1.id != c2.id
    assert c1.email != c2.email
    assert c1.name == "Ира"


@pytest.mark.asyncio
async def test_delete_from_panel_calls_delete_client(test_session):
    server, ib, owner = await _server_inbound_client(test_session)
    panel = MagicMock()
    panel.delete_client = AsyncMock(return_value=True)
    svc = ManualClientService(test_session)
    with _patched_xui([], panel):
        ok = await svc.delete_from_panel(server, "ira@x")
    assert ok is True
    panel.delete_client.assert_awaited_once_with("ira@x")
