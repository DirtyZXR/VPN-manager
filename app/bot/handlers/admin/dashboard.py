"""Admin dashboard and submenu handlers."""

import contextlib

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from sqlalchemy import func, select

from app.bot.keyboards.inline import (
    get_admin_clients_menu_keyboard,
    get_admin_dashboard_keyboard,
    get_admin_infra_menu_keyboard,
    get_admin_system_menu_keyboard,
)
from app.database import async_session_factory
from app.database.models import Client, Server, Subscription
from app.utils.texts import t

router = Router()


@router.callback_query(F.data == "admin_menu")
async def show_admin_dashboard(callback: CallbackQuery, is_admin: bool, state: FSMContext) -> None:
    """Show the main admin dashboard with statistics."""
    if not is_admin:
        await callback.answer(
            t("errors.admin_only", "❌ У вас нет прав администратора."), show_alert=True
        )
        return

    current_state = await state.get_state()
    if current_state:
        await state.clear()

    async with async_session_factory() as session:
        # Count servers
        total_servers = await session.scalar(select(func.count(Server.id)))
        active_servers = await session.scalar(
            select(func.count(Server.id)).where(Server.is_active.is_(True))
        )

        # Count clients
        total_clients = await session.scalar(select(func.count(Client.id)))
        active_clients = await session.scalar(
            select(func.count(Client.id)).where(Client.is_active.is_(True))
        )

        # Count subscriptions
        total_subs = await session.scalar(select(func.count(Subscription.id)))

    stats_text = t(
        "admin.dashboard.stats",
        "📊 <b>Статистика панели:</b>\n"
        "🖥 Серверов: {total_servers} (активно: {active_servers})\n"
        "👥 Клиентов: {total_clients} (активно: {active_clients})\n"
        "📦 Выдано подписок: {total_subs}\n\n"
        "Выберите раздел для управления:",
        total_servers=total_servers or 0,
        active_servers=active_servers or 0,
        total_clients=total_clients or 0,
        active_clients=active_clients or 0,
        total_subs=total_subs or 0,
    )

    with contextlib.suppress(Exception):
        await callback.message.edit_text(
            stats_text, reply_markup=get_admin_dashboard_keyboard(), parse_mode="HTML"
        )
    await callback.answer()


@router.callback_query(F.data == "admin_clients_menu")
async def show_clients_menu(callback: CallbackQuery, is_admin: bool, state: FSMContext) -> None:
    """Show clients management submenu."""
    if not is_admin:
        await callback.answer(
            t("errors.admin_only", "❌ У вас нет прав администратора."), show_alert=True
        )
        return

    current_state = await state.get_state()
    if current_state:
        await state.clear()

    with contextlib.suppress(Exception):
        await callback.message.edit_text(
            t(
                "admin.dashboard.clients_menu",
                "👥 <b>Клиентская часть</b>\n\nУправление пользователями, их подписками, шаблонами и рассылками:",
            ),
            reply_markup=get_admin_clients_menu_keyboard(),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data == "admin_infra_menu")
async def show_infra_menu(callback: CallbackQuery, is_admin: bool, state: FSMContext) -> None:
    """Show infrastructure management submenu."""
    if not is_admin:
        await callback.answer(
            t("errors.admin_only", "❌ У вас нет прав администратора."), show_alert=True
        )
        return

    current_state = await state.get_state()
    if current_state:
        await state.clear()

    with contextlib.suppress(Exception):
        await callback.message.edit_text(
            t(
                "admin.dashboard.infra_menu",
                "🖥 <b>Инфраструктура</b>\n\nУправление серверами XUI и синхронизацией данных:",
            ),
            reply_markup=get_admin_infra_menu_keyboard(),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data == "admin_system_menu")
async def show_system_menu(callback: CallbackQuery, is_admin: bool, state: FSMContext) -> None:
    """Show system and settings submenu."""
    if not is_admin:
        await callback.answer(
            t("errors.admin_only", "❌ У вас нет прав администратора."), show_alert=True
        )
        return

    current_state = await state.get_state()
    if current_state:
        await state.clear()

    with contextlib.suppress(Exception):
        await callback.message.edit_text(
            t(
                "admin.dashboard.system_menu",
                "🛠 <b>Система и Настройки</b>\n\nСистемные функции, обновление конфигов и бэкапы:",
            ),
            reply_markup=get_admin_system_menu_keyboard(),
            parse_mode="HTML",
        )
    await callback.answer()
