"""ManualClientService.list_unmanaged — детект неуправляемых клиентов панели."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.database.models import (
    Client,
    Server,
    Subscription,
    XUIInbound,
    XUIInboundConnection,
)
from app.services.manual_client_service import ManualClientService


def _patched_xui(snapshot):
    fake_client = MagicMock()
    fake_client.get_clients = AsyncMock(return_value=snapshot)
    fake_xui = MagicMock()
    fake_xui._get_client = AsyncMock(return_value=fake_client)
    return patch("app.services.xui_service.XUIService", return_value=fake_xui)


async def _setup(session):
    server = Server(name="S", ip_address="1.2.3.4", is_active=True)
    session.add(server)
    await session.flush()
    ib = XUIInbound(server_id=server.id, remark="r", protocol="vless", is_active=True, xui_id=5)
    client = Client(name="N", email="n@x", telegram_id=1, is_admin=False, is_active=True)
    session.add_all([ib, client])
    await session.flush()
    sub = Subscription(
        client_id=client.id, name="s", subscription_token="bottok", total_gb=1,
        expiry_date=datetime.now(UTC) + timedelta(days=10), is_active=True,
    )
    session.add(sub)
    await session.flush()
    session.add(XUIInboundConnection(
        subscription_id=sub.id, inbound_id=ib.id, is_enabled=True, total_gb=1,
        sync_status="synced", email="bot@x", uuid="bot-uuid",
    ))
    await session.flush()
    return server, ib


@pytest.mark.asyncio
async def test_list_unmanaged_excludes_bot_includes_manual(test_session):
    server, ib = await _setup(test_session)
    snapshot = [
        {"email": "bot@x", "id": "bot-uuid", "subId": "bottok", "inboundIds": [5]},  # наш
        {"email": "ira@x", "id": "ira-uuid", "subId": "irasub",
         "inboundIds": [5], "expiryTime": 0, "totalGB": 0, "enable": True},          # ручной
    ]
    svc = ManualClientService(test_session)
    with _patched_xui(snapshot):
        items = await svc.list_unmanaged(server)
    assert len(items) == 1
    it = items[0]
    assert it.email == "ira@x" and it.uuid == "ira-uuid" and it.sub_id == "irasub"
    assert it.inbound_db_ids == [ib.id] and it.importable is True


@pytest.mark.asyncio
async def test_list_unmanaged_unimportable_when_inbound_unknown(test_session):
    server, ib = await _setup(test_session)
    snapshot = [
        {"email": "x@x", "id": "x-uuid", "subId": "s", "inboundIds": [999]},  # inbound вне БД
    ]
    svc = ManualClientService(test_session)
    with _patched_xui(snapshot):
        items = await svc.list_unmanaged(server)
    assert len(items) == 1
    assert items[0].importable is False and items[0].inbound_db_ids == []
