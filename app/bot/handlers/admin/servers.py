"""Admin server management handlers."""

import contextlib

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
from app.bot.states import AWGInstall, FirstSetup, MTProxyInstall, ServerManagement, XUIInstall
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

    text = t(
        "admin.servers.add_success",
        "✅ Сервер <b>{name}</b> успешно добавлен!\n\n🌐 IP: <code>{ip}</code>\n\nТеперь вы можете настроить SSH и установить необходимые сервисы.",
        name=name,
        ip=ip_address,
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

    await callback.answer(
        t("admin.servers.sync_started", "🔄 Синхронизация запущена..."),
        show_alert=False,
    )

    async with async_session_factory() as session:
        from app.services import SyncService

        sync_service = SyncService(session)
        try:
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
                result = await sync_service.sync_server(server, force=True)
                await session.commit()
                if result:
                    await callback.message.answer(
                        "✅ Синхронизация завершена! Inbounds и клиенты синхронизированы",
                    )
                else:
                    await callback.message.answer(
                        "⚠️ Синхронизация завершена с ошибкой. Проверьте статус сервера.",
                    )
            else:
                await callback.message.answer(
                    t("admin.servers.errors.not_found", "❌ Сервер не найден")
                )
        except Exception as e:
            logger.error("Error syncing server {}: {}", server_id, e, exc_info=True)
            with contextlib.suppress(Exception):
                await callback.message.answer(
                    f"❌ Ошибка при синхронизации: {str(e)[:200]}",
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

        from aiogram.utils.keyboard import InlineKeyboardBuilder

        text = t(
            "admin.servers.inbounds.title",
            "📊 Inbounds сервера <b>{name}</b>\n\n",
            name=server.name,
        )

        for ib in inbounds:
            status = "✅" if ib.is_active else "❌"
            line = f"{status} <b>{ib.remark}</b> ({ib.protocol})"
            if ib.port:
                line += f"\n   Порт: {ib.port}"
            if hasattr(ib, "client_count"):
                line += f"\n   Клиентов: {ib.client_count}"
            text += line + "\n\n"

        kb = InlineKeyboardBuilder()
        kb.button(
            text=t("admin.servers.buttons.stats", "📊 Статистика"),
            callback_data=f"inbound_stats_{server_id}",
        )
        kb.button(
            text=t("admin.servers.buttons.cleanup_inbounds", "🧹 Очистить неактивные"),
            callback_data=f"cleanup_inbounds_{server_id}",
        )
        kb.button(
            text=t("admin.servers.buttons.sync", "🔄 Синхронизировать"),
            callback_data=f"server_sync_{server_id}",
        )
        kb.button(
            text=t("admin.servers.buttons.back", "🔙 Назад"),
            callback_data=f"server_select_{server_id}",
        )
        kb.adjust(1)

        await callback.message.edit_text(
            text,
            reply_markup=kb.as_markup(),
            parse_mode="HTML",
        )
        await callback.answer()


# ── 3x-ui Installation Flow ────────────────────────────────────────────


@router.callback_query(F.data.startswith("server_install_xui_"))
async def start_xui_install(callback: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    """Start 3x-ui installation: check SSH, then ask for domain."""
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
            .options(selectinload(Server.xui_panel))
            .where(Server.id == server_id)
        )
        server = result.scalar_one_or_none()

    if not server:
        await callback.answer(
            t("admin.servers.errors.not_found", "❌ Сервер не найден."), show_alert=True
        )
        return

    if server.xui_panel:
        await callback.answer("3x-ui уже установлен на этом сервере.", show_alert=True)
        return

    if not server.ssh_user:
        await callback.message.edit_text(
            t(
                "admin.servers.services.ssh_not_configured",
                "❌ SSH не настроен для этого сервера. Сначала настройте SSH.",
            ),
            reply_markup=get_back_keyboard(f"server_services_{server_id}"),
        )
        return

    status_msg = await callback.message.edit_text(
        "🔄 Проверяю доступность сервера и SSH-подключение..."
    )

    from app.services.installers.xui_installer import XUIInstaller
    from app.services.ssh_service import SSHManager

    ssh = SSHManager(server)
    installer = XUIInstaller(ssh)
    ok, msg = await installer.preflight_check()

    if not ok:
        await status_msg.edit_text(
            f"❌ <b>Предварительная проверка не пройдена</b>\n\n{msg}",
            reply_markup=get_back_keyboard(f"server_services_{server_id}"),
            parse_mode="HTML",
        )
        return

    if await installer.check_already_installed():
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

        await status_msg.edit_text(
            "🔍 <b>3x-ui уже установлен на этом сервере</b>\n\n"
            "Обнаружен контейнер <code>vpnbot-xui</code> или <code>vpnbot-caddy</code>.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="🔌 Подключить",
                    callback_data=f"xui_connect_existing_{server_id}",
                )],
                [InlineKeyboardButton(
                    text="🔄 Переустановить",
                    callback_data=f"xui_reinstall_{server_id}",
                )],
                [InlineKeyboardButton(
                    text="🔙 Назад",
                    callback_data=f"server_services_{server_id}",
                )],
            ]),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    await state.update_data(server_id=server_id)

    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    await status_msg.edit_text(
        "🌐 <b>3x-ui не найден на сервере</b>\n\n"
        "Выберите способ добавления:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="📦 Установить новую",
                callback_data=f"xui_install_new_{server_id}",
            )],
            [InlineKeyboardButton(
                text="🔌 Подключить существующую",
                callback_data=f"xui_connect_existing_{server_id}",
            )],
            [InlineKeyboardButton(
                text="🔙 Назад",
                callback_data=f"server_services_{server_id}",
            )],
        ]),
        parse_mode="HTML",
    )
    await callback.answer()
    return


@router.callback_query(F.data.startswith("xui_install_new_"))
async def xui_install_new(callback: CallbackQuery, state: FSMContext) -> None:
    """Start fresh 3x-ui installation."""
    server_id = int(callback.data.split("_")[-1])
    await state.update_data(server_id=server_id)

    policy_shown = await _check_first_setup(callback, state, server_id, "xui")
    if policy_shown:
        await callback.answer()
        return

    await _xui_ask_domain(callback.message, state)
    await callback.answer()


@router.callback_query(F.data.startswith("xui_connect_existing_"))
async def xui_connect_existing(callback: CallbackQuery, state: FSMContext) -> None:
    """Connect existing 3x-ui — auto-discover params, ask password choice, save to DB."""
    server_id = int(callback.data.split("_")[-1])

    msg = await callback.message.edit_text(
        "🔍 <b>Читаю конфигурацию 3x-ui с сервера...</b>",
        parse_mode="HTML",
    )
    await callback.answer()

    try:
        from app.services.installers.xui_installer import XUIInstaller
        from app.services.ssh_service import SSHManager

        async with async_session_factory() as session:
            from sqlalchemy import select

            from app.database.models import Server

            server = (await session.execute(
                select(Server).where(Server.id == server_id)
            )).scalar_one()

        ssh = SSHManager(server)
        installer = XUIInstaller(ssh)
        
        ok, err_msg = await installer.preflight_check()
        if not ok:
            await msg.edit_text(f"❌ Ошибка проверки прав SSH:\n<code>{err_msg}</code>", reply_markup=get_back_keyboard(f"server_services_{server_id}"), parse_mode="HTML")
            return
            
        params = await installer.discover_existing()
    except Exception as e:
        logger.error(f"XUI discover failed: {e}", exc_info=True)
        await msg.edit_text(
            f"❌ <b>Не удалось прочитать конфигурацию</b>\n\n<code>{e}</code>",
            reply_markup=get_back_keyboard(f"server_services_{server_id}"),
            parse_mode="HTML",
        )
        return

    await state.update_data(
        server_id=server_id,
        connect_existing=True,
        domain=params["domain"],
        caddy_port=params["caddy_port"],
        web_path=params["web_path"],
        sub_path=params["sub_path"],
        sub_json_path=params["sub_json_path"],
        username=params["username"],
    )

    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    await msg.edit_text(
        "🌐 <b>3x-ui найден!</b> Параметры из сервера:\n\n"
        f"Домен: <code>{params['domain']}</code>\n"
        f"Порт: <code>{params['caddy_port']}</code>\n"
        f"Web path: <code>{params['web_path']}</code>\n"
        f"Sub path: <code>{params['sub_path']}</code>\n"
        f"Sub JSON path: <code>{params['sub_json_path']}</code>\n"
        f"Логин: <code>{params['username']}</code>\n\n"
        "Пароль хранится как bcrypt-хеш — восстановить нельзя.\n"
        "Выберите способ:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="🔑 Сгенерировать новый пароль",
                callback_data="xui_connect_gen_password",
            )],
            [InlineKeyboardButton(
                text="✏️ Я помню пароль",
                callback_data="xui_connect_enter_password",
            )],
            [InlineKeyboardButton(
                text="🔙 Отмена",
                callback_data=f"server_services_{server_id}",
            )],
        ]),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "xui_connect_gen_password")
async def xui_connect_gen_password(callback: CallbackQuery, state: FSMContext) -> None:
    """Generate new password, set it in 3x-ui DB, save everything."""
    from app.services.installers.base import BaseInstaller

    new_password = BaseInstaller.generate_random_string(16)

    data = await state.get_data()
    server_id = data["server_id"]
    domain = data["domain"]
    caddy_port = data["caddy_port"]
    web_path = data["web_path"]
    sub_path = data["sub_path"]
    sub_json_path = data["sub_json_path"]
    username = data["username"]
    await state.clear()

    msg = await callback.message.edit_text(
        "🔑 <b>Установка нового пароля в 3x-ui...</b>",
        parse_mode="HTML",
    )
    await callback.answer()

    try:
        from app.services.installers.xui_installer import XUIInstaller
        from app.services.ssh_service import SSHManager

        async with async_session_factory() as session:
            from sqlalchemy import select

            from app.database.models import Server

            server = (await session.execute(
                select(Server).where(Server.id == server_id)
            )).scalar_one()

        ssh = SSHManager(server)
        installer = XUIInstaller(ssh)

        hashed = XUIInstaller._hash_password_bcrypt(new_password)
        sql = (
            f"UPDATE users SET password='{hashed}' WHERE id=1"
        )
        await installer._cmd(
            "docker exec -i vpnbot-xui apk add --no-cache sqlite 2>/dev/null || true"
        )
        await installer._cmd(
            "docker exec -i vpnbot-xui sqlite3 /etc/x-ui/x-ui.db",
            input_data=sql,
        )
        await installer._cmd("docker restart vpnbot-xui")
        await installer._cmd("sleep 3")

        from app.database.models.services import XUIPanel

        async with async_session_factory() as session:
            result = await session.execute(
                select(Server)
                .where(Server.id == server_id)
            )
            server = result.scalar_one()

            from app.utils import encrypt_password

            encrypted_pwd = encrypt_password(new_password)
            panel_url = f"https://{domain}:{caddy_port}"
            existing = await session.execute(
                select(XUIPanel).where(XUIPanel.server_id == server.id)
            )
            existing_panel = existing.scalar_one_or_none()
            if existing_panel:
                existing_panel.url = panel_url
                existing_panel.username = username
                existing_panel.password_encrypted = encrypted_pwd
                existing_panel.panel_path = web_path
                existing_panel.subscription_path = sub_path
                existing_panel.subscription_json_path = sub_json_path
                existing_panel.caddy_port = caddy_port
            else:
                panel = XUIPanel(
                    server_id=server.id,
                    url=panel_url,
                    username=username,
                    password_encrypted=encrypted_pwd,
                    panel_path=web_path,
                    subscription_path=sub_path,
                    subscription_json_path=sub_json_path,
                    caddy_port=caddy_port,
                    verify_ssl=False,
                )
                session.add(panel)
            await session.commit()

        clean_web = web_path.strip("/")
        panel_full_url = f"{panel_url}/{clean_web}/" if clean_web else f"{panel_url}/"
        await msg.edit_text(
            "✅ <b>3x-ui подключён!</b>\n\n"
            f"Панель: <code>{panel_full_url}</code>\n"
            f"Логин: <code>{username}</code>\n"
            f"Пароль: <code>{new_password}</code>\n\n"
            "⚠️ <b>Сохраните пароль!</b> Он больше не будет показан.\n\n"
            "Выполните синхронизацию для загрузки inbounds.",
            reply_markup=get_back_keyboard(f"server_services_{server_id}"),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"XUI connect (gen password) failed: {e}", exc_info=True)
        await msg.edit_text(
            f"❌ <b>Ошибка подключения</b>\n\n<code>{e}</code>",
            reply_markup=get_back_keyboard(f"server_services_{server_id}"),
            parse_mode="HTML",
        )


@router.callback_query(F.data == "xui_connect_enter_password")
async def xui_connect_enter_password(callback: CallbackQuery, state: FSMContext) -> None:
    """Ask admin to enter the existing password."""
    await state.set_state(XUIInstall.waiting_for_password)
    await callback.message.edit_text(
        "🔑 Введите <b>пароль</b> администратора 3x-ui:",
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("xui_reinstall_"))
async def xui_reinstall(callback: CallbackQuery, state: FSMContext) -> None:
    """Start 3x-ui reinstallation flow (force=True)."""
    server_id = int(callback.data.split("_")[-1])
    await state.update_data(server_id=server_id, force_reinstall=True)
    await _xui_ask_domain(callback.message, state)
    await callback.answer()


