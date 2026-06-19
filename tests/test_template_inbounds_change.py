"""Регресс: массовое изменение inbound'ов шаблона добавляет inbound'ы через
группировку (XUI одной панели → attach к существующему клиенту), а не поштучно
старым add_inbound_to_subscription — иначе панель отвечает 'subId already in use'.
"""

import pytest

from app.database.models import Client, Subscription
from app.database.models.subscription_template import SubscriptionTemplate
from app.services.new_subscription_service import NewSubscriptionService
from app.services.subscription_template_service import SubscriptionTemplateService


@pytest.mark.asyncio
async def test_template_additions_go_through_grouping(test_session, mock_settings, monkeypatch):
    tmpl = SubscriptionTemplate(name="T", is_active=True)
    test_session.add(tmpl)
    await test_session.flush()
    client = Client(name="C", email="c@x.com", telegram_id=1, is_active=True)
    test_session.add(client)
    await test_session.flush()
    s1 = Subscription(
        client_id=client.id, name="s1", subscription_token="tt1",
        total_gb=1, template_id=tmpl.id, is_active=True,
    )
    s2 = Subscription(
        client_id=client.id, name="s2", subscription_token="tt2",
        total_gb=1, template_id=tmpl.id, is_active=True,
    )
    test_session.add_all([s1, s2])
    await test_session.flush()

    calls = []

    async def fake_add(self, subscription_id, inbound_ids, mtproxy_domain=None):
        calls.append((subscription_id, set(inbound_ids)))
        return []

    # Подменяем групповой метод — проверяем, что шаблон ходит именно через него,
    # а не через поштучный add_inbound_to_subscription.
    monkeypatch.setattr(NewSubscriptionService, "add_inbounds_to_subscription", fake_add)

    svc = SubscriptionTemplateService(test_session)
    await svc._apply_template_inbounds_change(tmpl.id, added_inbound_ids={5})

    # по разу на каждую подписку шаблона, с полным набором добавляемых inbound'ов
    assert sorted(c[0] for c in calls) == sorted([s1.id, s2.id])
    assert all(c[1] == {5} for c in calls)
