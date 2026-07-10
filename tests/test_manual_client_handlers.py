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


def _msg(text):
    return SimpleNamespace(text=text, answer=AsyncMock())


class _FakeSessionCtx:
    """Асинхронный контекст-менеджер, отдающий фейковую сессию."""

    async def __aenter__(self):
        return SimpleNamespace(commit=AsyncMock())

    async def __aexit__(self, *a):
        return False


@pytest.mark.asyncio
async def test_new_client_name_lost_state_errors():
    """Правка 1: потеря FSM-контекста не роняет хэндлер (int(None)), а даёт ошибку."""
    fsm = _FSM()  # нет umc_server_id / umc_panel_email
    msg = _msg("Вася")
    await h.unmanaged_new_client_name(msg, fsm)  # не должно бросать
    msg.answer.assert_awaited_once()
    assert "устарел" in msg.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_accept_escapes_html_in_email():
    """Правка 3: спецсимволы в email экранируются в HTML-сообщении."""
    fsm = _FSM({"umc_emails": ["<b>a</b>@x"]})
    cb = _cb("uimp:accept:7:0")
    await h.unmanaged_accept(cb, fsm)
    text = cb.message.edit_text.await_args.args[0]
    assert "&lt;b&gt;" in text
    assert "<b>a</b>@x" not in text


@pytest.mark.asyncio
async def test_pick_client_import_error_handled(monkeypatch):
    """Правка 2: сбой панели при импорте не роняет хэндлер, а показывает ошибку."""
    monkeypatch.setattr(h, "async_session_factory", lambda: _FakeSessionCtx())
    monkeypatch.setattr(h, "_load_xui_server", AsyncMock(return_value=SimpleNamespace(name="S")))
    monkeypatch.setattr(
        h,
        "ManualClientService",
        lambda session: SimpleNamespace(
            import_client=AsyncMock(side_effect=RuntimeError("panel down"))
        ),
    )
    fsm = _FSM({"umc_server_id": 7, "umc_panel_email": "a@x"})
    cb = _cb("uimp:pick:3")
    await h.unmanaged_pick_client(cb, fsm)  # не должно бросать
    cb.answer.assert_awaited()
    assert "Ошибка" in cb.answer.await_args.args[0]
