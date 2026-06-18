"""Регресс: при ошибке создания подписки админ должен увидеть текст ошибки.

Раньше в except-ветке повторно вызывался ``callback.answer()`` на уже отвеченном
и протухшем callback ('query is too old and response timeout expired'). Исключение
рвало обработчик до ``edit_text``, и админ оставался с сообщением
«⏳ Создание подписки, подождите…», не узнав о провале.
"""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.xui_client.exceptions import XUIError


@pytest.mark.asyncio
async def test_create_subscription_error_shows_message_and_answers_once(monkeypatch):
    import app.bot.handlers.admin.subscriptions as subs

    mock_session = AsyncMock()

    @asynccontextmanager
    async def fake_factory():
        yield mock_session

    monkeypatch.setattr(subs, "async_session_factory", fake_factory)

    # Сервисы, не участвующие в error-пути, заменяем заглушками
    mock_xui = MagicMock()
    mock_xui.close_all_clients = AsyncMock()
    monkeypatch.setattr(subs, "XUIService", MagicMock(return_value=mock_xui))
    monkeypatch.setattr(subs, "ClientService", MagicMock())

    # create_subscription падает с XUIError (как при невалидном email на панели)
    mock_sub_service = MagicMock()
    mock_sub_service.create_subscription = AsyncMock(
        side_effect=XUIError("Failed to create client in VPN panel: bad email")
    )
    mock_sub_service.close_all_clients = AsyncMock()
    monkeypatch.setattr(
        "app.services.new_subscription_service.NewSubscriptionService",
        MagicMock(return_value=mock_sub_service),
    )

    callback = AsyncMock()
    callback.message = AsyncMock()
    state = AsyncMock()
    state.get_data = AsyncMock(
        return_value={
            "client_id": 1,
            "subscription_name": "Sub",
            "total_gb": 10,
            "expiry_days": 30,
        }
    )

    await subs.create_subscription(callback, state)

    # callback отвечён ровно один раз (в начале), без повторного answer в except
    assert callback.answer.await_count == 1
    # админ увидел текст ошибки через edit_text
    error_edits = [
        c for c in callback.message.edit_text.await_args_list if "Ошибка" in str(c)
    ]
    assert error_edits, "edit_text должен показать текст ошибки"
