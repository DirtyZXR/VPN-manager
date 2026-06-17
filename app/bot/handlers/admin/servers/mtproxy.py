"""Домен MTProxy: установка/подключение, реализации mtg/mtg-multi, desync-восстановление."""

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from aiogram.types import Message as TgMessage
from loguru import logger

from app.bot.handlers.admin.servers.first_setup import _check_first_setup
from app.bot.handlers.admin.servers.services import show_server_services
from app.bot.keyboards import get_back_keyboard
from app.bot.states import MTProxyInstall
from app.database import async_session_factory
from app.utils.texts import t

router = Router()


@router.callback_query(F.data.startswith("server_edit_mtproxy_"))
async def edit_mtproxy_service(callback: CallbackQuery) -> None:
    """Edit MTProxy service or show desync menu."""
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


# ── MTProxy Installation Flow ─────────────────────────────────────────


@router.callback_query(F.data.startswith("server_install_mtproxy_"))
async def start_mtproxy_install(callback: CallbackQuery, state: FSMContext) -> None:
    """Start MTProxy installation."""
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
        logger.error("Ошибка авто-обнаружения MTProxy: {}", e, exc_info=True)
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
        logger.error("Ошибка подключения MTProxy: {}", e, exc_info=True)
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

                ssh = SSHManager(server, session=session)
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
            logger.error("Ошибка установки MTProxy: {}", e, exc_info=True)
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
        logger.error("Ошибка переустановки MTProxy: {}", e, exc_info=True)
        await msg.edit_text(
            f"❌ <b>Ошибка переустановки MTProxy</b>\n\n<code>{e}</code>",
            reply_markup=get_back_keyboard(f"server_services_{server_id}"),
            parse_mode="HTML",
        )


# ── Desync Recovery Handlers ──────────────────────────────────────

@router.callback_query(F.data.startswith("mtp_desync_remove_db_"))
async def mtp_desync_remove_db(callback: CallbackQuery, state: FSMContext) -> None:
    server_id = int(callback.data.split("_")[-1])
    async with async_session_factory() as session:
        from sqlalchemy import delete

        from app.database.models import Inbound, MTProxyService
        await session.execute(delete(MTProxyService).where(MTProxyService.server_id == server_id))
        await session.execute(delete(Inbound).where(Inbound.server_id == server_id, Inbound.protocol == "mtproto"))
        await session.commit()
    await callback.answer("✅ MTProxy удален из БД", show_alert=True)
    await show_server_services(callback, state)

@router.callback_query(F.data.startswith("mtp_desync_restore_db_"))
async def mtp_desync_restore_db(callback: CallbackQuery, state: FSMContext) -> None:
    server_id = int(callback.data.split("_")[-1])

    msg = await callback.message.edit_text("🔄 <b>Восстановление MTProxy из БД...</b>\n\nНачинаю установку...", parse_mode="HTML")

    try:
        async with async_session_factory() as session:
            from sqlalchemy import select
            from sqlalchemy.orm import selectinload

            from app.database.models import Inbound, MTProxyInboundConnection, Server

            server = (await session.execute(select(Server).options(selectinload(Server.mtproxy_service)).where(Server.id == server_id))).scalar_one()

            from app.services.installers.mtproxy_installer import MTProxyInstaller
            from app.services.ssh_service import SSHManager

            installer = MTProxyInstaller(SSHManager(server, session=session), progress_callback=lambda text: msg.edit_text(f"🔄 <b>Восстановление MTProxy</b>\n\n{text}", parse_mode="HTML"))

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
        logger.error("Ошибка восстановления MTProxy: {}", e, exc_info=True)
        await msg.edit_text(f"❌ Ошибка восстановления:\n<code>{e}</code>", reply_markup=get_back_keyboard(f"server_services_{server_id}"), parse_mode="HTML")
