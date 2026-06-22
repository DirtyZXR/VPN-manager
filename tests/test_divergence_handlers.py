"""Хендлеры решений по расхождениям: разбор callback_data и резолюция."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.bot.handlers.admin import divergences as h
from app.database.models import (
    Client,
    PendingDivergence,
    Server,
    Subscription,
    XUIInbound,
    XUIInboundConnection,
)
from app.services.divergence_service import (
    KIND_EXTRA,
    KIND_MISSING,
    STATUS_APPLIED,
    STATUS_IGNORED,
)


class _FakeFactory:
    """Подменяет async_session_factory: всегда отдаёт тестовую сессию."""

    def __init__(self, session):
        self._s = session

    def __call__(self):
        return self

    async def __aenter__(self):
        # commit хендлера не должен персистить в общую сессионную БД — заменяем на
        # flush: данные видны в этой же сессии и откатываются на teardown фикстуры.
        self._s.commit = self._s.flush
        return self._s

    async def __aexit__(self, *exc):
        return False


def _callback(data):
    return SimpleNamespace(
        data=data,
        from_user=SimpleNamespace(id=1),
        message=SimpleNamespace(edit_text=AsyncMock()),
        answer=AsyncMock(),
    )


async def _server(session):
    s = Server(name="S", ip_address="1.2.3.4", is_active=True)
    session.add(s)
    await session.flush()
    return s


def test_item_text_missing_and_extra():
    pd_m = PendingDivergence(server_id=1, kind=KIND_MISSING, email="a@x", batch_id="b", details_json={})
    pd_e = PendingDivergence(server_id=1, kind=KIND_EXTRA, email="b@x", batch_id="b", details_json={})
    assert "пропал с панели" in h._item_text(pd_m, 0, 2)
    assert "лишнее на панели" in h._item_text(pd_e, 1, 2)


@pytest.mark.asyncio
async def test_group_ignore_resolves(test_session):
    server = await _server(test_session)
    test_session.add_all([
        PendingDivergence(server_id=server.id, kind=KIND_MISSING, email="a@x", batch_id="bt", details_json={}),
        PendingDivergence(server_id=server.id, kind=KIND_EXTRA, email="b@x", batch_id="bt", details_json={}),
    ])
    await test_session.flush()

    with (
        patch.object(h, "async_session_factory", _FakeFactory(test_session)),
        patch(
            "app.services.notification_service.NotificationService.refresh_divergence_digest",
            new=AsyncMock(),
        ),
    ):
        await h.divergence_group(_callback("div:gall:ignore:bt"))

    rows = (await test_session.execute(select(PendingDivergence))).scalars().all()
    assert all(r.status == STATUS_IGNORED for r in rows)


@pytest.mark.asyncio
async def test_item_apply_missing_deletes_db_row(test_session):
    server = await _server(test_session)
    inbound = XUIInbound(server_id=server.id, remark="r", protocol="vless", is_active=True, xui_id=5)
    client = Client(name="N", email="n@x", telegram_id=1, is_admin=False, is_active=True)
    test_session.add_all([inbound, client])
    await test_session.flush()
    sub = Subscription(
        client_id=client.id, name="s", subscription_token="t", total_gb=1,
        expiry_date=datetime.now(UTC) + timedelta(days=10), is_active=True,
    )
    test_session.add(sub)
    await test_session.flush()
    conn = XUIInboundConnection(
        subscription_id=sub.id, inbound_id=inbound.id, is_enabled=True,
        total_gb=1, sync_status="error", email="panelmail", uuid="u",
    )
    test_session.add(conn)
    await test_session.flush()
    pd = PendingDivergence(
        server_id=server.id, kind=KIND_MISSING, email="panelmail",
        subscription_id=sub.id, batch_id="bt", details_json={"inbound_db_ids": [inbound.id]},
    )
    test_session.add(pd)
    await test_session.flush()

    with (
        patch.object(h, "async_session_factory", _FakeFactory(test_session)),
        patch(
            "app.services.notification_service.NotificationService.refresh_divergence_digest",
            new=AsyncMock(),
        ),
    ):
        await h.divergence_item(_callback(f"div:item:apply:{pd.id}:bt:0"))

    assert (await test_session.execute(select(XUIInboundConnection))).first() is None
    assert pd.status == STATUS_APPLIED


@pytest.mark.asyncio
async def test_wizard_shows_card(test_session):
    server = await _server(test_session)
    test_session.add(
        PendingDivergence(server_id=server.id, kind=KIND_MISSING, email="a@x", batch_id="bt", details_json={})
    )
    await test_session.flush()
    cb = _callback("div:wiz:bt:0")

    with patch.object(h, "async_session_factory", _FakeFactory(test_session)):
        await h.divergence_wizard(cb)

    cb.message.edit_text.assert_awaited_once()
    cb.answer.assert_awaited()