@router.message(XUIInstall.waiting_for_domain)
async def xui_process_domain(message: TgMessage, state: FSMContext) -> None:
    """Process domain/IP input."""
    domain = message.text.strip()

    if not domain or len(domain) > 253:
        await message.answer("❌ Введите корректный домен или IP.")
        return

    await state.update_data(domain=domain)
    await state.set_state(XUIInstall.waiting_for_caddy_port)

    from aiogram.utils.keyboard import InlineKeyboardBuilder

    kb = InlineKeyboardBuilder()
    kb.button(text="🎲 Авто (8443)", callback_data="xui_port_auto")
    kb.button(text="🔙 Отмена", callback_data="cancel")
    kb.adjust(1)

    await message.answer(
        f"🌐 Домен: <code>{domain}</code>\n\n"
        "Введите HTTPS-порт для Caddy (дефолт: <code>8443</code>):",
        reply_markup=kb.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(XUIInstall.waiting_for_caddy_port, F.data == "xui_port_auto")
async def xui_caddy_port_auto(callback: CallbackQuery, state: FSMContext) -> None:
    """Auto-assign Caddy port."""
    await state.update_data(caddy_port=8443)
    await _xui_ask_paths_mode(callback.message, state)


@router.message(XUIInstall.waiting_for_caddy_port)
async def xui_caddy_port_manual(message: TgMessage, state: FSMContext) -> None:
    """Process manually entered Caddy port."""
    text = message.text.strip()
    if not text.isdigit() or int(text) < 1 or int(text) > 65535:
        await message.answer("❌ Введите число от 1 до 65535.")
        return
    await state.update_data(caddy_port=int(text))
    await _xui_ask_paths_mode(message, state)


async def _xui_ask_paths_mode(message_or_callback, state: FSMContext) -> None:
    """Ask Quick/Advanced for paths."""
    await state.set_state(XUIInstall.waiting_for_paths_mode)

    from aiogram.utils.keyboard import InlineKeyboardBuilder

    kb = InlineKeyboardBuilder()
    kb.button(text="⚡ Авто (случайные пути)", callback_data="xui_paths_auto")
    kb.button(text="🔧 Вручную", callback_data="xui_paths_manual")
    kb.button(text="🔙 Отмена", callback_data="cancel")
    kb.adjust(1)

    target = message_or_callback if isinstance(message_or_callback, TgMessage) else message_or_callback.message
    await target.edit_text(
        "📝 <b>Пути панели</b>\n\n"
        "⚡ <b>Авто</b> — генерируются случайные пути\n"
        "🔧 <b>Вручную</b> — задать webBasePath, subPath, subJsonPath",
        reply_markup=kb.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(XUIInstall.waiting_for_paths_mode, F.data == "xui_paths_auto")
async def xui_paths_auto(callback: CallbackQuery, state: FSMContext) -> None:
    """Auto-generate random paths."""
    from app.services.installers.base import BaseInstaller

    r = BaseInstaller.generate_random_string
    await state.update_data(
        web_path=f"/{r(8)}/",
        sub_path=f"/{r(6)}/",
        sub_json_path=f"/{r(6)}/",
    )
    await _xui_ask_auth_mode(callback.message, state)


@router.callback_query(XUIInstall.waiting_for_paths_mode, F.data == "xui_paths_manual")
async def xui_paths_manual_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Ask for webBasePath manually."""
    await state.set_state(XUIInstall.waiting_for_web_path)
    await callback.message.edit_text(
        "📝 Введите <b>webBasePath</b> — путь к панели (например, <code>/admin-xyz/</code>):",
        reply_markup=get_back_keyboard("cancel"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(XUIInstall.waiting_for_web_path)
async def xui_web_path(message: TgMessage, state: FSMContext) -> None:
    path = message.text.strip()
    if not path.startswith("/"):
        path = "/" + path
    if not path.endswith("/"):
        path += "/"
    await state.update_data(web_path=path)
    await state.set_state(XUIInstall.waiting_for_sub_path)
    await message.answer(
        f"✅ webBasePath: <code>{path}</code>\n\n"
        "Введите <b>subPath</b> — путь подписки (например, <code>/sub-abc/</code>):",
        reply_markup=get_back_keyboard("cancel"),
        parse_mode="HTML",
    )


@router.message(XUIInstall.waiting_for_sub_path)
async def xui_sub_path(message: TgMessage, state: FSMContext) -> None:
    path = message.text.strip()
    if not path.startswith("/"):
        path = "/" + path
    if not path.endswith("/"):
        path += "/"
    await state.update_data(sub_path=path)
    await state.set_state(XUIInstall.waiting_for_sub_json_path)
    await message.answer(
        f"✅ subPath: <code>{path}</code>\n\n"
        "Введите <b>subJsonPath</b> (например, <code>/json-def/</code>):",
        reply_markup=get_back_keyboard("cancel"),
        parse_mode="HTML",
    )


@router.message(XUIInstall.waiting_for_sub_json_path)
async def xui_sub_json_path(message: TgMessage, state: FSMContext) -> None:
    path = message.text.strip()
    if not path.startswith("/"):
        path = "/" + path
    if not path.endswith("/"):
        path += "/"
    await state.update_data(sub_json_path=path)
    await _xui_ask_auth_mode(message, state)


async def _xui_ask_auth_mode(message_or_callback, state: FSMContext) -> None:
    """Ask auth mode: API Token or Username+Password."""
    await state.set_state(XUIInstall.waiting_for_auth_mode)

    from aiogram.utils.keyboard import InlineKeyboardBuilder

    kb = InlineKeyboardBuilder()
    kb.button(text="👤 Логин и пароль", callback_data="xui_auth_credentials")
    kb.button(text="🔑 API Токен", callback_data="xui_auth_token")
    kb.button(text="🔙 Отмена", callback_data="cancel")
    kb.adjust(1)

    target = message_or_callback if isinstance(message_or_callback, TgMessage) else message_or_callback.message
    await target.edit_text(
        "🔐 <b>Способ авторизации</b>\n\n"
        "👤 <b>Логин и пароль</b> — бот создаст API-токен автоматически\n"
        "🔑 <b>API Токен</b> — вставьте готовый токен из панели 3x-ui\n\n"
        "<i>Токен можно получить в 3x-ui: Settings → Security → API Tokens</i>",
        reply_markup=kb.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(XUIInstall.waiting_for_auth_mode, F.data == "xui_auth_credentials")
async def xui_auth_credentials(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(auth_mode="credentials")
    await _xui_ask_credentials_mode(callback, state)


@router.callback_query(XUIInstall.waiting_for_auth_mode, F.data == "xui_auth_token")
async def xui_auth_token_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(XUIInstall.waiting_for_api_token)
    await callback.message.edit_text(
        "🔑 <b>Введите API-токен</b>\n\n"
        "Скопируйте токен из панели 3x-ui:\n"
        "<code>Settings → Security → API Tokens</code>\n\n"
        "Или создайте новый токен в панели.",
        reply_markup=get_back_keyboard("cancel"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(XUIInstall.waiting_for_api_token)
async def xui_api_token(message: TgMessage, state: FSMContext) -> None:
    token = message.text.strip()
    if not token or len(token) < 10:
        await message.answer("❌ Токен слишком короткий. Введите корректный API-токен.")
        return
    try:
        await message.delete()
    except Exception:
        pass

    data = await state.get_data()
    await state.update_data(
        auth_mode="token",
        api_token=token,
        username="",
        password="",
    )

    if data.get("connect_existing"):
        await state.update_data(inbound_ranges=[(10000, 10100)])
        await _xui_show_confirm(message, state)
    else:
        await _xui_ask_inbound_range(message, state)


async def _xui_ask_credentials_mode(message_or_callback, state: FSMContext) -> None:
    """Ask Quick/Advanced for credentials."""
    await state.set_state(XUIInstall.waiting_for_credentials_mode)

    from aiogram.utils.keyboard import InlineKeyboardBuilder

    kb = InlineKeyboardBuilder()
    kb.button(text="⚡ Авто (случайные)", callback_data="xui_cred_auto")
    kb.button(text="🔧 Вручную", callback_data="xui_cred_manual")
    kb.button(text="🔙 Отмена", callback_data="cancel")
    kb.adjust(1)

    target = message_or_callback if isinstance(message_or_callback, TgMessage) else message_or_callback.message
    await target.edit_text(
        "🔑 <b>Учётные данные панели</b>\n\n"
        "⚡ <b>Авто</b> — случайный логин и пароль\n"
        "🔧 <b>Вручную</b> — задать логин и пароль",
        reply_markup=kb.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(XUIInstall.waiting_for_credentials_mode, F.data == "xui_cred_auto")
async def xui_cred_auto(callback: CallbackQuery, state: FSMContext) -> None:
    from app.services.installers.base import BaseInstaller

    r = BaseInstaller.generate_random_string
    await state.update_data(
        username=f"admin-{r(6)}",
        password=r(20),
    )
    await _xui_ask_inbound_range(callback.message, state)


@router.callback_query(XUIInstall.waiting_for_credentials_mode, F.data == "xui_cred_manual")
async def xui_cred_manual_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(XUIInstall.waiting_for_username)
    await callback.message.edit_text(
        "🔑 Введите логин для панели 3x-ui:",
        reply_markup=get_back_keyboard("cancel"),
    )
    await callback.answer()


@router.message(XUIInstall.waiting_for_username)
async def xui_username(message: TgMessage, state: FSMContext) -> None:
    username = message.text.strip()
    if not username or len(username) > 50:
        await message.answer("❌ Логин не может быть пустым или длиннее 50 символов.")
        return
    await state.update_data(username=username)
    await state.set_state(XUIInstall.waiting_for_password)
    await message.answer("🔑 Введите пароль для панели 3x-ui:")


@router.message(XUIInstall.waiting_for_password)
async def xui_password(message: TgMessage, state: FSMContext) -> None:
    password = message.text.strip()
    if not password or len(password) < 6:
        await message.answer("❌ Пароль минимум 6 символов.")
        return

    data = await state.get_data()
    if data.get("connect_existing"):
        await state.update_data(password=password, inbound_ranges=[(10000, 10100)])
        await _xui_show_confirm(message, state)
    else:
        await state.update_data(password=password)
        await _xui_ask_inbound_range(message, state)


async def _xui_ask_inbound_range(message_or_callback, state: FSMContext) -> None:
    """Ask for inbound port range."""
    await state.set_state(XUIInstall.waiting_for_inbound_range)

    from aiogram.utils.keyboard import InlineKeyboardBuilder

    kb = InlineKeyboardBuilder()
    kb.button(text="🎲 Дефолт (10000-10100)", callback_data="xui_range_default")
    kb.button(text="🔙 Отмена", callback_data="cancel")
    kb.adjust(1)

    target = message_or_callback if isinstance(message_or_callback, TgMessage) else message_or_callback.message
    await target.edit_text(
        "📊 <b>Диапазон портов для inbounds</b>\n\n"
        "Введите порты для VPN-подключений.\n"
        "Формат: отдельные порты или диапазоны через запятую.\n"
        "Пример: <code>443, 10000-10100, 666</code>\n\n"
        "Или используйте дефолт: <code>10000-10100</code>",
        reply_markup=kb.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(XUIInstall.waiting_for_inbound_range, F.data == "xui_range_default")
async def xui_range_default(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(inbound_ranges=[(10000, 10100)])
    await _xui_show_confirm(callback.message, state)


@router.message(XUIInstall.waiting_for_inbound_range)
async def xui_range_manual(message: TgMessage, state: FSMContext) -> None:
    from app.services.installers.xui_installer import _parse_port_ranges

    try:
        ranges = _parse_port_ranges(message.text.strip())
    except ValueError as e:
        await message.answer(f"❌ Ошибка: {e}\nПопробуйте снова.")
        return

    total = sum(end - start + 1 for start, end in ranges)
    if total > 1000:
        await message.answer(f"❌ Слишком много портов ({total}). Максимум 1000.")
        return

    await state.update_data(inbound_ranges=ranges)
    await _xui_show_confirm(message, state)


async def _xui_show_confirm(message_or_callback, state: FSMContext) -> None:
    """Show confirmation with all parameters."""
    data = await state.get_data()
    domain = data["domain"]
    caddy_port = data["caddy_port"]
    web_path = data["web_path"]
    sub_path = data["sub_path"]
    sub_json_path = data["sub_json_path"]
    username = data["username"]
    inbound_ranges = data["inbound_ranges"]
    connect_existing = data.get("connect_existing", False)

    ranges_str = ", ".join(
        f"{s}-{e}" if s != e else str(s) for s, e in inbound_ranges
    )

    await state.set_state(XUIInstall.confirm_install)

    action = "подключение" if connect_existing else "установку"
    btn_text = "✅ Подключить" if connect_existing else "✅ Установить"

    from aiogram.utils.keyboard import InlineKeyboardBuilder

    kb = InlineKeyboardBuilder()
    kb.button(text=btn_text, callback_data="xui_confirm_install")
    kb.button(text="❌ Отмена", callback_data="cancel")
    kb.adjust(1)

    target = message_or_callback if isinstance(message_or_callback, TgMessage) else message_or_callback.message
    text = (
        f"🌐 <b>Подтвердите {action} 3x-ui</b>\n\n"
        f"Домен: <code>{domain}</code>\n"
        f"Caddy порт: <code>{caddy_port}</code>\n"
        f"webBasePath: <code>{web_path}</code>\n"
        f"subPath: <code>{sub_path}</code>\n"
        f"subJsonPath: <code>{sub_json_path}</code>\n"
        f"Логин: <code>{username}</code>\n"
        f"Пароль: <code>{data['password']}</code>\n"
        f"Inbound порты: <code>{ranges_str}</code>\n\n"
        "⚠️ Пароль будет показан только сейчас. Сохраните его!"
    )
    try:
        await target.edit_text(
            text,
            reply_markup=kb.as_markup(),
            parse_mode="HTML",
        )
    except Exception:
        await target.answer(
            text,
            reply_markup=kb.as_markup(),
            parse_mode="HTML",
        )


@router.callback_query(XUIInstall.confirm_install, F.data == "xui_confirm_install")
async def xui_execute_install(callback: CallbackQuery, state: FSMContext) -> None:
    """Execute 3x-ui installation."""
    await callback.answer()

    data = await state.get_data()
    server_id = data["server_id"]
    domain = data["domain"]
    caddy_port = data["caddy_port"]
    web_path = data["web_path"]
    sub_path = data["sub_path"]
    sub_json_path = data["sub_json_path"]
    username = data.get("username", "")
    password = data.get("password", "")
    inbound_ranges = data["inbound_ranges"]
    force = data.get("force_reinstall", False)
    connect_existing = data.get("connect_existing", False)
    auth_mode = data.get("auth_mode", "credentials")
    api_token = data.get("api_token")

    await state.clear()

    if connect_existing:
        msg = await callback.message.edit_text(
            "🔌 <b>Подключение 3x-ui...</b>\n\n"
            "Сохранение параметров в базу данных.",
            parse_mode="HTML",
        )
    else:
        msg = await callback.message.edit_text(
            "🔄 <b>Установка 3x-ui...</b>\n\n"
            "Подготовка сервера, запуск контейнеров, настройка панели.\n"
            "Это может занять 2-3 минуты.",
            parse_mode="HTML",
        )

    try:
        async with async_session_factory() as session:
            from sqlalchemy import select
            from sqlalchemy.orm import selectinload

            from app.database.models import Server

            result = await session.execute(
                select(Server)
                .options(selectinload(Server.xui_panel))
                .where(Server.id == server_id)
            )
            server = result.scalar_one()

            if not connect_existing:
                from app.services.installers.xui_installer import XUIInstaller
                from app.services.ssh_service import SSHManager

                ssh = SSHManager(server)
                installer = XUIInstaller(
                    ssh,
                    progress_callback=lambda text: msg.edit_text(
                        f"🔄 <b>Установка 3x-ui</b>\n\n{text}",
                        parse_mode="HTML",
                    ),
                )
                
                ok, err_msg = await installer.preflight_check()
                if not ok:
                    await msg.edit_text(f"❌ Ошибка проверки прав:\n<code>{err_msg}</code>", reply_markup=get_back_keyboard(f"server_services_{server_id}"), parse_mode="HTML")
                    return

                await installer.install(
                    domain=domain,
                    caddy_port=caddy_port,
                    web_path=web_path,
                    sub_path=sub_path,
                    sub_json_path=sub_json_path,
                    username=username,
                    password=password,
                    inbound_ranges=inbound_ranges,
                    force=force,
                )

            from app.database.models.services import XUIPanel
            from app.utils import encrypt_password

            panel_url = f"https://{domain}:{caddy_port}"
            encrypted_pwd = encrypt_password(password) if password else None
            encrypted_token = encrypt_password(api_token) if api_token else None

            existing = await session.execute(
                select(XUIPanel).where(XUIPanel.server_id == server.id)
            )
            existing_panel = existing.scalar_one_or_none()
            if existing_panel:
                existing_panel.url = panel_url
                existing_panel.panel_path = web_path
                existing_panel.subscription_path = sub_path
                existing_panel.subscription_json_path = sub_json_path
                existing_panel.caddy_port = caddy_port
                existing_panel.inbound_ranges = inbound_ranges
                existing_panel.auth_mode = auth_mode
                if auth_mode == "token":
                    existing_panel.api_token_encrypted = encrypted_token
                    existing_panel.username = None
                    existing_panel.password_encrypted = None
                else:
                    existing_panel.username = username
                    existing_panel.password_encrypted = encrypted_pwd
            else:
                panel = XUIPanel(
                    server_id=server.id,
                    url=panel_url,
                    username=username if auth_mode == "credentials" else None,
                    password_encrypted=encrypted_pwd if auth_mode == "credentials" else None,
                    panel_path=web_path,
                    subscription_path=sub_path,
                    subscription_json_path=sub_json_path,
                    caddy_port=caddy_port,
                    inbound_ranges=inbound_ranges,
                    verify_ssl=False,
                    auth_mode=auth_mode,
                    api_token_encrypted=encrypted_token,
                )
                session.add(panel)
            await session.commit()

        ranges_str = ", ".join(
            f"{s}-{e}" if s != e else str(s) for s, e in inbound_ranges
        )
        clean_web = web_path.strip("/")
        panel_full_url = f"{panel_url}/{clean_web}/" if clean_web else f"{panel_url}/"
        action = "подключена" if connect_existing else ("переустановлен" if force else "установлен")

        auth_info = ""
        if auth_mode == "token":
            auth_info = "🔑 Авторизация: API-токен\n"
        else:
            auth_info = (
                f"Логин: <code>{username}</code>\n"
                f"Пароль: <code>{password}</code>\n"
            )

        await msg.edit_text(
            f"✅ <b>3x-ui {action}!</b>\n\n"
            f"Панель: <code>{panel_full_url}</code>\n"
            f"{auth_info}"
            f"Inbound порты: <code>{ranges_str}</code>\n\n"
            + (
                "⚠️ <b>Сохраните пароль!</b> Он больше не будет показан.\n\n"
                if auth_mode == "credentials" else ""
            )
            + "Выполните синхронизацию для загрузки inbounds.",
            reply_markup=get_back_keyboard(f"server_services_{server_id}"),
            parse_mode="HTML",
        )

    except Exception as e:
        from app.services.installers.base import AlreadyInstalledError

        if isinstance(e, AlreadyInstalledError):
            from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="🔄 Переустановить",
                    callback_data=f"xui_force_reinstall_{server_id}",
                )],
                [InlineKeyboardButton(
                    text="🔙 Назад",
                    callback_data=f"server_services_{server_id}",
                )],
            ])
            await msg.edit_text(
                f"⚠️ <b>3x-ui уже установлен</b>\n\n{e}",
                reply_markup=kb,
                parse_mode="HTML",
            )
        else:
            logger.error(f"3x-ui installation failed: {e}", exc_info=True)
            await msg.edit_text(
                f"❌ <b>Ошибка установки 3x-ui</b>\n\n<code>{e}</code>",
                reply_markup=get_back_keyboard(f"server_services_{server_id}"),
                parse_mode="HTML",
            )


@router.callback_query(F.data.startswith("xui_force_reinstall_"))
async def xui_force_reinstall(callback: CallbackQuery, state: FSMContext) -> None:
    """Force reinstall 3x-ui — remove existing and install fresh."""
    await callback.answer()

    server_id = int(callback.data.split("_")[-1])

    data = await state.get_data()
    domain = data.get("domain")
    caddy_port = data.get("caddy_port")
    web_path = data.get("web_path")
    sub_path = data.get("sub_path")
    sub_json_path = data.get("sub_json_path")
    username = data.get("username")
    password = data.get("password")
    inbound_ranges = data.get("inbound_ranges")
    await state.clear()

    if not all([domain, caddy_port, username, password]):
        await callback.message.edit_text(
            "❌ Данные установки устарели. Начните установку заново.",
            reply_markup=get_back_keyboard(f"server_services_{server_id}"),
            parse_mode="HTML",
        )
        return

    msg = await callback.message.edit_text(
        "🔄 <b>Переустановка 3x-ui...</b>\n\n"
        "Удаление старой установки и запуск новой.",
        parse_mode="HTML",
    )

    try:
        from app.services.installers.xui_installer import XUIInstaller
        from app.services.ssh_service import SSHManager

        async with async_session_factory() as session:
            from sqlalchemy import select
            from sqlalchemy.orm import selectinload

            from app.database.models import Server

            result = await session.execute(
                select(Server)
                .options(selectinload(Server.xui_panel))
                .where(Server.id == server_id)
            )
            server = result.scalar_one()

            ssh = SSHManager(server)
            installer = XUIInstaller(
                ssh,
                progress_callback=lambda text: msg.edit_text(
                    f"🔄 <b>Переустановка 3x-ui</b>\n\n{text}",
                    parse_mode="HTML",
                ),
            )

            await installer.install(
                domain=domain,
                caddy_port=caddy_port,
                web_path=web_path,
                sub_path=sub_path,
                sub_json_path=sub_json_path,
                username=username,
                password=password,
                inbound_ranges=inbound_ranges,
                force=True,
            )

            from app.database.models.services import XUIPanel
            from app.utils import encrypt_password

            encrypted_pwd = encrypt_password(password)
            panel_url = f"https://{domain}:{caddy_port}"
            clean_web = web_path.strip("/")
            panel_full_url = f"{panel_url}/{clean_web}/" if clean_web else f"{panel_url}/"

            existing = await session.execute(
                select(XUIPanel).where(XUIPanel.server_id == server.id)
            )
            existing_panel = existing.scalar_one_or_none()
            if existing_panel:
                existing_panel.url = panel_url
                existing_panel.username = username
                existing_panel.password_encrypted = encrypted_pwd
                existing_panel.panel_path = web_path
                existing_panel.subscription_path = sub_path
                existing_panel.subscription_json_path = sub_json_path
                existing_panel.caddy_port = caddy_port
                existing_panel.inbound_ranges = inbound_ranges
            else:
                panel = XUIPanel(
                    server_id=server.id,
                    url=panel_url,
                    username=username,
                    password_encrypted=encrypted_pwd,
                    panel_path=web_path,
                    subscription_path=sub_path,
                    subscription_json_path=sub_json_path,
                    caddy_port=caddy_port,
                    inbound_ranges=inbound_ranges,
                    verify_ssl=False,
                )
                session.add(panel)
            await session.commit()

        ranges_str = ", ".join(
            f"{s}-{e}" if s != e else str(s) for s, e in inbound_ranges
        )
        await msg.edit_text(
            "✅ <b>3x-ui переустановлен!</b>\n\n"
            f"Панель: <code>{panel_full_url}</code>\n"
            f"Логин: <code>{username}</code>\n"
            f"Пароль: <code>{password}</code>\n"
            f"Inbound порты: <code>{ranges_str}</code>\n\n"
            "⚠️ <b>Сохраните пароль!</b>",
            reply_markup=get_back_keyboard(f"server_services_{server_id}"),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"3x-ui force reinstall failed: {e}", exc_info=True)
        await msg.edit_text(
            f"❌ <b>Ошибка переустановки 3x-ui</b>\n\n<code>{e}</code>",
            reply_markup=get_back_keyboard(f"server_services_{server_id}"),
            parse_mode="HTML",
        )


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
            from aiogram.utils.keyboard import InlineKeyboardBuilder

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


@router.callback_query(F.data.startswith("server_edit_main_"))
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


@router.callback_query(F.data.startswith("server_edit_xui_"))
async def edit_xui_service(callback: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    """Show XUI edit menu or desync menu if container is missing."""
    if not is_admin:
        await callback.answer(
            t("admin.errors.no_rights", "❌ У вас нет прав администратора."), show_alert=True
        )
        return

    server_id = int(callback.data.split("_")[-1])
    await state.update_data(server_id=server_id)

    msg = await callback.message.edit_text("🔍 Проверка состояния 3x-ui на сервере...")

    async with async_session_factory() as session:
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        from app.database.models import Server

        result = await session.execute(
            select(Server)
            .options(selectinload(Server.xui_panel))
            .where(Server.id == server_id)
        )
        server = result.scalar_one_or_none()

    if not server or not server.xui_panel:
        await msg.edit_text(
            t("admin.servers.errors.not_found", "❌ Сервер или 3x-ui панель не найдены.")
        )
        return

    from app.services.installers.xui_installer import XUIInstaller
    from app.services.ssh_service import SSHManager

    try:
        ssh = SSHManager(server)
        installer = XUIInstaller(ssh)
        
        ok, err_msg = await installer.preflight_check()
        if not ok:
            from aiogram.utils.keyboard import InlineKeyboardBuilder
            kb = InlineKeyboardBuilder()
            kb.button(text="🔙 Назад", callback_data=f"server_services_{server_id}")
            await msg.edit_text(f"❌ Ошибка проверки прав SSH:\n<code>{err_msg}</code>", reply_markup=kb.as_markup(), parse_mode="HTML")
            return
            
        is_installed = await installer.check_already_installed()
    except Exception as e:
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        kb = InlineKeyboardBuilder()
        kb.button(text="🔙 Назад", callback_data=f"server_services_{server_id}")
        await msg.edit_text(f"❌ Ошибка подключения по SSH:\n<code>{e}</code>", reply_markup=kb.as_markup(), parse_mode="HTML")
        return

    if not is_installed:
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        kb = InlineKeyboardBuilder()
        kb.button(text="📂 Восстановить из x-ui.db", callback_data=f"xui_desync_restore_file_{server_id}")
        kb.button(text="🆘 Аварийное восстановление", callback_data=f"xui_desync_restore_db_{server_id}")
        kb.button(text="🗑 Удалить панель из БД", callback_data=f"xui_desync_remove_db_{server_id}")
        kb.button(text="🔙 Назад", callback_data=f"server_services_{server_id}")
        kb.adjust(1)

        text = (
            "⚠️ <b>Обнаружен рассинхрон!</b>\n\n"
            "В БД бота числится установленная панель 3x-ui, но физически на сервере контейнеры отсутствуют. "
            "Вероятно, сервер был очищен или переустановлен.\n\n"
            "Выберите действие:"
        )
        await msg.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
        return

    panel = server.xui_panel
    auth_mode = getattr(panel, "auth_mode", "credentials")
    has_token = bool(getattr(panel, "api_token_encrypted", None))

    if auth_mode == "token":
        auth_text = "🔑 API-токен"
        cred_lines = f"API Token: {'✅ Задан' if has_token else '❌ Не задан'}\n"
    else:
        auth_text = "👤 Логин и пароль"
        cred_lines = (
            f"Логин: {panel.username or 'Не задан'}\n"
            f"Пароль: {'***' if panel.password_encrypted else 'Не задан'}\n"
            f"API Token: {'✅ Есть' if has_token else '❌ Нет'}\n"
        )

    text = t(
        "admin.servers.xui.edit_menu",
        "⚙️ Редактирование 3x-ui для сервера: <b>{name}</b>\n\n"
        "Авторизация: {auth_text}\n"
        "{cred_lines}"
        "webBasePath: {web_base_path}\n"
        "subPath: {sub_path}\n"
        "subJsonPath: {sub_json_path}\n"
        "SSL проверка: {ssl}\n\n"
        "Выберите, что изменить:",
        name=server.name,
        auth_text=auth_text,
        cred_lines=cred_lines,
        web_base_path=panel.panel_path or "Не задан",
        sub_path=panel.subscription_path or "Не задан",
        sub_json_path=panel.subscription_json_path or "Не задан",
        ssl="Включена 🔒" if panel.verify_ssl else "Отключена 🔓",
    )

    from aiogram.utils.keyboard import InlineKeyboardBuilder

    kb = InlineKeyboardBuilder()
    kb.button(text="🔑 Задать/Изменить API Токен", callback_data=f"edit_xui_api_token_{server_id}")
    if auth_mode == "credentials":
        kb.button(text="🔄 Пересоздать API Токен", callback_data=f"xui_regenerate_token_{server_id}")
        kb.button(text="Изменить логин", callback_data=f"edit_xui_username_{server_id}")
        kb.button(text="Изменить пароль", callback_data=f"edit_xui_password_{server_id}")
    kb.button(text="Изменить webBasePath", callback_data=f"edit_xui_panel_path_{server_id}")
    kb.button(text="Изменить subPath", callback_data=f"edit_xui_sub_path_{server_id}")
    kb.button(text="Изменить subJsonPath", callback_data=f"xui_edit_jsonpath_{server_id}")
    kb.button(
        text="🔏 Включить SSL" if not panel.verify_ssl else "🔏 Отключить SSL",
        callback_data=f"xui_toggle_ssl_{server_id}",
    )
    kb.button(text="🔙 Назад", callback_data=f"server_services_{server_id}")
    kb.adjust(1)

    await callback.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("server_edit_awg_"))
async def edit_awg_service(callback: CallbackQuery, is_admin: bool) -> None:
    """Edit AWG service or show desync menu."""
    if not is_admin:
        await callback.answer(
            t("admin.errors.no_rights", "❌ У вас нет прав администратора."), show_alert=True
        )
        return

    server_id = int(callback.data.split("_")[-1])
    msg = await callback.message.edit_text("🔍 Проверка состояния AWG на сервере...")

    async with async_session_factory() as session:
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        from app.database.models import Server

        result = await session.execute(
            select(Server)
            .options(selectinload(Server.awg_service))
            .where(Server.id == server_id)
        )
        server = result.scalar_one_or_none()

    if not server or not server.awg_service:
        await msg.edit_text("❌ Сервер или сервис AWG не найдены.")
        return

    from app.services.installers.awg_installer import AWGInstaller
    from app.services.ssh_service import SSHManager

    try:
        ssh = SSHManager(server)
        installer = AWGInstaller(ssh)
        
        ok, err_msg = await installer.preflight_check()
        if not ok:
            from aiogram.utils.keyboard import InlineKeyboardBuilder
            kb = InlineKeyboardBuilder()
            kb.button(text="🔙 Назад", callback_data=f"server_services_{server_id}")
            await msg.edit_text(f"❌ Ошибка проверки прав SSH:\n<code>{err_msg}</code>", reply_markup=kb.as_markup(), parse_mode="HTML")
            return
            
        is_installed = await installer.check_already_installed()
    except Exception as e:
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        kb = InlineKeyboardBuilder()
        kb.button(text="🔙 Назад", callback_data=f"server_services_{server_id}")
        await msg.edit_text(f"❌ Ошибка подключения по SSH:\n<code>{e}</code>", reply_markup=kb.as_markup(), parse_mode="HTML")
        return

    if not is_installed:
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        kb = InlineKeyboardBuilder()
        kb.button(text="🛠 Восстановить сервис из БД", callback_data=f"awg_desync_restore_db_{server_id}")
        kb.button(text="🗑 Удалить из БД бота", callback_data=f"awg_desync_remove_db_{server_id}")
        kb.button(text="🔙 Назад", callback_data=f"server_services_{server_id}")
        kb.adjust(1)

        text = (
            "⚠️ <b>Обнаружен рассинхрон!</b>\n\n"
            "В БД бота числится сервис AmneziaWG, но физически на сервере он отсутствует.\n\n"
            "Выберите действие:"
        )
        await msg.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
        return

    await msg.edit_text("Меню управления AWG (в разработке).", reply_markup=get_back_keyboard(f"server_services_{server_id}"))

@router.callback_query(F.data.startswith("server_edit_mtproxy_"))
async def edit_mtproxy_service(callback: CallbackQuery, is_admin: bool) -> None:
    """Edit MTProxy service or show desync menu."""
    if not is_admin:
        await callback.answer(
            t("admin.errors.no_rights", "❌ У вас нет прав администратора."), show_alert=True
        )
        return

    server_id = int(callback.data.split("_")[-1])
    msg = await callback.message.edit_text("🔍 Проверка состояния MTProxy на сервере...")

    async with async_session_factory() as session:
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        from app.database.models import Server

        result = await session.execute(
            select(Server)
            .options(selectinload(Server.mtproxy_service))
            .where(Server.id == server_id)
        )
        server = result.scalar_one_or_none()

    if not server or not server.mtproxy_service:
        await msg.edit_text("❌ Сервер или сервис MTProxy не найдены.")
        return

    from app.services.installers.mtproxy_installer import MTProxyInstaller
    from app.services.ssh_service import SSHManager

    try:
        ssh = SSHManager(server)
        installer = MTProxyInstaller(ssh)
        
        ok, err_msg = await installer.preflight_check()
        if not ok:
            from aiogram.utils.keyboard import InlineKeyboardBuilder
            kb = InlineKeyboardBuilder()
            kb.button(text="🔙 Назад", callback_data=f"server_services_{server_id}")
            await msg.edit_text(f"❌ Ошибка проверки прав SSH:\n<code>{err_msg}</code>", reply_markup=kb.as_markup(), parse_mode="HTML")
            return
            
        is_installed = await installer.check_already_installed()
    except Exception as e:
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        kb = InlineKeyboardBuilder()
        kb.button(text="🔙 Назад", callback_data=f"server_services_{server_id}")
        await msg.edit_text(f"❌ Ошибка подключения по SSH:\n<code>{e}</code>", reply_markup=kb.as_markup(), parse_mode="HTML")
        return

    if not is_installed:
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        kb = InlineKeyboardBuilder()
        kb.button(text="🛠 Восстановить сервис из БД", callback_data=f"mtp_desync_restore_db_{server_id}")
        kb.button(text="🗑 Удалить из БД бота", callback_data=f"mtp_desync_remove_db_{server_id}")
        kb.button(text="🔙 Назад", callback_data=f"server_services_{server_id}")
        kb.adjust(1)

        text = (
            "⚠️ <b>Обнаружен рассинхрон!</b>\n\n"
            "В БД бота числится сервис MTProxy, но физически на сервере он отсутствует.\n\n"
            "Выберите действие:"
        )
        await msg.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
        return

    await msg.edit_text("Меню управления MTProxy (в разработке).", reply_markup=get_back_keyboard(f"server_services_{server_id}"))

@router.callback_query(F.data.startswith("xui_toggle_ssl_"))
async def xui_toggle_ssl(callback: CallbackQuery, state: FSMContext) -> None:
    """Toggle SSL verification for XUI panel."""
    server_id = int(callback.data.split("_")[-1])

    async with async_session_factory() as session:
        from sqlalchemy import select

        from app.database.models.services import XUIPanel

        result = await session.execute(
            select(XUIPanel).where(XUIPanel.server_id == server_id)
        )
        panel = result.scalar_one_or_none()

        if panel:
            panel.verify_ssl = not panel.verify_ssl
            await session.commit()

            # Re-render the menu
            await edit_xui_service(callback, state, is_admin=True)
        else:
            await callback.answer("❌ Панель не найдена.", show_alert=True)


@router.callback_query(F.data.startswith("edit_xui_username_"))
async def start_edit_xui_username(callback: CallbackQuery, state: FSMContext) -> None:
    server_id = int(callback.data.split("_")[-1])
    await state.update_data(server_id=server_id)
    await state.set_state(ServerManagement.waiting_for_edit_username)
    await callback.message.edit_text(
        "✏️ Введите новый логин для 3x-ui панели (или /skip для отмены):",
        reply_markup=get_back_keyboard(f"server_edit_xui_{server_id}"),
    )
    await callback.answer()


@router.message(ServerManagement.waiting_for_edit_username)
async def process_edit_xui_username(message: TgMessage, state: FSMContext) -> None:
    data = await state.get_data()
    server_id = data["server_id"]
    new_username = message.text.strip()

    if new_username == "/skip":
        # Return to menu by simulating a callback using the same FSM logic
        await _show_xui_edit_menu(message, server_id)
        return

    async with async_session_factory() as session:
        service = XUIService(session)
        await service.update_server(server_id, username=new_username)
        await session.commit()
        await message.answer(f"✅ Логин 3x-ui изменен на: {new_username}")

    await _show_xui_edit_menu(message, server_id)


@router.callback_query(F.data.startswith("edit_xui_password_"))
async def start_edit_xui_password(callback: CallbackQuery, state: FSMContext) -> None:
    server_id = int(callback.data.split("_")[-1])
    await state.update_data(server_id=server_id)
    await state.set_state(ServerManagement.waiting_for_edit_password)
    await callback.message.edit_text(
        "✏️ Введите новый пароль для 3x-ui панели (или /skip для отмены):",
        reply_markup=get_back_keyboard(f"server_edit_xui_{server_id}"),
    )
    await callback.answer()


@router.message(ServerManagement.waiting_for_edit_password)
async def process_edit_xui_password(message: TgMessage, state: FSMContext) -> None:
    data = await state.get_data()
    server_id = data["server_id"]
    new_password = message.text.strip()

    try:
        await message.delete()
    except Exception as e:
        logger.warning(f"Could not delete message: {e}")

    if new_password == "/skip":
        await _show_xui_edit_menu(message, server_id)
        return

    async with async_session_factory() as session:
        service = XUIService(session)
        await service.update_server(server_id, password=new_password)
        await session.commit()
        await message.answer("✅ Пароль 3x-ui успешно изменен.")

    await _show_xui_edit_menu(message, server_id)


@router.callback_query(F.data.startswith("edit_xui_api_token_"))
async def start_edit_xui_api_token(callback: CallbackQuery, state: FSMContext) -> None:
    server_id = int(callback.data.split("_")[-1])
    await state.update_data(server_id=server_id)
    await state.set_state(ServerManagement.waiting_for_edit_api_token)
    await callback.message.edit_text(
        "🔑 <b>Введите API-токен</b>\n\n"
        "Получите токен в 3x-ui: Settings → Security → API Tokens\n\n"
        "Отправьте /skip для отмены.",
        reply_markup=get_back_keyboard(f"server_edit_xui_{server_id}"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(ServerManagement.waiting_for_edit_api_token)
async def process_edit_xui_api_token(message: TgMessage, state: FSMContext) -> None:
    data = await state.get_data()
    server_id = data["server_id"]
    await state.clear()

    token = message.text.strip()
    if token == "/skip":
        await _show_xui_edit_menu(message, server_id)
        return

    if len(token) < 10:
        await message.answer("❌ Токен слишком короткий. Введите корректный API-токен.")
        return

    try:
        await message.delete()
    except Exception:
        pass

    async with async_session_factory() as session:
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        from app.database.models import Server

        result = await session.execute(
            select(Server).options(selectinload(Server.xui_panel)).where(Server.id == server_id)
        )
        server = result.scalar_one_or_none()
        if not server or not server.xui_panel:
            await message.answer("❌ Сервер не найден.")
            return

        service = XUIService(session)
        await service.update_server(
            server_id,
            auth_mode="token",
            api_token=token,
        )
        await session.commit()
        await message.answer("✅ API-токен сохранён.")

    await _show_xui_edit_menu(message, server_id)


@router.callback_query(F.data.startswith("xui_regenerate_token_"))
async def xui_regenerate_token(callback: CallbackQuery) -> None:
    server_id = int(callback.data.split("_")[-1])
    msg = await callback.message.edit_text("🔄 Создание нового API-токена...")

    try:
        async with async_session_factory() as session:
            from sqlalchemy import select
            from sqlalchemy.orm import selectinload
            from app.database.models import Server

            result = await session.execute(
                select(Server).options(selectinload(Server.xui_panel)).where(Server.id == server_id)
            )
            server = result.scalar_one_or_none()
            if not server or not server.xui_panel:
                await msg.edit_text("❌ Сервер не найден.")
                return

            service = XUIService(session)
            token = await service.create_and_save_api_token(server)
            await session.commit()

            await msg.edit_text(
                f"✅ <b>API-токен создан!</b>\n\n"
                f"Токен: <code>{token}</code>\n\n"
                f"⚠️ Сохраните токен — он больше не будет показан.",
                reply_markup=get_back_keyboard(f"server_edit_xui_{server_id}"),
                parse_mode="HTML",
            )
    except Exception as e:
        await msg.edit_text(
            f"❌ Ошибка создания токена: <code>{e}</code>",
            reply_markup=get_back_keyboard(f"server_edit_xui_{server_id}"),
            parse_mode="HTML",
        )


@router.callback_query(F.data.startswith("edit_xui_panel_path_"))
async def start_edit_xui_panel_path(callback: CallbackQuery, state: FSMContext) -> None:
    server_id = int(callback.data.split("_")[-1])
    await state.update_data(server_id=server_id)
    await state.set_state(ServerManagement.waiting_for_edit_panel_path)
    await callback.message.edit_text(
        "✏️ Введите новый webBasePath для 3x-ui панели (например, /panel/). Нажмите /skip для отмены.",
        reply_markup=get_back_keyboard(f"server_edit_xui_{server_id}"),
    )
    await callback.answer()


@router.message(ServerManagement.waiting_for_edit_panel_path)
async def process_edit_xui_panel_path(message: TgMessage, state: FSMContext) -> None:
    data = await state.get_data()
    server_id = data["server_id"]
    new_path = message.text.strip()

    if new_path == "/skip":
        await _show_xui_edit_menu(message, server_id)
        return

    if not new_path.startswith("/"):
        new_path = "/" + new_path

    async with async_session_factory() as session:
        service = XUIService(session)
        await service.update_server(server_id, panel_path=new_path)
        await session.commit()
        await message.answer(f"✅ webBasePath изменен на: {new_path}")

    await _show_xui_edit_menu(message, server_id)


@router.callback_query(F.data.startswith("edit_xui_sub_path_"))
async def start_edit_xui_sub_path(callback: CallbackQuery, state: FSMContext) -> None:
    server_id = int(callback.data.split("_")[-1])
    await state.update_data(server_id=server_id)
    await state.set_state(ServerManagement.waiting_for_edit_subscription_path)
    await callback.message.edit_text(
        "✏️ Введите новый subPath для подписок (например, /sub/). Нажмите /skip для отмены.",
        reply_markup=get_back_keyboard(f"server_edit_xui_{server_id}"),
    )
    await callback.answer()


@router.message(ServerManagement.waiting_for_edit_subscription_path)
async def process_edit_xui_sub_path(message: TgMessage, state: FSMContext) -> None:
    data = await state.get_data()
    server_id = data["server_id"]
    new_path = message.text.strip()

    if new_path == "/skip":
        await _show_xui_edit_menu(message, server_id)
        return

    if not new_path.startswith("/"):
        new_path = "/" + new_path

    async with async_session_factory() as session:
        service = XUIService(session)
        await service.update_server(server_id, subscription_path=new_path)
        await session.commit()
        await message.answer(f"✅ subPath изменен на: {new_path}")

    await _show_xui_edit_menu(message, server_id)


@router.callback_query(F.data.startswith("xui_edit_jsonpath_"))
async def start_edit_xui_jsonpath(callback: CallbackQuery, state: FSMContext) -> None:
    server_id = int(callback.data.split("_")[-1])
    await state.update_data(server_id=server_id)
    await state.set_state(ServerManagement.waiting_for_edit_subscription_json_path)
    await callback.message.edit_text(
        "✏️ Введите новый subJsonPath для подписок (например, /sub/json/). Нажмите /skip для отмены.",
        reply_markup=get_back_keyboard(f"server_edit_xui_{server_id}"),
    )
    await callback.answer()


@router.message(ServerManagement.waiting_for_edit_subscription_json_path)
async def process_edit_xui_jsonpath(message: TgMessage, state: FSMContext) -> None:
    data = await state.get_data()
    server_id = data["server_id"]
    new_path = message.text.strip()

    if new_path == "/skip":
        await _show_xui_edit_menu(message, server_id)
        return

    if not new_path.startswith("/"):
        new_path = "/" + new_path

    async with async_session_factory() as session:
        service = XUIService(session)
        await service.update_server(server_id, subscription_json_path=new_path)
        await session.commit()
        await message.answer(f"✅ subJsonPath изменен на: {new_path}")

    await _show_xui_edit_menu(message, server_id)


async def _show_xui_edit_menu(message: TgMessage, server_id: int) -> None:
    """Helper to show the XUI edit menu after an edit operation."""
    async with async_session_factory() as session:
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        from app.database.models import Server

        result = await session.execute(
            select(Server)
            .options(selectinload(Server.xui_panel))
            .where(Server.id == server_id)
        )
        server = result.scalar_one_or_none()

    if not server or not server.xui_panel:
        await message.answer("❌ Сервер или 3x-ui панель не найдены.")
        return

    panel = server.xui_panel
    auth_mode = getattr(panel, "auth_mode", "credentials")
    has_token = bool(getattr(panel, "api_token_encrypted", None))

    if auth_mode == "token":
        auth_text = "🔑 API-токен"
        cred_lines = f"API Token: {'✅ Задан' if has_token else '❌ Не задан'}\n"
    else:
        auth_text = "👤 Логин и пароль"
        cred_lines = (
            f"Логин: {panel.username or 'Не задан'}\n"
            f"Пароль: {'***' if panel.password_encrypted else 'Не задан'}\n"
            f"API Token: {'✅ Есть' if has_token else '❌ Нет'}\n"
        )

    text = t(
        "admin.servers.xui.edit_menu",
        "⚙️ Редактирование 3x-ui для сервера: <b>{name}</b>\n\n"
        "Авторизация: {auth_text}\n"
        "{cred_lines}"
        "webBasePath: {web_base_path}\n"
        "subPath: {sub_path}\n"
        "subJsonPath: {sub_json_path}\n"
        "SSL проверка: {ssl}\n\n"
        "Выберите, что изменить:",
        name=server.name,
        auth_text=auth_text,
        cred_lines=cred_lines,
        web_base_path=panel.panel_path or "Не задан",
        sub_path=panel.subscription_path or "Не задан",
        sub_json_path=panel.subscription_json_path or "Не задан",
        ssl="Включена 🔒" if panel.verify_ssl else "Отключена 🔓",
    )

    from aiogram.utils.keyboard import InlineKeyboardBuilder

    kb = InlineKeyboardBuilder()
    kb.button(text="🔑 Задать/Изменить API Токен", callback_data=f"edit_xui_api_token_{server_id}")
    if auth_mode == "credentials":
        kb.button(text="🔄 Пересоздать API Токен", callback_data=f"xui_regenerate_token_{server_id}")
        kb.button(text="Изменить логин", callback_data=f"edit_xui_username_{server_id}")
        kb.button(text="Изменить пароль", callback_data=f"edit_xui_password_{server_id}")
    kb.button(text="Изменить webBasePath", callback_data=f"edit_xui_panel_path_{server_id}")
    kb.button(text="Изменить subPath", callback_data=f"edit_xui_sub_path_{server_id}")
    kb.button(text="Изменить subJsonPath", callback_data=f"xui_edit_jsonpath_{server_id}")
    kb.button(
        text="🔏 Включить SSL" if not panel.verify_ssl else "🔏 Отключить SSL",
        callback_data=f"xui_toggle_ssl_{server_id}",
    )
    kb.button(text="🔙 Назад", callback_data=f"server_services_{server_id}")
    kb.adjust(1)

    await message.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")


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
        from app.database.models.inbound import AWGInbound, MTProxyInbound
        from app.database.models.services import AWGService, MTProxyService, XUIPanel

        result = await session.execute(
            select(Server)
            .options(
                selectinload(Server.xui_panel),
                selectinload(Server.awg_service),
                selectinload(Server.mtproxy_service),
                selectinload(Server.inbounds),
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
            details = discovered["3x-ui"]
            if not server.xui_panel:
                panel = XUIPanel(
                    server_id=server.id,
                    url=f"https://{details['domain']}:{details['caddy_port']}",
                    username=details.get("username"),
                    password_encrypted="",
                    panel_path=details.get("web_path", "/"),
                    subscription_path=details.get("sub_path", "/sub/"),
                    subscription_json_path=details.get("sub_json_path", "/json/"),
                    caddy_port=details.get("caddy_port", 8443),
                    verify_ssl=False,
                )
                session.add(panel)
                discovered_list.append(
                    f"3x-ui ({details['domain']}:{details['caddy_port']})"
                )
            else:
                discovered_list.append("3x-ui (уже подключён)")

        if "amnezia-awg" in discovered:
            details = discovered["amnezia-awg"]
            if not server.awg_service:
                awg = AWGService(
                    server_id=server.id,
                    port=details.get("port", 51820),
                    subnet_ip=details.get("subnet_ip", "10.8.0.1"),
                    subnet_cidr=details.get("subnet_cidr", 24),
                    obfuscation=details.get("obfuscation", {}),
                )
                session.add(awg)
                discovered_list.append(
                    f"AmneziaWG (порт {details.get('port', 51820)})"
                )
            else:
                discovered_list.append("AmneziaWG (уже подключён)")

            if not any(ib.type == "awg_inbound" for ib in server.inbounds):
                awg_inbound = AWGInbound(
                    server_id=server.id,
                    protocol="awg",
                    remark="AmneziaWG",
                    port=details.get("port", 51820),
                )
                session.add(awg_inbound)

        if "mtproxy" in discovered:
            details = discovered["mtproxy"]
            if not server.mtproxy_service:
                mtproxy = MTProxyService(
                    server_id=server.id,
                    implementation=details.get("implementation", "mtg-multi"),
                    port=details.get("port", 443),
                    domain=details.get("domain"),
                    max_connections=details.get("max_connections"),
                    default_secret=details.get("secret"),
                )
                session.add(mtproxy)
                discovered_list.append(
                    f"MTProxy {details.get('implementation', 'mtg')} (порт {details.get('port', 443)})"
                )
            else:
                discovered_list.append("MTProxy (уже подключён)")

            if not any(ib.type == "mtproxy_inbound" for ib in server.inbounds):
                mtproxy_inbound = MTProxyInbound(
                    server_id=server.id,
                    protocol="mtproto",
                    remark="MTProxy",
                    port=details.get("port", 443),
                )
                session.add(mtproxy_inbound)

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


# ── Shared: First-install setup (firewall + SSH port) ─────────────────


async def _check_first_setup(
    callback: CallbackQuery, state: FSMContext, server_id: int, installer_target: str
) -> bool | None:
    """Check if first-setup steps needed. Returns True if setup question shown.

    Args:
        installer_target: 'awg' or 'xui' — determines where to redirect after.
    """
    from app.services.installers.base import BaseInstaller
    from app.services.ssh_service import SSHManager

    async with async_session_factory() as session:
        from sqlalchemy import select

        from app.database.models import Server

        result = await session.execute(select(Server).where(Server.id == server_id))
        server = result.scalar_one_or_none()

    if not server:
        return None

    ssh = SSHManager(server)
    installer = BaseInstaller(ssh)
    
    ok, err_msg = await installer.preflight_check()
    if not ok:
        await message.answer(f"❌ Ошибка проверки прав SSH:\n<code>{err_msg}</code>", parse_mode="HTML")
        return False

    policy = await installer.get_firewall_policy()
    if policy is not None:
        return False

    await state.update_data(server_id=server_id, _setup_target=installer_target)
    await state.set_state(FirstSetup.waiting_for_firewall_policy)

    from aiogram.utils.keyboard import InlineKeyboardBuilder

    kb = InlineKeyboardBuilder()
    kb.button(text="🔒 Strict (рекомендуется)", callback_data="firewall_strict")
    kb.button(text="🔓 Permissive", callback_data="firewall_permissive")
    kb.button(text="🔙 Отмена", callback_data=f"server_services_{server_id}")
    kb.adjust(1)

    await callback.message.edit_text(
        "🛡 <b>Первичная настройка сервера</b>\n\n"
        "Это первая установка на этом сервере.\n\n"
        "🔒 <b>Strict</b> — закрыть все порты, кроме SSH. "
        "Нужные порты откроются автоматически при установке сервисов.\n"
        "🔓 <b>Permissive</b> — не менять текущие правила UFW.\n\n"
        "⚠️ <b>Рекомендуется Strict</b> для безопасности.",
        reply_markup=kb.as_markup(),
        parse_mode="HTML",
    )
    return True


@router.callback_query(FirstSetup.waiting_for_firewall_policy, F.data == "firewall_strict")
async def firewall_strict(callback: CallbackQuery, state: FSMContext) -> None:
    await _apply_firewall_policy(callback, state, strict=True)


@router.callback_query(FirstSetup.waiting_for_firewall_policy, F.data == "firewall_permissive")
async def firewall_permissive(callback: CallbackQuery, state: FSMContext) -> None:
    await _apply_firewall_policy(callback, state, strict=False)


async def _apply_firewall_policy(callback: CallbackQuery, state: FSMContext, strict: bool) -> None:
    """Apply firewall policy and ask about SSH port."""
    data = await state.get_data()
    server_id = data["server_id"]

    msg = await callback.message.edit_text("🔄 Применяю политику файрвола...")

    from app.services.installers.base import BaseInstaller
    from app.services.ssh_service import SSHManager

    async with async_session_factory() as session:
        from sqlalchemy import select

        from app.database.models import Server

        result = await session.execute(select(Server).where(Server.id == server_id))
        server = result.scalar_one()

    ssh = SSHManager(server)
    installer = BaseInstaller(ssh)

    try:
        ok, err_msg = await installer.preflight_check()
        if not ok:
            await msg.edit_text(f"❌ Ошибка проверки прав SSH:\n<code>{err_msg}</code>", reply_markup=get_back_keyboard(f"server_services_{server_id}"), parse_mode="HTML")
            return
            
        await installer.apply_firewall_policy(strict=strict)
    except Exception as e:
        await msg.edit_text(
            f"❌ Ошибка настройки файрвола: {e}",
            reply_markup=get_back_keyboard(f"server_services_{server_id}"),
        )
        await state.clear()
        return

    policy_text = "🔒 Strict" if strict else "🔓 Permissive"

    await state.set_state(FirstSetup.waiting_for_ssh_port_choice)

    from aiogram.utils.keyboard import InlineKeyboardBuilder

    kb = InlineKeyboardBuilder()
    kb.button(text="🔢 Изменить SSH порт", callback_data="ssh_port_change")
    kb.button(text="⏭️ Пропустить", callback_data="ssh_port_skip")
    kb.button(text="🔙 Отмена", callback_data=f"server_services_{server_id}")
    kb.adjust(1)

    await msg.edit_text(
        f"✅ Политика файрвола: {policy_text}\n\n"
        "🔑 <b>SSH порт</b>\n\n"
        f"Текущий SSH порт: <code>{ssh.port}</code>\n\n"
        "Хотите изменить SSH порт на другой?\n"
        "Рекомендуется для безопасности (стандартный порт 22 часто сканируется).",
        reply_markup=kb.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(FirstSetup.waiting_for_ssh_port_choice, F.data == "ssh_port_skip")
async def ssh_port_skip(callback: CallbackQuery, state: FSMContext) -> None:
    """Skip SSH port change, proceed to installer."""
    await _continue_to_installer(callback.message, state)


@router.callback_query(FirstSetup.waiting_for_ssh_port_choice, F.data == "ssh_port_change")
async def ssh_port_change_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Ask for new SSH port."""
    await state.set_state(FirstSetup.waiting_for_ssh_port)

    data = await state.get_data()
    server_id = data["server_id"]

    await callback.message.edit_text(
        "🔑 <b>Смена SSH порта</b>\n\n"
        "Введите новый SSH порт (например, <code>2222</code>):\n\n"
        "⚠️ Бот сначала добавит новый порт, проверит подключение, "
        "и только потом удалит старый. Если что-то пойдёт не так — "
        "автоматический откат.",
        reply_markup=get_back_keyboard(f"server_services_{server_id}"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(FirstSetup.waiting_for_ssh_port)
async def ssh_port_process(message: TgMessage, state: FSMContext) -> None:
    """Process new SSH port, change it, then continue."""
    text = message.text.strip()
    if not text.isdigit() or int(text) < 1 or int(text) > 65535:
        await message.answer("❌ Введите число от 1 до 65535.")
        return

    new_port = int(text)
    data = await state.get_data()
    server_id = data["server_id"]

    msg = await message.answer(
        f"🔄 Меняю SSH порт на <code>{new_port}</code>...\n\n"
        "Проверяю подключение на новом порту...",
        parse_mode="HTML",
    )

    from app.services.installers.base import BaseInstaller
    from app.services.ssh_service import SSHManager

    async with async_session_factory() as session:
        from sqlalchemy import select

        from app.database.models import Server

        result = await session.execute(select(Server).where(Server.id == server_id))
        server = result.scalar_one()

    ssh = SSHManager(server)
    installer = BaseInstaller(ssh)

    ok, err_msg = await installer.preflight_check()
    if not ok:
        await message.answer(f"❌ Ошибка проверки прав SSH:\n<code>{err_msg}</code>", parse_mode="HTML")
        return

    success, change_msg = await installer.change_ssh_port(new_port)

    if success:
        async with async_session_factory() as session:
            from sqlalchemy import select

            from app.database.models import Server

            result = await session.execute(select(Server).where(Server.id == server_id))
            server = result.scalar_one()
            server.ssh_port = new_port
            await session.commit()

        await msg.edit_text(
            f"✅ {change_msg}\n\n"
            f"Новый SSH порт сохранён в базе данных.",
        )
    else:
        await msg.edit_text(
            f"⚠️ {change_msg}",
        )

    await _continue_to_installer(msg, state)


async def _continue_to_installer(message, state: FSMContext) -> None:
    """Redirect to the actual installer flow after first-setup."""
    data = await state.get_data()
    target = data.get("_setup_target")

    if target == "awg":
        await _awg_ask_port(message, state)
    elif target == "xui":
        await _xui_ask_domain(message, state)
    else:
        server_id = data.get("server_id", 0)
        await state.clear()
        await message.edit_text(
            "⚠️ Не удалось продолжить установку.",
            reply_markup=get_back_keyboard(f"server_services_{server_id}"),
        )


async def _awg_ask_port(message_or_callback, state: FSMContext) -> None:
    """Show AWG port input."""
    await state.set_state(AWGInstall.waiting_for_port)

    data = await state.get_data()
    server_id = data["server_id"]

    from aiogram.utils.keyboard import InlineKeyboardBuilder

    kb = InlineKeyboardBuilder()
    kb.button(text="🎲 Сгенерировать случайный", callback_data="awg_port_random")
    kb.button(text="🔙 Отмена", callback_data=f"server_services_{server_id}")
    kb.adjust(1)

    target = message_or_callback if isinstance(message_or_callback, TgMessage) else message_or_callback.message if hasattr(message_or_callback, "message") else message_or_callback
    await target.edit_text(
        "🛡 <b>Установка AmneziaWG</b>\n\n"
        "Введите UDP-порт для AWG (рекомендуется диапазон 30000-50000).\n"
        "Бот проверит, свободен ли порт на сервере.",
        reply_markup=kb.as_markup(),
        parse_mode="HTML",
    )


async def _xui_ask_domain(message_or_callback, state: FSMContext) -> None:
    """Show XUI domain input."""
    await state.set_state(XUIInstall.waiting_for_domain)

    data = await state.get_data()
    server_id = data["server_id"]

    target = message_or_callback if isinstance(message_or_callback, TgMessage) else message_or_callback.message if hasattr(message_or_callback, "message") else message_or_callback
    await target.edit_text(
        "🌐 <b>Установка 3x-ui</b>\n\n"
        "Введите домен для панели (например, <code>vpn.example.com</code>)\n"
        "или IP-адрес сервера (SSL не будет настроен):",
        reply_markup=get_back_keyboard(f"server_services_{server_id}"),
        parse_mode="HTML",
    )


# ── AWG Installation Flow ──────────────────────────────────────────────


@router.callback_query(F.data.startswith("server_install_awg_"))
async def start_awg_install(callback: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    """Start AWG installation: check SSH, then ask for port."""
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
            .options(selectinload(Server.awg_service))
            .where(Server.id == server_id)
        )
        server = result.scalar_one_or_none()

    if not server:
        await callback.answer(
            t("admin.servers.errors.not_found", "❌ Сервер не найден."), show_alert=True
        )
        return

    if server.awg_service:
        await callback.answer("AmneziaWG уже установлен на этом сервере.", show_alert=True)
        return

    if not server.ssh_user:
        await callback.message.edit_text(
            t(
                "admin.servers.services.ssh_not_configured",
                "❌ SSH не настроен для этого сервера. Сначала настройте SSH.",
            ),
            reply_markup=get_back_keyboard(f"server_services_{server_id}"),
        )
        return

    status_msg = await callback.message.edit_text(
        "🔄 Проверяю доступность сервера и SSH-подключение..."
    )

    from app.services.installers.awg_installer import AWGInstaller
    from app.services.ssh_service import SSHManager

    ssh = SSHManager(server)
    installer = AWGInstaller(ssh)
    ok, msg = await installer.preflight_check()

    if not ok:
        await status_msg.edit_text(
            f"❌ <b>Предварительная проверка не пройдена</b>\n\n{msg}",
            reply_markup=get_back_keyboard(f"server_services_{server_id}"),
            parse_mode="HTML",
        )
        return

    if await installer.check_already_installed():
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

        await status_msg.edit_text(
            "🔍 <b>AmneziaWG уже установлен на этом сервере</b>\n\n"
            "Обнаружен контейнер <code>vpnbot-awg</code>.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="🔌 Подключить",
                    callback_data=f"awg_connect_existing_{server_id}",
                )],
                [InlineKeyboardButton(
                    text="🔄 Переустановить",
                    callback_data=f"awg_reinstall_{server_id}",
                )],
                [InlineKeyboardButton(
                    text="🔙 Назад",
                    callback_data=f"server_services_{server_id}",
                )],
            ]),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    await state.update_data(server_id=server_id)

    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    await status_msg.edit_text(
        "🛡 <b>AmneziaWG не найден на сервере</b>\n\n"
        "Выберите способ добавления:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="📦 Установить новую",
                callback_data=f"awg_install_new_{server_id}",
            )],
            [InlineKeyboardButton(
                text="🔌 Подключить существующую",
                callback_data=f"awg_connect_existing_{server_id}",
            )],
            [InlineKeyboardButton(
                text="🔙 Назад",
                callback_data=f"server_services_{server_id}",
            )],
        ]),
        parse_mode="HTML",
    )
    await callback.answer()
    return


