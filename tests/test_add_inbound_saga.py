"""Регресс: saga-компенсация в add_inbound_to_subscription строит временный объект
через SimpleNamespace, а не ORM-__new__ (последнее падает в рантайме без
_sa_instance_state). При ошибке записи в БД клиент снимается с панели один раз.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.services.new_subscription_service as nss
from app.services.new_subscription_service import NewSubscriptionService
from app.xui_client.exceptions import XUIError


@pytest.mark.asyncio
async def test_add_inbound_saga_uses_namespace(monkeypatch):
    sub = SimpleNamespace(
        id=1, name="Sub", total_gb=10, expiry_date=None,
        subscription_token="tok", client=SimpleNamespace(name="C", telegram_id=1),
    )
    inbound = SimpleNamespace(
        id=10, type="xui_inbound", xui_id=3, server=SimpleNamespace(id=3), client_count=0
    )

    existing_res = MagicMock()
    existing_res.scalar_one_or_none.return_value = None
    inbound_res = MagicMock()
    inbound_res.scalar_one_or_none.return_value = inbound

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=[existing_res, inbound_res])
    nested = AsyncMock()
    nested.__aenter__ = AsyncMock(return_value=nested)
    nested.__aexit__ = AsyncMock(return_value=False)
    mock_session.begin_nested = MagicMock(return_value=nested)
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock(side_effect=RuntimeError("boom"))  # запись в БД падает

    svc = NewSubscriptionService(mock_session)
    monkeypatch.setattr(svc, "get_subscription", AsyncMock(return_value=sub))

    provider = AsyncMock()
    provider.add_client = AsyncMock(
        return_value={"uuid": "U", "email": "Sub-C", "xui_client_id": "U"}
    )
    provider.remove_client = AsyncMock(return_value=True)

    # Заглушка под ORM-модель, чтобы конструктор в цикле не требовал реальной сессии.
    class _Stub:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    monkeypatch.setattr(nss, "XUIInboundConnection", _Stub)

    with patch.object(svc, "_get_provider", AsyncMock(return_value=provider)), \
            pytest.raises(XUIError):
        await svc.add_inbound_to_subscription(1, 10)

    # Компенсация ровно один раз; temp — SimpleNamespace с доступными полями (не падает).
    assert provider.remove_client.await_count == 1
    tmp = provider.remove_client.call_args[0][1]
    assert tmp.email == "Sub-C"
    assert tmp.uuid == "U"
