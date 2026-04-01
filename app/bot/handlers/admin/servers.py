"""Admin server management handlers."""

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message as TgMessage
from aiogram.fsm.context import FSMContext
from loguru import logger
from typing import Any

from app.bot.keyboards import (
    get_back_keyboard,
    get_confirm_keyboard,
    get_servers_keyboard,
)
from app.bot.states import ServerManagement
from app.database import async_session_factory
from app.services.xui_service import XUIService

router = Router()


@router.callback_query(F.data == "admin_servers")
async def show_servers(callback: CallbackQuery, is_admin: bool) -> None:
    """Show servers list."""
    if not is_admin:
        await callback.answer("❌ У вас нет прав администратора.", show_alert=True)
        return

    async with async_session_factory() as session:
        service = XUIService(session)
        servers = await service.get_all_servers()

    if not servers:
        await callback.message.edit_text(
            "📋 Список серверов пуст.\n\n"
            "Нажмите '➕ Добавить сервер' для добавления первого сервера.",
            reply_markup=get_servers_keyboard([]),
        )
    else:
        await callback.message.edit_text(
            "📋 Список серверов:",
            reply_markup=get_servers_keyboard(servers),
        )
    await callback.answer()


@router.callback_query(F.data == "server_add")
async def start_add_server(callback: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    """Start adding new server."""
    if not is_admin:
        await callback.answer("❌ У вас нет прав администратора.", show_alert=True)
        return

    await state.set_state(ServerManagement.waiting_for_name)
    await callback.message.edit_text(
        "➕ Добавление нового сервера\n\n"
        "Введите название сервера (например, 'NL-Server-1'):",
        reply_markup=get_back_keyboard("admin_servers"),
    )
    await callback.answer()


@router.message(ServerManagement.waiting_for_name)
async def process_server_name(message: TgMessage, state: FSMContext) -> None:
    """Process server name input."""
    name = message.text.strip()

    if not name:
        await message.answer("❌ Название не может быть пустым.", reply_markup=get_back_keyboard("admin_servers"))
        return

    if len(name) > 100:
        await message.answer("❌ Название не должно превышать 100 символов.", reply_markup=get_back_keyboard("admin_servers"))
        return

    await state.update_data(name=name)
    await state.set_state(ServerManagement.waiting_for_base_url)
    await message.answer(
        "Введите базовый адрес сервера (например, https://example.com):",
        reply_markup=get_back_keyboard("admin_servers"),
    )


@router.message(ServerManagement.waiting_for_base_url)
async def process_server_base_url(message: TgMessage, state: FSMContext) -> None:
    """Process server base URL input."""
    url = message.text.strip()

    if not url:
        await message.answer("❌ URL не может быть пустым.", reply_markup=get_back_keyboard("admin_servers"))
        return

    if not url.startswith(("http://", "https://")):
        await message.answer("❌ URL должен начинаться с http:// или https://", reply_markup=get_back_keyboard("admin_servers"))
        return

    if len(url) > 500:
        await message.answer("❌ URL не должен превышать 500 символов.", reply_markup=get_back_keyboard("admin_servers"))
        return

    await state.update_data(url=url)
    await state.set_state(ServerManagement.waiting_for_panel_path)
    await message.answer(
        "Введите путь к панели управления (опционально).\n\n"
        "❗ Важно: пути нужно указывать с обоих сторон со слешами (/path/)\n\n"
        "Если не указать, будет использоваться / (корневой путь).\n\n"
        "Примеры:\n"
        "• /panel/ - для стандартной установки\n"
        "• /xui/ - для кастомного пути\n\n"
        "Отправьте /skip чтобы использовать значение по умолчанию (/).",
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
                await message.answer("❌ Путь не должен превышать 500 символов.", reply_markup=get_back_keyboard("admin_servers"))
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
        "Введите путь для подписок (опционально).\n\n"
        "❗ Важно: пути нужно указывать с обоих сторон со слешами (/path/)\n\n"
        "Если не указать, будет использоваться /sub/\n\n"
        "Примеры:\n"
        "• /sub/ - стандартный путь\n"
        "• /custom/sub/ - кастомный путь\n\n"
        "Отправьте /skip чтобы использовать значение по умолчанию (/sub/).",
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
                await message.answer("❌ Путь не должен превышать 500 символов.", reply_markup=get_back_keyboard("admin_servers"))
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
        "Введите путь для JSON подписок (опционально).\n\n"
        "❗ Важно: пути нужно указывать с обоих сторон со слешами (/path/)\n\n"
        "Если не указать, будет использоваться /subjson/\n\n"
        "Примеры:\n"
        "• /subjson/ - стандартный путь\n"
        "• /custom/json/ - кастомный путь\n\n"
        "Отправьте /skip чтобы использовать значение по умолчанию (/subjson/).",
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
                await message.answer("❌ Путь не должен превышать 500 символов.", reply_markup=get_back_keyboard("admin_servers"))
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
        "Введите имя пользователя для входа в панель:",
        reply_markup=get_back_keyboard("admin_servers"),
    )


@router.message(ServerManagement.waiting_for_username)
async def process_server_username(message: TgMessage, state: FSMContext) -> None:
    """Process server username input."""
    username = message.text.strip()

    if not username:
        await message.answer("❌ Имя пользователя не может быть пустым.", reply_markup=get_back_keyboard("admin_servers"))
        return

    if len(username) > 100:
        await message.answer("❌ Имя пользователя не должно превышать 100 символов.", reply_markup=get_back_keyboard("admin_servers"))
        return

    await state.update_data(username=username)
    await state.set_state(ServerManagement.waiting_for_password)
    await message.answer(
        "Введите пароль для входа в панель:",
        reply_markup=get_back_keyboard("admin_servers"),
    )


@router.message(ServerManagement.waiting_for_password)
async def process_server_password(message: TgMessage, state: FSMContext) -> None:
    """Process server password input and ask for SSL verification."""
    data = await state.get_data()
    password = message.text

    if not password:
        await message.answer("❌ Пароль не может быть пустым.", reply_markup=get_back_keyboard("admin_servers"))
        return

    await state.update_data(password=password)
    await state.set_state(ServerManagement.waiting_for_verify_ssl)

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Да (рекомендуется)", callback_data="verify_ssl_yes")
    kb.button(text="❌ Нет (для самоподписанных сертификатов)", callback_data="verify_ssl_no")
    kb.adjust(1)

    await message.answer(
        "Проверять SSL сертификат при подключении к серверу?\n\n"
        "⚠️ Отключение проверки небезопасно и рекомендуется только для "
        "серверов с самоподписанными или проблемными сертификатами.",
        reply_markup=kb.as_markup(),
    )


@router.callback_query(F.data.startswith("verify_ssl_"))
async def process_verify_ssl_selection(callback: CallbackQuery, state: FSMContext) -> None:
    """Process SSL verification selection and create server."""
    data = await state.get_data()
    verify_ssl = callback.data == "verify_ssl_yes"

    # Test connection before creating server
    await callback.message.edit_text(
        "🔄 Проверка подключения к серверу...",
        reply_markup=None,
    )

    async with async_session_factory() as session:
        service = XUIService(session)

        try:
            # Create temporary client to test connection
            from app.xui_client import XUIClient, XUIError
            from urllib.parse import urljoin

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

            # Sync inbounds automatically
            try:
                synced_inbounds = await service.sync_server_inbounds(server.id)
                await session.commit()
                logger.info(f"✅ Автосинхронизация сервера {server.id}: {synced_inbounds} inbounds")
            except Exception as sync_error:
                logger.error(f"❌ Ошибка синхронизации inbounds: {sync_error}", exc_info=True)
                await session.rollback()  # Rollback sync but keep server
                # Re-commit just the server creation
                await session.commit()

            await state.clear()
            await callback.message.edit_text(
                f"✅ Сервер '{server.name}' успешно добавлен!\n\n"
                f"URL: {server.url}\n"
                f"Проверка SSL: {'Включена' if verify_ssl else 'Отключена'}\n"
                f"Найдено inbounds: {len(inbounds)}\n"
                f"Синхронизировано inbounds: {synced_inbounds if 'synced_inbounds' in locals() else 'Ошибка'}",
                reply_markup=get_back_keyboard("admin_servers"),
            )

        except XUIError as e:
            logger.error(f"Connection test failed: {e}", exc_info=True)

            # Check if it's an SSL error
            if "SSL" in str(e) or "tls" in str(e).lower():
                from aiogram.utils.keyboard import InlineKeyboardBuilder
                kb = InlineKeyboardBuilder()
                kb.button(text="❌ Нет, отменить", callback_data="cancel_ssl_bypass")
                kb.button(text="✅ Да, попробовать без проверки", callback_data="retry_without_ssl")
                kb.adjust(1)

                await callback.message.edit_text(
                    f"❌ Ошибка SSL сертификата:\n{e}\n\n"
                    "Хотите попробовать подключиться без проверки SSL сертификата?",
                    reply_markup=kb.as_markup(),
                )
            else:
                await callback.message.edit_text(
                    f"❌ Не удалось подключиться к серверу:\n{e}\n\n"
                    "Проверьте URL, логин и пароль.",
                    reply_markup=get_back_keyboard("admin_servers"),
                )
                await state.clear()

        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            await callback.message.edit_text(
                f"❌ Ошибка при проверке сервера:\n{e}",
                reply_markup=get_back_keyboard("admin_servers"),
            )
            await state.clear()

    await callback.answer()


@router.callback_query(F.data == "retry_without_ssl")
async def retry_without_ssl(callback: CallbackQuery, state: FSMContext) -> None:
    """Retry connection without SSL verification."""
    data = await state.get_data()

    await callback.message.edit_text(
        "🔄 Повторная проверка подключения к серверу (без SSL)...",
        reply_markup=None,
    )

    async with async_session_factory() as session:
        service = XUIService(session)

        try:
            from app.xui_client import XUIClient, XUIError
            from urllib.parse import urljoin

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

            # Sync inbounds automatically
            try:
                synced_inbounds = await service.sync_server_inbounds(server.id)
                await session.commit()
                logger.info(f"✅ Автосинхронизация сервера {server.id}: {synced_inbounds} inbounds")
            except Exception as sync_error:
                logger.error(f"❌ Ошибка синхронизации inbounds: {sync_error}", exc_info=True)
                await session.rollback()  # Rollback sync but keep server
                # Re-commit just the server creation
                await session.commit()

            await state.clear()
            await callback.message.edit_text(
                f"✅ Сервер '{server.name}' успешно добавлен!\n\n"
                f"URL: {server.url}\n"
                f"⚠️ Проверка SSL: ОТКЛЮЧЕНА\n"
                f"Найдено inbounds: {len(inbounds)}\n"
                f"Синхронизировано inbounds: {synced_inbounds if 'synced_inbounds' in locals() else 'Ошибка'}",
                reply_markup=get_back_keyboard("admin_servers"),
            )

        except XUIError as e:
            logger.error(f"Connection test failed even without SSL: {e}", exc_info=True)
            await callback.message.edit_text(
                f"❌ Не удалось подключиться к серверу даже без проверки SSL:\n{e}\n\n"
                "Проверьте URL, логин и пароль.",
                reply_markup=get_back_keyboard("admin_servers"),
            )
            await state.clear()

        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            await callback.message.edit_text(
                f"❌ Ошибка при проверке сервера:\n{e}",
                reply_markup=get_back_keyboard("admin_servers"),
            )
            await state.clear()

    await callback.answer()


@router.callback_query(F.data == "cancel_ssl_bypass")
async def cancel_ssl_bypass(callback: CallbackQuery, state: FSMContext) -> None:
    """Cancel SSL bypass and return to server list."""
    await state.clear()
    await callback.message.edit_text(
        "❌ Добавление сервера отменено.",
        reply_markup=get_back_keyboard("admin_servers"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("server_select_"))
async def select_server(callback: CallbackQuery, is_admin: bool) -> None:
    """Show server details."""
    if not is_admin:
        await callback.answer("❌ У вас нет прав администратора.", show_alert=True)
        return

    server_id = int(callback.data.split("_")[-1])

    async with async_session_factory() as session:
        service = XUIService(session)
        server = await service.get_server_by_id(server_id)

    if not server:
        await callback.answer("❌ Сервер не найден.", show_alert=True)
        return

    status = "✅ Активен" if server.is_active else "❌ Неактивен"
    last_sync = server.last_sync_at.strftime("%d.%m.%Y %H:%M") if server.last_sync_at else "Никогда"
    ssl_status = "✅" if server.verify_ssl else "❌"

    # Get paths with defaults
    panel_path = getattr(server, 'panel_path', '/')
    subscription_path = getattr(server, 'subscription_path', '/sub/')
    subscription_json_path = getattr(server, 'subscription_json_path', '/subjson/')

    text = (
        f"🖥️ Сервер: {server.name}\n\n"
        f"🌐 URL: {server.url}\n"
        f"📁 Путь панели: {panel_path}\n"
        f"📝 Путь подписок: {subscription_path}\n"
        f"📋 Путь JSON: {subscription_json_path}\n"
        f"👤 Логин: {server.username}\n"
        f"🔒 SSL: {ssl_status}\n"
        f"📊 Статус: {status}\n"
        f"🔄 Последняя синхронизация: {last_sync}"
    )

    builder = []
    builder.append({"text": "✏️ Редактировать", "callback_data": f"server_edit_{server_id}"})
    builder.append({"text": "📊 Inbounds", "callback_data": f"server_inbounds_{server_id}"})
    builder.append({"text": "🔄 Синхронизировать", "callback_data": f"server_sync_{server_id}"})
    builder.append({"text": "🔌 Проверить подключение", "callback_data": f"server_test_{server_id}"})
    if server.is_active:
        builder.append({"text": "❌ Отключить", "callback_data": f"server_disable_{server_id}"})
    else:
        builder.append({"text": "✅ Включить", "callback_data": f"server_enable_{server_id}"})
    builder.append({"text": "🗑️ Удалить", "callback_data": f"server_delete_{server_id}"})
    builder.append({"text": "🔙 Назад", "callback_data": "admin_servers"})

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
        await callback.answer("❌ У вас нет прав администратора.", show_alert=True)
        return

    server_id = int(callback.data.split("_")[-1])

    async with async_session_factory() as session:
        from app.services import SyncService
        sync_service = SyncService(session)
        try:
            # Sync inbounds and clients
            from sqlalchemy import select
            from app.database.models import Server
            server = await session.get(Server, server_id)
            if server:
                await sync_service.sync_server(server, force=True)
                await session.commit()
                await callback.answer(f"✅ Синхронизация завершена! Inbounds и клиенты синхронизированы", show_alert=True)
            else:
                await callback.answer(f"❌ Сервер не найден", show_alert=True)
        except Exception as e:
            logger.error(f"Error syncing server {server_id}: {e}", exc_info=True)
            await callback.answer(f"❌ Ошибка при синхронизации: {e}", show_alert=True)


@router.callback_query(F.data.startswith("server_test_"))
async def test_server(callback: CallbackQuery, is_admin: bool) -> None:
    """Test server connection."""
    if not is_admin:
        await callback.answer("❌ У вас нет прав администратора.", show_alert=True)
        return

    server_id = int(callback.data.split("_")[-1])

    async with async_session_factory() as session:
        service = XUIService(session)
        success, message = await service.test_server_connection(server_id)
        await service.close_all_clients()

    if success:
        await callback.answer(f"✅ {message}", show_alert=True)
    else:
        await callback.answer(f"❌ {message}", show_alert=True)


@router.callback_query(F.data.startswith("server_inbounds_"))
async def show_server_inbounds(callback: CallbackQuery, is_admin: bool) -> None:
    """Show inbounds for a server with detailed information."""
    if not is_admin:
        await callback.answer("❌ У вас нет прав администратора.", show_alert=True)
        return

    server_id = int(callback.data.split("_")[-1])

    async with async_session_factory() as session:
        service = XUIService(session)
        server = await service.get_server_by_id(server_id)
        if not server:
            await callback.answer("❌ Сервер не найден.", show_alert=True)
            return

        # Get inbounds from database
        inbounds = await service.get_server_inbounds(server_id)

        if not inbounds:
            await callback.message.edit_text(
                f"📊 Inbounds сервера {server.name}\n\n"
                "❌ Нет доступных inbounds.\n\n"
                "Нажмите '🔄 Синхронизировать' для получения inbounds с панели.",
                reply_markup=get_back_keyboard(f"server_select_{server_id}"),
            )
            await callback.answer()
            return

        # Build text with inbound details
        text = f"📊 Inbounds сервера {server.name}\n\n"
        text += f"Всего: {len(inbounds)} inbounds\n\n"

        for inbound in inbounds:
            status = "✅" if inbound.is_active else "❌"
            text += (
                f"{status} {inbound.remark}\n"
                f"   Протокол: {inbound.protocol}\n"
                f"   Порт: {inbound.port}\n"
                f"   Клиентов (БД): {inbound.client_count}\n\n"
            )

        from aiogram.utils.keyboard import InlineKeyboardBuilder
        kb = InlineKeyboardBuilder()
        kb.button(text="🔄 Обновить статистику", callback_data=f"inbound_stats_{server_id}")
        kb.button(text="🔙 Назад", callback_data=f"server_select_{server_id}")
        kb.adjust(1)

        await callback.message.edit_text(text, reply_markup=kb.as_markup())
        await callback.answer()


@router.callback_query(F.data.startswith("inbound_stats_"))
async def show_inbound_stats(callback: CallbackQuery, is_admin: bool) -> None:
    """Show live statistics for inbounds from XUI panel."""
    if not is_admin:
        await callback.answer("❌ У вас нет прав администратора.", show_alert=True)
        return

    server_id = int(callback.data.split("_")[-1])

    async with async_session_factory() as session:
        service = XUIService(session)
        server = await service.get_server_by_id(server_id)
        if not server:
            await callback.answer("❌ Сервер не найден.", show_alert=True)
            return

        try:
            # Get inbounds from database
            inbounds = await service.get_server_inbounds(server_id)

            if not inbounds:
                await callback.answer("❌ Нет inbounds для обновления.", show_alert=True)
                return

            # Get live stats from XUI panel
            text = f"📊 Статистика Inbounds сервера {server.name}\n\n"

            for inbound in inbounds:
                stats = await service.get_inbound_client_stats(inbound.id)
                status = "✅" if inbound.is_active else "❌"

                text += (
                    f"{status} {inbound.remark} ({inbound.protocol})\n"
                    f"   Порт: {inbound.port}\n"
                    f"   Всего клиентов: {stats['total_clients']}\n"
                    f"   Активных: {stats['enabled_clients']}\n"
                    f"   Отключенных: {stats['disabled_clients']}\n"
                    f"   Использовано трафика: {stats['total_used_gb']:.2f} GB\n\n"
                )

            from aiogram.utils.keyboard import InlineKeyboardBuilder
            kb = InlineKeyboardBuilder()
            kb.button(text="🔄 Обновить", callback_data=f"inbound_stats_{server_id}")
            kb.button(text="🔙 Назад", callback_data=f"server_select_{server_id}")
            kb.adjust(1)

            await callback.message.edit_text(text, reply_markup=kb.as_markup())
            await callback.answer("✅ Статистика обновлена")

        except Exception as e:
            logger.error(f"Error getting inbound stats: {e}", exc_info=True)
            await callback.answer(f"❌ Ошибка: {e}", show_alert=True)
        finally:
            await service.close_all_clients()


@router.callback_query(F.data.startswith("server_enable_"))
async def enable_server(callback: CallbackQuery, is_admin: bool) -> None:
    """Enable server."""
    if not is_admin:
        await callback.answer("❌ У вас нет прав администратора.", show_alert=True)
        return

    server_id = int(callback.data.split("_")[-1])

    async with async_session_factory() as session:
        service = XUIService(session)
        await service.update_server(server_id, is_active=True)
        await session.commit()

    await callback.answer("✅ Сервер включен.")
    await select_server(callback, is_admin)


@router.callback_query(F.data.startswith("server_disable_"))
async def disable_server(callback: CallbackQuery, is_admin: bool) -> None:
    """Disable server."""
    if not is_admin:
        await callback.answer("❌ У вас нет прав администратора.", show_alert=True)
        return

    server_id = int(callback.data.split("_")[-1])

    async with async_session_factory() as session:
        service = XUIService(session)
        await service.update_server(server_id, is_active=False)
        await session.commit()

    await callback.answer("✅ Сервер отключен.")
    await select_server(callback, is_admin)


@router.callback_query(F.data.startswith("server_delete_"))
async def confirm_delete_server(callback: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    """Confirm server deletion."""
    if not is_admin:
        await callback.answer("❌ У вас нет прав администратора.", show_alert=True)
        return

    server_id = int(callback.data.split("_")[-1])
    await state.update_data(server_id=server_id)
    await state.set_state(ServerManagement.confirm_delete)

    await callback.message.edit_text(
        "⚠️ Вы уверены, что хотите удалить этот сервер?\n\n"
        "Все связанные подписки будут также удалены!",
        reply_markup=get_confirm_keyboard(f"server_delete_{server_id}", "admin_servers"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("confirm_server_delete_"))
async def delete_server(callback: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    """Delete server."""
    if not is_admin:
        await callback.answer("❌ У вас нет прав администратора.", show_alert=True)
        return

    server_id = int(callback.data.split("_")[-1])

    async with async_session_factory() as session:
        service = XUIService(session)
        await service.delete_server(server_id)
        await session.commit()

    await state.clear()
    await callback.answer("✅ Сервер удален.")
    await show_servers(callback, is_admin)


@router.callback_query(F.data.startswith("server_edit_"))
async def edit_server(callback: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    """Show server edit menu."""
    if not is_admin:
        await callback.answer("❌ У вас нет прав администратора.", show_alert=True)
        return

    server_id = int(callback.data.split("_")[-1])
    await state.update_data(server_id=server_id)

    async with async_session_factory() as session:
        service = XUIService(session)
        server = await service.get_server_by_id(server_id)

    if not server:
        await callback.answer("❌ Сервер не найден.", show_alert=True)
        return

    # Get paths with defaults
    panel_path = getattr(server, 'panel_path', '/')
    subscription_path = getattr(server, 'subscription_path', '/sub/')
    subscription_json_path = getattr(server, 'subscription_json_path', '/subjson/')

    builder = []
    builder.append({"text": "✏️ Название", "callback_data": "edit_server_name"})
    builder.append({"text": "🌐 URL сервера", "callback_data": "edit_server_url"})
    builder.append({"text": "📁 Путь панели", "callback_data": "edit_server_panel_path"})
    builder.append({"text": "📝 Путь подписок", "callback_data": "edit_server_sub_path"})
    builder.append({"text": "📋 Путь JSON", "callback_data": "edit_server_json_path"})
    builder.append({"text": "👤 Логин", "callback_data": "edit_server_username"})
    builder.append({"text": "🔒 Пароль", "callback_data": "edit_server_password"})
    builder.append({"text": "🔐 SSL", "callback_data": "edit_server_ssl"})
    builder.append({"text": "🔙 Назад", "callback_data": f"server_select_{server_id}"})

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    for btn in builder:
        kb.button(**btn)
    kb.adjust(1)

    text = (
        f"✏️ Редактирование сервера: <b>{server.name}</b>\n\n"
        f"🌐 URL: {server.url}\n"
        f"📁 Путь панели: {panel_path}\n"
        f"📝 Путь подписок: {subscription_path}\n"
        f"📋 Путь JSON: {subscription_json_path}\n"
        f"👤 Логин: {server.username}\n\n"
        f"Выберите поле для редактирования:"
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
        await callback.answer("❌ Сервер не найден.", show_alert=True)
        return

    await state.set_state(ServerManagement.waiting_for_edit_name)
    await callback.message.edit_text(
        f"✏️ Редактирование названия сервера\n\n"
        f"Текущее название: <b>{server.name}</b>\n\n"
        f"Введите новое название (или /skip чтобы оставить текущее):",
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
        await message.answer("❌ Название не может быть пустым.")
        return

    if len(new_name) > 100:
        await message.answer("❌ Название не должно превышать 100 символов.")
        return

    async with async_session_factory() as session:
        service = XUIService(session)
        server = await service.update_server(server_id, name=new_name)
        if server:
            await session.commit()
            await message.answer(f"✅ Название изменено на: {new_name}")
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
        await callback.answer("❌ Сервер не найден.", show_alert=True)
        return

    await state.set_state(ServerManagement.waiting_for_edit_base_url)
    await callback.message.edit_text(
        f"✏️ Редактирование URL сервера\n\n"
        f"Текущий URL: <b>{server.url}</b>\n\n"
        f"Введите новый URL (или /skip чтобы оставить текущий):",
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
        await message.answer("❌ URL не может быть пустым.")
        return

    if not new_url.startswith(("http://", "https://")):
        await message.answer("❌ URL должен начинаться с http:// или https://")
        return

    if len(new_url) > 500:
        await message.answer("❌ URL не должен превышать 500 символов.")
        return

    async with async_session_factory() as session:
        service = XUIService(session)
        server = await service.update_server(server_id, url=new_url)
        if server:
            await session.commit()
            await message.answer(f"✅ URL изменен на: {new_url}")

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
        await callback.answer("❌ Сервер не найден.", show_alert=True)
        return

    panel_path = getattr(server, 'panel_path', '/')

    await state.set_state(ServerManagement.waiting_for_edit_panel_path)
    await callback.message.edit_text(
        f"✏️ Редактирование пути панели\n\n"
        f"Текущий путь: <b>{panel_path}</b>\n\n"
        f"Введите новый путь (или /skip чтобы оставить текущий).\n\n"
        f"❗ Важно: путь нужно указывать с обоих сторон со слешами (/path/)",
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
            await message.answer("❌ Путь не должен превышать 500 символов.")
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
            await message.answer(f"✅ Путь панели изменен на: {new_path}")

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
        await callback.answer("❌ Сервер не найден.", show_alert=True)
        return

    subscription_path = getattr(server, 'subscription_path', '/sub/')

    await state.set_state(ServerManagement.waiting_for_edit_subscription_path)
    await callback.message.edit_text(
        f"✏️ Редактирование пути подписок\n\n"
        f"Текущий путь: <b>{subscription_path}</b>\n\n"
        f"Введите новый путь (или /skip чтобы оставить текущий).\n\n"
        f"❗ Важно: путь нужно указывать с обоих сторон со слешами (/path/)",
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
            await message.answer("❌ Путь не должен превышать 500 символов.")
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
            await message.answer(f"✅ Путь подписок изменен на: {new_path}")

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
        await callback.answer("❌ Сервер не найден.", show_alert=True)
        return

    subscription_json_path = getattr(server, 'subscription_json_path', '/subjson/')

    await state.set_state(ServerManagement.waiting_for_edit_subscription_json_path)
    await callback.message.edit_text(
        f"✏️ Редактирование пути JSON подписок\n\n"
        f"Текущий путь: <b>{subscription_json_path}</b>\n\n"
        f"Введите новый путь (или /skip чтобы оставить текущий).\n\n"
        f"❗ Важно: путь нужно указывать с обоих сторон со слешами (/path/)",
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
            await message.answer("❌ Путь не должен превышать 500 символов.")
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
            await message.answer(f"✅ Путь JSON подписок изменен на: {new_path}")

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
        await callback.answer("❌ Сервер не найден.", show_alert=True)
        return

    await state.set_state(ServerManagement.waiting_for_edit_username)
    await callback.message.edit_text(
        f"✏️ Редактирование логина\n\n"
        f"Текущий логин: <b>{server.username}</b>\n\n"
        f"Введите новый логин (или /skip чтобы оставить текущий):",
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
        await message.answer("❌ Логин не может быть пустым.")
        return

    if len(new_username) > 100:
        await message.answer("❌ Логин не должен превышать 100 символов.")
        return

    async with async_session_factory() as session:
        service = XUIService(session)
        server = await service.update_server(server_id, username=new_username)
        if server:
            await session.commit()
            await message.answer(f"✅ Логин изменен на: {new_username}")

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
        await callback.answer("❌ Сервер не найден.", show_alert=True)
        return

    await state.set_state(ServerManagement.waiting_for_edit_password)
    await callback.message.edit_text(
        f"✏️ Редактирование пароля\n\n"
        f"Введите новый пароль (или /skip чтобы оставить текущий):",
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
        await message.answer("❌ Пароль не может быть пустым.")
        return

    async with async_session_factory() as session:
        service = XUIService(session)
        server = await service.update_server(server_id, password=new_password)
        if server:
            await session.commit()
            await message.answer("✅ Пароль изменен")

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
        await callback.answer("❌ Сервер не найден.", show_alert=True)
        return

    await state.set_state(ServerManagement.waiting_for_edit_verify_ssl)
    current_ssl = "✅ Включена" if server.verify_ssl else "❌ Отключена"

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Включить", callback_data="edit_ssl_enable")
    kb.button(text="❌ Отключить", callback_data="edit_ssl_disable")
    kb.adjust(1)

    await callback.message.edit_text(
        f"✏️ Редактирование проверки SSL\n\n"
        f"Текущее состояние: {current_ssl}\n\n"
        f"Выберите новое состояние:",
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
            ssl_text = "✅ Включена" if new_ssl else "❌ Отключена"
            await callback.message.edit_text(f"✅ Проверка SSL {ssl_text}")

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
        await message.answer("❌ Сервер не найден.")
        return

    # Get paths with defaults
    panel_path = getattr(server, 'panel_path', '/')
    subscription_path = getattr(server, 'subscription_path', '/sub/')
    subscription_json_path = getattr(server, 'subscription_json_path', '/subjson/')

    builder = []
    builder.append({"text": "✏️ Название", "callback_data": "edit_server_name"})
    builder.append({"text": "🌐 URL сервера", "callback_data": "edit_server_url"})
    builder.append({"text": "📁 Путь панели", "callback_data": "edit_server_panel_path"})
    builder.append({"text": "📝 Путь подписок", "callback_data": "edit_server_sub_path"})
    builder.append({"text": "📋 Путь JSON", "callback_data": "edit_server_json_path"})
    builder.append({"text": "👤 Логин", "callback_data": "edit_server_username"})
    builder.append({"text": "🔒 Пароль", "callback_data": "edit_server_password"})
    builder.append({"text": "🔐 SSL", "callback_data": "edit_server_ssl"})
    builder.append({"text": "🔙 Назад", "callback_data": f"server_select_{server_id}"})

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    for btn in builder:
        kb.button(**btn)
    kb.adjust(1)

    text = (
        f"✏️ Редактирование сервера: <b>{server.name}</b>\n\n"
        f"🌐 URL: {server.url}\n"
        f"📁 Путь панели: {panel_path}\n"
        f"📝 Путь подписок: {subscription_path}\n"
        f"📋 Путь JSON: {subscription_json_path}\n"
        f"👤 Логин: {server.username}\n\n"
        f"Выберите поле для редактирования:"
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
        await message.answer("❌ Сервер не найден.")
        return

    status = "✅ Активен" if server.is_active else "❌ Неактивен"
    last_sync = server.last_sync_at.strftime("%d.%m.%Y %H:%M") if server.last_sync_at else "Никогда"
    ssl_status = "✅" if server.verify_ssl else "❌"

    # Get paths with defaults
    panel_path = getattr(server, 'panel_path', '/')
    subscription_path = getattr(server, 'subscription_path', '/sub/')
    subscription_json_path = getattr(server, 'subscription_json_path', '/subjson/')

    text = (
        f"🖥️ Сервер: {server.name}\n\n"
        f"🌐 URL: {server.url}\n"
        f"📁 Путь панели: {panel_path}\n"
        f"📝 Путь подписок: {subscription_path}\n"
        f"📋 Путь JSON: {subscription_json_path}\n"
        f"👤 Логин: {server.username}\n"
        f"🔒 SSL: {ssl_status}\n"
        f"📊 Статус: {status}\n"
        f"🔄 Последняя синхронизация: {last_sync}"
    )

    builder = []
    builder.append({"text": "✏️ Редактировать", "callback_data": f"server_edit_{server_id}"})
    builder.append({"text": "📊 Inbounds", "callback_data": f"server_inbounds_{server_id}"})
    builder.append({"text": "🔄 Синхронизировать", "callback_data": f"server_sync_{server_id}"})
    builder.append({"text": "🔌 Проверить подключение", "callback_data": f"server_test_{server_id}"})
    if server.is_active:
        builder.append({"text": "❌ Отключить", "callback_data": f"server_disable_{server_id}"})
    else:
        builder.append({"text": "✅ Включить", "callback_data": f"server_enable_{server_id}"})
    builder.append({"text": "🗑️ Удалить", "callback_data": f"server_delete_{server_id}"})
    builder.append({"text": "🔙 Назад", "callback_data": "admin_servers"})

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    for btn in builder:
        kb.button(**btn)
    kb.adjust(1)

    await message.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")
