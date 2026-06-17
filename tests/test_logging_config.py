"""Тесты конфигурации логирования: формат с контекстом, приглушение шума."""

import logging

from app.logging_config import (
    NOISY_LOGGERS,
    _console_format,
    _context_suffix,
    _file_format,
    setup_logging,
)


def _record(extra: dict) -> dict:
    return {"extra": extra}


def test_context_suffix_empty():
    assert _context_suffix(_record({})) == ""


def test_context_suffix_renders_pairs():
    assert _context_suffix(_record({"server": 2, "cycle": "ab12"})) == " [server=2 cycle=ab12]"


def test_context_suffix_escapes_braces():
    assert "{{" in _context_suffix(_record({"x": "a{b}"}))


def test_console_format_includes_message_and_context_and_newline():
    fmt = _console_format(_record({"server": 7}))
    assert "{message}" in fmt
    assert "[server=7]" in fmt
    assert fmt.endswith("\n{exception}")


def test_file_format_has_no_color_tags():
    fmt = _file_format(_record({}))
    assert "<green>" not in fmt and "<level>" not in fmt
    assert "{message}" in fmt and fmt.endswith("\n{exception}")


def test_setup_logging_silences_noisy_libraries():
    setup_logging()
    for name in NOISY_LOGGERS:
        assert logging.getLogger(name).level == logging.WARNING


def test_contextualize_adds_extra_to_records():
    from loguru import logger

    captured = []
    sink_id = logger.add(captured.append, level="DEBUG", format="{message}")
    try:
        with logger.contextualize(cycle="zz99"):
            logger.info("inside")
        logger.info("outside")
    finally:
        logger.remove(sink_id)

    assert captured[0].record["extra"].get("cycle") == "zz99"
    assert "cycle" not in captured[1].record["extra"]
