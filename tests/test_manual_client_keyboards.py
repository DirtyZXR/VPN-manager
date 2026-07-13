"""Клавиатуры экрана неуправляемых клиентов."""

from app.bot.keyboards.inline import (
    get_unmanaged_import_wizard_keyboard,
    get_unmanaged_list_keyboard,
)
from app.services.manual_client_service import UnmanagedClient


def _all(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]


def test_unmanaged_list_keyboard():
    items = [
        UnmanagedClient("ira@x", "u1", "s", [1], 0, 0, True, importable=True),
        UnmanagedClient("foo@x", "u2", "s", [], 0, 0, True, importable=False),
    ]
    markup = get_unmanaged_list_keyboard(server_id=7, items=items, page=0)
    cbs = _all(markup)
    assert "uimp:accept:7:0" in cbs
    assert "uimp:del:7:0" in cbs
    assert "uimp:accept:7:1" not in cbs  # неimportable → нет «Принять»
    assert "uimp:del:7:1" in cbs
    assert all(len(c.encode()) <= 64 for c in cbs)


def test_unmanaged_list_pagination():
    items = [
        UnmanagedClient(f"u{i}@x", f"id{i}", "s", [1], 0, 0, True, importable=True)
        for i in range(7)
    ]
    markup = get_unmanaged_list_keyboard(server_id=3, items=items, page=0, per_page=5)
    cbs = _all(markup)
    assert "uimp:page:3:1" in cbs  # есть кнопка «вперёд»
    assert "uimp:accept:3:0" in cbs and "uimp:accept:3:5" not in cbs  # только первая страница


def test_import_wizard_keyboard():
    markup = get_unmanaged_import_wizard_keyboard(server_id=7, idx=0)
    cbs = _all(markup)
    assert "uimp:new:7:0" in cbs
    assert "uimp:existing:7:0" in cbs
