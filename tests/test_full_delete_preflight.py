"""Pre-flight расхождения перед полным удалением подписки (scope B)."""

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
from app.services.new_subscription_service import NewSubscriptionService


async def _sub_with_xui_conn(session, email="m@x", xui_id=5):
    server = Server(name="S", ip_address="1.2.3.4", is_active=True)
    session.add(server)
    await session.flush()
    inbound = XUIInbound(
        server_id=server.id, remark="r", protocol="vless", is_active=True, xui_id=xui_id
    )
    client = Client(name="N", email="n@x", telegram_id=1, is_admin=False, is_active=True)
    session.add_all([inbound, client])
    await session.flush()
    sub = Subscription(
        client_id=client.id, name="s", subscription_token="t", total_gb=1,
        expiry_date=datetime.now(UTC) + timedelta(days=10), is_active=True,
    )
    session.add(sub)
    await session.flush()
    conn = XUIInboundConnection(
        subscription_id=sub.id, inbound_id=inbound.id, is_enabled=True,
        total_gb=1, sync_status="synced", email=email, uuid="u",
    )
    session.add(conn)
    await session.flush()
    return server, sub


def _patched_xui(snapshot):
    fake_client = MagicMock()
    fake_client.get_clients = AsyncMock(return_value=snapshot)
    fake_xui = MagicMock()
    fake_xui._get_client = AsyncMock(return_value=fake_client)
    return patch("app.services.xui_service.XUIService", return_value=fake_xui)


@pytest.mark.asyncio
async def test_detects_manual_panel_attachment(test_session):
    server, sub = await _sub_with_xui_conn(test_session, email="m@x", xui_id=5)
    snapshot = [{"email": "m@x", "subId": "t", "inboundIds": [5, 7]}]  # 7 — ручной
    svc = NewSubscriptionService(test_session)
    with _patched_xui(snapshot):
        extra = await svc.panel_extra_inbounds(sub.id)
    assert len(extra) == 1
    assert extra[0]["email"] == "m@x"
    assert extra[0]["extra_xui_ids"] == [7]


@pytest.mark.asyncio
async def test_no_divergence_returns_empty(test_session):
    server, sub = await _sub_with_xui_conn(test_session, email="m@x", xui_id=5)
    snapshot = [{"email": "m@x", "subId": "t", "inboundIds": [5]}]  # ровно как в БД
    svc = NewSubscriptionService(test_session)
    with _patched_xui(snapshot):
        extra = await svc.panel_extra_inbounds(sub.id)
    assert extra == []
