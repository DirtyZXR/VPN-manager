"""Tests for InterceptHandler (stdlib logging → loguru bridge) and loguru-converted modules."""

import logging

import pytest
from loguru import logger


# ---------------------------------------------------------------------------
# InterceptHandler tests
# ---------------------------------------------------------------------------


class InterceptHandler(logging.Handler):
    """Duplicate of app/main.py InterceptHandler — imported here to avoid
    triggering full app startup (Bot, DB, settings) during import."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def test_intercept_handler_routes_to_loguru_sink():
    """Records emitted through stdlib logging reach the loguru sink."""
    received: list[str] = []

    sink_id = logger.add(lambda msg: received.append(msg), level="DEBUG", format="{message}")
    try:
        stdlib_logger = logging.getLogger("test_intercept_basic")
        stdlib_logger.addHandler(InterceptHandler())
        stdlib_logger.setLevel(logging.DEBUG)
        stdlib_logger.propagate = False

        stdlib_logger.info("hello from stdlib")

        assert any("hello from stdlib" in m for m in received), (
            f"Expected message not found in sink output: {received}"
        )
    finally:
        logger.remove(sink_id)


def test_intercept_handler_preserves_log_level():
    """WARNING records are forwarded with WARNING severity."""
    received_levels: list[str] = []

    def sink(msg):
        received_levels.append(msg.record["level"].name)

    sink_id = logger.add(sink, level="DEBUG", format="{message}")
    try:
        std = logging.getLogger("test_intercept_level")
        std.addHandler(InterceptHandler())
        std.setLevel(logging.DEBUG)
        std.propagate = False

        std.warning("a warning message")

        assert "WARNING" in received_levels, f"Level not found: {received_levels}"
    finally:
        logger.remove(sink_id)


def test_intercept_handler_propagates_root_logger():
    """logging.basicConfig with InterceptHandler sends root-logger output to loguru."""
    received: list[str] = []
    sink_id = logger.add(lambda msg: received.append(msg), level="DEBUG", format="{message}")
    try:
        # Install handler on root logger (mimics main.py setup_logging())
        root = logging.getLogger()
        handler = InterceptHandler()
        root.addHandler(handler)
        root.setLevel(logging.DEBUG)
        try:
            logging.getLogger("some.library").info("library log message")
            assert any("library log message" in m for m in received), (
                f"Root-propagated message not found: {received}"
            )
        finally:
            root.removeHandler(handler)
    finally:
        logger.remove(sink_id)


# ---------------------------------------------------------------------------
# Smoke tests: converted modules import cleanly and their loggers work
# ---------------------------------------------------------------------------


def test_server_monitor_import():
    """app.services.server_monitor uses loguru logger without stdlib logging."""
    from app.services import server_monitor  # noqa: F401

    assert not hasattr(server_monitor.logger, "handlers"), (
        "server_monitor.logger should be a loguru logger, not stdlib Logger"
    )


def test_port_manager_import():
    """app.services.vpn_providers.port_manager uses loguru logger."""
    from app.services.vpn_providers import port_manager  # noqa: F401

    assert not hasattr(port_manager.logger, "handlers")


def test_auto_discovery_import():
    """app.services.auto_discovery uses loguru logger."""
    from app.services import auto_discovery  # noqa: F401

    assert not hasattr(auto_discovery.logger, "handlers")


def test_base_installer_import():
    """app.services.installers.base uses loguru logger."""
    from app.services.installers import base  # noqa: F401

    assert not hasattr(base.logger, "handlers")


def test_ssh_service_import():
    """app.services.ssh_service uses loguru logger."""
    from app.services import ssh_service  # noqa: F401

    assert not hasattr(ssh_service.logger, "handlers")
