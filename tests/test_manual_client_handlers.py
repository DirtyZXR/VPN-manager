"""Смоук хендлеров импорта: разбор callback_data и переходы FSM."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.bot.handlers.admin import manual_clients as h
from app.bot.states.admin import ManualImport


class _FSM:
    """Минимальный FSMContext на словаре."""

    def __init__(self, data=None):
        self._data = dict(data or {})
        self.state = None

    async def get_data(self):
        return dict(self._data)

    async def update_data(self, **kw):
        self._data.update(kw)

    async def set_state(self, s):
        self.state = s

    async def clear(self):
        self._data = {}
        self.state = None


def _cb(data):
    return SimpleNamespace(
        data=data,
        from_user=SimpleNamespace(id=1),
        message=SimpleNamespace(edit_text=AsyncMock(), answer=AsyncMock()),
        answer=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_accept_stores_email_and_shows_wizard():
    fsm = _FSM({"umc_emails": ["ira@x"]})
    cb = _cb("uimp:accept:7:0")
    await h.unmanaged_accept(cb, fsm)
    d = await fsm.get_data()
    assert d["umc_panel_email"] == "ira@x"
    assert d["umc_server_id"] == 7
    cb.message.edit_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_new_client_sets_state():
    fsm = _FSM()
    cb = _cb("uimp:new:7:0")
    await h.unmanaged_new_client(cb, fsm)
    assert fsm.state == ManualImport.entering_new_name
    cb.message.edit_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_accept_stale_list_alerts():
    fsm = _FSM({"umc_emails": []})
    cb = _cb("uimp:accept:7:5")
    await h.unmanaged_accept(cb, fsm)
    cb.answer.assert_awaited()  # предупреждение об устаревшем списке
    cb.message.edit_text.assert_not_called()