@router.callback_query(F.data.startswith("awg_install_new_"))
async def awg_install_new(callback: CallbackQuery, state: FSMContext) -> None:
    """Start fresh AWG installation."""
    server_id = int(callback.data.split("_")[-1])
    await state.update_data(server_id=server_id)

    policy_shown = await _check_first_setup(callback, state, server_id, "awg")
    if policy_shown:
        await callback.answer()
        return

    await _awg_ask_port(callback.message, state)
    await callback.answer()


@router.callback_query(F.data.startswith("awg_connect_existing_"))
async def awg_connect_existing(callback: CallbackQuery, state: FSMContext) -> None:
    """Connect existing AWG — auto-discover params and save to DB."""
    server_id = int(callback.data.split("_")[-1])

    msg = await callback.message.edit_text(
        "🔍 <b>Читаю конфигурацию AmneziaWG с сервера...</b>",
        parse_mode="HTML",
    )
    await callback.answer()

    try:
        from app.services.installers.awg_installer import AWGInstaller
        from app.services.ssh_service import SSHManager

        async with async_session_factory() as session:
            from sqlalchemy import select

            from app.database.models import Server

            server = (await session.execute(
                select(Server).where(Server.id == server_id)
            )).scalar_one()

        ssh = SSHManager(server)
        installer = AWGInstaller(ssh)
        
        ok, err_msg = await installer.preflight_check()
        if not ok:
            await msg.edit_text(f"❌ Ошибка проверки прав SSH:\n<code>{err_msg}</code>", reply_markup=get_back_keyboard(f"server_services_{server_id}"), parse_mode="HTML")
            return
            
        params = await installer.discover_existing()
    except Exception as e:
        logger.error(f"AWG discover failed: {e}", exc_info=True)
        await msg.edit_text(
            f"❌ <b>Не удалось прочитать конфигурацию</b>\n\n<code>{e}</code>",
            reply_markup=get_back_keyboard(f"server_services_{server_id}"),
            parse_mode="HTML",
        )
        return

    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    from aiogram.utils.text_decorations import html_decoration

    obf_text = "\n".join(
        f"  {k} = {html_decoration.quote(v)}"
        for k, v in params["obfuscation"].items()
    )
    await msg.edit_text(
        "🛡 <b>AmneziaWG найден!</b> Параметры из awg0.conf:\n\n"
        f"Порт: <code>{params['port']}/udp</code>\n"
        f"Подсеть: <code>{params['subnet_ip']}/{params['subnet_cidr']}</code>\n\n"
        f"<b>Обфускация:</b>\n{obf_text}\n\n"
        "Подключить с этими параметрами?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="✅ Подключить",
                callback_data="awg_confirm_connect",
            )],
            [InlineKeyboardButton(
                text="🔙 Отмена",
                callback_data=f"server_services_{server_id}",
            )],
        ]),
        parse_mode="HTML",
    )
    await state.update_data(
        server_id=server_id,
        connect_existing=True,
        port=params["port"],
        obfuscation=params["obfuscation"],
        subnet_ip=params["subnet_ip"],
        subnet_cidr=params["subnet_cidr"],
        server_public_key=params.get("server_public_key", ""),
        server_private_key=params.get("server_private_key", ""),
    )


