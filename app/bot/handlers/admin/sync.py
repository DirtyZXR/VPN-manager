"""Admin synchronization handlers."""

import contextlib

from aiogram import F, Router
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from loguru import logger

from app.bot.keyboards import get_back_keyboard
from app.database import async_session_factory
from app.services import SyncService
from app.utils.texts import t

router = Router()


@router.callback_query(F.data == "admin_sync")
async def show_sync_menu(callback: CallbackQuery, is_admin: bool) -> None:
    """Меню синхронизации."""
    if not is_admin:
        await callback.answer(
            t("admin.sync.access_denied", "❌ У вас нет прав администратора."), show_alert=True
        )
        return

    keyboard = InlineKeyboardBuilder()
    keyboard.button(
        text=t("admin.sync.btn_sync_servers", "🖥️ Синхронизировать сервера"),
        callback_data="sync_servers",
    )
    keyboard.button(
        text=t("admin.sync.btn_check_integrity", "📊 Проверить целостность"),
        callback_data="sync_integrity",
    )
    keyboard.button(text=t("admin.sync.btn_back", "🔙 Назад"), callback_data="admin_infra_menu")
    keyboard.adjust(1)

    with contextlib.suppress(Exception):
        await callback.message.edit_text(
            t(
                "admin.sync.menu_text",
                "🔄 Управление синхронизацией данных\n\n"
                "Выберите действие для синхронизации данных между ботом и 3x-ui панелями.\n\n"
                "✅ Синхронизируются: серверы, inbounds и клиенты\n\n"
                "📌 Что делает каждая кнопка:\n"
                "• 🖥️ Синхронизировать сервера - Все серверы с inbounds и клиентами\n"
                "• 📊 Проверить целостность - Только проверка, без синхронизации",
            ),
            reply_markup=keyboard.as_markup(),
        )
    await callback.answer()


@router.callback_query(F.data == "sync_servers")
async def sync_servers(callback: CallbackQuery, is_admin: bool) -> None:
    """Синхронизировать все сервера."""
    if not is_admin:
        await callback.answer(
            t("admin.sync.access_denied", "❌ У вас нет прав администратора."), show_alert=True
        )
        return

    try:
        # Сначала отправляем ответ на callback, чтобы не истекло время
        await callback.answer(t("admin.sync.sync_started_alert", "⏳ Синхронизация запущена..."))

        await callback.message.edit_text(
            t(
                "admin.sync.sync_started_text",
                "🔄 Синхронизация серверов...\n⏳ Пожалуйста, подождите.",
            ),
            reply_markup=get_back_keyboard("admin_sync"),
        )

        async with async_session_factory() as session:
            sync_service = SyncService(session)
            try:
                results = await sync_service.manual_sync("server")
                await session.commit()  # Сохранить изменения в базу данных
            finally:
                await sync_service.close_xui_clients()

        status_emoji = "✅" if results["errors"] == 0 else "⚠️"
        await callback.message.edit_text(
            t(
                "admin.sync.sync_completed",
                "{status_emoji} Синхронизация серверов завершена\n\n"
                "Синхронизировано серверов: {synced}\n"
                "Ошибок: {errors}\n"
                "✅ Серверы, inbounds и клиенты синхронизированы",
                status_emoji=status_emoji,
                synced=results["synced"],
                errors=results["errors"],
            ),
            reply_markup=get_back_keyboard("admin_sync"),
        )
        # Не отправляем callback.answer снова - уже отправили в начале

    except Exception as e:
        logger.error(f"Ошибка синхронизации серверов: {e}", exc_info=True)
        with contextlib.suppress(Exception):
            await callback.message.edit_text(
                t("admin.sync.sync_error", "❌ Ошибка при синхронизации: {error}", error=str(e)),
                reply_markup=get_back_keyboard("admin_sync"),
            )


@router.callback_query(F.data == "sync_integrity")
async def check_integrity(callback: CallbackQuery, is_admin: bool) -> None:
    """Проверить целостность данных."""
    if not is_admin:
        await callback.answer(
            t("admin.sync.access_denied", "❌ У вас нет прав администратора."), show_alert=True
        )
        return

    try:
        # Сначала отправляем ответ на callback
        await callback.answer(
            t("admin.sync.integrity_started_alert", "⏳ Проверка целостности запущена...")
        )

        await callback.message.edit_text(
            t(
                "admin.sync.integrity_started_text",
                "🔍 Проверка целостности данных...\n⏳ Пожалуйста, подождите.",
            ),
            reply_markup=get_back_keyboard("admin_sync"),
        )

        async with async_session_factory() as session:
            sync_service = SyncService(session)
            try:
                integrity_ok = await sync_service.verify_connections_integrity()
            finally:
                await sync_service.close_xui_clients()

        status_emoji = "✅" if integrity_ok else "⚠️"
        status_text = (
            t("admin.sync.integrity_ok", "Все данные актуальны")
            if integrity_ok
            else t("admin.sync.integrity_issues", "Обнаружены расхождения")
        )

        await callback.message.edit_text(
            t(
                "admin.sync.integrity_completed",
                "{status_emoji} Проверка целостности завершена\n\n"
                "Статус: {status_text}\n"
                "💡 При необходимости запустите полную синхронизацию.",
                status_emoji=status_emoji,
                status_text=status_text,
            ),
            reply_markup=get_back_keyboard("admin_sync"),
        )
        # Не отправляем callback.answer снова - уже отправили в начале

    except Exception as e:
        logger.error(f"Ошибка проверки целостности: {e}", exc_info=True)
        with contextlib.suppress(Exception):
            await callback.message.edit_text(
                t("admin.sync.integrity_error", "❌ Ошибка при проверке: {error}", error=str(e)),
                reply_markup=get_back_keyboard("admin_sync"),
            )
