"""Клавиатуры расхождений: корректность callback_data и лимит 64 байта."""

from app.bot.keyboards.inline import (
    get_divergence_digest_keyboard,
    get_divergence_item_keyboard,
)


def _all_callbacks(markup):
    return [btn.callback_data for row in markup.inline_keyboard for btn in row]


def test_digest_keyboard_buttons():
    markup = get_divergence_digest_keyboard("abcd1234", open_count=3)
    cbs = _all_callbacks(markup)
    assert "div:wiz:abcd1234:0" in cbs
    assert "div:gall:apply:abcd1234" in cbs
    assert "div:gall:save:abcd1234" in cbs
    assert "div:gall:ignore:abcd1234" in cbs
    assert all(len(c.encode()) <= 64 for c in cbs)


def test_digest_keyboard_empty_when_no_open():
    markup = get_divergence_digest_keyboard("abcd1234", open_count=0)
    assert _all_callbacks(markup) == []


def test_item_keyboard_actions_and_nav():
    markup = get_divergence_item_keyboard(pid=42, batch_id="abcd1234", idx=1, total=3)
    cbs = _all_callbacks(markup)
    assert "div:item:apply:42:abcd1234:1" in cbs
    assert "div:item:save:42:abcd1234:1" in cbs
    assert "div:item:ignore:42:abcd1234:1" in cbs
    # есть и назад, и вперёд (idx=1 из 3)
    assert "div:wiz:abcd1234:0" in cbs
    assert "div:wiz:abcd1234:2" in cbs
    assert all(len(c.encode()) <= 64 for c in cbs)


def test_item_keyboard_first_has_no_prev():
    markup = get_divergence_item_keyboard(pid=1, batch_id="b", idx=0, total=2)
    cbs = _all_callbacks(markup)
    assert "div:wiz:b:1" in cbs  # вперёд есть
    assert not any(c == "div:wiz:b:-1" for c in cbs)  # назад нет
