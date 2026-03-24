"""Admin client management handlers."""

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from loguru import logger

from app.bot.keyboards import (
    get_back_keyboard,
    get_confirm_keyboard,
    get_clients_keyboard,
    get_servers_keyboard,
)
from app.bot.states import ClientManagement, SubscriptionManagement
from app.database import async_session_factory
from app.services.client_service import ClientService

router = Router()


@router.callback_query(F.data == "admin_clients")
async def show_clients(callback: CallbackQuery, is_admin: bool) -> None:
    """Show clients list."""
    if not is_admin:
        await callback.answer("❌ У вас нет прав администратора.", show_alert=True)
        return

    async with async_session_factory() as session:
        service = ClientService(session)
        clients = await service.get_all_clients()

    try:
        if not clients:
            await callback.message.edit_text(
                "👥 Список клиентов пуст.\n\n"
                "Нажмите '➕ Добавить клиента' для добавления.",
                reply_markup=get_clients_keyboard([]),
            )
        else:
            await callback.message.edit_text(
                f"👥 Список клиентов ({len(clients)}):",
                reply_markup=get_clients_keyboard(clients),
            )
    except Exception:
        # Message hasn't changed, skip edit
        pass
    await callback.answer()


@router.callback_query(F.data == "client_add")
async def start_add_client(callback: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    """Start adding new client."""
    if not is_admin:
        await callback.answer("❌ У вас нет прав администратора.", show_alert=True)
        return

    await state.set_state(ClientManagement.waiting_for_name)
    try:
        await callback.message.edit_text(
            "➕ Добавление нового клиента\n\n"
            "Введите имя клиента:",
            reply_markup=get_back_keyboard("admin_clients"),
        )
    except Exception:
        # Message hasn't changed, skip edit
        pass
    await callback.answer()


@router.message(ClientManagement.waiting_for_name)
async def process_client_name(message: Message, state: FSMContext) -> None:
    """Process client name input."""
    name = message.text.strip()

    if not name:
        await message.answer("❌ Имя не может быть пустым.")
        return

    if len(name) > 100:
        await message.answer("❌ Имя не должно превышать 100 символов.")
        return

    await state.update_data(name=name)
    await state.set_state(ClientManagement.waiting_for_email)
    await message.answer(
        "Введите email клиента (или отправьте '-' для автоматической генерации):",
        reply_markup=get_back_keyboard("admin_clients"),
    )


@router.message(ClientManagement.waiting_for_email)
async def process_client_email(message: Message, state: FSMContext) -> None:
    """Process client email input."""
    email = message.text.strip()

    if email != "-":
        # Basic email validation
        if "@" not in email or "." not in email:
            await message.answer("❌ Некорректный формат email.")
            return

    await state.update_data(email=email if email != "-" else None)
    await state.set_state(ClientManagement.waiting_for_telegram_id)
    await message.answer(
        "Введите Telegram ID клиента (число) или отправьте '-' чтобы пропустить:",
        reply_markup=get_back_keyboard("admin_clients"),
    )


@router.message(ClientManagement.waiting_for_telegram_id)
async def process_client_telegram_id(message: Message, state: FSMContext) -> None:
    """Process telegram ID input and create client."""
    data = await state.get_data()

    telegram_id = None
    if message.text != "-":
        try:
            telegram_id = int(message.text)
        except ValueError:
            await message.answer("❌ Telegram ID должен быть числом или '-'.")
            return

    async with async_session_factory() as session:
        service = ClientService(session)
        try:
            client = await service.create_client(
                name=data["name"],
                email=data.get("email"),
                telegram_id=telegram_id,
            )
            await session.commit()

            await state.clear()
            await message.answer(
                f"✅ Клиент '{client.name}' успешно создан!\n\n"
                f"ID: {client.id}\n"
                f"Email: {client.email}\n"
                f"Telegram ID: {client.telegram_id or 'Не указан'}",
                reply_markup=get_back_keyboard("admin_clients"),
            )
        except Exception as e:
            logger.error(f"Error creating client: {e}", exc_info=True)
            await message.answer(f"❌ Ошибка при создании клиента: {e}")


async def _show_client_details(client_id: int, callback: CallbackQuery) -> None:
    """Helper function to show client details.

    Args:
        client_id: Client ID
        callback: Original callback query
    """
    async with async_session_factory() as session:
        service = ClientService(session)
        client = await service.get_client_by_id(client_id)

    if not client:
        await callback.answer("❌ Клиент не найден.", show_alert=True)
        return

    status = "✅ Активен" if client.is_active else "❌ Неактивен"
    admin_status = "✅ Админ" if client.is_admin else "👤 Клиент"

    text = (
        f"👤 Клиент: {client.name}\n\n"
        f"ID: {client.id}\n"
        f"Email: {client.email}\n"
        f"Telegram ID: {client.telegram_id or 'Не указан'}\n"
        f"Статус: {status}\n"
        f"Роль: {admin_status}\n"
        f"Подписок: {len(client.subscriptions)}\n"
        f"Создан: {client.created_at.strftime('%d.%m.%Y %H:%M')}"
    )

    # Build keyboard with actions
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    kb.button(text="📝 Подписки", callback_data=f"client_subscriptions_{client_id}")
    kb.button(text="✏️ Изменить имя", callback_data=f"client_rename_name_{client_id}")
    kb.button(text="📱 Изменить Telegram ID", callback_data=f"client_rename_telegram_{client_id}")
    if client.is_admin:
        kb.button(text="⬇️ Снять админа", callback_data=f"client_unadmin_{client_id}")
    else:
        kb.button(text="⬆️ Сделать админом", callback_data=f"client_make_admin_{client_id}")
    if client.is_active:
        kb.button(text="❌ Отключить", callback_data=f"client_disable_{client_id}")
    else:
        kb.button(text="✅ Включить", callback_data=f"client_enable_{client_id}")
    kb.button(text="🗑️ Удалить", callback_data=f"client_delete_{client_id}")
    kb.button(text="🔙 Назад", callback_data="admin_clients")
    kb.adjust(1)

    try:
        await callback.message.edit_text(text, reply_markup=kb.as_markup())
    except Exception:
        # Message hasn't changed, skip edit
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("client_select_"))
async def select_client(callback: CallbackQuery, is_admin: bool) -> None:
    """Show client details and actions."""
    if not is_admin:
        await callback.answer("❌ У вас нет прав администратора.", show_alert=True)
        return

    client_id = int(callback.data.split("_")[-1])
    await _show_client_details(client_id, callback)


