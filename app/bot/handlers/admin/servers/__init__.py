"""Admin server management handlers."""

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from aiogram.types import Message as TgMessage
from loguru import logger

from app.bot.handlers.admin.servers import (
    crud,
    first_setup,
    monitoring,
    services,
    ssh,
    xui_edit,
    xui_install,
)
from app.bot.handlers.admin.servers.first_setup import _check_first_setup
from app.bot.handlers.admin.servers.services import show_server_services
from app.bot.keyboards import get_back_keyboard
from app.bot.states import AWGInstall, MTProxyInstall, ServerManagement
from app.database import async_session_factory
from app.utils.texts import t

router = Router()
router.include_router(crud.router)
router.include_router(services.router)
router.include_router(first_setup.router)
router.include_router(ssh.router)
router.include_router(monitoring.router)
router.include_router(xui_install.router)
router.include_router(xui_edit.router)



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

                ssh = SSHManager(server, session=session)
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

            ssh = SSHManager(server, session=session)
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

        from app.database.models import Inbound, XUIPanel
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

        from app.database.models import Inbound, MTProxyService
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

            from app.database.models import AWGInboundConnection, Inbound, Server

            server = (await session.execute(select(Server).options(selectinload(Server.awg_service)).where(Server.id == server_id))).scalar_one()

            from app.services.installers.awg_installer import AWGInstaller
            from app.services.ssh_service import SSHManager

            installer = AWGInstaller(SSHManager(server, session=session), progress_callback=lambda text: msg.edit_text(f"🔄 <b>Восстановление AWG</b>\n\n{text}", parse_mode="HTML"))

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
        logger.error(f"Failed to restore AWG: {e}", exc_info=True)
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
        logger.error(f"Failed to restore MTProxy: {e}", exc_info=True)
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

            installer = XUIInstaller(SSHManager(server, session=session), progress_callback=lambda text: msg.edit_text(f"🔄 <b>Аварийное восстановление 3x-ui</b>\n\n{text}", parse_mode="HTML"))

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
            from app.database.models import Inbound, XUIInboundConnection
            from app.xui_client import XUIAddClientRequest, XUIClient

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
                        logger.warning(f"Failed to recreate inbound {ib.id} port {ib.port}: {e}")

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
                                logger.warning(f"Failed to recreate client {conn.id}: {e}")

        await msg.edit_text("✅ <b>Аварийное восстановление 3x-ui завершено!</b>\n\nБазовые настройки и клиенты воссозданы. Тонкие настройки Xray (сертификаты/streamSettings) могли сброситься к значениям по умолчанию.", reply_markup=get_back_keyboard(f"server_services_{server_id}"), parse_mode="HTML")
    except Exception as e:
        logger.error(f"Failed to restore 3x-ui: {e}", exc_info=True)
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

            ssh = SSHManager(server, session=session)
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
        logger.error(f"Failed to restore 3x-ui from file: {e}", exc_info=True)
        await msg.edit_text(f"❌ Ошибка восстановления:\n<code>{e}</code>", reply_markup=get_back_keyboard(f"server_services_{server_id}"), parse_mode="HTML")
        await state.clear()
