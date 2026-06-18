"""First-setup: firewall-политика и SSH-порт перед установкой инсталлятора."""

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from aiogram.types import Message as TgMessage

from app.bot.keyboards import get_back_keyboard
from app.bot.states import FirstSetup
from app.database import async_session_factory

router = Router()


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
        await callback.message.answer(
            f"❌ Ошибка проверки прав SSH:\n<code>{err_msg}</code>", parse_mode="HTML"
        )
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
        from app.bot.handlers.admin.servers.awg import _awg_ask_port
        await _awg_ask_port(message, state)
    elif target == "xui":
        from app.bot.handlers.admin.servers.xui_install import _xui_ask_domain
        await _xui_ask_domain(message, state)
    elif target == "mtproxy":
        from app.bot.handlers.admin.servers.mtproxy import _mtproxy_ask_implementation
        await _mtproxy_ask_implementation(message, state)
    else:
        server_id = data.get("server_id", 0)
        await state.clear()
        await message.edit_text(
            "⚠️ Не удалось продолжить установку.",
            reply_markup=get_back_keyboard(f"server_services_{server_id}"),
        )
