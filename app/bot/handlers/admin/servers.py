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

    from app.bot.keyboards.inline import get_server_panel_type_keyboard

    await callback.message.edit_text(
        t("admin.servers.select_type", "Выберите тип панели для нового сервера:"),
        reply_markup=get_server_panel_type_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "add_server_type_xui")
async def add_server_type_xui(callback: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    """Start adding new XUI server."""
    if not is_admin:
        return

    await state.set_state(ServerManagement.waiting_for_name)
    await callback.message.edit_text(
        t(
            "admin.servers.add_name",
            "➕ Добавление нового сервера 3x-ui\n\nВведите название сервера (например, 'NL-Server-1'):",
        ),
        reply_markup=get_back_keyboard("server_add"),
    )
    await callback.answer()


@router.callback_query(F.data == "add_server_type_amnezia")
async def add_server_type_amnezia(
    callback: CallbackQuery, state: FSMContext, is_admin: bool
) -> None:
    """Start adding new Amnezia server."""
    if not is_admin:
        return

    await state.update_data(panel_type="amnezia")
    await state.set_state(ServerManagement.waiting_for_amnezia_api_url)
    await callback.message.edit_text(
        t(
            "admin.servers.add_amnezia_url",
            "🛡 Добавление Amnezia PHP Panel\n\nВведите API URL сервера Amnezia (например, https://vpn.example.com):",
        ),
        reply_markup=get_back_keyboard("server_add"),
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
    await state.set_state(ServerManagement.waiting_for_base_url)
    await message.answer(
        t(
            "admin.servers.add_url",
            "Введите базовый адрес сервера (например, https://example.com):",
        ),
        reply_markup=get_back_keyboard("admin_servers"),
    )


@router.message(ServerManagement.waiting_for_base_url)
async def process_server_base_url(message: TgMessage, state: FSMContext) -> None:
    """Process server base URL input."""
    url = message.text.strip()

    if not url:
        await message.answer(
            t("admin.servers.errors.empty_url", "❌ URL не может быть пустым."),
            reply_markup=get_back_keyboard("admin_servers"),
        )
        return

    if not url.startswith(("http://", "https://")):
        await message.answer(
            t(
                "admin.servers.errors.invalid_url_scheme",
                "❌ URL должен начинаться с http:// или https://",
            ),
            reply_markup=get_back_keyboard("admin_servers"),
        )
        return

    if len(url) > 500:
        await message.answer(
            t("admin.servers.errors.url_too_long", "❌ URL не должен превышать 500 символов."),
            reply_markup=get_back_keyboard("admin_servers"),
        )
        return

    await state.update_data(url=url)
    await state.set_state(ServerManagement.waiting_for_panel_path)
    await message.answer(
        t(
            "admin.servers.add_panel_path",
            "Введите путь к панели управления (опционально).\n\n❗ Важно: пути нужно указывать с обоих сторон со слешами (/path/)\n\nЕсли не указать, будет использоваться / (корневой путь).\n\nПримеры:\n• /panel/ - для стандартной установки\n• /xui/ - для кастомного пути\n\nОтправьте /skip чтобы использовать значение по умолчанию (/).",
        ),
        reply_markup=get_back_keyboard("admin_servers"),
    )


@router.message(ServerManagement.waiting_for_panel_path)
async def process_server_panel_path(message: TgMessage, state: FSMContext) -> None:
    """Process panel path input."""
    if message.text == "/skip":
        await state.update_data(panel_path="/")
    else:
        panel_path = message.text.strip()
        if panel_path:
            if len(panel_path) > 500:
                await message.answer(
                    t(
                        "admin.servers.errors.path_too_long",
                        "❌ Путь не должен превышать 500 символов.",
                    ),
                    reply_markup=get_back_keyboard("admin_servers"),
                )
                return
            # Ensure path starts with /
            if not panel_path.startswith("/"):
                panel_path = "/" + panel_path
            # Ensure path ends with / (except for root)
            if panel_path != "/" and not panel_path.endswith("/"):
                panel_path = panel_path + "/"
        else:
            panel_path = "/"
        await state.update_data(panel_path=panel_path)

    await state.set_state(ServerManagement.waiting_for_subscription_path)
    await message.answer(
        t(
            "admin.servers.add_sub_path",
            "Введите путь для подписок (опционально).\n\n❗ Важно: пути нужно указывать с обоих сторон со слешами (/path/)\n\nЕсли не указать, будет использоваться /sub/\n\nПримеры:\n• /sub/ - стандартный путь\n• /custom/sub/ - кастомный путь\n\nОтправьте /skip чтобы использовать значение по умолчанию (/sub/).",
        ),
        reply_markup=get_back_keyboard("admin_servers"),
    )


@router.message(ServerManagement.waiting_for_subscription_path)
async def process_server_subscription_path(message: TgMessage, state: FSMContext) -> None:
    """Process subscription path input."""
    if message.text == "/skip":
        await state.update_data(subscription_path="/sub/")
    else:
        subscription_path = message.text.strip()
        if subscription_path:
            if len(subscription_path) > 500:
                await message.answer(
                    t(
                        "admin.servers.errors.path_too_long",
                        "❌ Путь не должен превышать 500 символов.",
                    ),
                    reply_markup=get_back_keyboard("admin_servers"),
                )
                return
            # Ensure path starts with /
            if not subscription_path.startswith("/"):
                subscription_path = "/" + subscription_path
            # Ensure path ends with /
            if not subscription_path.endswith("/"):
                subscription_path = subscription_path + "/"
        else:
            subscription_path = "/sub/"
        await state.update_data(subscription_path=subscription_path)

    await state.set_state(ServerManagement.waiting_for_subscription_json_path)
    await message.answer(
        t(
            "admin.servers.add_json_path",
            "Введите путь для JSON подписок (опционально).\n\n❗ Важно: пути нужно указывать с обоих сторон со слешами (/path/)\n\nЕсли не указать, будет использоваться /subjson/\n\nПримеры:\n• /subjson/ - стандартный путь\n• /custom/json/ - кастомный путь\n\nОтправьте /skip чтобы использовать значение по умолчанию (/subjson/).",
        ),
        reply_markup=get_back_keyboard("admin_servers"),
    )


@router.message(ServerManagement.waiting_for_subscription_json_path)
async def process_server_subscription_json_path(message: TgMessage, state: FSMContext) -> None:
    """Process subscription JSON path input."""
    if message.text == "/skip":
        await state.update_data(subscription_json_path="/subjson/")
    else:
        subscription_json_path = message.text.strip()
        if subscription_json_path:
            if len(subscription_json_path) > 500:
                await message.answer(
                    t(
                        "admin.servers.errors.path_too_long",
                        "❌ Путь не должен превышать 500 символов.",
                    ),
                    reply_markup=get_back_keyboard("admin_servers"),
                )
                return
            # Ensure path starts with /
            if not subscription_json_path.startswith("/"):
                subscription_json_path = "/" + subscription_json_path
            # Ensure path ends with /
            if not subscription_json_path.endswith("/"):
                subscription_json_path = subscription_json_path + "/"
        else:
            subscription_json_path = "/subjson/"
        await state.update_data(subscription_json_path=subscription_json_path)

    await state.set_state(ServerManagement.waiting_for_username)
    await message.answer(
        t(
            "admin.servers.add_url",
            "Введите базовый адрес сервера (например, https://example.com):",
        ),
        reply_markup=get_back_keyboard("admin_servers"),
    )


@router.message(ServerManagement.waiting_for_username)
async def process_server_username(message: TgMessage, state: FSMContext) -> None:
    """Process server username input."""
    username = message.text.strip()

    if not username:
        await message.answer(
            t("admin.servers.errors.empty_username", "❌ Имя пользователя не может быть пустым."),
            reply_markup=get_back_keyboard("admin_servers"),
        )
        return

    if len(username) > 100:
        await message.answer(
            t(
                "admin.servers.errors.username_too_long",
                "❌ Имя пользователя не должно превышать 100 символов.",
            ),
            reply_markup=get_back_keyboard("admin_servers"),
        )
        return

    await state.update_data(username=username)
    await state.set_state(ServerManagement.waiting_for_password)
    await message.answer(
        t("admin.servers.add_password", "Введите пароль для входа в панель:"),
        reply_markup=get_back_keyboard("admin_servers"),
    )


@router.message(ServerManagement.waiting_for_password)
async def process_server_password(message: TgMessage, state: FSMContext) -> None:
    """Process server password input and ask for SSL verification."""
    await state.get_data()
    password = message.text

    if not password:
        await message.answer(
            t("admin.servers.errors.empty_password", "❌ Пароль не может быть пустым."),
            reply_markup=get_back_keyboard("admin_servers"),
        )
        return

    await state.update_data(password=password)
    await state.set_state(ServerManagement.waiting_for_verify_ssl)

    from aiogram.utils.keyboard import InlineKeyboardBuilder

    kb = InlineKeyboardBuilder()
    kb.button(
        text=t("admin.servers.buttons.verify_ssl_yes", "✅ Да (рекомендуется)"),
        callback_data="verify_ssl_yes",
    )
    kb.button(
        text=t("admin.servers.buttons.verify_ssl_no", "❌ Нет (для самоподписанных сертификатов)"),
        callback_data="verify_ssl_no",
    )
    kb.adjust(1)

    await message.answer(
        t(
            "admin.servers.add_ssl",
            "Проверять SSL сертификат при подключении к серверу?\n\n⚠️ Отключение проверки небезопасно и рекомендуется только для серверов с самоподписанными или проблемными сертификатами.",
        ),
        reply_markup=kb.as_markup(),
    )


@router.callback_query(F.data.startswith("verify_ssl_"))
async def process_verify_ssl_selection(callback: CallbackQuery, state: FSMContext) -> None:
    """Process SSL verification selection and create server."""
    data = await state.get_data()
    verify_ssl = callback.data == "verify_ssl_yes"

    # Test connection before creating server
    await callback.message.edit_text(
        t("admin.servers.testing_connection", "🔄 Проверка подключения к серверу..."),
        reply_markup=None,
    )

    async with async_session_factory() as session:
        service = XUIService(session)

        try:
            # Create temporary client to test connection
            from urllib.parse import urljoin

            from app.xui_client import XUIClient, XUIError

            # Build full URL with panel path for testing
            panel_path = data.get("panel_path", "/")
            test_base_url = urljoin(data["url"], panel_path)

            test_client = XUIClient(
                base_url=test_base_url,
                username=data["username"],
                password=data["password"],
                timeout=30,
                verify_ssl=verify_ssl,
            )

            await test_client.connect()
            inbounds = await test_client.get_inbounds()
            await test_client.close()

            # Connection successful, create server
            server = await service.create_server(
                name=data["name"],
                url=data["url"],
                username=data["username"],
                password=data["password"],
                verify_ssl=verify_ssl,
                panel_path=data.get("panel_path", "/"),
                subscription_path=data.get("subscription_path", "/sub/"),
                subscription_json_path=data.get("subscription_json_path", "/subjson/"),
            )
            await session.flush()

            server_id = server.id

            # Sync inbounds automatically
            try:
                synced_inbounds = await service.sync_server_inbounds(server_id)
                await session.commit()
                logger.info(
                    "✅ Автосинхронизация сервера {}: {} inbounds", server_id, synced_inbounds
                )
            except Exception as sync_error:
                logger.error("❌ Ошибка синхронизации inbounds: {}", sync_error, exc_info=True)
                await session.rollback()  # Rollback sync but keep server
                # Re-commit just the server creation
                await session.commit()

            await state.clear()
            ssl_status_text = (
                t("admin.servers.ssl_enabled", "Включена")
                if verify_ssl
                else t("admin.servers.ssl_disabled", "Отключена")
            )
            synced_text = (
                synced_inbounds
                if "synced_inbounds" in locals()
                else t("admin.servers.sync_error", "Ошибка")
            )
            await callback.message.edit_text(
                t(
                    "admin.servers.added_success",
                    "✅ Сервер '{name}' успешно добавлен!\n\nURL: {url}\nПроверка SSL: {ssl_status}\nНайдено inbounds: {inbounds_count}\nСинхронизировано inbounds: {synced_count}",
                    name=server.name,
                    url=server.url,
                    ssl_status=ssl_status_text,
                    inbounds_count=len(inbounds),
                    synced_count=synced_text,
                ),
                reply_markup=get_back_keyboard("admin_servers"),
            )

        except XUIError as e:
            logger.error("Connection test failed: {}", e, exc_info=True)

            # Check if it's an SSL error
            if "SSL" in str(e) or "tls" in str(e).lower():
                from aiogram.utils.keyboard import InlineKeyboardBuilder

                kb = InlineKeyboardBuilder()
                kb.button(
                    text=t("admin.servers.buttons.cancel", "❌ Нет, отменить"),
                    callback_data="cancel_ssl_bypass",
                )
                kb.button(
                    text=t(
                        "admin.servers.buttons.retry_without_ssl", "✅ Да, попробовать без проверки"
                    ),
                    callback_data="retry_without_ssl",
                )
                kb.adjust(1)

                await callback.message.edit_text(
                    t(
                        "admin.servers.errors.ssl_error",
                        "❌ Ошибка SSL сертификата:\n{error}\n\nХотите попробовать подключиться без проверки SSL сертификата?",
                        error=str(e),
                    ),
                    reply_markup=kb.as_markup(),
                )
            else:
                await callback.message.edit_text(
                    t(
                        "admin.servers.errors.connection_failed",
                        "❌ Не удалось подключиться к серверу:\n{error}\n\nПроверьте URL, логин и пароль.",
                        error=str(e),
                    ),
                    reply_markup=get_back_keyboard("admin_servers"),
                )
                await state.clear()

        except Exception as e:
            logger.error("Unexpected error: {}", e, exc_info=True)
            await callback.message.edit_text(
                t(
                    "admin.servers.errors.unexpected",
                    "❌ Ошибка при проверке сервера:\n{error}",
                    error=str(e),
                ),
                reply_markup=get_back_keyboard("admin_servers"),
            )
            await state.clear()

    await callback.answer()


@router.callback_query(F.data == "retry_without_ssl")
async def retry_without_ssl(callback: CallbackQuery, state: FSMContext) -> None:
    """Retry connection without SSL verification."""
    data = await state.get_data()

    await callback.message.edit_text(
        t(
            "admin.servers.testing_connection_no_ssl",
            "🔄 Повторная проверка подключения к серверу (без SSL)...",
        ),
        reply_markup=None,
    )

    async with async_session_factory() as session:
        service = XUIService(session)

        try:
            from urllib.parse import urljoin

            from app.xui_client import XUIClient, XUIError

            # Build full URL with panel path for testing
            panel_path = data.get("panel_path", "/")
            test_base_url = urljoin(data["url"], panel_path)

            test_client = XUIClient(
                base_url=test_base_url,
                username=data["username"],
                password=data["password"],
                timeout=30,
                verify_ssl=False,  # Disable SSL verification
            )

            await test_client.connect()
            inbounds = await test_client.get_inbounds()
            await test_client.close()

            # Connection successful, create server with SSL verification disabled
            server = await service.create_server(
                name=data["name"],
                url=data["url"],
                username=data["username"],
                password=data["password"],
                verify_ssl=False,  # Store this setting
                panel_path=data.get("panel_path", "/"),
                subscription_path=data.get("subscription_path", "/sub/"),
                subscription_json_path=data.get("subscription_json_path", "/subjson/"),
            )
            await session.flush()

            server_name = server.name
            server_url = server.url
            server_id = server.id

            # Sync inbounds automatically
            try:
                synced_inbounds = await service.sync_server_inbounds(server_id)
                await session.commit()
                logger.info(
                    "✅ Автосинхронизация сервера {}: {} inbounds", server_id, synced_inbounds
                )
            except Exception as sync_error:
                logger.error("❌ Ошибка синхронизации inbounds: {}", sync_error, exc_info=True)
                await session.rollback()  # Rollback sync but keep server
                # Re-commit just the server creation
                await session.commit()

            await state.clear()
            synced_text = (
                synced_inbounds
                if "synced_inbounds" in locals()
                else t("admin.servers.sync_error", "Ошибка")
            )
            await callback.message.edit_text(
                t(
                    "admin.servers.added_success_no_ssl",
                    "✅ Сервер '{name}' успешно добавлен!\n\nURL: {url}\n⚠️ Проверка SSL: ОТКЛЮЧЕНА\nНайдено inbounds: {inbounds_count}\nСинхронизировано inbounds: {synced_count}",
                    name=server_name,
                    url=server_url,
                    inbounds_count=len(inbounds),
                    synced_count=synced_text,
                ),
                reply_markup=get_back_keyboard("admin_servers"),
            )

        except XUIError as e:
            logger.error("Connection test failed even without SSL: {}", e, exc_info=True)
            await callback.message.edit_text(
                t(
                    "admin.servers.errors.connection_failed_no_ssl",
                    "❌ Не удалось подключиться к серверу даже без проверки SSL:\n{error}\n\nПроверьте URL, логин и пароль.",
                    error=str(e),
                ),
                reply_markup=get_back_keyboard("admin_servers"),
            )
            await state.clear()

        except Exception as e:
            logger.error("Unexpected error: {}", e, exc_info=True)
            await callback.message.edit_text(
                t(
                    "admin.servers.errors.unexpected",
                    "❌ Ошибка при проверке сервера:\n{error}",
                    error=str(e),
                ),
                reply_markup=get_back_keyboard("admin_servers"),
            )
            await state.clear()

    await callback.answer()


@router.callback_query(F.data == "cancel_ssl_bypass")
async def cancel_ssl_bypass(callback: CallbackQuery, state: FSMContext) -> None:
    """Cancel SSL bypass and return to server list."""
    await state.clear()
    await callback.message.edit_text(
        t("admin.servers.add_cancelled", "❌ Добавление сервера отменено."),
        reply_markup=get_back_keyboard("admin_servers"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("server_select_"))
async def select_server(callback: CallbackQuery, is_admin: bool) -> None:
    """Show server details."""
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

    status = (
        t("admin.servers.status.active", "✅ Активен")
        if server.is_active
        else t("admin.servers.status.inactive", "❌ Неактивен")
    )
    last_sync = (
        server.last_sync_at.strftime("%d.%m.%Y %H:%M")
        if server.last_sync_at
        else t("admin.servers.sync.never", "Никогда")
    )
    ssl_status = "✅" if server.verify_ssl else "❌"

    # Get paths with defaults
    panel_path = getattr(server, "panel_path", "/")
    subscription_path = getattr(server, "subscription_path", "/sub/")
    subscription_json_path = getattr(server, "subscription_json_path", "/subjson/")

    if server.panel_type == "xui":
        text = t(
            "admin.servers.info",
            "🖥️ Сервер: {name}\n\n🌐 URL: {url}\n📁 Путь панели: {panel_path}\n📝 Путь подписок: {sub_path}\n📋 Путь JSON: {json_path}\n👤 Логин: {username}\n🔒 SSL: {ssl_status}\n📊 Статус: {status}\n🔄 Последняя синхронизация: {last_sync}",
            name=server.name,
            url=server.url,
            panel_path=panel_path,
            sub_path=subscription_path,
            json_path=subscription_json_path,
            username=server.username,
            ssl_status=ssl_status,
            status=status,
            last_sync=last_sync,
        )
    else:
        text = t(
            "admin.servers.info_amnezia",
            "🖥️ Сервер: {name}\n\n🌐 URL: {url}\n👤 Логин: {username}\n🔒 SSL: {ssl_status}\n📊 Статус: {status}\n🔄 Последняя синхронизация: {last_sync}",
            name=server.name,
            url=server.url,
            username=server.username,
            ssl_status=ssl_status,
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
    if server.is_active:
        builder.append(
            {
                "text": t("admin.servers.buttons.disable", "❌ Отключить"),
                "callback_data": f"server_disable_{server_id}",
            }
        )
    else:
        builder.append(
            {
                "text": t("admin.servers.buttons.enable", "✅ Включить"),
                "callback_data": f"server_enable_{server_id}",
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
            from app.database.models import Server

            server = await session.get(Server, server_id)
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

        if getattr(server, "panel_type", "xui") == "amnezia":
            from app.amnezia_client import AmneziaError
            from app.services.vpn_providers.amnezia_provider import AmneziaProvider

            try:
                provider = AmneziaProvider(server)
                client = await provider._get_client()
                # Test connection with an API call
                await client.get_server_stats(1)
                success, message = True, "Подключение к Amnezia Panel успешно."
            except AmneziaError as e:
                success, message = False, f"Ошибка подключения: {e}"
            except Exception as e:
                success, message = False, f"Ошибка: {e}"
            finally:
                if "provider" in locals():
                    await provider.close()
        else:
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
                clients=inbound.client_count,
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


@router.callback_query(F.data.startswith("server_enable_"))
async def enable_server(callback: CallbackQuery, is_admin: bool) -> None:
    """Enable server."""
    if not is_admin:
        await callback.answer(
            t("admin.errors.no_rights", "❌ У вас нет прав администратора."), show_alert=True
        )
        return

    server_id = int(callback.data.split("_")[-1])

    async with async_session_factory() as session:
        service = XUIService(session)
        await service.update_server(server_id, is_active=True)
        await session.commit()

    await callback.answer(t("admin.servers.enabled", "✅ Сервер включен."))
    await select_server(callback, is_admin)


@router.callback_query(F.data.startswith("server_disable_"))
async def disable_server(callback: CallbackQuery, is_admin: bool) -> None:
    """Disable server."""
    if not is_admin:
        await callback.answer(
            t("admin.errors.no_rights", "❌ У вас нет прав администратора."), show_alert=True
        )
        return

    server_id = int(callback.data.split("_")[-1])

    async with async_session_factory() as session:
        service = XUIService(session)
        await service.update_server(server_id, is_active=False)
        await session.commit()

    await callback.answer(t("admin.servers.disabled", "✅ Сервер отключен."))
    await select_server(callback, is_admin)


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

    # Get paths with defaults
    panel_path = getattr(server, "panel_path", "/")
    subscription_path = getattr(server, "subscription_path", "/sub/")
    subscription_json_path = getattr(server, "subscription_json_path", "/subjson/")

    builder = []
    builder.append(
        {
            "text": t("admin.servers.buttons.edit_name", "✏️ Название"),
            "callback_data": "edit_server_name",
        }
    )
    builder.append(
        {
            "text": t("admin.servers.buttons.edit_url", "🌐 URL сервера"),
            "callback_data": "edit_server_url",
        }
    )
    if server.panel_type == "xui":
        builder.append(
            {
                "text": t("admin.servers.buttons.edit_panel_path", "📁 Путь панели"),
                "callback_data": "edit_server_panel_path",
            }
        )
        builder.append(
            {
                "text": t("admin.servers.buttons.edit_sub_path", "📝 Путь подписок"),
                "callback_data": "edit_server_sub_path",
            }
        )
        builder.append(
            {
                "text": t("admin.servers.buttons.edit_json_path", "📋 Путь JSON"),
                "callback_data": "edit_server_json_path",
            }
        )
    builder.append(
        {
            "text": t("admin.servers.buttons.edit_username", "👤 Логин"),
            "callback_data": "edit_server_username",
        }
    )
    builder.append(
        {
            "text": t("admin.servers.buttons.edit_password", "🔒 Пароль"),
            "callback_data": "edit_server_password",
        }
    )
    builder.append(
        {"text": t("admin.servers.buttons.edit_ssl", "🔐 SSL"), "callback_data": "edit_server_ssl"}
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

    if server.panel_type == "xui":
        text = t(
            "admin.servers.edit_menu",
            "✏️ Редактирование сервера: <b>{name}</b>\n\n🌐 URL: {url}\n📁 Путь панели: {panel_path}\n📝 Путь подписок: {sub_path}\n📋 Путь JSON: {json_path}\n👤 Логин: {username}\n\nВыберите поле для редактирования:",
            name=server.name,
            url=server.url,
            panel_path=panel_path,
            sub_path=subscription_path,
            json_path=subscription_json_path,
            username=server.username,
        )
    else:
        text = t(
            "admin.servers.edit_menu_amnezia",
            "✏️ Редактирование сервера: <b>{name}</b>\n\n🌐 URL: {url}\n👤 Логин: {username}\n\nВыберите поле для редактирования:",
            name=server.name,
            url=server.url,
            username=server.username,
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


@router.callback_query(F.data == "edit_server_url")
async def start_edit_url(callback: CallbackQuery, state: FSMContext) -> None:
    """Start editing server URL."""
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

    await state.set_state(ServerManagement.waiting_for_edit_base_url)
    await callback.message.edit_text(
        t(
            "admin.servers.edit_url",
            "✏️ Редактирование URL сервера\n\nТекущий URL: <b>{url}</b>\n\nВведите новый URL (или /skip чтобы оставить текущий):",
            url=server.url,
        ),
        reply_markup=get_back_keyboard(f"server_select_{server_id}"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(ServerManagement.waiting_for_edit_base_url)
async def process_edit_url(message: TgMessage, state: FSMContext) -> None:
    """Process server URL edit."""
    data = await state.get_data()
    server_id = data["server_id"]
    new_url = message.text.strip()

    if new_url == "/skip":
        await show_server_details(message, state, server_id)
        return

    if not new_url:
        await message.answer(t("admin.servers.errors.empty_url", "❌ URL не может быть пустым."))
        return

    if not new_url.startswith(("http://", "https://")):
        await message.answer(
            t(
                "admin.servers.errors.invalid_url_scheme",
                "❌ URL должен начинаться с http:// или https://",
            )
        )
        return

    if len(new_url) > 500:
        await message.answer(
            t("admin.servers.errors.url_too_long", "❌ URL не должен превышать 500 символов.")
        )
        return

    async with async_session_factory() as session:
        service = XUIService(session)
        server = await service.update_server(server_id, url=new_url)
        if server:
            await session.commit()
            await message.answer(
                t("admin.servers.url_changed", "✅ URL изменен на: {url}", url=new_url)
            )

    await edit_server_menu(message, state, server_id)


@router.callback_query(F.data == "edit_server_panel_path")
async def start_edit_panel_path(callback: CallbackQuery, state: FSMContext) -> None:
    """Start editing panel path."""
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

    panel_path = getattr(server, "panel_path", "/")

    await state.set_state(ServerManagement.waiting_for_edit_panel_path)
    await callback.message.edit_text(
        t(
            "admin.servers.edit_panel_path",
            "✏️ Редактирование пути панели\n\nТекущий путь: <b>{path}</b>\n\nВведите новый путь (или /skip чтобы оставить текущий).\n\n❗ Важно: путь нужно указывать с обоих сторон со слешами (/path/)",
            path=panel_path,
        ),
        reply_markup=get_back_keyboard(f"server_select_{server_id}"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(ServerManagement.waiting_for_edit_panel_path)
async def process_edit_panel_path(message: TgMessage, state: FSMContext) -> None:
    """Process panel path edit."""
    data = await state.get_data()
    server_id = data["server_id"]
    new_path = message.text.strip()

    if new_path == "/skip":
        await show_server_details(message, state, server_id)
        return

    if new_path:
        if len(new_path) > 500:
            await message.answer(
                t("admin.servers.errors.path_too_long", "❌ Путь не должен превышать 500 символов.")
            )
            return
        # Ensure path starts with /
        if not new_path.startswith("/"):
            new_path = "/" + new_path
        # Ensure path ends with / (except for root)
        if new_path != "/" and not new_path.endswith("/"):
            new_path = new_path + "/"
    else:
        new_path = "/"

    async with async_session_factory() as session:
        service = XUIService(session)
        server = await service.update_server(server_id, panel_path=new_path)
        if server:
            await session.commit()
            await message.answer(
                t(
                    "admin.servers.panel_path_changed",
                    "✅ Путь панели изменен на: {path}",
                    path=new_path,
                )
            )

    await edit_server_menu(message, state, server_id)


@router.callback_query(F.data == "edit_server_sub_path")
async def start_edit_subscription_path(callback: CallbackQuery, state: FSMContext) -> None:
    """Start editing subscription path."""
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

    subscription_path = getattr(server, "subscription_path", "/sub/")

    await state.set_state(ServerManagement.waiting_for_edit_subscription_path)
    await callback.message.edit_text(
        t(
            "admin.servers.edit_sub_path",
            "✏️ Редактирование пути подписок\n\nТекущий путь: <b>{path}</b>\n\nВведите новый путь (или /skip чтобы оставить текущий).\n\n❗ Важно: путь нужно указывать с обоих сторон со слешами (/path/)",
            path=subscription_path,
        ),
        reply_markup=get_back_keyboard(f"server_select_{server_id}"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(ServerManagement.waiting_for_edit_subscription_path)
async def process_edit_subscription_path(message: TgMessage, state: FSMContext) -> None:
    """Process subscription path edit."""
    data = await state.get_data()
    server_id = data["server_id"]
    new_path = message.text.strip()

    if new_path == "/skip":
        await show_server_details(message, state, server_id)
        return

    if new_path:
        if len(new_path) > 500:
            await message.answer(
                t("admin.servers.errors.path_too_long", "❌ Путь не должен превышать 500 символов.")
            )
            return
        # Ensure path starts with /
        if not new_path.startswith("/"):
            new_path = "/" + new_path
        # Ensure path ends with /
        if not new_path.endswith("/"):
            new_path = new_path + "/"
    else:
        new_path = "/sub/"

    async with async_session_factory() as session:
        service = XUIService(session)
        server = await service.update_server(server_id, subscription_path=new_path)
        if server:
            await session.commit()
            await message.answer(
                t(
                    "admin.servers.sub_path_changed",
                    "✅ Путь подписок изменен на: {path}",
                    path=new_path,
                )
            )

    await edit_server_menu(message, state, server_id)


@router.callback_query(F.data == "edit_server_json_path")
async def start_edit_json_path(callback: CallbackQuery, state: FSMContext) -> None:
    """Start editing JSON subscription path."""
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

    subscription_json_path = getattr(server, "subscription_json_path", "/subjson/")

    await state.set_state(ServerManagement.waiting_for_edit_subscription_json_path)
    await callback.message.edit_text(
        t(
            "admin.servers.edit_json_path",
            "✏️ Редактирование пути JSON подписок\n\nТекущий путь: <b>{path}</b>\n\nВведите новый путь (или /skip чтобы оставить текущий).\n\n❗ Важно: путь нужно указывать с обоих сторон со слешами (/path/)",
            path=subscription_json_path,
        ),
        reply_markup=get_back_keyboard(f"server_select_{server_id}"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(ServerManagement.waiting_for_edit_subscription_json_path)
async def process_edit_json_path(message: TgMessage, state: FSMContext) -> None:
    """Process JSON subscription path edit."""
    data = await state.get_data()
    server_id = data["server_id"]
    new_path = message.text.strip()

    if new_path == "/skip":
        await show_server_details(message, state, server_id)
        return

    if new_path:
        if len(new_path) > 500:
            await message.answer(
                t("admin.servers.errors.path_too_long", "❌ Путь не должен превышать 500 символов.")
            )
            return
        # Ensure path starts with /
        if not new_path.startswith("/"):
            new_path = "/" + new_path
        # Ensure path ends with /
        if not new_path.endswith("/"):
            new_path = new_path + "/"
    else:
        new_path = "/subjson/"

    async with async_session_factory() as session:
        service = XUIService(session)
        server = await service.update_server(server_id, subscription_json_path=new_path)
        if server:
            await session.commit()
            await message.answer(
                t(
                    "admin.servers.json_path_changed",
                    "✅ Путь JSON подписок изменен на: {path}",
                    path=new_path,
                )
            )

    await edit_server_menu(message, state, server_id)


@router.callback_query(F.data == "edit_server_username")
async def start_edit_username(callback: CallbackQuery, state: FSMContext) -> None:
    """Start editing username."""
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

    await state.set_state(ServerManagement.waiting_for_edit_username)
    await callback.message.edit_text(
        t(
            "admin.servers.edit_username",
            "✏️ Редактирование логина\n\nТекущий логин: <b>{username}</b>\n\nВведите новый логин (или /skip чтобы оставить текущий):",
            username=server.username,
        ),
        reply_markup=get_back_keyboard(f"server_select_{server_id}"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(ServerManagement.waiting_for_edit_username)
async def process_edit_username(message: TgMessage, state: FSMContext) -> None:
    """Process username edit."""
    data = await state.get_data()
    server_id = data["server_id"]
    new_username = message.text.strip()

    if new_username == "/skip":
        await show_server_details(message, state, server_id)
        return

    if not new_username:
        await message.answer(
            t("admin.servers.errors.empty_username", "❌ Имя пользователя не может быть пустым.")
        )
        return

    if len(new_username) > 100:
        await message.answer(
            t(
                "admin.servers.errors.username_too_long",
                "❌ Имя пользователя не должно превышать 100 символов.",
            )
        )
        return

    async with async_session_factory() as session:
        service = XUIService(session)
        server = await service.update_server(server_id, username=new_username)
        if server:
            await session.commit()
            await message.answer(
                t(
                    "admin.servers.username_changed",
                    "✅ Логин изменен на: {username}",
                    username=new_username,
                )
            )

    await edit_server_menu(message, state, server_id)


@router.callback_query(F.data == "edit_server_password")
async def start_edit_password(callback: CallbackQuery, state: FSMContext) -> None:
    """Start editing password."""
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

    await state.set_state(ServerManagement.waiting_for_edit_password)
    await callback.message.edit_text(
        t(
            "admin.servers.edit_password",
            "✏️ Редактирование пароля\n\nВведите новый пароль (или /skip чтобы оставить текущий):",
        ),
        reply_markup=get_back_keyboard(f"server_select_{server_id}"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(ServerManagement.waiting_for_edit_password)
async def process_edit_password(message: TgMessage, state: FSMContext) -> None:
    """Process password edit."""
    data = await state.get_data()
    server_id = data["server_id"]
    new_password = message.text

    if new_password == "/skip":
        await show_server_details(message, state, server_id)
        return

    if not new_password:
        await message.answer(
            t("admin.servers.errors.empty_password", "❌ Пароль не может быть пустым.")
        )
        return

    async with async_session_factory() as session:
        service = XUIService(session)
        server = await service.update_server(server_id, password=new_password)
        if server:
            await session.commit()
            await message.answer(t("admin.servers.password_changed", "✅ Пароль изменен"))

    await edit_server_menu(message, state, server_id)


@router.callback_query(F.data == "edit_server_ssl")
async def start_edit_ssl(callback: CallbackQuery, state: FSMContext) -> None:
    """Start editing SSL verification."""
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

    await state.set_state(ServerManagement.waiting_for_edit_verify_ssl)
    current_ssl = (
        t("admin.servers.ssl_enabled", "✅ Включена")
        if server.verify_ssl
        else t("admin.servers.ssl_disabled", "❌ Отключена")
    )

    from aiogram.utils.keyboard import InlineKeyboardBuilder

    kb = InlineKeyboardBuilder()
    kb.button(
        text=t("admin.servers.buttons.enable_ssl", "✅ Включить"), callback_data="edit_ssl_enable"
    )
    kb.button(
        text=t("admin.servers.buttons.disable_ssl", "❌ Отключить"),
        callback_data="edit_ssl_disable",
    )
    kb.adjust(1)

    await callback.message.edit_text(
        t(
            "admin.servers.edit_ssl",
            "✏️ Редактирование проверки SSL\n\nТекущее состояние: {current}\n\nВыберите новое состояние:",
            current=current_ssl,
        ),
        reply_markup=kb.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("edit_ssl_"))
async def process_edit_ssl(callback: CallbackQuery, state: FSMContext) -> None:
    """Process SSL verification edit."""
    data = await state.get_data()
    server_id = data["server_id"]
    new_ssl = callback.data == "edit_ssl_enable"

    async with async_session_factory() as session:
        service = XUIService(session)
        server = await service.update_server(server_id, verify_ssl=new_ssl)
        if server:
            await session.commit()
            ssl_text = (
                t("admin.servers.ssl_enabled", "✅ Включена")
                if new_ssl
                else t("admin.servers.ssl_disabled", "❌ Отключена")
            )
            await callback.message.edit_text(
                t("admin.servers.ssl_changed", "✅ Проверка SSL: {status}", status=ssl_text)
            )

    await edit_server_menu(callback.message, state, server_id)


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

    # Get paths with defaults
    panel_path = getattr(server, "panel_path", "/")
    subscription_path = getattr(server, "subscription_path", "/sub/")
    subscription_json_path = getattr(server, "subscription_json_path", "/subjson/")

    builder = []
    builder.append(
        {
            "text": t("admin.servers.buttons.edit_name", "✏️ Название"),
            "callback_data": "edit_server_name",
        }
    )
    builder.append(
        {
            "text": t("admin.servers.buttons.edit_url", "🌐 URL сервера"),
            "callback_data": "edit_server_url",
        }
    )
    if server.panel_type == "xui":
        builder.append(
            {
                "text": t("admin.servers.buttons.edit_panel_path", "📁 Путь панели"),
                "callback_data": "edit_server_panel_path",
            }
        )
        builder.append(
            {
                "text": t("admin.servers.buttons.edit_sub_path", "📝 Путь подписок"),
                "callback_data": "edit_server_sub_path",
            }
        )
        builder.append(
            {
                "text": t("admin.servers.buttons.edit_json_path", "📋 Путь JSON"),
                "callback_data": "edit_server_json_path",
            }
        )
    builder.append(
        {
            "text": t("admin.servers.buttons.edit_username", "👤 Логин"),
            "callback_data": "edit_server_username",
        }
    )
    builder.append(
        {
            "text": t("admin.servers.buttons.edit_password", "🔒 Пароль"),
            "callback_data": "edit_server_password",
        }
    )
    builder.append(
        {"text": t("admin.servers.buttons.edit_ssl", "🔐 SSL"), "callback_data": "edit_server_ssl"}
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

    if server.panel_type == "xui":
        text = t(
            "admin.servers.edit_menu",
            "✏️ Редактирование сервера: <b>{name}</b>\n\n🌐 URL: {url}\n📁 Путь панели: {panel_path}\n📝 Путь подписок: {sub_path}\n📋 Путь JSON: {json_path}\n👤 Логин: {username}\n\nВыберите поле для редактирования:",
            name=server.name,
            url=server.url,
            panel_path=panel_path,
            sub_path=subscription_path,
            json_path=subscription_json_path,
            username=server.username,
        )
    else:
        text = t(
            "admin.servers.edit_menu_amnezia",
            "✏️ Редактирование сервера: <b>{name}</b>\n\n🌐 URL: {url}\n👤 Логин: {username}\n\nВыберите поле для редактирования:",
            name=server.name,
            url=server.url,
            username=server.username,
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
        if server.is_active
        else t("admin.servers.status.inactive", "❌ Неактивен")
    )
    last_sync = (
        server.last_sync_at.strftime("%d.%m.%Y %H:%M")
        if server.last_sync_at
        else t("admin.servers.sync.never", "Никогда")
    )
    ssl_status = "✅" if server.verify_ssl else "❌"

    # Get paths with defaults
    panel_path = getattr(server, "panel_path", "/")
    subscription_path = getattr(server, "subscription_path", "/sub/")
    subscription_json_path = getattr(server, "subscription_json_path", "/subjson/")

    if server.panel_type == "xui":
        text = t(
            "admin.servers.info",
            "🖥️ Сервер: {name}\n\n🌐 URL: {url}\n📁 Путь панели: {panel_path}\n📝 Путь подписок: {sub_path}\n📋 Путь JSON: {json_path}\n👤 Логин: {username}\n🔒 SSL: {ssl_status}\n📊 Статус: {status}\n🔄 Последняя синхронизация: {last_sync}",
            name=server.name,
            url=server.url,
            panel_path=panel_path,
            sub_path=subscription_path,
            json_path=subscription_json_path,
            username=server.username,
            ssl_status=ssl_status,
            status=status,
            last_sync=last_sync,
        )
    else:
        text = t(
            "admin.servers.info_amnezia",
            "🖥️ Сервер: {name}\n\n🌐 URL: {url}\n👤 Логин: {username}\n🔒 SSL: {ssl_status}\n📊 Статус: {status}\n🔄 Последняя синхронизация: {last_sync}",
            name=server.name,
            url=server.url,
            username=server.username,
            ssl_status=ssl_status,
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
    if server.is_active:
        builder.append(
            {
                "text": t("admin.servers.buttons.disable", "❌ Отключить"),
                "callback_data": f"server_disable_{server_id}",
            }
        )
    else:
        builder.append(
            {
                "text": t("admin.servers.buttons.enable", "✅ Включить"),
                "callback_data": f"server_enable_{server_id}",
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


# ==========================================
# Amnezia Server Addition Flow
# ==========================================


@router.message(ServerManagement.waiting_for_amnezia_api_url)
async def process_amnezia_api_url(message: TgMessage, state: FSMContext) -> None:
    """Process Amnezia API URL input."""
    url = message.text.strip()
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"

    await state.update_data(url=url)
    await state.set_state(ServerManagement.waiting_for_amnezia_username)
    await message.answer(
        t("admin.servers.add_amnezia_email", "Введите Email (логин) для Amnezia:"),
        reply_markup=get_back_keyboard("server_add"),
    )


@router.message(ServerManagement.waiting_for_amnezia_username)
async def process_amnezia_username(message: TgMessage, state: FSMContext) -> None:
    """Process Amnezia username input."""
    await state.update_data(username=message.text.strip())
    await state.set_state(ServerManagement.waiting_for_amnezia_password)
    await message.answer(
        t("admin.servers.add_amnezia_password", "Введите пароль для Amnezia:"),
        reply_markup=get_back_keyboard("server_add"),
    )


@router.message(ServerManagement.waiting_for_amnezia_password)
async def process_amnezia_password(message: TgMessage, state: FSMContext) -> None:
    """Process Amnezia password input and ask for SSL verification."""
    await state.update_data(password=message.text.strip())
    await state.set_state(ServerManagement.waiting_for_amnezia_verify_ssl)

    from aiogram.utils.keyboard import InlineKeyboardBuilder

    kb = InlineKeyboardBuilder()
    kb.button(
        text=t("admin.servers.buttons.verify_ssl_yes", "✅ Да (рекомендуется)"),
        callback_data="amnezia_verify_ssl_yes",
    )
    kb.button(
        text=t("admin.servers.buttons.verify_ssl_no", "❌ Нет (для самоподписанных сертификатов)"),
        callback_data="amnezia_verify_ssl_no",
    )
    kb.adjust(1)

    await message.answer(
        t(
            "admin.servers.add_amnezia_ssl",
            "Включить проверку SSL сертификата?\n\n"
            "Рекомендуется оставить включенной. Отключайте только если "
            "вы используете самоподписанный сертификат.",
        ),
        reply_markup=kb.as_markup(),
    )


@router.callback_query(F.data.startswith("amnezia_verify_ssl_"))
async def process_amnezia_verify_ssl(callback: CallbackQuery, state: FSMContext) -> None:
    """Process SSL verification selection and save Amnezia server."""
    logger.info("Starting Amnezia server creation")
    verify_ssl = callback.data == "amnezia_verify_ssl_yes"
    data = await state.get_data()

    await callback.message.edit_text(
        t("admin.servers.saving", "⏳ Подключение и сохранение сервера..."),
        reply_markup=None,
    )

    from urllib.parse import urlparse

    from sqlalchemy import select

    from app.amnezia_client.client import AmneziaClient
    from app.database.models import Inbound, Server

    api_url = data.get("url", "")
    if not api_url.startswith("http://") and not api_url.startswith("https://"):
        api_url = f"https://{api_url}"
    if not api_url.endswith("/api"):
        api_url = api_url.rstrip("/") + "/api"

    # Validate credentials with Amnezia API BEFORE creating DB record
    logger.info("Connecting to Amnezia API to validate credentials")
    client = AmneziaClient(
        base_url=api_url,
        email=data.get("username", ""),
        password=data.get("password", ""),
        verify_ssl=verify_ssl,
    )

    amnezia_servers = []
    try:
        async with client:
            await client.login()
            amnezia_servers = await client.get_servers()
            logger.info("Amnezia servers fetched successfully")
    except Exception as api_error:
        logger.error(
            "Failed to authenticate or fetch servers from Amnezia API: {}", api_error, exc_info=True
        )
        error_msg = str(api_error)
        if "login failed" in error_msg.lower() or "auth" in error_msg.lower():
            err_text = t(
                "admin.servers.errors.auth_failed",
                "❌ Ошибка авторизации: неверный логин или пароль.\n\nДетали: {error}",
                error=error_msg,
            )
        else:
            err_text = t(
                "admin.servers.errors.connection_failed",
                "❌ Ошибка подключения: {error}",
                error=error_msg,
            )

        await callback.message.edit_text(
            err_text,
            reply_markup=get_back_keyboard("admin_servers"),
        )
        await state.clear()
        return

    # If API calls succeed, proceed to DB operations
    parsed = urlparse(data.get("url", ""))
    name = f"Amnezia {parsed.netloc}"
    if "name" in data:
        name = data["name"]

    async with async_session_factory() as session:
        service = XUIService(session)

        try:
            original_name = name
            counter = 1
            while True:
                existing = await session.execute(select(Server).where(Server.name == name))
                if not existing.scalar_one_or_none():
                    break
                name = f"{original_name} ({counter})"
                counter += 1

            server = await service.create_server(
                name=name,
                url=data.get("url", ""),
                username=data.get("username", ""),
                password=data.get("password", ""),
                verify_ssl=verify_ssl,
            )
            server.panel_type = "amnezia"

            # Access properties before commit to avoid lazy loading
            server_name = server.name
            server_url = server.url
            server_id = server.id

            synced_count = 0
            for am_srv in amnezia_servers:
                protocols = (
                    [{"slug": p.slug, "id": p.id} for p in am_srv.protocols]
                    if am_srv.protocols
                    else [{"slug": "amnezia", "id": None}]
                )

                for p in protocols:
                    p_slug = p["slug"]
                    p_id = p["id"]

                    result = await session.execute(
                        select(Inbound).where(
                            Inbound.server_id == server_id,
                            Inbound.xui_id == am_srv.id,
                            Inbound.protocol == p_slug,
                        )
                    )
                    inbound = result.scalar_one_or_none()

                    remark_str = am_srv.name
                    payload = {"amnezia_server_id": am_srv.id}
                    if p_id is not None:
                        payload["amnezia_protocol_id"] = p_id

                    if not inbound:
                        inbound = Inbound(
                            server_id=server_id,
                            xui_id=am_srv.id,
                            remark=remark_str,
                            protocol=p_slug,
                            port=0,
                            settings_json="{}",
                            provider_payload=payload,
                            is_active=True,
                        )
                        session.add(inbound)
                    else:
                        inbound.remark = remark_str
                        inbound.provider_payload = payload
                    synced_count += 1

            await session.commit()
            logger.info("Server and inbounds saved to DB successfully")

            await state.clear()
            ssl_status_text = (
                t("admin.servers.ssl_enabled", "Включена")
                if verify_ssl
                else t("admin.servers.ssl_disabled", "Отключена")
            )

            logger.info("Sending success message")
            await callback.message.edit_text(
                t(
                    "admin.servers.amnezia_added_success",
                    "✅ Сервер Amnezia '{name}' успешно добавлен!\n\nURL: {url}\nПроверка SSL: {ssl_status}\nСинхронизировано inbounds: {synced_count}",
                    name=server_name,
                    url=server_url,
                    ssl_status=ssl_status_text,
                    synced_count=str(synced_count),
                ),
                reply_markup=get_back_keyboard("admin_servers"),
            )

        except Exception as e:
            await session.rollback()
            logger.exception("Amnezia server addition failed during DB save:")
            await callback.message.edit_text(
                t(
                    "admin.servers.errors.save_failed",
                    "❌ Ошибка при сохранении сервера: {error}",
                    error=str(e),
                ),
                reply_markup=get_back_keyboard("admin_servers"),
            )