@router.callback_query(F.data == "awg_confirm_connect")
async def awg_confirm_connect(callback: CallbackQuery, state: FSMContext) -> None:
    """Save discovered AWG params to DB."""
    await callback.answer()

    data = await state.get_data()
    server_id = data["server_id"]
    port = data["port"]
    obf = data["obfuscation"]
    subnet_ip = data.get("subnet_ip", "10.8.0.1")
    subnet_cidr = data.get("subnet_cidr", 24)
    await state.clear()

    try:
        async with async_session_factory() as session:
            from sqlalchemy import select

            from app.database.models import Server
            from app.database.models.inbound import AWGInbound
            from app.database.models.services import AWGService

            server = (await session.execute(
                select(Server).where(Server.id == server_id)
            )).scalar_one()

            existing_svc = await session.execute(
                select(AWGService).where(AWGService.server_id == server.id)
            )
            existing = existing_svc.scalar_one_or_none()
            if existing:
                existing.port = port
                existing.subnet_ip = subnet_ip
                existing.subnet_cidr = subnet_cidr
                existing.obfuscation = obf
                if data.get("server_public_key"):
                    existing.server_public_key = data["server_public_key"]
                if data.get("server_private_key"):
                    existing.server_private_key = data["server_private_key"]
            else:
                awg_service = AWGService(
                    server_id=server.id,
                    port=port,
                    subnet_ip=subnet_ip,
                    subnet_cidr=subnet_cidr,
                    obfuscation=obf,
                    server_public_key=data.get("server_public_key"),
                    server_private_key=data.get("server_private_key"),
                )
                session.add(awg_service)

            existing_ib = await session.execute(
                select(AWGInbound).where(AWGInbound.server_id == server.id)
            )
            if not existing_ib.scalar_one_or_none():
                awg_inbound = AWGInbound(
                    server_id=server.id,
                    protocol="awg",
                    remark=f"AmneziaWG:{port}",
                    port=port,
                )
                session.add(awg_inbound)
            await session.commit()

        await callback.message.edit_text(
            f"✅ <b>AmneziaWG подключён!</b>\n\n"
            f"Порт: <code>{port}/udp</code>\n"
            f"Контейнер: <code>vpnbot-awg</code>\n\n"
            "Сервис и inbound добавлены в базу данных.",
            reply_markup=get_back_keyboard(f"server_services_{server_id}"),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"AWG connect failed: {e}", exc_info=True)
        await callback.message.edit_text(
            f"❌ <b>Ошибка подключения AmneziaWG</b>\n\n<code>{e}</code>",
            reply_markup=get_back_keyboard(f"server_services_{server_id}"),
            parse_mode="HTML",
        )


