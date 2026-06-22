"""Настройки режима обработки расхождений БД ↔ панель."""

import pytest

from app.config import Settings


def _make(**over):
    base = dict(
        bot_token="t",
        encryption_key="SpWH-ifTebQwpAlasE5SvZsgUwi0onGmILmSrm7G1BQ=",
    )
    base.update(over)
    return Settings(**base)


def test_reconcile_defaults():
    s = _make()
    assert s.reconcile_mode == "ask"
    assert s.reconcile_mass_threshold == 5


def test_reconcile_mode_valid():
    assert _make(reconcile_mode="auto").reconcile_mode == "auto"
    assert _make(reconcile_mode="report").reconcile_mode == "report"


def test_reconcile_mode_invalid_rejected():
    with pytest.raises(ValueError):
        _make(reconcile_mode="destroy")
