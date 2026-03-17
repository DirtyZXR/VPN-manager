"""Admin server management handlers."""

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext

from app.bot.keyboards import (
    get_back_keyboard,
    get_confirm_keyboard,
    get_servers_keyboard,
)
from app.bot.states import ServerManagement
from app.database import async_session_factory
from app.services.xui_service import XUIService

router = Router()


async def check_admin(callback: CallbackQuery) -> bool:
    """Check if user is admin."""
    is_admin = callback.conf.get("is_admin", False)
    if not is_admin:
        await callback.answer("❌ У вас нет прав администратора.", show_alert=True)
    return is_admin


@router.callback_query(F.data == "admin_servers")
async def show_servers(callback: CallbackQuery) -> None:
    """Show servers list."""
    if not await check_admin(callback):
        return

    async with async_session_factory() as session:
        service = XUIService(session)
        servers = await service.get_all_servers()

    if not servers:
        await callback.message.edit_text(
            "📋 Список серверов пуст.\n\n"
            "Нажмите '➕ Добавить сервер' для добавления первого сервера.",
            reply_markup=get_servers_keyboard([]),
        )
    else:
        await callback.message.edit_text(
            "📋 Список серверов:",
            reply_markup=get_servers_keyboard(servers),
        )
    await callback.answer()


@router.callback_query(F.data == "server_add")
async def start_add_server(callback: CallbackQuery, state: FSMContext) -> None:
    """Start adding new server."""
    if not await check_admin(callback):
        return

    await state.set_state(ServerManagement.waiting_for_name)
    await callback.message.edit_text(
        "➕ Добавление нового сервера\n\n"
        "Введите название сервера (например, 'NL-Server-1'):",
        reply_markup=get_back_keyboard("admin_servers"),
    )
    await callback.answer()


@router.message(ServerManagement.waiting_for_name)
async def process_server_name(message: Message, state: FSMContext) -> None:
    """Process server name input."""
    await state.update_data(name=message.text)
    await state.set_state(ServerManagement.waiting_for_url)
    await message.answer(
        "Введите URL панели 3x-ui (например, https://panel.example.com):",
        reply_markup=get_back_keyboard("admin_servers"),
    )


@router.message(ServerManagement.waiting_for_url)
async def process_server_url(message: Message, state: FSMContext) -> None:
    """Process server URL input."""
    url = message.text.strip()
    if not url.startswith(("http://", "https://")):
        await message.answer("❌ URL должен начинаться с http:// или https://")
        return

    await state.update_data(url=url)
    await state.set_state(ServerManagement.waiting_for_username)
    await message.answer(
        "Введите имя пользователя для входа в панель:",
        reply_markup=get_back_keyboard("admin_servers"),
    )


@router.message(ServerManagement.waiting_for_username)
async def process_server_username(message: Message, state: FSMContext) -> None:
    """Process server username input."""
    await state.update_data(username=message.text)
    await state.set_state(ServerManagement.waiting_for_password)
    await message.answer(
        "Введите пароль для входа в панель:",
        reply_markup=get_back_keyboard("admin_servers"),
    )


@router.message(ServerManagement.waiting_for_password)
async def process_server_password(message: Message, state: FSMContext) -> None:
    """Process server password input and create server."""
    data = await state.get_data()
    password = message.text

    async with async_session_factory() as session:
        service = XUIService(session)
        server = await service.create_server(
            name=data["name"],
            url=data["url"],
            username=data["username"],
            password=password,
        )
        await session.commit()

    await state.clear()
    await message.answer(
        f"✅ Сервер '{server.name}' успешно добавлен!\n\n"
        f"URL: {server.url}",
        reply_markup=get_back_keyboard("admin_servers"),
    )