@router.callback_query(F.data.startswith("awg_reinstall_"))
async def awg_reinstall(callback: CallbackQuery, state: FSMContext) -> None:
    """Start AWG reinstallation flow (force=True)."""
    server_id = int(callback.data.split("_")[-1])
    await state.update_data(server_id=server_id, force_reinstall=True)
    await _awg_ask_port(callback.message, state)
    await callback.answer()


@router.callback_query(AWGInstall.waiting_for_port, F.data == "awg_port_random")
async def awg_port_random(callback: CallbackQuery, state: FSMContext) -> None:
    """Generate random port for AWG."""
    data = await state.get_data()
    server_id = data["server_id"]

    msg = await callback.message.edit_text("🔄 Подбираю свободный порт на сервере...")

    try:
        from app.services.ssh_service import SSHManager
        from app.services.vpn_providers.port_manager import PortManager

        async with async_session_factory() as session:
            from sqlalchemy import select

            from app.database.models import Server

            result = await session.execute(select(Server).where(Server.id == server_id))
            server = result.scalar_one()

        ssh = SSHManager(server)
        pm = PortManager(ssh)
        port = await pm.allocate_free_port()
    except Exception as e:
        logger.error(f"Port allocation failed: {e}")
        await msg.edit_text(
            f"❌ Не удалось подобрать порт: {e}",
            reply_markup=get_back_keyboard(f"server_services_{server_id}"),
        )
        await state.clear()
        return

    await state.update_data(port=port)
    await _show_awg_obfuscation_choice(msg, state, port)


@router.message(AWGInstall.waiting_for_port)
async def awg_port_manual(message: TgMessage, state: FSMContext) -> None:
    """Process manually entered AWG port."""
    text = message.text.strip()

    if not text.isdigit():
        await message.answer(
            "❌ Введите число (например, 30120).",
            reply_markup=get_back_keyboard("cancel"),
        )
        return

    port = int(text)
    if port < 1 or port > 65535:
        await message.answer("❌ Порт должен быть от 1 до 65535.")
        return

    data = await state.get_data()
    server_id = data["server_id"]

    msg = await message.answer(f"🔄 Проверяю порт {port} на сервере...")

    try:
        from app.services.ssh_service import SSHManager
        from app.services.vpn_providers.port_manager import PortManager

        async with async_session_factory() as session:
            from sqlalchemy import select

            from app.database.models import Server

            result = await session.execute(select(Server).where(Server.id == server_id))
            server = result.scalar_one()

        ssh = SSHManager(server)
        pm = PortManager(ssh)

        if not await pm.is_port_free(port):
            await msg.edit_text(
                f"❌ Порт {port} занят на сервере. Введите другой порт:",
                reply_markup=get_back_keyboard("cancel"),
            )
            return
    except Exception as e:
        logger.error(f"Port check failed: {e}")
        await msg.edit_text(
            f"❌ Не удалось проверить порт: {e}",
            reply_markup=get_back_keyboard(f"server_services_{server_id}"),
        )
        await state.clear()
        return

    await state.update_data(port=port)
    await _show_awg_obfuscation_choice(msg, state, port)


async def _show_awg_obfuscation_choice(message, state: FSMContext, port: int) -> None:
    """Show Quick/Advanced obfuscation mode selection."""
    await state.set_state(AWGInstall.waiting_for_obfuscation_mode)

    from aiogram.utils.keyboard import InlineKeyboardBuilder

    kb = InlineKeyboardBuilder()
    kb.button(text="⚡ Quick (авто)", callback_data="awg_obf_quick")
    kb.button(text="🔧 Advanced (вручную)", callback_data="awg_obf_advanced")
    kb.button(text="🔙 Отмена", callback_data="cancel")
    kb.adjust(1)

    await message.edit_text(
        f"🛡 <b>Установка AmneziaWG</b>\n\n"
        f"Порт: <code>{port}/udp</code>\n\n"
        f"Выберите режим настройки обфускации:\n"
        f"⚡ <b>Quick</b> — параметры генерируются автоматически\n"
        f"🔧 <b>Advanced</b> — задать Jc, Jmin, Jmax, S1-S4, H1-H4 вручную",
        reply_markup=kb.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(AWGInstall.waiting_for_obfuscation_mode, F.data == "awg_obf_quick")
async def awg_obf_quick(callback: CallbackQuery, state: FSMContext) -> None:
    """Quick mode: auto-generate obfuscation and show confirmation."""
    from app.services.installers.awg_installer import generate_obfuscation_params

    obf = generate_obfuscation_params()
    await state.update_data(obfuscation=obf)
    await _show_awg_confirm(callback.message, state)


@router.callback_query(AWGInstall.waiting_for_obfuscation_mode, F.data == "awg_obf_advanced")
async def awg_obf_advanced(callback: CallbackQuery, state: FSMContext) -> None:
    """Advanced mode: ask admin for obfuscation parameters."""
    await state.set_state(AWGInstall.waiting_for_obfuscation_params)

    await callback.message.edit_text(
        "🔧 <b>Advanced: параметры обфускации</b>\n\n"
        "Введите параметры в формате:\n"
        "<code>Jc Jmin Jmax S1 S2 S3 S4 H1 H2 H3 H4</code>\n\n"
        "11 чисел через пробел.\n"
        "Пример: <code>5 100 800 50 50 50 50 1234567890 9876543210 5555555555 1111111111</code>",
        reply_markup=get_back_keyboard("cancel"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AWGInstall.waiting_for_obfuscation_params)
async def awg_obf_params_input(message: TgMessage, state: FSMContext) -> None:
    """Parse manually entered obfuscation parameters."""
    parts = message.text.strip().split()

    if len(parts) != 11:
        await message.answer(
            f"❌ Нужно ровно 11 чисел, получено {len(parts)}. Попробуйте снова.",
            reply_markup=get_back_keyboard("cancel"),
        )
        return

    try:
        values = [int(p) for p in parts]
    except ValueError:
        await message.answer(
            "❌ Все значения должны быть числами.",
            reply_markup=get_back_keyboard("cancel"),
        )
        return

    keys = ["Jc", "Jmin", "Jmax", "S1", "S2", "S3", "S4", "H1", "H2", "H3", "H4"]
    obf = dict(zip(keys, values, strict=True))
    await state.update_data(obfuscation=obf)
    await _show_awg_confirm(message, state)


async def _show_awg_confirm(message, state: FSMContext) -> None:
    """Show installation confirmation with all parameters."""
    from aiogram.utils.text_decorations import html_decoration

    data = await state.get_data()
    port = data["port"]
    obf = data["obfuscation"]
    connect_existing = data.get("connect_existing", False)

    obf_text = "\n".join(
        f"  {k} = {html_decoration.quote(str(v))}" for k, v in obf.items()
    )

    await state.set_state(AWGInstall.confirm_install)

    action = "подключение" if connect_existing else "установку"
    btn_text = "✅ Подключить" if connect_existing else "✅ Установить"

    from aiogram.utils.keyboard import InlineKeyboardBuilder

    kb = InlineKeyboardBuilder()
    kb.button(text=btn_text, callback_data="awg_confirm_install")
    kb.button(text="❌ Отмена", callback_data="cancel")
    kb.adjust(1)

    target = message if isinstance(message, TgMessage) else message

    await target.edit_text(
        f"🛡 <b>Подтвердите {action} AmneziaWG</b>\n\n"
        f"Порт: <code>{port}/udp</code>\n\n"
        f"<b>Параметры обфускации:</b>\n{obf_text}\n\n"
        f"Нажмите «{'Подключить' if connect_existing else 'Установить'}» для начала.",
        reply_markup=kb.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(AWGInstall.confirm_install, F.data == "awg_confirm_install")
async def awg_execute_install(callback: CallbackQuery, state: FSMContext) -> None:
    """Execute AWG installation."""
    await callback.answer()

    data = await state.get_data()
    server_id = data["server_id"]
    port = data["port"]
    obf = data["obfuscation"]
    force = data.get("force_reinstall", False)
    connect_existing = data.get("connect_existing", False)

    await state.clear()

    if connect_existing:
        msg = await callback.message.edit_text(
            "🔌 <b>Подключение AmneziaWG...</b>\n\n"
            "Сохранение параметров в базу данных.",
            parse_mode="HTML",
        )
    else:
        msg = await callback.message.edit_text(
            "🔄 <b>Установка AmneziaWG...</b>\n\n"
            "Подготовка сервера, сборка контейнера, генерация ключей.\n"
            "Это может занять 1-2 минуты.",
            parse_mode="HTML",
        )

    try:
        async with async_session_factory() as session:
            from sqlalchemy import select
            from sqlalchemy.orm import selectinload

            from app.database.models import Server

            result = await session.execute(
                select(Server)
                .options(selectinload(Server.awg_service))
                .where(Server.id == server_id)
            )
            server = result.scalar_one()

            install_result = None
            if not connect_existing:
                from app.services.installers.awg_installer import AWGInstaller
                from app.services.ssh_service import SSHManager

                ssh = SSHManager(server)
                installer = AWGInstaller(
                    ssh,
                    progress_callback=lambda text: msg.edit_text(
                        f"🔄 <b>Установка AmneziaWG</b>\n\n{text}",
                        parse_mode="HTML",
                    ),
                )
                
                ok, err_msg = await installer.preflight_check()
                if not ok:
                    await msg.edit_text(f"❌ Ошибка проверки прав:\n<code>{err_msg}</code>", reply_markup=get_back_keyboard(f"server_services_{server_id}"), parse_mode="HTML")
                    return

                install_result = await installer.install(
                    port=port,
                    obfuscation=obf,
                    force=force,
                )

            from app.database.models.inbound import AWGInbound
            from app.database.models.services import AWGService

            existing_svc = await session.execute(
                select(AWGService).where(AWGService.server_id == server.id)
            )
            existing_awg = existing_svc.scalar_one_or_none()
            if existing_awg:
                existing_awg.port = port
                if install_result:
                    existing_awg.subnet_ip = install_result["subnet_ip"]
                    existing_awg.subnet_cidr = install_result["subnet_cidr"]
                    existing_awg.obfuscation = install_result["obfuscation"]
                    existing_awg.server_public_key = install_result.get("server_public_key")
                    existing_awg.server_private_key = install_result.get("server_private_key")
                else:
                    existing_awg.obfuscation = obf
            else:
                awg_service = AWGService(
                    server_id=server.id,
                    port=port,
                    subnet_ip=install_result["subnet_ip"] if install_result else "10.8.0.1",
                    subnet_cidr=install_result["subnet_cidr"] if install_result else 24,
                    obfuscation=install_result["obfuscation"] if install_result else obf,
                    server_public_key=install_result.get("server_public_key") if install_result else None,
                    server_private_key=install_result.get("server_private_key") if install_result else None,
                )
                session.add(awg_service)

            existing_ib = await session.execute(
                select(AWGInbound).where(AWGInbound.server_id == server.id)
            )
            if not existing_ib.scalar_one_or_none():
                awg_inbound = AWGInbound(
                    server_id=server.id,
                    protocol="awg",
                    remark=f"AmneziaWG:{port}",
                    port=port,
                )
                session.add(awg_inbound)
            await session.commit()

        action = "подключён" if connect_existing else ("переустановлен" if force else "установлен")
        await msg.edit_text(
            f"✅ <b>AmneziaWG {action}!</b>\n\n"
            f"Порт: <code>{port}/udp</code>\n"
            f"Контейнер: <code>vpnbot-awg</code>\n\n"
            "Сервис и inbound добавлены в базу данных.",
            reply_markup=get_back_keyboard(f"server_services_{server_id}"),
            parse_mode="HTML",
        )
    except Exception as e:
        from app.services.installers.base import AlreadyInstalledError

        if isinstance(e, AlreadyInstalledError):
            from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="🔄 Переустановить",
                    callback_data=f"awg_force_reinstall_{server_id}",
                )],
                [InlineKeyboardButton(
                    text="🔙 Назад",
                    callback_data=f"server_services_{server_id}",
                )],
            ])
            await msg.edit_text(
                f"⚠️ <b>AmneziaWG уже установлен</b>\n\n{e}",
                reply_markup=kb,
                parse_mode="HTML",
            )
        else:
            logger.error(f"AWG installation failed: {e}", exc_info=True)
            await msg.edit_text(
                f"❌ <b>Ошибка установки AmneziaWG</b>\n\n<code>{e}</code>",
                reply_markup=get_back_keyboard(f"server_services_{server_id}"),
                parse_mode="HTML",
            )


@router.callback_query(F.data.startswith("awg_force_reinstall_"))
async def awg_force_reinstall(callback: CallbackQuery, state: FSMContext) -> None:
    """Force reinstall AWG — remove existing and install fresh."""
    await callback.answer()

    server_id = int(callback.data.split("_")[-1])

    data = await state.get_data()
    port = data.get("port")
    obf = data.get("obfuscation")
    await state.clear()

    if not port:
        await callback.message.edit_text(
            "❌ Данные установки устарели. Начните установку заново.",
            reply_markup=get_back_keyboard(f"server_services_{server_id}"),
            parse_mode="HTML",
        )
        return

    msg = await callback.message.edit_text(
        "🔄 <b>Переустановка AmneziaWG...</b>\n\n"
        "Удаление старой установки и запуск новой.",
        parse_mode="HTML",
    )

    try:
        from app.services.installers.awg_installer import AWGInstaller
        from app.services.ssh_service import SSHManager

        async with async_session_factory() as session:
            from sqlalchemy import select
            from sqlalchemy.orm import selectinload

            from app.database.models import Server

            result = await session.execute(
                select(Server)
                .options(selectinload(Server.awg_service))
                .where(Server.id == server_id)
            )
            server = result.scalar_one()

            ssh = SSHManager(server)
            installer = AWGInstaller(
                ssh,
                progress_callback=lambda text: msg.edit_text(
                    f"🔄 <b>Переустановка AmneziaWG</b>\n\n{text}",
                    parse_mode="HTML",
                ),
            )

            install_result = await installer.install(
                port=port,
                obfuscation=obf,
                force=True,
            )

            from app.database.models.inbound import AWGInbound
            from app.database.models.services import AWGService

            existing_svc = await session.execute(
                select(AWGService).where(AWGService.server_id == server.id)
            )
            existing = existing_svc.scalar_one_or_none()
            if existing:
                existing.port = port
                existing.subnet_ip = install_result["subnet_ip"]
                existing.subnet_cidr = install_result["subnet_cidr"]
                existing.obfuscation = install_result["obfuscation"]
                existing.server_public_key = install_result.get("server_public_key")
                existing.server_private_key = install_result.get("server_private_key")
            else:
                awg_service = AWGService(
                    server_id=server.id,
                    port=port,
                    subnet_ip=install_result["subnet_ip"],
                    subnet_cidr=install_result["subnet_cidr"],
                    obfuscation=install_result["obfuscation"],
                    server_public_key=install_result.get("server_public_key"),
                    server_private_key=install_result.get("server_private_key"),
                )
                session.add(awg_service)

            existing_ib = await session.execute(
                select(AWGInbound).where(AWGInbound.server_id == server.id)
            )
            if not existing_ib.scalar_one_or_none():
                awg_inbound = AWGInbound(
                    server_id=server.id,
                    protocol="awg",
                    remark=f"AmneziaWG:{port}",
                    port=port,
                )
                session.add(awg_inbound)
            await session.commit()

        await msg.edit_text(
            "✅ <b>AmneziaWG переустановлен!</b>\n\n"
            f"Порт: <code>{port}/udp</code>\n"
            f"Контейнер: <code>vpnbot-awg</code>\n\n"
            "Сервис обновлён в базе данных.",
            reply_markup=get_back_keyboard(f"server_services_{server_id}"),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"AWG force reinstall failed: {e}", exc_info=True)
        await msg.edit_text(
            f"❌ <b>Ошибка переустановки AmneziaWG</b>\n\n<code>{e}</code>",
            reply_markup=get_back_keyboard(f"server_services_{server_id}"),
            parse_mode="HTML",
        )


# ── MTProxy Installation Flow ─────────────────────────────────────────


@router.callback_query(F.data.startswith("server_install_mtproxy_"))
async def start_mtproxy_install(callback: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    """Start MTProxy installation."""
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
            .options(selectinload(Server.mtproxy_service))
            .where(Server.id == server_id)
        )
        server = result.scalar_one_or_none()

    if not server:
        await callback.answer(
            t("admin.servers.errors.not_found", "❌ Сервер не найден."), show_alert=True
        )
        return

    if server.mtproxy_service:
        await callback.answer("MTProxy уже установлен на этом сервере.", show_alert=True)
        return

    if not server.ssh_user:
        await callback.message.edit_text(
            t(
                "admin.servers.services.ssh_not_configured",
                "❌ SSH не настроен для этого сервера. Сначала настройте SSH.",
            ),
            reply_markup=get_back_keyboard(f"server_services_{server_id}"),
        )
        return

    status_msg = await callback.message.edit_text(
        "🔄 Проверяю доступность сервера и SSH-подключение..."
    )

    from app.services.installers.mtproxy_installer import MTProxyInstaller
    from app.services.ssh_service import SSHManager

    ssh = SSHManager(server)
    installer = MTProxyInstaller(ssh)
    ok, msg = await installer.preflight_check()

    if not ok:
        await status_msg.edit_text(
            f"❌ <b>Предварительная проверка не пройдена</b>\n\n{msg}",
            reply_markup=get_back_keyboard(f"server_services_{server_id}"),
            parse_mode="HTML",
        )
        return

    if await installer.check_already_installed():
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

        await status_msg.edit_text(
            "🔍 <b>MTProxy уже установлен на этом сервере</b>\n\n"
            "Обнаружен контейнер <code>vpnbot-mtproxy</code>.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="🔌 Подключить",
                    callback_data=f"mtproxy_connect_existing_{server_id}",
                )],
                [InlineKeyboardButton(
                    text="🔄 Переустановить",
                    callback_data=f"mtproxy_reinstall_{server_id}",
                )],
                [InlineKeyboardButton(
                    text="🔙 Назад",
                    callback_data=f"server_services_{server_id}",
                )],
            ]),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    await state.update_data(server_id=server_id)

    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    await status_msg.edit_text(
        "📡 <b>MTProxy не найден на сервере</b>\n\n"
        "Выберите способ добавления:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="📦 Установить новую",
                callback_data=f"mtproxy_install_new_{server_id}",
            )],
            [InlineKeyboardButton(
                text="🔌 Подключить существующую",
                callback_data=f"mtproxy_connect_existing_{server_id}",
            )],
            [InlineKeyboardButton(
                text="🔙 Назад",
                callback_data=f"server_services_{server_id}",
            )],
        ]),
        parse_mode="HTML",
    )
    await callback.answer()
    return


@router.callback_query(F.data.startswith("mtproxy_install_new_"))
async def mtproxy_install_new(callback: CallbackQuery, state: FSMContext) -> None:
    """Start fresh MTProxy installation."""
    server_id = int(callback.data.split("_")[-1])
    await state.update_data(server_id=server_id)

    policy_shown = await _check_first_setup(callback, state, server_id, "mtproxy")
    if policy_shown:
        await callback.answer()
        return

    await _mtproxy_ask_implementation(callback.message, state)
    await callback.answer()


