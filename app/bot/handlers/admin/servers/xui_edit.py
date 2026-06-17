"""Редактирование панели 3x-ui: креды, пути, токен, SSL."""

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from aiogram.types import Message as TgMessage
from loguru import logger

from app.bot.keyboards import get_back_keyboard
from app.bot.states import ServerManagement
from app.database import async_session_factory
from app.services.xui_service import XUIService
from app.utils.texts import t

router = Router()


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