@router.callback_query(F.data.startswith("server_select_"))
async def select_server(callback: CallbackQuery) -> None:
    """Show server details."""
    if not await check_admin(callback):
        return

    server_id = int(callback.data.split("_")[-1])

    async with async_session_factory() as session:
        service = XUIService(session)
        server = await service.get_server_by_id(server_id)

    if not server:
        await callback.answer("❌ Сервер не найден.", show_alert=True)
        return

    status = "✅ Активен" if server.is_active else "❌ Неактивен"
    last_sync = server.last_sync.strftime("%d.%m.%Y %H:%M") if server.last_sync else "Никогда"

    text = (
        f"🖥️ Сервер: {server.name}\n\n"
        f"URL: {server.url}\n"
        f"Статус: {status}\n"
        f"Последняя синхронизация: {last_sync}"
    )

    builder = []
    builder.append({"text": "🔄 Синхронизировать", "callback_data": f"server_sync_{server_id}"})
    builder.append({"text": "🔌 Проверить подключение", "callback_data": f"server_test_{server_id}"})
    if server.is_active:
        builder.append({"text": "❌ Отключить", "callback_data": f"server_disable_{server_id}"})
    else:
        builder.append({"text": "✅ Включить", "callback_data": f"server_enable_{server_id}"})
    builder.append({"text": "🗑️ Удалить", "callback_data": f"server_delete_{server_id}"})
    builder.append({"text": "🔙 Назад", "callback_data": "admin_servers"})

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    for btn in builder:
        kb.button(**btn)
    kb.adjust(1)

    await callback.message.edit_text(text, reply_markup=kb.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("server_sync_"))
async def sync_server(callback: CallbackQuery) -> None:
    """Sync server inbounds."""
    if not await check_admin(callback):
        return

    server_id = int(callback.data.split("_")[-1])

    async with async_session_factory() as session:
        service = XUIService(session)
        try:
            count = await service.sync_server_inbounds(server_id)
            await session.commit()
            await callback.answer(f"✅ Синхронизировано {count} inbounds", show_alert=True)
        except Exception as e:
            await callback.answer(f"❌ Ошибка: {e}", show_alert=True)
        finally:
            await service.close_all_clients()


@router.callback_query(F.data.startswith("server_test_"))
async def test_server(callback: CallbackQuery) -> None:
    """Test server connection."""
    if not await check_admin(callback):
        return

    server_id = int(callback.data.split("_")[-1])

    async with async_session_factory() as session:
        service = XUIService(session)
        success, message = await service.test_server_connection(server_id)
        await service.close_all_clients()

    if success:
        await callback.answer(f"✅ {message}", show_alert=True)
    else:
        await callback.answer(f"❌ {message}", show_alert=True)


@router.callback_query(F.data.startswith("server_enable_"))
async def enable_server(callback: CallbackQuery) -> None:
    """Enable server."""
    if not await check_admin(callback):
        return

    server_id = int(callback.data.split("_")[-1])

    async with async_session_factory() as session:
        service = XUIService(session)
        await service.update_server(server_id, is_active=True)
        await session.commit()

    await callback.answer("✅ Сервер включен.")
    await select_server(callback)


@router.callback_query(F.data.startswith("server_disable_"))
async def disable_server(callback: CallbackQuery) -> None:
    """Disable server."""
    if not await check_admin(callback):
        return

    server_id = int(callback.data.split("_")[-1])

    async with async_session_factory() as session:
        service = XUIService(session)
        await service.update_server(server_id, is_active=False)
        await session.commit()

    await callback.answer("✅ Сервер отключен.")
    await select_server(callback)


@router.callback_query(F.data.startswith("server_delete_"))
async def confirm_delete_server(callback: CallbackQuery, state: FSMContext) -> None:
    """Confirm server deletion."""
    if not await check_admin(callback):
        return

    server_id = int(callback.data.split("_")[-1])
    await state.update_data(server_id=server_id)
    await state.set_state(ServerManagement.confirm_delete)

    await callback.message.edit_text(
        "⚠️ Вы уверены, что хотите удалить этот сервер?\n\n"
        "Все связанные подписки будут также удалены!",
        reply_markup=get_confirm_keyboard(f"server_delete_{server_id}", "admin_servers"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("confirm_server_delete_"))
async def delete_server(callback: CallbackQuery, state: FSMContext) -> None:
    """Delete server."""
    if not await check_admin(callback):
        return

    server_id = int(callback.data.split("_")[-1])

    async with async_session_factory() as session:
        service = XUIService(session)
        await service.delete_server(server_id)
        await session.commit()

    await state.clear()
    await callback.answer("✅ Сервер удален.")
    await show_servers(callback)
