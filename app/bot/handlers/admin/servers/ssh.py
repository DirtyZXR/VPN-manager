"""Настройка SSH-доступа к серверу: user → port → auth, тест соединения."""

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from aiogram.types import Message as TgMessage
from loguru import logger

from app.bot.handlers.admin.servers._shared import show_server_details
from app.bot.keyboards import get_back_keyboard
from app.bot.states import ServerManagement
from app.database import async_session_factory
from app.services.xui_service import XUIService
from app.utils.texts import t

router = Router()


@router.callback_query(F.data.startswith("server_setup_ssh_"))
async def start_ssh_setup(callback: CallbackQuery, state: FSMContext) -> None:
    """Start SSH setup for a server."""
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
        logger.warning("Не удалось удалить сообщение: {}", e)
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
