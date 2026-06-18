"""Общие для модулей серверов хелперы рендера."""

from aiogram.fsm.context import FSMContext
from aiogram.types import Message as TgMessage

from app.database import async_session_factory
from app.services.xui_service import XUIService
from app.utils.texts import t


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

    from app.services.server_monitor import ServerMonitor
    is_online = await ServerMonitor.check_server_status(server_id)

    status = (
        t("admin.servers.status.active", "✅ Активен")
        if server.is_active
        else t("admin.servers.status.inactive", "❌ Неактивен")
    )
    online_status = (
        t("admin.servers.status.online", "✅ В сети")
        if is_online
        else t("admin.servers.status.offline", "❌ Офлайн")
    )
    last_sync = (
        server.last_sync_at.strftime("%d.%m.%Y %H:%M")
        if hasattr(server, "last_sync_at") and server.last_sync_at
        else t("admin.servers.sync.never", "Никогда")
    )

    ip_info = f"\n🌐 IP: {server.ip_address}" if server.ip_address else ""

    text = t(
        "admin.servers.info_new",
        "🖥️ Сервер: {name}{ip_info}\n📊 Статус: {status}\n🌐 Доступность: {online_status}\n🔄 Последняя синхронизация: {last_sync}",
        name=server.name,
        ip_info=ip_info,
        status=status,
        online_status=online_status,
        last_sync=last_sync,
    )

    builder = []
    builder.append(
        {
            "text": t("admin.servers.buttons.edit", "✏️ Редактировать"),
            "callback_data": f"server_edit_main_{server_id}",
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
