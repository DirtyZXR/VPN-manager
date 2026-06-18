"""_continue_to_installer после first-setup должен маршрутизировать в установку
нужного протокола (awg/xui/mtproxy), а не упираться в else-тупик.

Регресс: ветки 'mtproxy' не было — установка MTProxy на свежем сервере
застревала на «⚠️ Не удалось продолжить установку».
"""

from unittest.mock import AsyncMock

import pytest

from app.bot.handlers.admin.servers.first_setup import _continue_to_installer


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "target, module, func",
    [
        ("awg", "app.bot.handlers.admin.servers.awg", "_awg_ask_port"),
        ("xui", "app.bot.handlers.admin.servers.xui_install", "_xui_ask_domain"),
        ("mtproxy", "app.bot.handlers.admin.servers.mtproxy", "_mtproxy_ask_implementation"),
    ],
)
async def test_continue_to_installer_routes(monkeypatch, target, module, func):
    entry = AsyncMock()
    monkeypatch.setattr(f"{module}.{func}", entry)

    state = AsyncMock()
    state.get_data = AsyncMock(return_value={"_setup_target": target, "server_id": 1})
    message = AsyncMock()

    await _continue_to_installer(message, state)

    entry.assert_awaited_once_with(message, state)
    # не должен сваливаться в else-тупик
    message.edit_text.assert_not_called()