@router.callback_query(F.data.startswith("mtproxy_connect_existing_"))
async def mtproxy_connect_existing(callback: CallbackQuery, state: FSMContext) -> None:
    """Connect existing MTProxy — auto-discover params and save to DB."""
    server_id = int(callback.data.split("_")[-1])

    msg = await callback.message.edit_text(
        "🔍 <b>Читаю конфигурацию MTProxy с сервера...</b>",
        parse_mode="HTML",
    )
    await callback.answer()

    try:
        from app.services.installers.mtproxy_installer import MTProxyInstaller
        from app.services.ssh_service import SSHManager

        async with async_session_factory() as session:
            from sqlalchemy import select

            from app.database.models import Server

            server = (await session.execute(
                select(Server).where(Server.id == server_id)
            )).scalar_one()

        ssh = SSHManager(server)
        installer = MTProxyInstaller(ssh)
        
        ok, err_msg = await installer.preflight_check()
        if not ok:
            await msg.edit_text(f"❌ Ошибка проверки прав SSH:\n<code>{err_msg}</code>", reply_markup=get_back_keyboard(f"server_services_{server_id}"), parse_mode="HTML")
            return
            
        params = await installer.discover_existing()
    except Exception as e:
        logger.error(f"MTProxy discover failed: {e}", exc_info=True)
        await msg.edit_text(
            f"❌ <b>Не удалось прочитать конфигурацию</b>\n\n<code>{e}</code>",
            reply_markup=get_back_keyboard(f"server_services_{server_id}"),
            parse_mode="HTML",
        )
        return

    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    impl_text = "⭐ mtg-multi" if params["implementation"] == "mtg-multi" else "🔹 mtg"
    conns_text = f"\nМакс. подключений: <code>{params['max_connections']}</code>" if params["implementation"] == "mtg-multi" else ""
    await msg.edit_text(
        f"📡 <b>MTProxy найден!</b> Параметры из config.toml:\n\n"
        f"Реализация: {impl_text}\n"
        f"Порт: <code>{params['port']}/tcp</code>{conns_text}\n\n"
        "Подключить с этими параметрами?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="✅ Подключить",
                callback_data="mtproxy_confirm_connect",
            )],
            [InlineKeyboardButton(
                text="🔙 Отмена",
                callback_data=f"server_services_{server_id}",
            )],
        ]),
        parse_mode="HTML",
    )
    await state.update_data(
        server_id=server_id,
        connect_existing=True,
        implementation=params["implementation"],
        port=params["port"],
        domain=params["domain"],
        max_connections=params["max_connections"],
        secret=params.get("secret"),
    )


@router.callback_query(F.data == "mtproxy_confirm_connect")
async def mtproxy_confirm_connect(callback: CallbackQuery, state: FSMContext) -> None:
    """Save discovered MTProxy params to DB."""
    await callback.answer()

    data = await state.get_data()
    server_id = data["server_id"]
    port = data["port"]
    domain = data["domain"]
    implementation = data["implementation"]
    max_connections = data.get("max_connections", 5000)
    secret = data.get("secret")
    await state.clear()

    try:
        async with async_session_factory() as session:
            from sqlalchemy import select

            from app.database.models import Server
            from app.database.models.inbound import MTProxyInbound
            from app.database.models.services import MTProxyService

            server = (await session.execute(
                select(Server).where(Server.id == server_id)
            )).scalar_one()

            existing_svc = await session.execute(
                select(MTProxyService).where(MTProxyService.server_id == server.id)
            )
            existing = existing_svc.scalar_one_or_none()
            if existing:
                existing.implementation = implementation
                existing.port = port
                existing.domain = domain
                existing.max_connections = max_connections if implementation == "mtg-multi" else None
                if secret:
                    existing.default_secret = secret
            else:
                mtproxy_service = MTProxyService(
                    server_id=server.id,
                    implementation=implementation,
                    port=port,
                    domain=domain,
                    max_connections=max_connections if implementation == "mtg-multi" else None,
                    default_secret=secret,
                )
                session.add(mtproxy_service)

            existing_ib = await session.execute(
                select(MTProxyInbound).where(MTProxyInbound.server_id == server.id)
            )
            if not existing_ib.scalar_one_or_none():
                mtproxy_inbound = MTProxyInbound(
                    server_id=server.id,
                    protocol="mtproto",
                    remark=f"MTProxy:{port}",
                    port=port,
                )
                session.add(mtproxy_inbound)
            await session.commit()

        impl_text = "mtg-multi" if implementation == "mtg-multi" else "mtg"
        await callback.message.edit_text(
            f"✅ <b>MTProxy подключён!</b>\n\n"
            f"Реализация: <code>{impl_text}</code>\n"
            f"Порт: <code>{port}/tcp</code>\n"
            f"Контейнер: <code>vpnbot-mtproxy</code>\n\n"
            "Сервис и inbound добавлены в базу данных.",
            reply_markup=get_back_keyboard(f"server_services_{server_id}"),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"MTProxy connect failed: {e}", exc_info=True)
        await callback.message.edit_text(
            f"❌ <b>Ошибка подключения MTProxy</b>\n\n<code>{e}</code>",
            reply_markup=get_back_keyboard(f"server_services_{server_id}"),
            parse_mode="HTML",
        )


@router.callback_query(F.data.startswith("mtproxy_reinstall_"))
async def mtproxy_reinstall(callback: CallbackQuery, state: FSMContext) -> None:
    """Start MTProxy reinstallation flow (force=True)."""
    server_id = int(callback.data.split("_")[-1])
    await state.update_data(server_id=server_id, force_reinstall=True)
    await _mtproxy_ask_implementation(callback.message, state)
    await callback.answer()


