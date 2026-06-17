"""Fallback-роутер: тихо гасит «часики» у необработанных callback'ов.

Срабатывает в т.ч. для не-админов, отсечённых AdminFilter от админ-роутеров,
и для устаревших кнопок. Включается последним в общий роутер.
"""

from aiogram import Router
from aiogram.types import CallbackQuery
from loguru import logger

router = Router(name="fallback")


@router.callback_query()
async def silent_unhandled_callback(callback: CallbackQuery) -> None:
    """Ответить на любой не пойманный callback без текста, чтобы не висел спиннер."""
    logger.debug(f"Необработанный callback тихо погашен: {callback.data!r}")
    await callback.answer()
