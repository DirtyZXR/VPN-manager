"""Admin server management handlers."""

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from aiogram.types import Message as TgMessage
from loguru import logger

from app.bot.keyboards import (
    get_back_keyboard,
    get_confirm_keyboard,
    get_servers_keyboard,
)
from app.bot.states import ServerManagement
from app.database import async_session_factory
from app.services.xui_service import XUIService
from app.utils.texts import t

router = Router()


@router.callback_query(F.data == "admin_servers")
async def show_servers(callback: CallbackQuery, is_admin: bool, state: FSMContext) -> None:
    """Show servers list."""
    if not is_admin:
        await callback.answer(
            t("admin.errors.no_rights", "❌ У вас нет прав администратора."), show_alert=True
        )
        return

    current_state = await state.get_state()
    if current_state:
        await state.clear()

    async with async_session_factory() as session:
        service = XUIService(session)
        servers = await service.get_all_servers()

    if not servers:
        await callback.message.edit_text(
            t(
                "admin.servers.list_empty",
                "📋 Список серверов пуст.\n\nНажмите '➕ Добавить сервер' для добавления первого сервера.",
            ),
            reply_markup=get_servers_keyboard([]),
        )
    else:
        await callback.message.edit_text(
            t("admin.servers.list", "📋 Список серверов:"),
            reply_markup=get_servers_keyboard(servers),
        )
    await callback.answer()