async def _mtproxy_ask_implementation(message_or_callback, state: FSMContext) -> None:
    """Ask which MTProxy implementation to use."""
    await state.set_state(MTProxyInstall.waiting_for_implementation)

    from aiogram.utils.keyboard import InlineKeyboardBuilder

    kb = InlineKeyboardBuilder()
    kb.button(text="⭐ mtg-multi (рекомендуется)", callback_data="mtproxy_impl_multi")
    kb.button(text="🔹 mtg (upstream)", callback_data="mtproxy_impl_mtg")
    kb.button(text="🔙 Отмена", callback_data="cancel")
    kb.adjust(1)

    target = message_or_callback if isinstance(message_or_callback, TgMessage) else message_or_callback.message if hasattr(message_or_callback, "message") else message_or_callback
    await target.edit_text(
        "📡 <b>Установка MTProxy</b>\n\n"
        "✅ Сервер доступен, SSH OK.\n\n"
        "Выберите реализацию:\n\n"
        "⭐ <b>mtg-multi</b> — форк с поддержкой:\n"
        "  • Множественные секреты (по одному на клиента)\n"
        "  • Stats API (мониторинг трафика)\n"
        "  • Throttling (fair-share)\n\n"
        "🔹 <b>mtg</b> — оригинал (3.4k ⭐):\n"
        "  • Один секрет на инстанс\n"
        "  • Проще, стабильнее\n"
        "  • Без Stats API",
        reply_markup=kb.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(MTProxyInstall.waiting_for_implementation, F.data == "mtproxy_impl_multi")
async def mtproxy_impl_multi(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(implementation="mtg-multi")
    await _mtproxy_ask_port(callback.message, state)


@router.callback_query(MTProxyInstall.waiting_for_implementation, F.data == "mtproxy_impl_mtg")
async def mtproxy_impl_mtg(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(implementation="mtg")
    await _mtproxy_ask_port(callback.message, state)


async def _mtproxy_ask_port(message_or_callback, state: FSMContext) -> None:
    """Ask for MTProxy port."""
    await state.set_state(MTProxyInstall.waiting_for_port)

    data = await state.get_data()
    server_id = data["server_id"]

    from aiogram.utils.keyboard import InlineKeyboardBuilder

    kb = InlineKeyboardBuilder()
    kb.button(text="🎲 Дефолт (443)", callback_data="mtproxy_port_auto")
    kb.button(text="🔙 Отмена", callback_data=f"server_services_{server_id}")
    kb.adjust(1)

    target = message_or_callback if isinstance(message_or_callback, TgMessage) else message_or_callback.message if hasattr(message_or_callback, "message") else message_or_callback
    await target.edit_text(
        "📡 Введите TCP-порт для MTProxy (дефолт: <code>443</code>):",
        reply_markup=kb.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(MTProxyInstall.waiting_for_port, F.data == "mtproxy_port_auto")
async def mtproxy_port_auto(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(port=443)
    await _mtproxy_ask_domain(callback.message, state)


@router.message(MTProxyInstall.waiting_for_port)
async def mtproxy_port_manual(message: TgMessage, state: FSMContext) -> None:
    text = message.text.strip()
    if not text.isdigit() or int(text) < 1 or int(text) > 65535:
        await message.answer("❌ Введите число от 1 до 65535.")
        return

    port = int(text)
    data = await state.get_data()
    server_id = data["server_id"]

    msg = await message.answer(f"🔄 Проверяю порт {port} на сервере...")

    from app.services.ssh_service import SSHManager
    from app.services.vpn_providers.port_manager import PortManager

    async with async_session_factory() as session:
        from sqlalchemy import select

        from app.database.models import Server

        result = await session.execute(select(Server).where(Server.id == server_id))
        server = result.scalar_one()

    ssh = SSHManager(server)
    pm = PortManager(ssh)

    if not await pm.is_port_free(port):
        await msg.edit_text(
            f"❌ Порт {port} занят. Введите другой:",
            reply_markup=get_back_keyboard("cancel"),
        )
        return

    await state.update_data(port=port)
    await _mtproxy_ask_domain(msg, state)


async def _mtproxy_ask_domain(message_or_callback, state: FSMContext) -> None:
    """Ask for Fake-TLS domain."""
    await state.set_state(MTProxyInstall.waiting_for_domain)

    data = await state.get_data()
    server_id = data["server_id"]

    from aiogram.utils.keyboard import InlineKeyboardBuilder

    kb = InlineKeyboardBuilder()
    kb.button(text="🎲 google.com (дефолт)", callback_data="mtproxy_domain_default")
    kb.button(text="🔙 Отмена", callback_data=f"server_services_{server_id}")
    kb.adjust(1)

    target = message_or_callback if isinstance(message_or_callback, TgMessage) else message_or_callback.message if hasattr(message_or_callback, "message") else message_or_callback
    await target.edit_text(
        "🔐 <b>Fake-TLS домен</b>\n\n"
        "Введите домен для маскировки трафика (должен поддерживать TLS 1.2+).\n"
        "Рекомендуется выбирать домен, связанный с хостингом вашего сервера.",
        reply_markup=kb.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(MTProxyInstall.waiting_for_domain, F.data == "mtproxy_domain_default")
async def mtproxy_domain_default(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(domain="google.com")
    data = await state.get_data()
    if data.get("implementation") == "mtg-multi":
        await _mtproxy_ask_max_connections(callback.message, state)
    else:
        await _mtproxy_show_confirm(callback.message, state)


@router.message(MTProxyInstall.waiting_for_domain)
async def mtproxy_domain_manual(message: TgMessage, state: FSMContext) -> None:
    domain = message.text.strip().lower()
    if not domain or "." not in domain:
        await message.answer("❌ Введите корректный домен (например, cloudflare.com).")
        return

    await state.update_data(domain=domain)
    data = await state.get_data()
    if data.get("implementation") == "mtg-multi":
        msg = await message.answer("🔄 Загрузка...")
        await _mtproxy_ask_max_connections(msg, state)
    else:
        msg = await message.answer("🔄 Загрузка...")
        await _mtproxy_show_confirm(msg, state)


async def _mtproxy_ask_max_connections(message_or_callback, state: FSMContext) -> None:
    """Ask for max connections (mtg-multi only)."""
    await state.set_state(MTProxyInstall.waiting_for_max_connections)

    data = await state.get_data()
    server_id = data["server_id"]

    from aiogram.utils.keyboard import InlineKeyboardBuilder

    kb = InlineKeyboardBuilder()
    kb.button(text="🎲 Дефолт (5000)", callback_data="mtproxy_conns_default")
    kb.button(text="🔙 Отмена", callback_data=f"server_services_{server_id}")
    kb.adjust(1)

    target = message_or_callback if isinstance(message_or_callback, TgMessage) else message_or_callback.message if hasattr(message_or_callback, "message") else message_or_callback
    await target.edit_text(
        "⚡ <b>Макс. подключений</b> (mtg-multi)\n\n"
        "Лимит одновременных подключений.\n"
        "Fair-share: если один пользователь превысит норму, "
        "его лимит будет перераспределён.\n\n"
        "Дефолт: <code>5000</code>",
        reply_markup=kb.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(MTProxyInstall.waiting_for_max_connections, F.data == "mtproxy_conns_default")
async def mtproxy_conns_default(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(max_connections=5000)
    await _mtproxy_show_confirm(callback.message, state)


@router.message(MTProxyInstall.waiting_for_max_connections)
async def mtproxy_conns_manual(message: TgMessage, state: FSMContext) -> None:
    text = message.text.strip()
    if not text.isdigit() or int(text) < 100:
        await message.answer("❌ Минимум 100 подключений.")
        return
    await state.update_data(max_connections=int(text))
    msg = await message.answer("🔄 Загрузка...")
    await _mtproxy_show_confirm(msg, state)


async def _mtproxy_show_confirm(message_or_callback, state: FSMContext) -> None:
    """Show confirmation."""
    data = await state.get_data()
    impl = data["implementation"]
    port = data["port"]
    domain = data["domain"]
    max_conns = data.get("max_connections")
    connect_existing = data.get("connect_existing", False)

    await state.set_state(MTProxyInstall.confirm_install)

    impl_text = "⭐ mtg-multi" if impl == "mtg-multi" else "🔹 mtg (upstream)"
    conns_text = f"\nМакс. подключений: <code>{max_conns}</code>" if max_conns else ""

    action = "подключение" if connect_existing else "установку"
    btn_text = "✅ Подключить" if connect_existing else "✅ Установить"

    from aiogram.utils.keyboard import InlineKeyboardBuilder

    kb = InlineKeyboardBuilder()
    kb.button(text=btn_text, callback_data="mtproxy_confirm_install")
    kb.button(text="❌ Отмена", callback_data="cancel")
    kb.adjust(1)

    target = message_or_callback if isinstance(message_or_callback, TgMessage) else message_or_callback.message if hasattr(message_or_callback, "message") else message_or_callback
    await target.edit_text(
        f"📡 <b>Подтвердите {action} MTProxy</b>\n\n"
        f"Реализация: {impl_text}\n"
        f"Порт: <code>{port}/tcp</code>\n"
        f"Fake-TLS домен: <code>{domain}</code>"
        f"{conns_text}",
        reply_markup=kb.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(MTProxyInstall.confirm_install, F.data == "mtproxy_confirm_install")
async def mtproxy_execute_install(callback: CallbackQuery, state: FSMContext) -> None:
    """Execute MTProxy installation."""
    await callback.answer()

    data = await state.get_data()
    server_id = data["server_id"]
    port = data["port"]
    domain = data["domain"]
    implementation = data["implementation"]
    max_connections = data.get("max_connections", 5000)
    force = data.get("force_reinstall", False)
    connect_existing = data.get("connect_existing", False)
    secret = data.get("secret")

    await state.clear()

    if connect_existing:
        msg = await callback.message.edit_text(
            "🔌 <b>Подключение MTProxy...</b>\n\n"
            "Сохранение параметров в базу данных.",
            parse_mode="HTML",
        )
    else:
        msg = await callback.message.edit_text(
            "🔄 <b>Установка MTProxy...</b>\n\n"
            "Подготовка сервера, запуск контейнера.",
            parse_mode="HTML",
        )

    try:
        async with async_session_factory() as session:
            from sqlalchemy import select
            from sqlalchemy.orm import selectinload

            from app.database.models import Server

            result = await session.execute(
                select(Server)
                .options(selectinload(Server.mtproxy_service))
                .where(Server.id == server_id)
            )
            server = result.scalar_one()

            if not connect_existing:
                from app.services.installers.mtproxy_installer import MTProxyInstaller
                from app.services.ssh_service import SSHManager

                ssh = SSHManager(server)
                installer = MTProxyInstaller(
                    ssh,
                    progress_callback=lambda text: msg.edit_text(
                        f"🔄 <b>Установка MTProxy</b>\n\n{text}",
                        parse_mode="HTML",
                    ),
                )
                
                ok, err_msg = await installer.preflight_check()
                if not ok:
                    await msg.edit_text(f"❌ Ошибка проверки прав:\n<code>{err_msg}</code>", reply_markup=get_back_keyboard(f"server_services_{server_id}"), parse_mode="HTML")
                    return

                install_result = await installer.install(
                    port=port,
                    domain=domain,
                    implementation=implementation,
                    max_connections=max_connections,
                    force=force,
                )
                secret = install_result.get("secret")

            from app.database.models.inbound import MTProxyInbound
            from app.database.models.services import MTProxyService

            existing_svc = await session.execute(
                select(MTProxyService).where(MTProxyService.server_id == server.id)
            )
            existing = existing_svc.scalar_one_or_none()
            if existing:
                existing.implementation = implementation
                existing.port = port
                existing.domain = domain
                existing.max_connections = max_connections if implementation == "mtg-multi" else None
                if secret:
                    existing.default_secret = secret
            else:
                mtproxy_service = MTProxyService(
                    server_id=server.id,
                    implementation=implementation,
                    port=port,
                    domain=domain,
                    max_connections=max_connections if implementation == "mtg-multi" else None,
                    default_secret=secret,
                )
                session.add(mtproxy_service)

            existing_ib = await session.execute(
                select(MTProxyInbound).where(MTProxyInbound.server_id == server.id)
            )
            if not existing_ib.scalar_one_or_none():
                mtproxy_inbound = MTProxyInbound(
                    server_id=server.id,
                    protocol="mtproto",
                    remark=f"MTProxy:{port}",
                    port=port,
                )
                session.add(mtproxy_inbound)
            await session.commit()

        impl_text = "mtg-multi" if implementation == "mtg-multi" else "mtg"
        action = "подключён" if connect_existing else ("переустановлен" if force else "установлен")
        await msg.edit_text(
            f"✅ <b>MTProxy {action}!</b>\n\n"
            f"Реализация: <code>{impl_text}</code>\n"
            f"Порт: <code>{port}/tcp</code>\n"
            f"Fake-TLS домен: <code>{domain}</code>\n"
            f"Контейнер: <code>vpnbot-mtproxy</code>\n\n"
            "Сервис и inbound добавлены в базу данных.",
            reply_markup=get_back_keyboard(f"server_services_{server_id}"),
            parse_mode="HTML",
        )
    except Exception as e:
        from app.services.installers.base import AlreadyInstalledError

        if isinstance(e, AlreadyInstalledError):
            from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="🔄 Переустановить",
                    callback_data=f"mtproxy_force_reinstall_{server_id}",
                )],
                [InlineKeyboardButton(
                    text="🔙 Назад",
                    callback_data=f"server_services_{server_id}",
                )],
            ])
            await msg.edit_text(
                f"⚠️ <b>MTProxy уже установлен</b>\n\n{e}",
                reply_markup=kb,
                parse_mode="HTML",
            )
        else:
            logger.error(f"MTProxy installation failed: {e}", exc_info=True)
            await msg.edit_text(
                f"❌ <b>Ошибка установки MTProxy</b>\n\n<code>{e}</code>",
                reply_markup=get_back_keyboard(f"server_services_{server_id}"),
                parse_mode="HTML",
            )


@router.callback_query(F.data.startswith("mtproxy_force_reinstall_"))
async def mtproxy_force_reinstall(callback: CallbackQuery, state: FSMContext) -> None:
    """Force reinstall MTProxy — remove existing and install fresh."""
    await callback.answer()

    server_id = int(callback.data.split("_")[-1])

    data = await state.get_data()
    port = data.get("port")
    domain = data.get("domain")
    implementation = data.get("implementation")
    max_connections = data.get("max_connections", 5000)
    await state.clear()

    if not all([port, domain, implementation]):
        await callback.message.edit_text(
            "❌ Данные установки устарели. Начните установку заново.",
            reply_markup=get_back_keyboard(f"server_services_{server_id}"),
            parse_mode="HTML",
        )
        return

    msg = await callback.message.edit_text(
        "🔄 <b>Переустановка MTProxy...</b>\n\n"
        "Удаление старой установки и запуск новой.",
        parse_mode="HTML",
    )

    try:
        from app.services.installers.mtproxy_installer import MTProxyInstaller
        from app.services.ssh_service import SSHManager

        async with async_session_factory() as session:
            from sqlalchemy import select
            from sqlalchemy.orm import selectinload

            from app.database.models import Server

            result = await session.execute(
                select(Server)
                .options(selectinload(Server.mtproxy_service))
                .where(Server.id == server_id)
            )
            server = result.scalar_one()

            ssh = SSHManager(server)
            installer = MTProxyInstaller(
                ssh,
                progress_callback=lambda text: msg.edit_text(
                    f"🔄 <b>Переустановка MTProxy</b>\n\n{text}",
                    parse_mode="HTML",
                ),
            )

            install_result = await installer.install(
                port=port,
                domain=domain,
                implementation=implementation,
                max_connections=max_connections,
                force=True,
            )
            secret = install_result.get("secret")

            from app.database.models.inbound import MTProxyInbound
            from app.database.models.services import MTProxyService

            existing_svc = await session.execute(
                select(MTProxyService).where(MTProxyService.server_id == server.id)
            )
            existing = existing_svc.scalar_one_or_none()
            if existing:
                existing.implementation = implementation
                existing.port = port
                existing.domain = domain
                existing.max_connections = max_connections if implementation == "mtg-multi" else None
                if secret:
                    existing.default_secret = secret
            else:
                mtproxy_service = MTProxyService(
                    server_id=server.id,
                    implementation=implementation,
                    port=port,
                    domain=domain,
                    max_connections=max_connections if implementation == "mtg-multi" else None,
                    default_secret=secret,
                )
                session.add(mtproxy_service)

            existing_ib = await session.execute(
                select(MTProxyInbound).where(MTProxyInbound.server_id == server.id)
            )
            if not existing_ib.scalar_one_or_none():
                mtproxy_inbound = MTProxyInbound(
                    server_id=server.id,
                    protocol="mtproto",
                    remark=f"MTProxy:{port}",
                    port=port,
                )
                session.add(mtproxy_inbound)
            await session.commit()

        impl_text = "mtg-multi" if implementation == "mtg-multi" else "mtg"
        await msg.edit_text(
            f"✅ <b>MTProxy переустановлен!</b>\n\n"
            f"Реализация: <code>{impl_text}</code>\n"
            f"Порт: <code>{port}/tcp</code>\n"
            f"Fake-TLS домен: <code>{domain}</code>\n"
            f"Контейнер: <code>vpnbot-mtproxy</code>\n\n"
            "Сервис обновлён в базе данных.",
            reply_markup=get_back_keyboard(f"server_services_{server_id}"),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"MTProxy force reinstall failed: {e}", exc_info=True)
        await msg.edit_text(
            f"❌ <b>Ошибка переустановки MTProxy</b>\n\n<code>{e}</code>",
            reply_markup=get_back_keyboard(f"server_services_{server_id}"),
            parse_mode="HTML",
        )


# ── Desync Recovery Handlers ──────────────────────────────────────

@router.callback_query(F.data.startswith("xui_desync_remove_db_"))
async def xui_desync_remove_db(callback: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    server_id = int(callback.data.split("_")[-1])
    async with async_session_factory() as session:
        from sqlalchemy import delete
        from app.database.models import XUIPanel, Inbound
        await session.execute(delete(XUIPanel).where(XUIPanel.server_id == server_id))
        await session.execute(delete(Inbound).where(Inbound.server_id == server_id, Inbound.protocol.in_(("vless", "vmess", "trojan", "shadowsocks", "wireguard", "socks", "http"))))
        await session.commit()
    await callback.answer("✅ 3x-ui панель и инбаунды удалены из БД", show_alert=True)
    await show_server_services(callback, state, is_admin)

@router.callback_query(F.data.startswith("awg_desync_remove_db_"))
async def awg_desync_remove_db(callback: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    server_id = int(callback.data.split("_")[-1])
    async with async_session_factory() as session:
        from sqlalchemy import delete
        from app.database.models import AWGService, Inbound
        await session.execute(delete(AWGService).where(AWGService.server_id == server_id))
        await session.execute(delete(Inbound).where(Inbound.server_id == server_id, Inbound.protocol == "awg"))
        await session.commit()
    await callback.answer("✅ AWG удален из БД", show_alert=True)
    await show_server_services(callback, state, is_admin)

@router.callback_query(F.data.startswith("mtp_desync_remove_db_"))
async def mtp_desync_remove_db(callback: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    server_id = int(callback.data.split("_")[-1])
    async with async_session_factory() as session:
        from sqlalchemy import delete
        from app.database.models import MTProxyService, Inbound
        await session.execute(delete(MTProxyService).where(MTProxyService.server_id == server_id))
        await session.execute(delete(Inbound).where(Inbound.server_id == server_id, Inbound.protocol == "mtproto"))
        await session.commit()
    await callback.answer("✅ MTProxy удален из БД", show_alert=True)
    await show_server_services(callback, state, is_admin)

@router.callback_query(F.data.startswith("awg_desync_restore_db_"))
async def awg_desync_restore_db(callback: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    server_id = int(callback.data.split("_")[-1])
    
    msg = await callback.message.edit_text("🔄 <b>Восстановление AWG из БД...</b>\n\nНачинаю установку...", parse_mode="HTML")
    
    try:
        async with async_session_factory() as session:
            from sqlalchemy import select
            from sqlalchemy.orm import selectinload
            from app.database.models import Server, AWGInboundConnection, Inbound

            server = (await session.execute(select(Server).options(selectinload(Server.awg_service)).where(Server.id == server_id))).scalar_one()
            
            from app.services.installers.awg_installer import AWGInstaller
            from app.services.ssh_service import SSHManager
            
            installer = AWGInstaller(SSHManager(server), progress_callback=lambda text: msg.edit_text(f"🔄 <b>Восстановление AWG</b>\n\n{text}", parse_mode="HTML"))
            
            # Need to initialize sudo if needed
            ok, err_msg = await installer.preflight_check()
            if not ok:
                await msg.edit_text(f"❌ Ошибка проверки прав:\n<code>{err_msg}</code>", reply_markup=get_back_keyboard(f"server_services_{server_id}"), parse_mode="HTML")
                return
            
            
            await installer.install(
                port=server.awg_service.port,
                subnet_ip=server.awg_service.subnet_ip,
                subnet_cidr=server.awg_service.subnet_cidr,
                obfuscation=server.awg_service.obfuscation,
                force=True
            )
            
            # Now restore peers
            from app.services.vpn_providers.factory import get_vpn_provider
            
            awg_inbound = (await session.execute(select(Inbound).where(Inbound.server_id == server_id, Inbound.protocol == "awg"))).scalar_one_or_none()
            if awg_inbound:
                connections = (await session.execute(select(AWGInboundConnection).where(AWGInboundConnection.inbound_id == awg_inbound.id))).scalars().all()
                if connections:
                    provider = get_vpn_provider(server, inbound_type="awg_inbound")
                    for conn in connections:
                        if conn.is_enabled:
                            await provider.enable_client(awg_inbound, conn)
                    await provider.close()
            
        await msg.edit_text("✅ <b>AWG успешно восстановлен!</b>\n\nВсе конфигурации и ключи перенесены на сервер.", reply_markup=get_back_keyboard(f"server_services_{server_id}"), parse_mode="HTML")
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Failed to restore AWG: {e}", exc_info=True)
        await msg.edit_text(f"❌ Ошибка восстановления:\n<code>{e}</code>", reply_markup=get_back_keyboard(f"server_services_{server_id}"), parse_mode="HTML")

@router.callback_query(F.data.startswith("mtp_desync_restore_db_"))
async def mtp_desync_restore_db(callback: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    server_id = int(callback.data.split("_")[-1])
    
    msg = await callback.message.edit_text("🔄 <b>Восстановление MTProxy из БД...</b>\n\nНачинаю установку...", parse_mode="HTML")
    
    try:
        async with async_session_factory() as session:
            from sqlalchemy import select
            from sqlalchemy.orm import selectinload
            from app.database.models import Server, MTProxyInboundConnection, Inbound

            server = (await session.execute(select(Server).options(selectinload(Server.mtproxy_service)).where(Server.id == server_id))).scalar_one()
            
            from app.services.installers.mtproxy_installer import MTProxyInstaller
            from app.services.ssh_service import SSHManager
            
            installer = MTProxyInstaller(SSHManager(server), progress_callback=lambda text: msg.edit_text(f"🔄 <b>Восстановление MTProxy</b>\n\n{text}", parse_mode="HTML"))
            
            # Need to initialize sudo if needed
            ok, err_msg = await installer.preflight_check()
            if not ok:
                await msg.edit_text(f"❌ Ошибка проверки прав:\n<code>{err_msg}</code>", reply_markup=get_back_keyboard(f"server_services_{server_id}"), parse_mode="HTML")
                return
            
            
            await installer.install(
                port=server.mtproxy_service.port,
                domain=server.mtproxy_service.domain,
                implementation=server.mtproxy_service.implementation,
                max_connections=server.mtproxy_service.max_connections or 5000,
                force=True
            )
            
            # Restore peers if mtg-multi
            if server.mtproxy_service.implementation == "mtg-multi":
                from app.services.vpn_providers.factory import get_vpn_provider
                mtp_inbound = (await session.execute(select(Inbound).where(Inbound.server_id == server_id, Inbound.protocol == "mtproto"))).scalar_one_or_none()
                if mtp_inbound:
                    connections = (await session.execute(select(MTProxyInboundConnection).where(MTProxyInboundConnection.inbound_id == mtp_inbound.id))).scalars().all()
                    if connections:
                        provider = get_vpn_provider(server, inbound_type="mtproxy_inbound")
                        for conn in connections:
                            if conn.is_enabled:
                                await provider.enable_client(mtp_inbound, conn)
                        await provider.close()
                        
        await msg.edit_text("✅ <b>MTProxy успешно восстановлен!</b>\n\nВсе секреты перенесены на сервер.", reply_markup=get_back_keyboard(f"server_services_{server_id}"), parse_mode="HTML")
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Failed to restore MTProxy: {e}", exc_info=True)
        await msg.edit_text(f"❌ Ошибка восстановления:\n<code>{e}</code>", reply_markup=get_back_keyboard(f"server_services_{server_id}"), parse_mode="HTML")

@router.callback_query(F.data.startswith("xui_desync_restore_db_"))
async def xui_desync_restore_db(callback: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    server_id = int(callback.data.split("_")[-1])
    
    msg = await callback.message.edit_text("🔄 <b>Аварийное восстановление 3x-ui из БД...</b>\n\nНачинаю переустановку панели...", parse_mode="HTML")
    
    try:
        async with async_session_factory() as session:
            from sqlalchemy import select
            from sqlalchemy.orm import selectinload
            from app.database.models import Server

            server = (await session.execute(select(Server).options(selectinload(Server.xui_panel)).where(Server.id == server_id))).scalar_one()
            panel = server.xui_panel
            
            from app.services.installers.xui_installer import XUIInstaller
            from app.services.ssh_service import SSHManager
            from app.utils import decrypt_password
            
            installer = XUIInstaller(SSHManager(server), progress_callback=lambda text: msg.edit_text(f"🔄 <b>Аварийное восстановление 3x-ui</b>\n\n{text}", parse_mode="HTML"))
            
            # Need to initialize sudo if needed
            ok, err_msg = await installer.preflight_check()
            if not ok:
                await msg.edit_text(f"❌ Ошибка проверки прав:\n<code>{err_msg}</code>", reply_markup=get_back_keyboard(f"server_services_{server_id}"), parse_mode="HTML")
                return
            
            
            pwd = decrypt_password(panel.password_encrypted) if panel.password_encrypted else "admin"
            domain = panel.url.split("://")[1].split(":")[0] if panel.url else server.ip_address
            
            await installer.install(
                domain=domain,
                caddy_port=panel.caddy_port or 8443,
                web_path=panel.panel_path or "/",
                sub_path=panel.subscription_path or "/sub/",
                sub_json_path=panel.subscription_json_path or "/json/",
                username=panel.username or "admin",
                password=pwd,
                inbound_ranges=panel.inbound_ranges or [(10000, 10100)],
                force=True
            )
            
            # Now restore inbounds and connections
            from app.xui_client import XUIClient, XUIAddClientRequest
            from app.database.models import Inbound, XUIInboundConnection

            await msg.edit_text("🔄 <b>Аварийное восстановление 3x-ui</b>\n\nВосстановление Inbound'ов и пользователей...", parse_mode="HTML")

            from urllib.parse import urlparse as _urlparse
            _parsed = _urlparse(panel.url or "")
            _scheme = _parsed.scheme or "http"
            _hostname = _parsed.hostname or panel.url or ""
            _port = _parsed.port
            _base_path = panel.panel_path or "/"
            if _parsed.path and _parsed.path != "/" and not panel.panel_path:
                _base_path = _parsed.path
            _port_part = f":{_port}" if _port else ""
            _base_url = f"{_scheme}://{_hostname}{_port_part}{_base_path}"

            async with XUIClient(
                base_url=_base_url,
                username=panel.username or "",
                password=pwd,
                api_token=None,
            ) as client:
                inbounds = (await session.execute(select(Inbound).where(Inbound.server_id == server_id, Inbound.protocol.in_(("vless", "vmess", "trojan", "shadowsocks", "wireguard", "socks", "http"))))).scalars().all()
                for ib in inbounds:
                    payload = {
                        "up": 0, "down": 0, "total": 0, "remark": ib.remark or f"Inbound_{ib.port}",
                        "enable": True, "expiryTime": 0, "listen": "", "port": ib.port, "protocol": ib.protocol,
                        "settings": '{"clients": [], "fallbacks": []}',
                        "streamSettings": '{"network": "tcp", "security": "none", "tcpSettings": {"header": {"type": "none"}}}',
                        "sniffing": '{"enabled": true, "destOverride": ["http", "tls", "quic"], "metadataOnly": false, "routeOnly": false}'
                    }
                    try:
                        await client.add_inbound(payload)
                    except Exception as e:
                        import logging
                        logging.getLogger(__name__).warning(f"Failed to recreate inbound {ib.id} port {ib.port}: {e}")

                    # Add clients to this inbound
                    connections = (await session.execute(select(XUIInboundConnection).where(XUIInboundConnection.inbound_id == ib.id))).scalars().all()
                    for conn in connections:
                        if conn.is_enabled:
                            try:
                                p = conn.provider_payload or {}
                                req = XUIAddClientRequest(
                                    id=conn.uuid or p.get("uuid", ""),
                                    email=conn.email or p.get("email", f"conn-{conn.id}"),
                                    enable=True,
                                    flow=p.get("flow", "xtls-rprx-vision"),
                                    totalGB=p.get("totalGB", 0),
                                    expiryTime=p.get("expiryTime", 0),
                                    subId=p.get("subId", ""),
                                    tgId=p.get("tgId", 0),
                                )
                                await client.add_client(req, [ib.xui_id])
                            except Exception as e:
                                import logging
                                logging.getLogger(__name__).warning(f"Failed to recreate client {conn.id}: {e}")
                                
        await msg.edit_text("✅ <b>Аварийное восстановление 3x-ui завершено!</b>\n\nБазовые настройки и клиенты воссозданы. Тонкие настройки Xray (сертификаты/streamSettings) могли сброситься к значениям по умолчанию.", reply_markup=get_back_keyboard(f"server_services_{server_id}"), parse_mode="HTML")
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Failed to restore 3x-ui: {e}", exc_info=True)
        await msg.edit_text(f"❌ Ошибка восстановления:\n<code>{e}</code>", reply_markup=get_back_keyboard(f"server_services_{server_id}"), parse_mode="HTML")

@router.callback_query(F.data.startswith("xui_desync_restore_file_"))
async def xui_desync_restore_file(callback: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    server_id = int(callback.data.split("_")[-1])
    await state.update_data(server_id=server_id)
    await state.set_state(ServerManagement.waiting_for_restore_file)
    
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Отмена", callback_data=f"server_services_{server_id}")]])
    
    await callback.message.edit_text(
        "📂 <b>Восстановление 3x-ui из бэкапа</b>\n\n"
        "Пожалуйста, отправьте файл <code>x-ui.db</code> в этот чат (как документ).\n"
        "⚠️ <i>Убедитесь, что это именно тот файл от панели, которая была привязана к боту.</i>",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await callback.answer()

@router.message(ServerManagement.waiting_for_restore_file, F.document)
async def process_xui_restore_file(message: TgMessage, state: FSMContext) -> None:
    document = message.document
    if not document.file_name.endswith(".db"):
        await message.answer("❌ Пожалуйста, отправьте файл с расширением .db (например, x-ui.db)")
        return
        
    data = await state.get_data()
    server_id = data.get("server_id")
    if not server_id:
        await message.answer("❌ Ошибка сессии. Начните заново.")
        await state.clear()
        return
        
    msg = await message.answer("🔄 Скачивание файла...")
    
    import base64
    from aiogram import Bot
    
    bot: Bot = message.bot
    file_id = document.file_id
    file_path_tg = (await bot.get_file(file_id)).file_path
    
    # Download file to memory
    file_bytes = await bot.download_file(file_path_tg)
    db_content = file_bytes.read()
    
    # Encode to base64 for safe transfer
    b64_db = base64.b64encode(db_content).decode("ascii")
    
    await msg.edit_text("🔄 <b>Восстановление 3x-ui из файла x-ui.db...</b>\n\nЗагрузка БД на сервер для анализа...", parse_mode="HTML")
    
    try:
        async with async_session_factory() as session:
            from sqlalchemy import select
            from sqlalchemy.orm import selectinload
            from app.database.models import Server

            server = (await session.execute(select(Server).options(selectinload(Server.xui_panel)).where(Server.id == server_id))).scalar_one()
            panel = server.xui_panel
            
            from app.services.installers.xui_installer import XUIInstaller
            from app.services.ssh_service import SSHManager
            from app.utils import decrypt_password
            
            ssh = SSHManager(server)
            installer = XUIInstaller(ssh, progress_callback=lambda text: msg.edit_text(f"🔄 <b>Восстановление 3x-ui (Файл)</b>\n\n{text}", parse_mode="HTML"))
            
            ok, err_msg = await installer.preflight_check()
            if not ok:
                await msg.edit_text(f"❌ Ошибка проверки прав:\n<code>{err_msg}</code>", reply_markup=get_back_keyboard(f"server_services_{server_id}"), parse_mode="HTML")
                return
                
            pwd = decrypt_password(panel.password_encrypted) if panel.password_encrypted else "admin"
            domain = panel.url.split("://")[1].split(":")[0] if panel.url else server.ip_address
            caddy_port = panel.caddy_port or 8443
            
            # 1. Сначала загружаем БД на сервер во временную папку
            tmp_db = "/tmp/x-ui_restore.db"
            # Для больших файлов echo 'huge_b64' ломает SSH сессию
            # Поэтому сначала пишем файл штатным методом asyncssh
            await ssh.write_file(tmp_db + ".b64", b64_db)
            # А затем декодируем его через sudo (чтобы права были нужные)
            await installer._cmd(f"base64 -d {tmp_db}.b64 > {tmp_db}")
            await installer._cmd(f"rm {tmp_db}.b64")
            
            # 2. Анализируем БД прямо на сервере с помощью sqlite3
            await msg.edit_text("🔄 <b>Восстановление 3x-ui (Файл)</b>\n\nИзвлечение путей и портов из БД...", parse_mode="HTML")
            
            # Убедимся, что sqlite3 установлен
            await installer._cmd("apt-get update -yq && apt-get install -yq sqlite3 || yum install -yq sqlite || apk add --no-cache sqlite")
            
            # Читаем пути
            web_path = await installer._cmd(f"sqlite3 {tmp_db} \"SELECT value FROM settings WHERE key='webBasePath'\" 2>/dev/null || echo ''")
            sub_path = await installer._cmd(f"sqlite3 {tmp_db} \"SELECT value FROM settings WHERE key='subPath'\" 2>/dev/null || echo ''")
            sub_json_path = await installer._cmd(f"sqlite3 {tmp_db} \"SELECT value FROM settings WHERE key='subJsonPath'\" 2>/dev/null || echo ''")
            
            web_path = web_path.strip() or "/"
            sub_path = sub_path.strip() or "/sub/"
            sub_json_path = sub_json_path.strip() or "/json/"
            
            # Читаем порты инбаундов
            inbound_ports_raw = await installer._cmd(f"sqlite3 {tmp_db} \"SELECT port FROM inbounds\" 2>/dev/null || echo ''")
            inbound_ranges = []
            for port_str in inbound_ports_raw.strip().split('\n'):
                if port_str.strip().isdigit():
                    p = int(port_str.strip())
                    inbound_ranges.append((p, p))
                    
            if not inbound_ranges:
                inbound_ranges = panel.inbound_ranges or [(10000, 10100)]
                
            await msg.edit_text(f"🔄 <b>Восстановление 3x-ui (Файл)</b>\n\nПути: {web_path}\nИнбаунды: {len(inbound_ranges)} шт.\n\nНачинаю установку...", parse_mode="HTML")
            
            # 3. Выполняем установку с извлеченными параметрами
            await installer.install(
                domain=domain,
                caddy_port=caddy_port,
                web_path=web_path,
                sub_path=sub_path,
                sub_json_path=sub_json_path,
                username=panel.username or "admin",
                password=pwd,
                inbound_ranges=inbound_ranges,
                force=True
            )
            
            # 4. Переносим файл БД в контейнер
            await msg.edit_text("🔄 <b>Восстановление 3x-ui (Файл)</b>\n\nЗамещение БД в контейнере...", parse_mode="HTML")
            await installer._cmd("docker stop vpnbot-xui")
            await installer._cmd(f"mv {tmp_db} /opt/vpnbot/xui/db/x-ui.db")
            await installer._cmd("docker start vpnbot-xui")
            import asyncio
            await asyncio.sleep(3)
            
            # 5. Принудительно перезаписываем пароль/домен в БД, чтобы гарантировать доступ бота к API
            await msg.edit_text("🔄 <b>Восстановление 3x-ui (Файл)</b>\n\nСинхронизация учетных данных бота...", parse_mode="HTML")
            await installer._configure_xui(
                username=panel.username or "admin",
                password=pwd,
                web_path=web_path,
                sub_path=sub_path,
                sub_json_path=sub_json_path,
                domain=domain,
                caddy_port=caddy_port
            )
            
            # 6. Обновляем пути и диапазоны в БД бота
            panel.panel_path = web_path
            panel.subscription_path = sub_path
            panel.subscription_json_path = sub_json_path
            panel.inbound_ranges = inbound_ranges
            await session.commit()
            
        await msg.edit_text("✅ <b>Панель 3x-ui успешно восстановлена из файла!</b>", reply_markup=get_back_keyboard(f"server_services_{server_id}"), parse_mode="HTML")
        await state.clear()
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Failed to restore 3x-ui from file: {e}", exc_info=True)
        await msg.edit_text(f"❌ Ошибка восстановления:\n<code>{e}</code>", reply_markup=get_back_keyboard(f"server_services_{server_id}"), parse_mode="HTML")
        await state.clear()

@router.callback_query(F.data.startswith("awg_desync_remove_db_"))
async def awg_desync_remove_db(callback: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    server_id = int(callback.data.split("_")[-1])
    async with async_session_factory() as session:
        from sqlalchemy import delete
        from app.database.models import AWGService, Inbound
        await session.execute(delete(AWGService).where(AWGService.server_id == server_id))
        await session.execute(delete(Inbound).where(Inbound.server_id == server_id, Inbound.protocol == "awg"))
        await session.commit()
    await callback.answer("✅ AWG удален из БД", show_alert=True)
    await show_server_services(callback, state, is_admin)

@router.callback_query(F.data.startswith("mtp_desync_remove_db_"))
async def mtp_desync_remove_db(callback: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    server_id = int(callback.data.split("_")[-1])
    async with async_session_factory() as session:
        from sqlalchemy import delete
        from app.database.models import MTProxyService, Inbound
        await session.execute(delete(MTProxyService).where(MTProxyService.server_id == server_id))
        await session.execute(delete(Inbound).where(Inbound.server_id == server_id, Inbound.protocol == "mtproto"))
        await session.commit()
    await callback.answer("✅ MTProxy удален из БД", show_alert=True)
    await show_server_services(callback, state, is_admin)

@router.callback_query(F.data.startswith("awg_desync_restore_db_"))
async def awg_desync_restore_db(callback: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    server_id = int(callback.data.split("_")[-1])
    
    msg = await callback.message.edit_text("🔄 <b>Восстановление AWG из БД...</b>\n\nНачинаю установку...", parse_mode="HTML")
    
    try:
        async with async_session_factory() as session:
            from sqlalchemy import select
            from sqlalchemy.orm import selectinload
            from app.database.models import Server, AWGInboundConnection, Inbound

            server = (await session.execute(select(Server).options(selectinload(Server.awg_service)).where(Server.id == server_id))).scalar_one()
            
            from app.services.installers.awg_installer import AWGInstaller
            from app.services.ssh_service import SSHManager
            
            installer = AWGInstaller(SSHManager(server), progress_callback=lambda text: msg.edit_text(f"🔄 <b>Восстановление AWG</b>\n\n{text}", parse_mode="HTML"))
            
            # Need to initialize sudo if needed
            ok, err_msg = await installer.preflight_check()
            if not ok:
                await msg.edit_text(f"❌ Ошибка проверки прав:\n<code>{err_msg}</code>", reply_markup=get_back_keyboard(f"server_services_{server_id}"), parse_mode="HTML")
                return
            
            
            await installer.install(
                port=server.awg_service.port,
                subnet_ip=server.awg_service.subnet_ip,
                subnet_cidr=server.awg_service.subnet_cidr,
                obfuscation=server.awg_service.obfuscation,
                force=True
            )
            
            # Now restore peers
            from app.services.vpn_providers.factory import get_vpn_provider
            
            awg_inbound = (await session.execute(select(Inbound).where(Inbound.server_id == server_id, Inbound.protocol == "awg"))).scalar_one_or_none()
            if awg_inbound:
                connections = (await session.execute(select(AWGInboundConnection).where(AWGInboundConnection.inbound_id == awg_inbound.id))).scalars().all()
                if connections:
                    provider = get_vpn_provider(server, inbound_type="awg_inbound")
                    for conn in connections:
                        if conn.is_enabled:
                            await provider.enable_client(awg_inbound, conn)
                    await provider.close()
            
        await msg.edit_text("✅ <b>AWG успешно восстановлен!</b>\n\nВсе конфигурации и ключи перенесены на сервер.", reply_markup=get_back_keyboard(f"server_services_{server_id}"), parse_mode="HTML")
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Failed to restore AWG: {e}", exc_info=True)
        await msg.edit_text(f"❌ Ошибка восстановления:\n<code>{e}</code>", reply_markup=get_back_keyboard(f"server_services_{server_id}"), parse_mode="HTML")

@router.callback_query(F.data.startswith("mtp_desync_restore_db_"))
async def mtp_desync_restore_db(callback: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    server_id = int(callback.data.split("_")[-1])
    
    msg = await callback.message.edit_text("🔄 <b>Восстановление MTProxy из БД...</b>\n\nНачинаю установку...", parse_mode="HTML")
    
    try:
        async with async_session_factory() as session:
            from sqlalchemy import select
            from sqlalchemy.orm import selectinload
            from app.database.models import Server, MTProxyInboundConnection, Inbound

            server = (await session.execute(select(Server).options(selectinload(Server.mtproxy_service)).where(Server.id == server_id))).scalar_one()
            
            from app.services.installers.mtproxy_installer import MTProxyInstaller
            from app.services.ssh_service import SSHManager
            
            installer = MTProxyInstaller(SSHManager(server), progress_callback=lambda text: msg.edit_text(f"🔄 <b>Восстановление MTProxy</b>\n\n{text}", parse_mode="HTML"))
            
            # Need to initialize sudo if needed
            ok, err_msg = await installer.preflight_check()
            if not ok:
                await msg.edit_text(f"❌ Ошибка проверки прав:\n<code>{err_msg}</code>", reply_markup=get_back_keyboard(f"server_services_{server_id}"), parse_mode="HTML")
                return
            
            
            await installer.install(
                port=server.mtproxy_service.port,
                domain=server.mtproxy_service.domain,
                implementation=server.mtproxy_service.implementation,
                max_connections=server.mtproxy_service.max_connections or 5000,
                force=True
            )
            
            # Restore peers if mtg-multi
            if server.mtproxy_service.implementation == "mtg-multi":
                from app.services.vpn_providers.factory import get_vpn_provider
                mtp_inbound = (await session.execute(select(Inbound).where(Inbound.server_id == server_id, Inbound.protocol == "mtproto"))).scalar_one_or_none()
                if mtp_inbound:
                    connections = (await session.execute(select(MTProxyInboundConnection).where(MTProxyInboundConnection.inbound_id == mtp_inbound.id))).scalars().all()
                    if connections:
                        provider = get_vpn_provider(server, inbound_type="mtproxy_inbound")
                        for conn in connections:
                            if conn.is_enabled:
                                await provider.enable_client(mtp_inbound, conn)
                        await provider.close()
                        
        await msg.edit_text("✅ <b>MTProxy успешно восстановлен!</b>\n\nВсе секреты перенесены на сервер.", reply_markup=get_back_keyboard(f"server_services_{server_id}"), parse_mode="HTML")
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Failed to restore MTProxy: {e}", exc_info=True)
        await msg.edit_text(f"❌ Ошибка восстановления:\n<code>{e}</code>", reply_markup=get_back_keyboard(f"server_services_{server_id}"), parse_mode="HTML")

@router.callback_query(F.data.startswith("xui_desync_restore_db_"))
async def xui_desync_restore_db(callback: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    server_id = int(callback.data.split("_")[-1])
    
    msg = await callback.message.edit_text("🔄 <b>Аварийное восстановление 3x-ui из БД...</b>\n\nНачинаю переустановку панели...", parse_mode="HTML")
    
    try:
        async with async_session_factory() as session:
            from sqlalchemy import select
            from sqlalchemy.orm import selectinload
            from app.database.models import Server

            server = (await session.execute(select(Server).options(selectinload(Server.xui_panel)).where(Server.id == server_id))).scalar_one()
            panel = server.xui_panel
            
            from app.services.installers.xui_installer import XUIInstaller
            from app.services.ssh_service import SSHManager
            from app.utils import decrypt_password
            
            installer = XUIInstaller(SSHManager(server), progress_callback=lambda text: msg.edit_text(f"🔄 <b>Аварийное восстановление 3x-ui</b>\n\n{text}", parse_mode="HTML"))
            
            # Need to initialize sudo if needed
            ok, err_msg = await installer.preflight_check()
            if not ok:
                await msg.edit_text(f"❌ Ошибка проверки прав:\n<code>{err_msg}</code>", reply_markup=get_back_keyboard(f"server_services_{server_id}"), parse_mode="HTML")
                return
            
            
            pwd = decrypt_password(panel.password_encrypted) if panel.password_encrypted else "admin"
            domain = panel.url.split("://")[1].split(":")[0] if panel.url else server.ip_address
            
            await installer.install(
                domain=domain,
                caddy_port=panel.caddy_port or 8443,
                web_path=panel.panel_path or "/",
                sub_path=panel.subscription_path or "/sub/",
                sub_json_path=panel.subscription_json_path or "/json/",
                username=panel.username or "admin",
                password=pwd,
                inbound_ranges=panel.inbound_ranges or [(10000, 10100)],
                force=True
            )
            
            # Now restore inbounds and connections
            from app.xui_client import XUIClient, XUIAddClientRequest
            from app.database.models import Inbound, XUIInboundConnection

            await msg.edit_text("🔄 <b>Аварийное восстановление 3x-ui</b>\n\nВосстановление Inbound'ов и пользователей...", parse_mode="HTML")

            from urllib.parse import urlparse as _urlparse
            _parsed = _urlparse(panel.url or "")
            _scheme = _parsed.scheme or "http"
            _hostname = _parsed.hostname or panel.url or ""
            _port = _parsed.port
            _base_path = panel.panel_path or "/"
            if _parsed.path and _parsed.path != "/" and not panel.panel_path:
                _base_path = _parsed.path
            _port_part = f":{_port}" if _port else ""
            _base_url = f"{_scheme}://{_hostname}{_port_part}{_base_path}"

            async with XUIClient(
                base_url=_base_url,
                username=panel.username or "",
                password=pwd,
                api_token=None,
            ) as client:
                inbounds = (await session.execute(select(Inbound).where(Inbound.server_id == server_id, Inbound.protocol.in_(("vless", "vmess", "trojan", "shadowsocks", "wireguard", "socks", "http"))))).scalars().all()
                for ib in inbounds:
                    payload = {
                        "up": 0, "down": 0, "total": 0, "remark": ib.remark or f"Inbound_{ib.port}",
                        "enable": True, "expiryTime": 0, "listen": "", "port": ib.port, "protocol": ib.protocol,
                        "settings": '{"clients": [], "fallbacks": []}',
                        "streamSettings": '{"network": "tcp", "security": "none", "tcpSettings": {"header": {"type": "none"}}}',
                        "sniffing": '{"enabled": true, "destOverride": ["http", "tls", "quic"], "metadataOnly": false, "routeOnly": false}'
                    }
                    try:
                        await client.add_inbound(payload)
                    except Exception as e:
                        import logging
                        logging.getLogger(__name__).warning(f"Failed to recreate inbound {ib.id} port {ib.port}: {e}")

                    # Add clients to this inbound
                    connections = (await session.execute(select(XUIInboundConnection).where(XUIInboundConnection.inbound_id == ib.id))).scalars().all()
                    for conn in connections:
                        if conn.is_enabled:
                            try:
                                p = conn.provider_payload or {}
                                req = XUIAddClientRequest(
                                    id=conn.uuid or p.get("uuid", ""),
                                    email=conn.email or p.get("email", f"conn-{conn.id}"),
                                    enable=True,
                                    flow=p.get("flow", "xtls-rprx-vision"),
                                    totalGB=p.get("totalGB", 0),
                                    expiryTime=p.get("expiryTime", 0),
                                    subId=p.get("subId", ""),
                                    tgId=p.get("tgId", 0),
                                )
                                await client.add_client(req, [ib.xui_id])
                            except Exception as e:
                                import logging
                                logging.getLogger(__name__).warning(f"Failed to recreate client {conn.id}: {e}")
                                
        await msg.edit_text("✅ <b>Аварийное восстановление 3x-ui завершено!</b>\n\nБазовые настройки и клиенты воссозданы. Тонкие настройки Xray (сертификаты/streamSettings) могли сброситься к значениям по умолчанию.", reply_markup=get_back_keyboard(f"server_services_{server_id}"), parse_mode="HTML")
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Failed to restore 3x-ui: {e}", exc_info=True)
        await msg.edit_text(f"❌ Ошибка восстановления:\n<code>{e}</code>", reply_markup=get_back_keyboard(f"server_services_{server_id}"), parse_mode="HTML")

@router.callback_query(F.data.startswith("xui_desync_restore_file_"))
async def xui_desync_restore_file(callback: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    server_id = int(callback.data.split("_")[-1])
    await state.update_data(server_id=server_id)
    await state.set_state(ServerManagement.waiting_for_restore_file)
    
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Отмена", callback_data=f"server_services_{server_id}")]])
    
    await callback.message.edit_text(
        "📂 <b>Восстановление 3x-ui из бэкапа</b>\n\n"
        "Пожалуйста, отправьте файл <code>x-ui.db</code> в этот чат (как документ).\n"
        "⚠️ <i>Убедитесь, что это именно тот файл от панели, которая была привязана к боту.</i>",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await callback.answer()

@router.message(ServerManagement.waiting_for_restore_file, F.document)
async def process_xui_restore_file(message: TgMessage, state: FSMContext) -> None:
    document = message.document
    if not document.file_name.endswith(".db"):
        await message.answer("❌ Пожалуйста, отправьте файл с расширением .db (например, x-ui.db)")
        return
        
    data = await state.get_data()
    server_id = data.get("server_id")
    if not server_id:
        await message.answer("❌ Ошибка сессии. Начните заново.")
        await state.clear()
        return
        
    msg = await message.answer("🔄 Скачивание файла...")
    
    import base64
    from aiogram import Bot
    
    bot: Bot = message.bot
    file_id = document.file_id
    file_path_tg = (await bot.get_file(file_id)).file_path
    
    # Download file to memory
    file_bytes = await bot.download_file(file_path_tg)
    db_content = file_bytes.read()
    
    # Encode to base64 for safe transfer
    b64_db = base64.b64encode(db_content).decode("ascii")
    
    await msg.edit_text("🔄 <b>Восстановление 3x-ui из файла x-ui.db...</b>\n\nНачинаю переустановку панели...", parse_mode="HTML")
    
    try:
        async with async_session_factory() as session:
            from sqlalchemy import select
            from sqlalchemy.orm import selectinload
            from app.database.models import Server

            server = (await session.execute(select(Server).options(selectinload(Server.xui_panel)).where(Server.id == server_id))).scalar_one()
            panel = server.xui_panel
            
            from app.services.installers.xui_installer import XUIInstaller
            from app.services.ssh_service import SSHManager
            from app.utils import decrypt_password
            
            ssh = SSHManager(server)
            installer = XUIInstaller(ssh, progress_callback=lambda text: msg.edit_text(f"🔄 <b>Восстановление 3x-ui (Файл)</b>\n\n{text}", parse_mode="HTML"))
            
            # Need to initialize sudo if needed
            ok, err_msg = await installer.preflight_check()
            if not ok:
                await msg.edit_text(f"❌ Ошибка проверки прав:\n<code>{err_msg}</code>", reply_markup=get_back_keyboard(f"server_services_{server_id}"), parse_mode="HTML")
                return
            
            
            pwd = decrypt_password(panel.password_encrypted) if panel.password_encrypted else "admin"
            domain = panel.url.split("://")[1].split(":")[0] if panel.url else server.ip_address
            
            # 1. Install fresh panel first
            await installer.install(
                domain=domain,
                caddy_port=panel.caddy_port or 8443,
                web_path=panel.panel_path or "/",
                sub_path=panel.subscription_path or "/sub/",
                sub_json_path=panel.subscription_json_path or "/json/",
                username=panel.username or "admin",
                password=pwd,
                inbound_ranges=panel.inbound_ranges or [(10000, 10100)],
                force=True
            )
            
            await msg.edit_text("🔄 <b>Восстановление 3x-ui (Файл)</b>\n\nЗагрузка вашей БД x-ui.db на сервер...", parse_mode="HTML")
            
            # 2. Stop container, upload db, restart container
            await installer._cmd("docker stop vpnbot-xui")
            
            # Write base64 to server and decode it to binary file
            remote_path = "/opt/vpnbot/xui/db/x-ui.db"
            await installer._cmd(f"echo '{b64_db}' | base64 -d > {remote_path}")
            
            # 3. Patch the DB with bot's credentials and paths (runs sqlite3 inside container)
            await installer._cmd("docker start vpnbot-xui")
            import asyncio
            await asyncio.sleep(3)
            
            await msg.edit_text("🔄 <b>Восстановление 3x-ui (Файл)</b>\n\nПрименение настроек панели...", parse_mode="HTML")
            
            await installer._configure_xui(
                username=panel.username or "admin",
                password=pwd,
                web_path=panel.panel_path,
                sub_path=panel.subscription_path,
                sub_json_path=panel.subscription_json_path,
                domain=domain,
                caddy_port=panel.caddy_port
            )
            
        await msg.edit_text("✅ <b>Панель 3x-ui успешно восстановлена из файла!</b>", reply_markup=get_back_keyboard(f"server_services_{server_id}"), parse_mode="HTML")
        await state.clear()
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Failed to restore 3x-ui from file: {e}", exc_info=True)
        await msg.edit_text(f"❌ Ошибка восстановления:\n<code>{e}</code>", reply_markup=get_back_keyboard(f"server_services_{server_id}"), parse_mode="HTML")
        await state.clear()
