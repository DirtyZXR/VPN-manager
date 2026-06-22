"""Регресс: protocol-sync (AWG/MTProxy) не помечает соединение отключённым в БД,
если серверная операция disable_client() провалилась (вернула False).

Иначе истёкший клиент остаётся активным на сервере, а в БД числится отключённым
(подписка кончилась, но VPN продолжает работать).
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database.models import (
    AWGInbound,
    AWGInboundConnection,
    Client,
    Server,
    Subscription,
)
from app.database.models.inbound import Inbound
from app.services.protocol_sync.awg_sync import AWGProtocolSync


async def _setup_expired(
    session, inbound_cls, conn_cls, uid, client_name="C", sub_expired=True, **conn_kwargs
):
    """Создать включённое соединение нужного протокола с истёкшим conn.expiry_date.

    sub_expired=True (по умолчанию) — подписка тоже истёкшая, отключение должно
    срабатывать. sub_expired=False — подписка активна при истёкшем conn.expiry_date
    (проверка того, что срок берётся из подписки — источника истины).
    """
    server = Server(name="S", ip_address="1.2.3.4", is_active=True)
    session.add(server)
    await session.flush()
    inbound = inbound_cls(server_id=server.id, remark="r", protocol="p", is_active=True)
    session.add(inbound)
    client = Client(
        name=client_name, email=f"c{uid}@example.com", telegram_id=uid, is_admin=False, is_active=True
    )
    session.add(client)
    await session.flush()
    sub = Subscription(
        client_id=client.id,
        name="sub",
        subscription_token=f"tok{uid}",
        total_gb=1,
        expiry_date=(
            datetime.now(UTC) - timedelta(days=1)
            if sub_expired
            else datetime.now(UTC) + timedelta(days=30)
        ),
        is_active=True,
    )
    session.add(sub)
    await session.flush()
    conn = conn_cls(
        subscription_id=sub.id,
        inbound_id=inbound.id,
        is_enabled=True,
        expiry_date=datetime.now(UTC) - timedelta(days=1),  # истёк
        **conn_kwargs,
    )
    session.add(conn)
    await session.flush()
    inbound = (
        await session.execute(
            select(inbound_cls)
            .where(inbound_cls.id == inbound.id)
            .options(selectinload(Inbound.server))
        )
    ).scalar_one()
    return inbound, conn


@pytest.mark.asyncio
async def test_awg_sync_keeps_enabled_when_disable_fails(test_session, mock_settings, monkeypatch):
    """AWG: при провале disable_client() (сервер вернул False) соединение
    НЕ должно помечаться отключённым в БД — иначе истёкший клиент остаётся
    активным на сервере, а бот думает, что отключил.

    (mtproxy_sync содержит идентичный паттерн и правится тем же фиксом.)
    """
    inbound, conn = await _setup_expired(
        test_session, AWGInbound, AWGInboundConnection, 990001, public_key="pk"
    )

    provider = AsyncMock()
    provider.disable_client = AsyncMock(return_value=False)  # сервер НЕ отключил
    provider.close = AsyncMock()
    monkeypatch.setattr(
        "app.services.vpn_providers.factory.get_vpn_provider",
        lambda *a, **k: provider,
    )

    synced = await AWGProtocolSync().sync_clients(test_session, inbound)

    # sync_clients модифицирует тот же объект conn в сессии — проверяем напрямую
    assert conn.is_enabled is True, "is_enabled нельзя флипать при провале disable_client"
    assert synced == 0
    provider.disable_client.assert_awaited_once()


@pytest.mark.asyncio
async def test_awg_disable_log_includes_client_name(test_session, mock_settings, monkeypatch):
    """AWG: лог отключения по истечению срока содержит имя клиента.

    Заодно проверяет, что клиент подгружается eager (иначе обращение к
    conn.subscription.client.name в async упало бы MissingGreenlet).
    """
    from loguru import logger

    inbound, conn = await _setup_expired(
        test_session, AWGInbound, AWGInboundConnection, 990003,
        client_name="Зелинская_Лариса", public_key="pk",
    )

    provider = AsyncMock()
    provider.disable_client = AsyncMock(return_value=True)  # сервер отключил успешно
    provider.close = AsyncMock()
    monkeypatch.setattr(
        "app.services.vpn_providers.factory.get_vpn_provider",
        lambda *a, **k: provider,
    )

    messages: list[str] = []
    sink_id = logger.add(lambda m: messages.append(str(m)), level="INFO")
    try:
        await AWGProtocolSync().sync_clients(test_session, inbound)
    finally:
        logger.remove(sink_id)

    assert conn.is_enabled is False
    assert any(
        "отключено (истёк срок)" in m and "Зелинская_Лариса" in m for m in messages
    ), messages


@pytest.mark.asyncio
async def test_awg_sync_not_disabled_when_subscription_active(
    test_session, mock_settings, monkeypatch
):
    """AWG: conn.expiry_date истёк, но ПОДПИСКА активна → НЕ отключать.

    Регресс на дрейф срока (как 206/208 на проде): срок берётся из подписки —
    источника истины, отставший conn.expiry_date не должен ронять активную подписку.
    """
    inbound, conn = await _setup_expired(
        test_session, AWGInbound, AWGInboundConnection, 990010,
        sub_expired=False, public_key="pk",
    )

    provider = AsyncMock()
    provider.disable_client = AsyncMock(return_value=True)
    provider.close = AsyncMock()
    monkeypatch.setattr(
        "app.services.vpn_providers.factory.get_vpn_provider",
        lambda *a, **k: provider,
    )

    synced = await AWGProtocolSync().sync_clients(test_session, inbound)

    assert conn.is_enabled is True, "активную подписку нельзя отключать из-за отставшего conn.expiry"
    assert synced == 0
    provider.disable_client.assert_not_called()