@router.callback_query(F.data == "server_add")
async def start_add_server(callback: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    """Start adding new server."""
    if not is_admin:
        await callback.answer(
            t("admin.errors.no_rights", "❌ У вас нет прав администратора."), show_alert=True
        )
        return

    await state.clear()
    await state.set_state(ServerManagement.waiting_for_name)
    await callback.message.edit_text(
        t(
            "admin.servers.add_name",
            "➕ Добавление нового сервера\n\nВведите название сервера (например, 'NL-Server-1'):",
        ),
        reply_markup=get_back_keyboard("admin_servers"),
    )
    await callback.answer()


@router.message(ServerManagement.waiting_for_name)
async def process_server_name(message: TgMessage, state: FSMContext) -> None:
    """Process server name input."""
    name = message.text.strip()

    if not name:
        await message.answer(
            t("admin.servers.errors.empty_name", "❌ Название не может быть пустым."),
            reply_markup=get_back_keyboard("admin_servers"),
        )
        return

    if len(name) > 100:
        await message.answer(
            t(
                "admin.servers.errors.name_too_long",
                "❌ Название не должно превышать 100 символов.",
            ),
            reply_markup=get_back_keyboard("admin_servers"),
        )
        return

    await state.update_data(name=name)
    await state.set_state(ServerManagement.waiting_for_ip_address)
    await message.answer(
        t(
            "admin.servers.add_ip",
            "Введите IP-адрес сервера (например, 192.168.1.1):",
        ),
        reply_markup=get_back_keyboard("admin_servers"),
    )


@router.message(ServerManagement.waiting_for_ip_address)
async def process_server_ip_address(message: TgMessage, state: FSMContext) -> None:
    """Process server IP address input."""
    ip_address = message.text.strip()

    if not ip_address:
        await message.answer(
            t("admin.servers.errors.empty_ip", "❌ IP-адрес не может быть пустым."),
            reply_markup=get_back_keyboard("admin_servers"),
        )
        return

    await state.update_data(ip_address=ip_address)

    msg = await message.answer(t("admin.servers.pinging", "🔄 Пингую сервер..."))

    from app.services.server_monitor import ServerMonitor

    is_online = await ServerMonitor.ping(ip_address)

    if not is_online:
        await state.set_state(ServerManagement.confirm_add_offline)

        from aiogram.utils.keyboard import InlineKeyboardBuilder

        kb = InlineKeyboardBuilder()
        kb.button(
            text=t("admin.servers.buttons.add_offline_yes", "✅ Да, добавить"),
            callback_data="add_offline_yes",
        )
        kb.button(
            text=t("admin.servers.buttons.add_offline_no", "❌ Нет, отменить"),
            callback_data="add_offline_no",
        )
        kb.adjust(1)

        await msg.edit_text(
            t(
                "admin.servers.errors.server_offline",
                "⚠️ Сервер не отвечает на ping.\nВы уверены, что хотите добавить его?",
            ),
            reply_markup=kb.as_markup(),
        )
        return

    # Online, proceed to create
    await _create_and_finish_server_addition(msg, state, ip_address, True)


@router.callback_query(ServerManagement.confirm_add_offline)
async def process_confirm_add_offline(callback: CallbackQuery, state: FSMContext) -> None:
    """Process confirmation to add offline server."""
    if callback.data == "add_offline_no":
        await state.clear()
        await callback.message.edit_text(
            t("admin.servers.add_cancelled", "❌ Добавление сервера отменено."),
            reply_markup=get_back_keyboard("admin_servers"),
        )
        await callback.answer()
        return

    # Proceed to create
    data = await state.get_data()
    ip_address = data.get("ip_address")
    await _create_and_finish_server_addition(callback.message, state, ip_address, False)
    await callback.answer()


async def _create_and_finish_server_addition(
    message: TgMessage, state: FSMContext, ip_address: str, is_online: bool
) -> None:
    """Helper to create server and notify admin."""
    data = await state.get_data()
    name = data.get("name")

    async with async_session_factory() as session:
        service = XUIService(session)
        server = await service.create_server(
            name=name,
            ip_address=ip_address,
            url=None,
            username=None,
            password=None,
        )
        server.is_online = is_online
        await session.commit()

    await state.clear()

    status_text = (
        t("admin.servers.status.online", "✅ В сети")
        if is_online
        else t("admin.servers.status.offline", "❌ Не в сети (добавлен принудительно)")
    )

    text = t(
        "admin.servers.added_success",
        "✅ Сервер '{name}' успешно добавлен!\n\nIP: {ip}\nСтатус: {status}",
        name=name,
        ip=ip_address,
        status=status_text,
    )

    await message.edit_text(text, reply_markup=get_back_keyboard("admin_servers"))


@router.callback_query(F.data.startswith("server_select_"))
async def select_server(callback: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    """Show server details."""
    if not is_admin:
        await callback.answer(
            t("admin.errors.no_rights", "❌ У вас нет прав администратора."), show_alert=True
        )
        return

    await state.clear()
    server_id = int(callback.data.split("_")[-1])

    async with async_session_factory() as session:
        service = XUIService(session)
        server = await service.get_server_by_id(server_id)

    if not server:
        await callback.answer(
            t("admin.servers.errors.not_found", "❌ Сервер не найден."), show_alert=True
        )
        return

    status = (
        t("admin.servers.status.active", "✅ Активен")
        if server.is_online
        else t("admin.servers.status.inactive", "❌ Неактивен")
    )
    last_sync = (
        server.last_sync_at.strftime("%d.%m.%Y %H:%M")
        if hasattr(server, "last_sync_at") and server.last_sync_at
        else t("admin.servers.sync.never", "Никогда")
    )

    ip_info = f"\n🌐 IP: {server.ip_address}" if server.ip_address else ""

    text = t(
        "admin.servers.info_new",
        "🖥️ Сервер: {name}{ip_info}\n📊 Статус: {status}\n🔄 Последняя синхронизация: {last_sync}",
        name=server.name,
        ip_info=ip_info,
        status=status,
        last_sync=last_sync,
    )

    builder = []
    builder.append(
        {
            "text": t("admin.servers.buttons.edit", "✏️ Редактировать"),
            "callback_data": f"server_edit_{server_id}",
        }
    )
    builder.append(
        {
            "text": t("admin.servers.buttons.ssh_setup", "🔑 Настроить SSH"),
            "callback_data": f"server_setup_ssh_{server_id}",
        }
    )
    builder.append(
        {
            "text": t("admin.servers.buttons.manage_services", "⚙️ Управление сервисами"),
            "callback_data": f"server_services_{server_id}",
        }
    )
    builder.append(
        {
            "text": t("admin.servers.buttons.inbounds", "📊 Inbounds"),
            "callback_data": f"server_inbounds_{server_id}",
        }
    )
    builder.append(
        {
            "text": t("admin.servers.buttons.sync", "🔄 Синхронизировать"),
            "callback_data": f"server_sync_{server_id}",
        }
    )
    builder.append(
        {
            "text": t("admin.servers.buttons.test_connection", "🔌 Проверить подключение"),
            "callback_data": f"server_test_{server_id}",
        }
    )
    builder.append(
        {
            "text": t("admin.servers.buttons.delete", "🗑️ Удалить"),
            "callback_data": f"server_delete_{server_id}",
        }
    )
    builder.append(
        {"text": t("admin.servers.buttons.back", "🔙 Назад"), "callback_data": "admin_servers"}
    )

    from aiogram.utils.keyboard import InlineKeyboardBuilder

    kb = InlineKeyboardBuilder()
    for btn in builder:
        kb.button(**btn)
    kb.adjust(1)

    await callback.message.edit_text(text, reply_markup=kb.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("server_sync_"))
async def sync_server(callback: CallbackQuery, is_admin: bool) -> None:
    """Sync server inbounds and clients."""
    if not is_admin:
        await callback.answer(
            t("admin.errors.no_rights", "❌ У вас нет прав администратора."), show_alert=True
        )
        return

    server_id = int(callback.data.split("_")[-1])

    async with async_session_factory() as session:
        from app.services import SyncService

        sync_service = SyncService(session)
        try:
            # Sync inbounds and clients
            from sqlalchemy.orm import selectinload

            from app.database.models import Server

            server = await session.get(
                Server,
                server_id,
                options=[
                    selectinload(Server.xui_panel),
                    selectinload(Server.awg_service),
                    selectinload(Server.mtproxy_service),
                    selectinload(Server.inbounds),
                ]
            )
            if server:
                await sync_service.sync_server(server, force=True)
                await session.commit()
                await callback.answer(
                    t(
                        "admin.servers.sync_success",
                        "✅ Синхронизация завершена! Inbounds и клиенты синхронизированы",
                    ),
                    show_alert=True,
                )
            else:
                await callback.answer(
                    t("admin.servers.errors.not_found", "❌ Сервер не найден"), show_alert=True
                )
        except Exception as e:
            logger.error("Error syncing server {}: {}", server_id, e, exc_info=True)
            await callback.answer(
                t(
                    "admin.servers.errors.sync_failed",
                    "❌ Ошибка при синхронизации: {error}",
                    error=str(e),
                ),
                show_alert=True,
            )


@router.callback_query(F.data.startswith("server_test_"))
async def test_server(callback: CallbackQuery, is_admin: bool) -> None:
    """Test server connection."""
    if not is_admin:
        await callback.answer(
            t("admin.errors.no_rights", "❌ У вас нет прав администратора."), show_alert=True
        )
        return

    server_id = int(callback.data.split("_")[-1])

    async with async_session_factory() as session:
        service = XUIService(session)
        server = await service.get_server_by_id(server_id)
        if not server:
            await callback.answer(
                t("admin.servers.errors.not_found", "❌ Сервер не найден."), show_alert=True
            )
            return

        success, message = await service.test_server_connection(server_id)

        await service.close_all_clients()

    if success:
        await callback.answer(
            t("admin.servers.test.success", "✅ {message}", message=message), show_alert=True
        )
    else:
        await callback.answer(
            t("admin.servers.test.error", "❌ {message}", message=message), show_alert=True
        )


@router.callback_query(F.data.startswith("server_inbounds_"))
async def show_server_inbounds(callback: CallbackQuery, is_admin: bool) -> None:
    """Show inbounds for a server with detailed information."""
    if not is_admin:
        await callback.answer(
            t("admin.errors.no_rights", "❌ У вас нет прав администратора."), show_alert=True
        )
        return

    server_id = int(callback.data.split("_")[-1])

    async with async_session_factory() as session:
        service = XUIService(session)
        server = await service.get_server_by_id(server_id)
        if not server:
            await callback.answer(
                t("admin.servers.errors.not_found", "❌ Сервер не найден."), show_alert=True
            )
            return

        # Get inbounds from database
        inbounds = await service.get_server_inbounds_all_status(server_id)

        if not inbounds:
            await callback.message.edit_text(
                t(
                    "admin.servers.inbounds.empty",
                    "📊 Inbounds сервера {name}\n\n❌ Нет доступных inbounds.\n\nНажмите '🔄 Синхронизировать' для получения inbounds с панели.",
                    name=server.name,
                ),
                reply_markup=get_back_keyboard(f"server_select_{server_id}"),
            )
            await callback.answer()
            return

        # Build text with inbound details
        text = t(
            "admin.servers.inbounds.title",
            "📊 Inbounds сервера {name}\n\nВсего: {count} inbounds\n\n",
            name=server.name,
            count=len(inbounds),
        )

        for inbound in inbounds:
            status = "✅" if inbound.is_active else "❌"
            text += t(
                "admin.servers.inbounds.item",
                "{status} {remark}\n   Протокол: {protocol}\n   Порт: {port}\n   Клиентов (БД): {clients}\n\n",
                status=status,
                remark=inbound.remark,
                protocol=inbound.protocol,
                port=inbound.port,
                clients=getattr(inbound, "client_count", 0),
            )

        has_inactive = any(not inbound.is_active for inbound in inbounds)

        from aiogram.utils.keyboard import InlineKeyboardBuilder

        kb = InlineKeyboardBuilder()
        kb.button(
            text=t("admin.servers.buttons.update_stats", "🔄 Обновить статистику"),
            callback_data=f"inbound_stats_{server_id}",
        )
        if has_inactive:
            kb.button(
                text=t("admin.servers.buttons.cleanup_inbounds", "🧹 Очистить удаленные inbounds"),
                callback_data=f"cleanup_inbounds_{server_id}",
            )
        kb.button(
            text=t("admin.servers.buttons.back", "🔙 Назад"),
            callback_data=f"server_select_{server_id}",
        )
        kb.adjust(1)

        await callback.message.edit_text(text, reply_markup=kb.as_markup())
        await callback.answer()


@router.callback_query(F.data.startswith("cleanup_inbounds_"))
async def cleanup_inbounds(callback: CallbackQuery, is_admin: bool) -> None:
    """Cleanup inactive inbounds for a server."""
    if not is_admin:
        await callback.answer(
            t("admin.errors.no_rights", "❌ У вас нет прав администратора."), show_alert=True
        )
        return

    server_id = int(callback.data.split("_")[-1])

    async with async_session_factory() as session:
        from sqlalchemy import delete

        from app.database.models import Inbound

        await session.execute(
            delete(Inbound).where(Inbound.server_id == server_id, Inbound.is_active.is_(False))
        )
        await session.commit()

    await callback.answer(
        t("admin.servers.inbounds.cleanup_success", "✅ Удаленные inbounds очищены"),
        show_alert=True,
    )
    await show_server_inbounds(callback, is_admin)


@router.callback_query(F.data.startswith("inbound_stats_"))
async def show_inbound_stats(callback: CallbackQuery, is_admin: bool) -> None:
    """Show live statistics for inbounds from XUI panel."""
    if not is_admin:
        await callback.answer(
            t("admin.errors.no_rights", "❌ У вас нет прав администратора."), show_alert=True
        )
        return

    server_id = int(callback.data.split("_")[-1])

    async with async_session_factory() as session:
        service = XUIService(session)
        server = await service.get_server_by_id(server_id)
        if not server:
            await callback.answer(
                t("admin.servers.errors.not_found", "❌ Сервер не найден."), show_alert=True
            )
            return

        try:
            # Get inbounds from database
            inbounds = await service.get_server_inbounds(server_id)

            if not inbounds:
                await callback.answer(
                    t(
                        "admin.servers.inbounds.no_inbounds_to_update",
                        "❌ Нет inbounds для обновления.",
                    ),
                    show_alert=True,
                )
                return

            # Get live stats from XUI panel
            text = t(
                "admin.servers.stats.title",
                "📊 Статистика Inbounds сервера {name}\n\n",
                name=server.name,
            )

            for inbound in inbounds:
                stats = await service.get_inbound_client_stats(inbound.id)
                status = "✅" if inbound.is_active else "❌"

                text += t(
                    "admin.servers.stats.item",
                    "{status} {remark} ({protocol})\n   Порт: {port}\n   Всего клиентов: {total}\n   Активных: {active}\n   Отключенных: {disabled}\n   Использовано трафика: {used:.2f} GB\n\n",
                    status=status,
                    remark=inbound.remark,
                    protocol=inbound.protocol,
                    port=inbound.port,
                    total=stats["total_clients"],
                    active=stats["enabled_clients"],
                    disabled=stats["disabled_clients"],
                    used=stats["total_used_gb"],
                )

            from aiogram.utils.keyboard import InlineKeyboardBuilder

            kb = InlineKeyboardBuilder()
            kb.button(
                text=t("admin.servers.buttons.refresh", "🔄 Обновить"),
                callback_data=f"inbound_stats_{server_id}",
            )
            kb.button(
                text=t("admin.servers.buttons.back", "🔙 Назад"),
                callback_data=f"server_select_{server_id}",
            )
            kb.adjust(1)

            await callback.message.edit_text(text, reply_markup=kb.as_markup())
            await callback.answer(t("admin.servers.stats.updated", "✅ Статистика обновлена"))

        except Exception as e:
            logger.error("Error getting inbound stats: {}", e, exc_info=True)
            await callback.answer(
                t("admin.servers.errors.generic", "❌ Ошибка: {error}", error=str(e)),
                show_alert=True,
            )
        finally:
            await service.close_all_clients()


@router.callback_query(F.data.startswith("server_delete_"))
async def confirm_delete_server(callback: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    """Confirm server deletion."""
    if not is_admin:
        await callback.answer(
            t("admin.errors.no_rights", "❌ У вас нет прав администратора."), show_alert=True
        )
        return

    server_id = int(callback.data.split("_")[-1])
    await state.update_data(server_id=server_id)
    await state.set_state(ServerManagement.confirm_delete)

    await callback.message.edit_text(
        t(
            "admin.servers.delete_confirm",
            "⚠️ Вы уверены, что хотите удалить этот сервер?\n\nВсе связанные подписки будут также удалены!",
        ),
        reply_markup=get_confirm_keyboard(f"server_delete_{server_id}", "admin_servers"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("confirm_server_delete_"))
async def delete_server(callback: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    """Delete server."""
    if not is_admin:
        await callback.answer(
            t("admin.errors.no_rights", "❌ У вас нет прав администратора."), show_alert=True
        )
        return

    server_id = int(callback.data.split("_")[-1])

    async with async_session_factory() as session:
        service = XUIService(session)
        await service.delete_server(server_id)
        await session.commit()

    await state.clear()
    await callback.answer(t("admin.servers.deleted", "✅ Сервер удален."))
    await show_servers(callback, is_admin, state)


@router.callback_query(F.data.startswith("server_edit_"))
async def edit_server(callback: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    """Show server edit menu."""
    if not is_admin:
        await callback.answer(
            t("admin.errors.no_rights", "❌ У вас нет прав администратора."), show_alert=True
        )
        return

    server_id = int(callback.data.split("_")[-1])
    await state.update_data(server_id=server_id)

    async with async_session_factory() as session:
        service = XUIService(session)
        server = await service.get_server_by_id(server_id)

    if not server:
        await callback.answer(
            t("admin.servers.errors.not_found", "❌ Сервер не найден."), show_alert=True
        )
        return

    builder = []
    builder.append(
        {
            "text": t("admin.servers.buttons.edit_name", "✏️ Название"),
            "callback_data": "edit_server_name",
        }
    )
    builder.append(
        {
            "text": t("admin.servers.buttons.edit_ip", "🌐 IP-адрес"),
            "callback_data": "edit_server_ip",
        }
    )
    builder.append(
        {
            "text": t("admin.servers.buttons.back", "🔙 Назад"),
            "callback_data": f"server_select_{server_id}",
        }
    )

    from aiogram.utils.keyboard import InlineKeyboardBuilder

    kb = InlineKeyboardBuilder()
    for btn in builder:
        kb.button(**btn)
    kb.adjust(1)

    text = t(
        "admin.servers.edit_menu_new",
        "✏️ Редактирование сервера: <b>{name}</b>\n\n🌐 IP-адрес: {ip}\n\nВыберите поле для редактирования:",
        name=server.name,
        ip=server.ip_address,
    )

    await callback.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "edit_server_name")
async def start_edit_name(callback: CallbackQuery, state: FSMContext) -> None:
    """Start editing server name."""
    data = await state.get_data()
    server_id = data["server_id"]

    async with async_session_factory() as session:
        service = XUIService(session)
        server = await service.get_server_by_id(server_id)

    if not server:
        await callback.answer(
            t("admin.servers.errors.not_found", "❌ Сервер не найден."), show_alert=True
        )
        return

    await state.set_state(ServerManagement.waiting_for_edit_name)
    await callback.message.edit_text(
        t(
            "admin.servers.edit_name",
            "✏️ Редактирование названия сервера\n\nТекущее название: <b>{name}</b>\n\nВведите новое название (или /skip чтобы оставить текущее):",
            name=server.name,
        ),
        reply_markup=get_back_keyboard(f"server_select_{server_id}"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(ServerManagement.waiting_for_edit_name)
async def process_edit_name(message: TgMessage, state: FSMContext) -> None:
    """Process server name edit."""
    data = await state.get_data()
    server_id = data["server_id"]
    new_name = message.text.strip()

    if new_name == "/skip":
        await show_server_details(message, state, server_id)
        return

    if not new_name:
        await message.answer(
            t("admin.servers.errors.empty_name", "❌ Название не может быть пустым.")
        )
        return

    if len(new_name) > 100:
        await message.answer(
            t("admin.servers.errors.name_too_long", "❌ Название не должно превышать 100 символов.")
        )
        return

    async with async_session_factory() as session:
        service = XUIService(session)
        server = await service.update_server(server_id, name=new_name)
        if server:
            await session.commit()
            await message.answer(
                t("admin.servers.name_changed", "✅ Название изменено на: {name}", name=new_name)
            )
            await edit_server_menu(message, state, server_id)


@router.callback_query(F.data == "edit_server_ip")
async def start_edit_ip_address(callback: CallbackQuery, state: FSMContext) -> None:
    """Start editing server IP address."""
    data = await state.get_data()
    server_id = data["server_id"]

    async with async_session_factory() as session:
        service = XUIService(session)
        server = await service.get_server_by_id(server_id)

    if not server:
        await callback.answer(
            t("admin.servers.errors.not_found", "❌ Сервер не найден."), show_alert=True
        )
        return

    await state.set_state(ServerManagement.waiting_for_edit_ip_address)
    await callback.message.edit_text(
        t(
            "admin.servers.edit_ip",
            "✏️ Редактирование IP-адреса сервера\n\nТекущий IP: <b>{ip}</b>\n\nВведите новый IP-адрес (или /skip чтобы оставить текущий):",
            ip=server.ip_address or "Не указан",
        ),
        reply_markup=get_back_keyboard(f"server_select_{server_id}"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(ServerManagement.waiting_for_edit_ip_address)
async def process_edit_ip_address(message: TgMessage, state: FSMContext) -> None:
    """Process server IP edit."""
    data = await state.get_data()
    server_id = data["server_id"]
    new_ip = message.text.strip()

    if new_ip == "/skip":
        await show_server_details(message, state, server_id)
        return

    if not new_ip:
        await message.answer(
            t("admin.servers.errors.empty_ip", "❌ IP-адрес не может быть пустым.")
        )
        return

    async with async_session_factory() as session:
        service = XUIService(session)
        server = await service.update_server(server_id, ip_address=new_ip)
        if server:
            await session.commit()
            await message.answer(
                t("admin.servers.ip_changed", "✅ IP-адрес изменен на: {ip}", ip=new_ip)
            )

    await edit_server_menu(message, state, server_id)


async def edit_server_menu(message: TgMessage, state: FSMContext, server_id: int) -> None:
    """Return to server edit menu."""
    data = await state.get_data()
    data["server_id"] = server_id
    await state.update_data(data)

    async with async_session_factory() as session:
        service = XUIService(session)
        server = await service.get_server_by_id(server_id)

    if not server:
        await message.answer(t("admin.servers.errors.not_found", "❌ Сервер не найден."))
        return

    builder = []
    builder.append(
        {
            "text": t("admin.servers.buttons.edit_name", "✏️ Название"),
            "callback_data": "edit_server_name",
        }
    )
    builder.append(
        {
            "text": t("admin.servers.buttons.edit_ip", "🌐 IP-адрес"),
            "callback_data": "edit_server_ip",
        }
    )
    builder.append(
        {
            "text": t("admin.servers.buttons.back", "🔙 Назад"),
            "callback_data": f"server_select_{server_id}",
        }
    )

    from aiogram.utils.keyboard import InlineKeyboardBuilder

    kb = InlineKeyboardBuilder()
    for btn in builder:
        kb.button(**btn)
    kb.adjust(1)

    text = t(
        "admin.servers.edit_menu_new",
        "✏️ Редактирование сервера: <b>{name}</b>\n\n🌐 IP-адрес: {ip}\n\nВыберите поле для редактирования:",
        name=server.name,
        ip=server.ip_address,
    )

    await message.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")


async def show_server_details(message: TgMessage, state: FSMContext, server_id: int) -> None:
    """Show server details via message."""
    data = await state.get_data()
    data["server_id"] = server_id
    await state.update_data(data)

    async with async_session_factory() as session:
        service = XUIService(session)
        server = await service.get_server_by_id(server_id)

    if not server:
        await message.answer(t("admin.servers.errors.not_found", "❌ Сервер не найден."))
        return

    status = (
        t("admin.servers.status.active", "✅ Активен")
        if server.is_online
        else t("admin.servers.status.inactive", "❌ Неактивен")
    )
    last_sync = (
        server.last_sync_at.strftime("%d.%m.%Y %H:%M")
        if hasattr(server, "last_sync_at") and server.last_sync_at
        else t("admin.servers.sync.never", "Никогда")
    )

    ip_info = f"\n🌐 IP: {server.ip_address}" if server.ip_address else ""

    text = t(
        "admin.servers.info_new",
        "🖥️ Сервер: {name}{ip_info}\n📊 Статус: {status}\n🔄 Последняя синхронизация: {last_sync}",
        name=server.name,
        ip_info=ip_info,
        status=status,
        last_sync=last_sync,
    )

    builder = []
    builder.append(
        {
            "text": t("admin.servers.buttons.edit", "✏️ Редактировать"),
            "callback_data": f"server_edit_{server_id}",
        }
    )
    builder.append(
        {
            "text": t("admin.servers.buttons.ssh_setup", "🔑 Настроить SSH"),
            "callback_data": f"server_setup_ssh_{server_id}",
        }
    )
    builder.append(
        {
            "text": t("admin.servers.buttons.manage_services", "⚙️ Управление сервисами"),
            "callback_data": f"server_services_{server_id}",
        }
    )
    builder.append(
        {
            "text": t("admin.servers.buttons.inbounds", "📊 Inbounds"),
            "callback_data": f"server_inbounds_{server_id}",
        }
    )
    builder.append(
        {
            "text": t("admin.servers.buttons.sync", "🔄 Синхронизировать"),
            "callback_data": f"server_sync_{server_id}",
        }
    )
    builder.append(
        {
            "text": t("admin.servers.buttons.test_connection", "🔌 Проверить подключение"),
            "callback_data": f"server_test_{server_id}",
        }
    )
    builder.append(
        {
            "text": t("admin.servers.buttons.delete", "🗑️ Удалить"),
            "callback_data": f"server_delete_{server_id}",
        }
    )
    builder.append(
        {"text": t("admin.servers.buttons.back", "🔙 Назад"), "callback_data": "admin_servers"}
    )

    from aiogram.utils.keyboard import InlineKeyboardBuilder

    kb = InlineKeyboardBuilder()
    for btn in builder:
        kb.button(**btn)
    kb.adjust(1)

    await message.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")


@router.callback_query(F.data.startswith("server_setup_ssh_"))
async def start_ssh_setup(callback: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    """Start SSH setup for a server."""
    if not is_admin:
        await callback.answer(
            t("admin.errors.no_rights", "❌ У вас нет прав администратора."), show_alert=True
        )
        return

    server_id = int(callback.data.split("_")[-1])
    await state.update_data(server_id=server_id)

    await state.set_state(ServerManagement.waiting_for_ssh_user)
    await callback.message.edit_text(
        t(
            "admin.servers.ssh_user",
            "🔑 Настройка SSH\n\nВведите имя пользователя SSH (по умолчанию: root):",
        ),
        reply_markup=get_back_keyboard(f"server_select_{server_id}"),
    )
    await callback.answer()


@router.message(ServerManagement.waiting_for_ssh_user)
async def process_ssh_user(message: TgMessage, state: FSMContext) -> None:
    """Process SSH user input."""
    ssh_user = message.text.strip()
    if not ssh_user or ssh_user.startswith("/"):
        ssh_user = "root"

    await state.update_data(ssh_user=ssh_user)
    data = await state.get_data()
    server_id = data["server_id"]

    await state.set_state(ServerManagement.waiting_for_ssh_port)
    await message.answer(
        t(
            "admin.servers.ssh_port",
            "Введите порт SSH (по умолчанию: 22):",
        ),
        reply_markup=get_back_keyboard(f"server_select_{server_id}"),
    )


@router.message(ServerManagement.waiting_for_ssh_port)
async def process_ssh_port(message: TgMessage, state: FSMContext) -> None:
    """Process SSH port input."""
    port_text = message.text.strip()
    if not port_text or port_text.startswith("/"):
        ssh_port = 22
    else:
        try:
            ssh_port = int(port_text)
            if not 1 <= ssh_port <= 65535:
                raise ValueError()
        except ValueError:
            data = await state.get_data()
            server_id = data["server_id"]
            await message.answer(
                t(
                    "admin.servers.errors.invalid_port",
                    "❌ Некорректный порт. Введите число от 1 до 65535:",
                ),
                reply_markup=get_back_keyboard(f"server_select_{server_id}"),
            )
            return

    await state.update_data(ssh_port=ssh_port)
    data = await state.get_data()
    server_id = data["server_id"]

    await state.set_state(ServerManagement.waiting_for_ssh_auth)
    await message.answer(
        t(
            "admin.servers.ssh_auth",
            "Введите пароль или приватный SSH ключ (начинается с -----BEGIN):",
        ),
        reply_markup=get_back_keyboard(f"server_select_{server_id}"),
    )


@router.message(ServerManagement.waiting_for_ssh_auth)
async def process_ssh_auth(message: TgMessage, state: FSMContext) -> None:
    """Process SSH auth input (password or key)."""
    try:
        await message.delete()
    except Exception as e:
        logger.warning(f"Could not delete message: {e}")
        await message.answer(
            "⚠️ В целях безопасности, пожалуйста, удалите свое сообщение с паролем/ключом вручную."
        )

    auth_data = message.text.strip()
    is_key = auth_data.startswith("-----BEGIN")

    ssh_password = None
    ssh_key = None
    if is_key:
        ssh_key = auth_data
    else:
        ssh_password = auth_data

    data = await state.get_data()
    server_id = data["server_id"]
    ssh_user = data["ssh_user"]
    ssh_port = data["ssh_port"]

    status_msg = await message.answer(
        t("admin.servers.ssh_testing", "🔄 Проверка SSH подключения...")
    )

    async with async_session_factory() as session:
        service = XUIService(session)
        server = await service.get_server_by_id(server_id)

        if not server:
            await status_msg.edit_text(
                t("admin.servers.errors.not_found", "❌ Сервер не найден."),
                reply_markup=get_back_keyboard("admin_servers"),
            )
            return

        from app.database.models import Server
        from app.services.ssh_service import SSHManager

        dummy_server = Server(
            ip_address=server.ip_address,
            ssh_port=ssh_port,
            ssh_user=ssh_user,
        )
        manager = SSHManager(dummy_server)

        success = await manager.test_connection(password=ssh_password, key=ssh_key)

        if not success:
            await status_msg.edit_text(
                t(
                    "admin.servers.ssh_test_failed",
                    "❌ Ошибка подключения по SSH. Проверьте данные и попробуйте снова.\nОтправьте пароль/ключ еще раз:",
                ),
                reply_markup=get_back_keyboard(f"server_select_{server_id}"),
            )
            return

        await service.update_server(
            server_id,
            ssh_user=ssh_user,
            ssh_port=ssh_port,
            ssh_password=ssh_password,
            ssh_key=ssh_key,
        )
        await session.commit()

    await state.clear()
    await status_msg.delete()
    await message.answer(t("admin.servers.ssh_success", "✅ SSH успешно настроен и проверен!"))
    await show_server_details(message, state, server_id)


@router.callback_query(F.data.startswith("server_services_"))
async def show_server_services(callback: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    """Show services installed on the server."""
    if not is_admin:
        await callback.answer(
            t("admin.errors.no_rights", "❌ У вас нет прав администратора."), show_alert=True
        )
        return

    server_id = int(callback.data.split("_")[-1])

    async with async_session_factory() as session:
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        from app.database.models import Server

        result = await session.execute(
            select(Server)
            .options(
                selectinload(Server.xui_panel),
                selectinload(Server.awg_service),
                selectinload(Server.mtproxy_service),
            )
            .where(Server.id == server_id)
        )
        server = result.scalar_one_or_none()

    if not server:
        await callback.answer(
            t("admin.servers.errors.not_found", "❌ Сервер не найден."), show_alert=True
        )
        return

    text = t(
        "admin.servers.services.title",
        "⚙️ Управление сервисами сервера: <b>{name}</b>\n\n",
        name=server.name,
    )

    from aiogram.utils.keyboard import InlineKeyboardBuilder

    kb = InlineKeyboardBuilder()

    # 3x-ui
    if server.xui_panel:
        text += "✅ <b>3x-ui</b>: Установлен\n"
        kb.button(
            text=t("admin.servers.services.edit_xui", "✏️ 3x-ui"),
            callback_data=f"server_edit_xui_{server_id}",
        )
    else:
        text += "❌ <b>3x-ui</b>: Не установлен\n"
        kb.button(
            text=t("admin.servers.services.install_xui", "➕ Добавить 3x-ui"),
            callback_data=f"server_install_xui_{server_id}",
        )

    # AmneziaWG
    if server.awg_service:
        text += "✅ <b>AmneziaWG</b>: Установлен\n"
        kb.button(
            text=t("admin.servers.services.edit_awg", "✏️ AmneziaWG"),
            callback_data=f"server_edit_awg_{server_id}",
        )
    else:
        text += "❌ <b>AmneziaWG</b>: Не установлен\n"
        kb.button(
            text=t("admin.servers.services.install_awg", "➕ Добавить AmneziaWG"),
            callback_data=f"server_install_awg_{server_id}",
        )

    # MTProxy
    if server.mtproxy_service:
        text += "✅ <b>MTProxy</b>: Установлен\n"
        kb.button(
            text=t("admin.servers.services.edit_mtproxy", "✏️ MTProxy"),
            callback_data=f"server_edit_mtproxy_{server_id}",
        )
    else:
        text += "❌ <b>MTProxy</b>: Не установлен\n"
        kb.button(
            text=t("admin.servers.services.install_mtproxy", "➕ Добавить MTProxy"),
            callback_data=f"server_install_mtproxy_{server_id}",
        )

    text += "\nВы можете запустить автообнаружение сервисов через SSH."

    kb.button(
        text=t("admin.servers.services.autodiscover", "🔍 Автообнаружение сервисов"),
        callback_data=f"server_autodiscover_{server_id}",
    )
    kb.button(
        text=t("admin.servers.buttons.back", "🔙 Назад"), callback_data=f"server_select_{server_id}"
    )

    kb.adjust(1)

    await callback.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("server_autodiscover_"))
async def run_server_autodiscover(
    callback: CallbackQuery, state: FSMContext, is_admin: bool
) -> None:
    """Run AutoDiscoveryService over SSH."""
    if not is_admin:
        await callback.answer(
            t("admin.errors.no_rights", "❌ У вас нет прав администратора."), show_alert=True
        )
        return

    server_id = int(callback.data.split("_")[-1])

    await callback.message.edit_text(
        t(
            "admin.servers.services.autodiscovering",
            "🔍 Запущено автообнаружение сервисов по SSH...\nПожалуйста, подождите.",
        ),
        reply_markup=None,
    )

    async with async_session_factory() as session:
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        from app.database.models import Server
        from app.database.models.services import AWGService, MTProxyService, XUIPanel

        result = await session.execute(
            select(Server)
            .options(
                selectinload(Server.xui_panel),
                selectinload(Server.awg_service),
                selectinload(Server.mtproxy_service),
            )
            .where(Server.id == server_id)
        )
        server = result.scalar_one_or_none()

        if not server:
            await callback.answer(
                t("admin.servers.errors.not_found", "❌ Сервер не найден."), show_alert=True
            )
            return

        if not server.ssh_user:
            await callback.message.edit_text(
                t(
                    "admin.servers.services.ssh_not_configured",
                    "❌ SSH не настроен для этого сервера. Сначала настройте SSH.",
                ),
                reply_markup=get_back_keyboard(f"server_select_{server_id}"),
            )
            return

        from app.services.auto_discovery import AutoDiscoveryService

        discovery = AutoDiscoveryService(server)

        try:
            discovered = await discovery.discover_all()
        except Exception as e:
            logger.error(f"Discovery error on server {server_id}: {e}", exc_info=True)
            await callback.message.edit_text(
                t(
                    "admin.servers.services.discovery_error",
                    "❌ Ошибка при выполнении автообнаружения: {error}",
                    error=str(e),
                ),
                reply_markup=get_back_keyboard(f"server_services_{server_id}"),
            )
            return

        discovered_list = []
        if "3x-ui" in discovered:
            if not server.xui_panel:
                details = discovered["3x-ui"]
                panel = XUIPanel(
                    server_id=server.id,
                    username=details.get("username"),
                    panel_path=details.get("base_path"),
                    subscription_path=details.get("sub_path"),
                )
                session.add(panel)
                discovered_list.append("3x-ui")
            else:
                discovered_list.append("3x-ui (уже был)")

        if "amnezia-awg" in discovered:
            if not server.awg_service:
                awg = AWGService(server_id=server.id)
                session.add(awg)
                discovered_list.append("AmneziaWG")
            else:
                discovered_list.append("AmneziaWG (уже был)")

        if "mtproxy" in discovered:
            if not server.mtproxy_service:
                mtproxy = MTProxyService(server_id=server.id)
                session.add(mtproxy)
                discovered_list.append("MTProxy")
            else:
                discovered_list.append("MTProxy (уже был)")

        if discovered_list:
            await session.commit()
            msg = t(
                "admin.servers.services.discovery_success",
                "✅ Автообнаружение завершено. Найдено:\n- {items}",
                items="\n- ".join(discovered_list),
            )
        else:
            msg = t(
                "admin.servers.services.discovery_empty",
                "❌ Никаких известных сервисов не найдено.",
            )

    from aiogram.utils.keyboard import InlineKeyboardBuilder

    kb = InlineKeyboardBuilder()
    kb.button(
        text=t("admin.servers.buttons.back", "🔙 Назад"),
        callback_data=f"server_services_{server_id}",
    )

    await callback.message.edit_text(msg, reply_markup=kb.as_markup())
    await callback.answer()
