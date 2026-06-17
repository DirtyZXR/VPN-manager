"""Конфигурация логирования (loguru): sinks, формат с контекстом, мост из stdlib."""

import logging
import sys
from pathlib import Path

from loguru import logger

from app.config import get_settings

# Болтливые сторонние библиотеки: их записи ниже WARNING не пропускаем в loguru.
NOISY_LOGGERS = ("aiogram", "aiosqlite", "sqlalchemy.engine", "asyncssh", "aiohttp")


def _context_suffix(record) -> str:
    """' [server=2 cycle=ab12]' из record['extra']; '' если контекста нет.

    Экранируем фигурные скобки в значениях — строка попадёт в format-шаблон
    loguru, и сырые '{'/'}' сломали бы подстановку.
    """
    extra = record["extra"]
    if not extra:
        return ""
    pairs = " ".join(f"{k}={v}" for k, v in extra.items())
    pairs = pairs.replace("{", "{{").replace("}", "}}")
    return f" [{pairs}]"


def _console_format(record) -> str:
    """Цветной формат для stdout (loguru обработает теги при colorize=True)."""
    return (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan>"
        + _context_suffix(record)
        + " - <level>{message}</level>\n{exception}"
    )


def _file_format(record) -> str:
    """Простой формат для файловых sink'ов (без цветовых тегов)."""
    return (
        "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | "
        "{name}:{function}:{line}"
        + _context_suffix(record)
        + " - {message}\n{exception}"
    )


class InterceptHandler(logging.Handler):
    """Мост: записи stdlib logging → loguru (один набор sinks с ротацией)."""

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


def setup_logging() -> None:
    """Настроить loguru: stdout + app.log + errors.log, контекст, приглушение шума."""
    settings = get_settings()
    level = settings.log_level

    logger.remove()

    logger.add(
        sys.stdout,
        level=level,
        format=_console_format,
        colorize=True,
        backtrace=True,
        diagnose=False,
    )

    log_path = Path("logs")
    log_path.mkdir(exist_ok=True)

    logger.add(
        log_path / "app.log",
        level=level,
        format=_file_format,
        rotation="10 MB",
        retention="7 days",
        enqueue=True,
        backtrace=True,
        diagnose=False,
    )
    logger.add(
        log_path / "errors.log",
        level="WARNING",
        format=_file_format,
        rotation="10 MB",
        retention="30 days",
        enqueue=True,
        backtrace=True,
        diagnose=False,
    )

    # Приглушить болтливые библиотеки, затем завернуть весь stdlib в loguru.
    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
