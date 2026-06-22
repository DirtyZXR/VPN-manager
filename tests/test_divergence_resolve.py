"""DivergenceService.resolve — apply / adopt / restore."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.database.models import (
    Client,
    PendingDivergence,
    Server,
    Subscription,
    XUIInbound,
    XUIInboundConnection,
)
from app.services.divergence_service import (
    DECISION_APPLY,
    DECISION_SAVE,
    KIND_EXTRA,
    KIND_MISSING,
    STATUS_ADOPTED,
    STATUS_APPLIED,
    DivergenceService,
)


async def _fixture(session):
    server = Server(name="S", ip_address="1.2.3.4", is_active=True)
    session.add(server)
    await session.flush()
    inbound = XUIInbound(
        server_id=server.id, remark="r", protocol="vless", is_active=True, xui_id=5
    )
    session.add(inbound)
    client = Client(name="N", email="n@x", telegram_id=1, is_admin=False, is_active=True)
    session.add(client)
    await session.flush()
    sub = Subscription(
        client_id=client.id,
        name="sub",
        subscription_token="tok1",
        total_gb=10,
        expiry_date=datetime.now(UTC) + timedelta(days=30),
        is_active=True,
    )
    session.add(sub)
    await session.flush()
    return server, inbound, sub


@pytest.mark.asyncio
async def test_adopt_extra_creates_db_row(test_session):
    server, inbound, sub = await _fixture(test_session)
    svc = DivergenceService(test_session)
    pd = PendingDivergence(
        server_id=server.id,
        kind=KIND_EXTRA,
        email="panelmail",
        subscription_id=sub.id,
        batch_id="b1",
        details_json={
            "inbound_db_ids": [inbound.id],
            "uuid": "uu",
            "total_gb": 10,
            "expiry_ms": int(sub.expiry_date.timestamp() * 1000),
            "enable": True,
        },
    )
    test_session.add(pd)
    await test_session.flush()

    await svc.resolve(pd.id, DECISION_SAVE, resolved_by=1)

    conn = (await test_session.execute(select(XUIInboundConnection))).scalar_one()
    assert conn.email == "panelmail"
    assert conn.uuid == "uu"
    assert conn.inbound_id == inbound.id
    assert pd.status == STATUS_ADOPTED


@pytest.mark.asyncio
async def test_apply_missing_deletes_db_row(test_session):
    server, inbound, sub = await _fixture(test_session)
    conn = XUIInboundConnection(
        subscription_id=sub.id,
        inbound_id=inbound.id,
        is_enabled=True,
        total_gb=10,
        sync_status="error",
        email="panelmail",
        uuid="uu",
    )
    test_session.add(conn)
    await test_session.flush()
    svc = DivergenceService(test_session)
    pd = PendingDivergence(
        server_id=server.id,
        kind=KIND_MISSING,
        email="panelmail",
        subscription_id=sub.id,
        batch_id="b1",
        details_json={"inbound_db_ids": [inbound.id]},
    )
    test_session.add(pd)
    await test_session.flush()

    await svc.resolve(pd.id, DECISION_APPLY, resolved_by=1)

    assert (await test_session.execute(select(XUIInboundConnection))).first() is None
    assert pd.status == STATUS_APPLIED


@pytest.mark.asyncio
async def test_apply_extra_detaches_on_panel(test_session):
    server, inbound, sub = await _fixture(test_session)
    svc = DivergenceService(test_session)
    pd = PendingDivergence(
        server_id=server.id,
        kind=KIND_EXTRA,
        email="panelmail",
        subscription_id=sub.id,
        batch_id="b1",
        details_json={"orphan_xui_ids": [5], "has_valid": True},
    )
    test_session.add(pd)
    await test_session.flush()
    xui = AsyncMock()

    await svc.resolve(pd.id, DECISION_APPLY, resolved_by=1, xui_client=xui)

    xui.detach_client.assert_awaited_once_with("panelmail", [5])
    assert pd.status == STATUS_APPLIED


@pytest.mark.asyncio
async def test_resolve_idempotent_on_non_open(test_session):
    server, inbound, sub = await _fixture(test_session)
    svc = DivergenceService(test_session)
    pd = PendingDivergence(
        server_id=server.id,
        kind=KIND_MISSING,
        email="panelmail",
        subscription_id=sub.id,
        batch_id="b1",
        status=STATUS_APPLIED,
        details_json={"inbound_db_ids": []},
    )
    test_session.add(pd)
    await test_session.flush()

    result = await svc.resolve(pd.id, DECISION_APPLY, resolved_by=1)
    assert result.status == STATUS_APPLIED  # не меняется
