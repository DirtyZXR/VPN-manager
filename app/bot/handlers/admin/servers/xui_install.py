"""Установка/подключение панели 3x-ui: FSM-цепочка XUIInstall + connect/reinstall."""

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from aiogram.types import Message as TgMessage
from loguru import logger

from app.bot.handlers.admin.servers.first_setup import _check_first_setup
from app.bot.keyboards import get_back_keyboard
from app.bot.states import XUIInstall
from app.database import async_session_factory
from app.utils.texts import t

router = Router()


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
        from app.services.installers.xui_installer import XUIInstaller, _sql_str
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
            f"UPDATE users SET password='{_sql_str(hashed)}' WHERE id=1"
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

                ssh = SSHManager(server, session=session)
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

            ssh = SSHManager(server, session=session)
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
