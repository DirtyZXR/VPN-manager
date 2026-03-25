"""Admin synchronization handlers."""

import asyncio

from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from loguru import logger

from app.bot.keyboards import get_back_keyboard
from app.database import async_session_factory
from app.services import SyncService

router = Router()


@router.callback_query(F.data == "admin_sync")
async def show_sync_menu(callback: CallbackQuery, is_admin: bool) -> None:
    """Меню синхронизации."""
    if not is_admin:
        await callback.answer("❌ У вас нет прав администратора.", show_alert=True)
        return

    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="🖥️ Синхронизировать сервера", callback_data="sync_servers")
    keyboard.button(text="📊 Проверить целостность", callback_data="sync_integrity")
    keyboard.button(text="🔙 Назад", callback_data="admin_menu")
    keyboard.adjust(1)

    try:
        await callback.message.edit_text(
            "🔄 Управление синхронизацией данных\n\n"
            "Выберите действие для синхронизации данных между ботом и 3x-ui панелями.\n\n"
            "✅ Синхронизируются: серверы, inbounds и клиенты\n\n"
            "📌 Что делает каждая кнопка:\n"
            "• 🖥️ Синхронизировать сервера - Все серверы с inbounds и клиентами\n"
            "• 📊 Проверить целостность - Только проверка, без синхронизации",
            reply_markup=keyboard.as_markup(),
        )
    except Exception:
        # Message hasn't changed, skip edit
        pass
    await callback.answer()


@router.callback_query(F.data == "sync_servers")
async def sync_servers(callback: CallbackQuery, is_admin: bool) -> None:
    """Синхронизировать все сервера."""
    if not is_admin:
        await callback.answer("❌ У вас нет прав администратора.", show_alert=True)
        return

    try:
        await callback.message.edit_text(
            "🔄 Синхронизация серверов...\n"
            "⏳ Пожалуйста, подождите.",
            reply_markup=get_back_keyboard("admin_sync"),
        )

        async with async_session_factory() as session:
            sync_service = SyncService(session)
            results = await sync_service.manual_sync("server")
            await session.commit()  # Сохранить изменения в базу данных

        status_emoji = "✅" if results["errors"] == 0 else "⚠️"
        await callback.message.edit_text(
            f"{status_emoji} Синхронизация серверов завершена\n\n"
            f"Синхронизировано серверов: {results['synced']}\n"
            f"Ошибок: {results['errors']}\n"
            f"✅ Серверы, inbounds и клиенты синхронизированы",
            reply_markup=get_back_keyboard("admin_sync"),
        )
        await callback.answer("✅ Сервера синхронизированы")

    except Exception as e:
        logger.error(f"Ошибка синхронизации серверов: {e}", exc_info=True)
        await callback.message.edit_text(
            f"❌ Ошибка при синхронизации: {e}",
            reply_markup=get_back_keyboard("admin_sync"),
        )
        await callback.answer("❌ Ошибка при синхронизации", show_alert=True)


@router.callback_query(F.data == "sync_integrity")
async def check_integrity(callback: CallbackQuery, is_admin: bool) -> None:
    """Проверить целостность данных."""
    if not is_admin:
        await callback.answer("❌ У вас нет прав администратора.", show_alert=True)
        return

    try:
        await callback.message.edit_text(
            "🔍 Проверка целостности данных...\n"
            "⏳ Пожалуйста, подождите.",
            reply_markup=get_back_keyboard("admin_sync"),
        )

        async with async_session_factory() as session:
            sync_service = SyncService(session)
            integrity_ok = await sync_service.verify_connections_integrity()

        status_emoji = "✅" if integrity_ok else "⚠️"
        status_text = "Все данные актуальны" if integrity_ok else "Обнаружены расхождения"

        await callback.message.edit_text(
            f"{status_emoji} Проверка целостности завершена\n\n"
            f"Статус: {status_text}\n"
            f"💡 При необходимости запустите полную синхронизацию.",
            reply_markup=get_back_keyboard("admin_sync"),
        )
        await callback.answer("✅ Проверка целостности завершена")

    except Exception as e:
        logger.error(f"Ошибка проверки целостности: {e}", exc_info=True)
        await callback.message.edit_text(
            f"❌ Ошибка при проверке: {e}",
            reply_markup=get_back_keyboard("admin_sync"),
        )
        await callback.answer("❌ Ошибка при проверке", show_alert=True)