@router.callback_query(F.data.startswith("client_subscriptions_"))
async def show_client_subscriptions(callback: CallbackQuery, is_admin: bool) -> None:
    """Show client subscriptions."""
    if not is_admin:
        await callback.answer("❌ У вас нет прав администратора.", show_alert=True)
        return

    client_id = int(callback.data.split("_")[-1])

    from app.services.new_subscription_service import NewSubscriptionService

    async with async_session_factory() as session:
        service = NewSubscriptionService(session)
        subscriptions = await service.get_client_subscriptions(client_id)

    if not subscriptions:
        await callback.answer("❌ У клиента нет подписок.", show_alert=True)
        return

    text = "📝 Подписки клиента:\n\n"

    for sub in subscriptions:
        status = "✅" if sub.is_active else "❌"
        expiry = sub.expiry_date.strftime("%d.%m.%Y") if sub.expiry_date else "Бессрочно"
        traffic = "Безлимит" if sub.is_unlimited else f"{sub.total_gb} GB"

        text += (
            f"{status} {sub.name}\n"
            f"   Трафик: {traffic}\n"
            f"   Срок: {expiry}\n"
            f"   Подключений: {len(sub.inbound_connections)}\n\n"
        )

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Создать подписку", callback_data=f"client_create_subscription_{client_id}")
    kb.button(text="🔙 Назад", callback_data=f"client_select_{client_id}")
    kb.adjust(1)

    try:
        await callback.message.edit_text(text, reply_markup=kb.as_markup())
    except Exception:
        # Message hasn't changed, skip edit
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("client_create_subscription_"))
async def start_create_subscription_for_client(callback: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    """Start creating subscription for specific client."""
    if not is_admin:
        await callback.answer("❌ У вас нет прав администратора.", show_alert=True)
        return

    client_id = int(callback.data.split("_")[-1])
    await state.update_data(client_id=client_id)

    from app.services.xui_service import XUIService
    from app.bot.handlers.admin.subscriptions import start_create_subscription

    # Reuse subscription creation flow with pre-selected client
    async with async_session_factory() as session:
        service = XUIService(session)
        servers = await service.get_active_servers()

    if not servers:
        await callback.answer("❌ Нет активных серверов. Сначала добавьте сервер.", show_alert=True)
        return

    await state.set_state(SubscriptionManagement.waiting_for_server_selection)
    try:
        await callback.message.edit_text(
            "Выберите сервер:",
            reply_markup=get_servers_keyboard(servers, action="sub_select"),
        )
    except Exception:
        # Message hasn't changed, skip edit
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("subscription_select_"))
async def select_subscription(callback: CallbackQuery, is_admin: bool) -> None:
    """Show subscription details and actions."""
    if not is_admin:
        await callback.answer("❌ У вас нет прав администратора.", show_alert=True)
        return

    subscription_id = int(callback.data.split("_")[-1])

    from app.services.new_subscription_service import NewSubscriptionService

    async with async_session_factory() as session:
        service = NewSubscriptionService(session)
        subscription = await service.get_subscription_by_id(subscription_id)

    if not subscription:
        await callback.answer("❌ Подписка не найдена.", show_alert=True)
        return

    # Load subscription with relations
    from app.database.models import Client
    client = await session.get(Client, subscription.client_id)

    status = "✅ Активен" if subscription.is_active else "❌ Неактивен"
    expiry = subscription.expiry_date.strftime("%d.%m.%Y") if subscription.expiry_date else "Бессрочно"
    traffic = "Безлимит" if subscription.is_unlimited else f"{subscription.total_gb} GB"

    text = (
        f"📝 Подписка: {subscription.name}\n\n"
        f"ID: {subscription.id}\n"
        f"Клиент: {client.name}\n"
        f"Токен: {subscription.subscription_token}\n"
        f"Статус: {status}\n"
        f"Трафик: {traffic}\n"
        f"Срок: {expiry}\n"
        f"Подключений: {len(subscription.inbound_connections)}"
    )

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    kb.button(text="📢 Inbounds", callback_data=f"subscription_inbounds_{subscription_id}")
    kb.button(text="✏️ Изменить", callback_data=f"subscription_edit_{subscription_id}")
    if subscription.is_active:
        kb.button(text="❌ Отключить", callback_data=f"subscription_disable_{subscription_id}")
    else:
        kb.button(text="✅ Включить", callback_data=f"subscription_enable_{subscription_id}")
    kb.button(text="🗑️ Удалить", callback_data=f"subscription_delete_{subscription_id}")
    kb.button(text="🔙 Назад", callback_data=f"client_subscriptions_{client_id}")
    kb.adjust(1)

    try:
        await callback.message.edit_text(text, reply_markup=kb.as_markup())
    except Exception:
        # Message hasn't changed, skip edit
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("subscription_inbounds_"))
async def show_subscription_inbounds(callback: CallbackQuery, is_admin: bool) -> None:
    """Show subscription inbounds."""
    if not is_admin:
        await callback.answer("❌ У вас нет прав администратора.", show_alert=True)
        return

    subscription_id = int(callback.data.split("_")[-1])

    from app.services.new_subscription_service import NewSubscriptionService

    async with async_session_factory() as session:
        service = NewSubscriptionService(session)
        subscription = await service.get_subscription_by_id(subscription_id)

    if not subscription:
        await callback.answer("❌ Подписка не найдена.", show_alert=True)
        return

    if not subscription.inbound_connections:
        await callback.answer("❌ У подписки нет подключений.", show_alert=True)
        return

    # Load inbound connections with server and inbound info
    from sqlalchemy.orm import selectinload
    from app.database.models import Subscription, Inbound, Server

    result = await session.execute(
        select(Subscription)
        .where(Subscription.id == subscription_id)
        .options(
            selectinload(Subscription.inbound_connections)
            .selectinload("inbound.server")
        )
    )
    subscription_with_relations = result.scalar_one_or_none()

    text = f"📢 Inbounds подписки '{subscription.name}':\n\n"

    for conn in subscription_with_relations.inbound_connections:
        status = "✅" if conn.is_enabled else "❌"
        inbound = conn.inbound
        server = inbound.server

        text += (
            f"{status} {inbound.remark} ({inbound.protocol})\n"
            f"   Сервер: {server.name}\n"
            f"   Порт: {inbound.port}\n"
            f"   Email: {conn.email}\n"
            f"   UUID: {conn.uuid}\n\n"
        )

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Добавить inbound", callback_data=f"subscription_add_inbound_{subscription_id}")
    kb.button(text="🔙 Назад", callback_data=f"subscription_select_{subscription_id}")
    kb.adjust(1)

    try:
        await callback.message.edit_text(text, reply_markup=kb.as_markup())
    except Exception:
        # Message hasn't changed, skip edit
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("subscription_add_inbound_"))
async def start_add_inbound(callback: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    """Start adding new inbound to subscription."""
    if not is_admin:
        await callback.answer("❌ У вас нет прав администратора.", show_alert=True)
        return

    subscription_id = int(callback.data.split("_")[-1])
    await state.update_data(subscription_id=subscription_id)

    # Show server selection
    from app.services.xui_service import XUIService

    async with async_session_factory() as session:
        service = XUIService(session)
        servers = await service.get_active_servers()

    if not servers:
        await callback.answer("❌ Нет активных серверов.", show_alert=True)
        return

    await state.set_state(ClientManagement.waiting_for_inbound_server)
    try:
        await callback.message.edit_text(
            "Выберите сервер:",
            reply_markup=get_servers_keyboard(servers, action="add_inbound"),
        )
    except Exception:
        # Message hasn't changed, skip edit
        pass
    await callback.answer()


@router.callback_query(ClientManagement.waiting_for_inbound_server, F.data.startswith("server_add_inbound_"))
async def select_server_for_add_inbound(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle server selection for adding inbound."""
    server_id = int(callback.data.split("_")[-1])
    await state.update_data(server_id=server_id)

    from app.services.xui_service import XUIService

    async with async_session_factory() as session:
        service = XUIService(session)
        inbounds = await service.get_server_inbounds(server_id)

    if not inbounds:
        await callback.answer("❌ У сервера нет активных inbounds.", show_alert=True)
        return

    await state.set_state(ClientManagement.waiting_for_inbound_selection)
    try:
        await callback.message.edit_text(
            "Выберите inbound:",
            reply_markup=await get_inbounds_keyboard(inbounds),
        )
    except Exception:
        # Message hasn't changed, skip edit
        pass
    await callback.answer()


@router.callback_query(ClientManagement.waiting_for_inbound_selection, F.data.startswith("add_inbound_"))
async def confirm_add_inbound(callback: CallbackQuery, state: FSMContext) -> None:
    """Confirm adding inbound to subscription."""
    data = await state.get_data()
    subscription_id = data["subscription_id"]
    server_id = data["server_id"]
    inbound_id = int(callback.data.split("_")[-1])

    from app.services.xui_service import XUIService
    from app.database.models import Subscription, Inbound

    async with async_session_factory() as session:
        service = XUIService(session)

        # Get subscription and inbound info
        result = await session.execute(
            select(Subscription).where(Subscription.id == subscription_id)
        )
        subscription = result.scalar_one_or_none()

        if not subscription:
            await callback.answer("❌ Подписка не найдена.", show_alert=True)
            return

        result = await session.execute(
            select(Inbound).where(Inbound.id == inbound_id)
        )
        inbound = result.scalar_one_or_none()

        if not inbound:
            await callback.answer("❌ Inbound не найден.", show_alert=True)
            return

        try:
            # Check if connection already exists
            from sqlalchemy import select as sql_select
            from app.database.models import InboundConnection

            existing = await session.execute(
                sql_select(InboundConnection).where(
                    (InboundConnection.subscription_id == subscription_id) &
                    (InboundConnection.inbound_id == inbound_id)
                )
            )
            if existing.scalar_one_or_none():
                await callback.answer("❌ Этот inbound уже добавлен к подписке.", show_alert=True)
                return

            # TODO: Create client in XUI panel
            # This requires implementing actual XUI client creation
            # For now, just show placeholder

            try:
                await callback.message.edit_text(
                    "⚠️ Создание клиентов в XUI в разработке.\n\n"
                    f"Подписка: {subscription.name}\n"
                    f"Inbound: {inbound.remark} ({inbound.protocol})\n\n"
                    "Функционал будет реализован в следующих этапах.",
                    reply_markup=get_back_keyboard(f"subscription_inbounds_{subscription_id}"),
                )
            except Exception:
                # Message hasn't changed, skip edit
                pass

        except Exception as e:
            logger.error(f"Error adding inbound: {e}", exc_info=True)
            await callback.answer(f"❌ Ошибка: {e}", show_alert=True)

        finally:
            await service.close_all_clients()

    await state.clear()
    await callback.answer()


async def get_inbounds_keyboard(inbounds: list) -> str:
    """Get inbounds keyboard."""
    builder = InlineKeyboardBuilder()

    for inbound in inbounds:
        status = "✅" if inbound.is_active else "❌"
        builder.button(
            text=f"📦 {status} {inbound.remark} ({inbound.protocol})",
            callback_data=f"add_inbound_{inbound.id}",
        )

    builder.adjust(1)
    return builder.as_markup()



@router.callback_query(F.data.startswith("client_rename_name_"))
async def start_rename_client_name(callback: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    """Start renaming client name."""
    if not is_admin:
        await callback.answer("❌ У вас нет прав администратора.", show_alert=True)
        return

    client_id = int(callback.data.split("_")[-1])
    await state.update_data(client_id=client_id)
    await state.set_state(ClientManagement.waiting_for_new_name)

    try:
        await callback.message.edit_text(
            "✏️ Изменение имени клиента\n\n"
            "Введите новое имя:",
            reply_markup=get_back_keyboard(f"client_select_{client_id}"),
        )
    except Exception:
        # Message hasn't changed, skip edit
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("client_rename_telegram_"))
async def start_rename_client_telegram(callback: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    """Start changing client Telegram ID."""
    if not is_admin:
        await callback.answer("❌ У вас нет прав администратора.", show_alert=True)
        return

    client_id = int(callback.data.split("_")[-1])
    await state.update_data(client_id=client_id)
    await state.set_state(ClientManagement.waiting_for_new_telegram_id)

    try:
        await callback.message.edit_text(
            "📱 Изменение Telegram ID\n\n"
            "Введите новый Telegram ID (или '-' для удаления):",
            reply_markup=get_back_keyboard(f"client_select_{client_id}"),
        )
    except Exception:
        # Message hasn't changed, skip edit
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("client_rename_"))
async def start_rename_client(callback: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    """Start renaming client - DEPRECATED handler, redirects to specific handlers."""
    # This handler is kept for backward compatibility but redirects to specific handlers
    # Extract the action from callback data
    parts = callback.data.split("_")
    if len(parts) >= 3:
        action = parts[2]  # "name" or "telegram"
        if action == "name":
            return await start_rename_client_name(callback, state, is_admin)
        elif action == "telegram":
            return await start_rename_client_telegram(callback, state, is_admin)

    # Default fallback to name change
    return await start_rename_client_name(callback, state, is_admin)


@router.message(ClientManagement.waiting_for_new_name)
async def process_rename_client(message: Message, state: FSMContext) -> None:
    """Process client rename."""
    data = await state.get_data()
    client_id = data["client_id"]

    async with async_session_factory() as session:
        service = ClientService(session)
        client = await service.rename_client(client_id, message.text)
        await session.commit()

    await state.clear()
    await message.answer(
        f"✅ Клиент переименован в '{client.name}'",
        reply_markup=get_back_keyboard(f"client_select_{client_id}"),
    )


@router.message(ClientManagement.waiting_for_new_telegram_id)
async def process_rename_client_telegram(message: Message, state: FSMContext) -> None:
    """Process client Telegram ID change."""
    data = await state.get_data()
    client_id = data["client_id"]
    telegram_id_input = message.text.strip()

    # Process Telegram ID change
    telegram_id = None
    if telegram_id_input and telegram_id_input != "-":
        try:
            telegram_id = int(telegram_id_input)
        except ValueError:
            await message.answer("❌ Telegram ID должен быть числом или '-'.")
            return
    elif telegram_id_input == "-":
        telegram_id = None  # Remove Telegram ID

    async with async_session_factory() as session:
        service = ClientService(session)
        client = await service.update_client(
            client_id,
            telegram_id=telegram_id,
        )
        await session.commit()

    await state.clear()
    if telegram_id:
        await message.answer(
            f"✅ Telegram ID изменен на {telegram_id}",
            reply_markup=get_back_keyboard(f"client_select_{client_id}"),
        )
    else:
        await message.answer(
            "✅ Telegram ID удален",
            reply_markup=get_back_keyboard(f"client_select_{client_id}"),
        )


@router.callback_query(F.data.startswith("client_enable_"))
async def enable_client(callback: CallbackQuery, is_admin: bool) -> None:
    """Enable client."""
    if not is_admin:
        await callback.answer("❌ У вас нет прав администратора.", show_alert=True)
        return

    client_id = int(callback.data.split("_")[-1])

    async with async_session_factory() as session:
        from app.services.new_subscription_service import NewSubscriptionService

        client_service = ClientService(session)
        sub_service = NewSubscriptionService(session)

        try:
            # Enable client in database
            await client_service.set_client_active(client_id, True)

            # Enable all XUI connections
            toggled = await sub_service.toggle_client_all_connections(client_id, enable=True)

            await session.commit()

            await callback.answer(f"✅ Клиент включен. Активировано {toggled} подключений в XUI.")
            # Re-select to refresh view
            await _show_client_details(client_id, callback)
        finally:
            await sub_service.close_all_clients()


@router.callback_query(F.data.startswith("client_disable_"))
async def disable_client(callback: CallbackQuery, is_admin: bool) -> None:
    """Disable client."""
    if not is_admin:
        await callback.answer("❌ У вас нет прав администратора.", show_alert=True)
        return

    client_id = int(callback.data.split("_")[-1])

    async with async_session_factory() as session:
        from app.services.new_subscription_service import NewSubscriptionService

        client_service = ClientService(session)
        sub_service = NewSubscriptionService(session)

        try:
            # Disable client in database
            await client_service.set_client_active(client_id, False)

            # Disable all XUI connections
            toggled = await sub_service.toggle_client_all_connections(client_id, enable=False)

            await session.commit()

            await callback.answer(f"✅ Клиент отключен. Деактивировано {toggled} подключений в XUI.")
            await _show_client_details(client_id, callback)
        finally:
            await sub_service.close_all_clients()


@router.callback_query(F.data.startswith("client_delete_"))
async def confirm_delete_client(callback: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    """Confirm client deletion."""
    if not is_admin:
        await callback.answer("❌ У вас нет прав администратора.", show_alert=True)
        return

    client_id = int(callback.data.split("_")[-1])
    await state.update_data(client_id=client_id)
    await state.set_state(ClientManagement.confirm_delete)

    try:
        await callback.message.edit_text(
            "⚠️ Вы уверены, что хотите удалить этого клиента?\n\n"
            "Все его подписки и подключения будут также удалены!",
            reply_markup=get_confirm_keyboard(f"client_delete_{client_id}", "admin_clients"),
        )
    except Exception:
        # Message hasn't changed, skip edit
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("confirm_client_delete_"))
async def delete_client(callback: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    """Delete client."""
    if not is_admin:
        await callback.answer("❌ У вас нет прав администратора.", show_alert=True)
        return

    client_id = int(callback.data.split("_")[-1])

    async with async_session_factory() as session:
        from app.services.new_subscription_service import NewSubscriptionService

        client_service = ClientService(session)
        sub_service = NewSubscriptionService(session)

        try:
            # Delete all XUI clients first
            deleted_count = await sub_service.delete_client_all_connections(client_id)

            # Then delete client from database
            await client_service.delete_client(client_id)
            await session.commit()

            await state.clear()
            await callback.answer(f"✅ Клиент удален. Удалено {deleted_count} подключений из XUI.")
            await show_clients(callback, is_admin)
        finally:
            await sub_service.close_all_clients()


@router.callback_query(F.data.startswith("client_make_admin_"))
async def make_admin(callback: CallbackQuery, is_admin: bool) -> None:
    """Make client admin."""
    if not is_admin:
        await callback.answer("❌ У вас нет прав администратора.", show_alert=True)
        return

    client_id = int(callback.data.split("_")[-1])

    async with async_session_factory() as session:
        service = ClientService(session)
        await service.set_client_admin(client_id, True)
        await session.commit()

    await callback.answer("✅ Клиент теперь админ.")
    # Re-select to refresh view
    await _show_client_details(client_id, callback)


@router.callback_query(F.data.startswith("client_unadmin_"))
async def unmake_admin(callback: CallbackQuery, is_admin: bool) -> None:
    """Remove admin status from client."""
    if not is_admin:
        await callback.answer("❌ У вас нет прав администратора.", show_alert=True)
        return

    client_id = int(callback.data.split("_")[-1])

    async with async_session_factory() as session:
        service = ClientService(session)
        await service.set_client_admin(client_id, False)
        await session.commit()

    await callback.answer("✅ Клиент больше не админ.")
    # Re-select to refresh view
    await _show_client_details(client_id, callback)