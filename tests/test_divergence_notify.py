"""Дайджест расхождений: рассылка, сохранение message_refs, обновление."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from app.database.models import PendingDivergence, Server
from app.services.divergence_service import (
    KIND_EXTRA,
    KIND_MISSING,
    STATUS_APPLIED,
)
from app.services.notification_service import NotificationService


def _settings_with_admins(*ids):
    return SimpleNamespace(admin_ids=set(ids), bot_token="t")


async def _server(session):
    s = Server(name="Srv", ip_address="1.2.3.4", is_active=True)
    session.add(s)
    await session.flush()
    return s


def _bot_with_send(message_id=555):
    bot = MagicMock()
    sent = MagicMock()
    sent.message_id = message_id
    bot.send_message = AsyncMock(return_value=sent)
    bot.edit_message_text = AsyncMock()
    return bot


@pytest.mark.asyncio
async def test_notify_divergences_sends_and_stores_refs(test_session):
    server = await _server(test_session)
    pendings = [
        PendingDivergence(
            server_id=server.id, kind=KIND_MISSING, email="a@x",
            subscription_id=None, batch_id="bt", details_json={}
        ),
        PendingDivergence(
            server_id=server.id, kind=KIND_EXTRA, email="b@x",
            subscription_id=None, batch_id="bt", details_json={}
        ),
    ]
    test_session.add_all(pendings)
    await test_session.flush()

    bot = _bot_with_send(message_id=777)
    with patch(
        "app.services.notification_service.get_settings",
        return_value=_settings_with_admins(1, 2),
    ):
        svc = NotificationService(test_session)
        with patch.object(svc, "_get_bot", AsyncMock(return_value=bot)):
            await svc.notify_admins_divergences(
                server_name="Srv", batch_id="bt", pendings=pendings, is_mass=False
            )

    assert bot.send_message.await_count == 2  # два админа
    rows = (await test_session.execute(select(PendingDivergence))).scalars().all()
    for pd in rows:
        assert pd.notify_message_refs  # refs сохранены
        assert [1, 777] in pd.notify_message_refs


@pytest.mark.asyncio
async def test_refresh_digest_edits_messages(test_session):
    server = await _server(test_session)
    pd = PendingDivergence(
        server_id=server.id, kind=KIND_EXTRA, email="b@x",
        subscription_id=None, batch_id="bt2", details_json={},
        notify_message_refs=[[1, 777]], status=STATUS_APPLIED,
    )
    test_session.add(pd)
    await test_session.flush()

    bot = _bot_with_send()
    with patch(
        "app.services.notification_service.get_settings",
        return_value=_settings_with_admins(1),
    ):
        svc = NotificationService(test_session)
        with patch.object(svc, "_get_bot", AsyncMock(return_value=bot)):
            await svc.refresh_divergence_digest("bt2", test_session)

    bot.edit_message_text.assert_awaited_once()
    kwargs = bot.edit_message_text.await_args.kwargs
    assert kwargs["chat_id"] == 1 and kwargs["message_id"] == 777
    # все разрешены → клавиатуры нет
    assert kwargs["reply_markup"] is None


@pytest.mark.asyncio
async def test_report_notify_sends_plain(test_session):
    await _server(test_session)
    findings = [
        SimpleNamespace(kind=KIND_MISSING, email="a@x"),
        SimpleNamespace(kind=KIND_EXTRA, email="b@x"),
    ]
    bot = _bot_with_send()
    with patch(
        "app.services.notification_service.get_settings",
        return_value=_settings_with_admins(1),
    ):
        svc = NotificationService(test_session)
        with patch.object(svc, "_get_bot", AsyncMock(return_value=bot)):
            await svc.notify_admins_divergences_report(server_name="Srv", findings=findings)

    bot.send_message.assert_awaited_once()
    # отчёт без клавиатуры
    assert "reply_markup" not in bot.send_message.await_args.kwargs
