"""Admin subscription management handlers."""

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from loguru import logger
from typing import Set
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.bot.keyboards import (
    get_back_keyboard,
    get_confirm_keyboard,
    get_servers_keyboard,
    get_clients_keyboard,
)
from app.bot.states import SubscriptionManagement
from app.database import async_session_factory
from app.database.models import Inbound
from app.services.client_service import ClientService
from app.services.xui_service import XUIService

router = Router()


@router.callback_query(F.data == "admin_create_subscription")
async def start_create_subscription(callback: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    """Start subscription creation flow."""
    if not is_admin:
        await callback.answer("❌ У вас нет прав администратора.", show_alert=True)
        return

    async with async_session_factory() as session:
        service = ClientService(session)
        clients = await service.get_active_clients()

    if not clients:
        await callback.answer("❌ Нет клиентов. Сначала создайте клиента.", show_alert=True)
        return

    await state.set_state(SubscriptionManagement.waiting_for_client_selection)
    await callback.message.edit_text(
        "📝 Создание подписки\n\n"
        "Выберите клиента:",
        reply_markup=await get_clients_keyboard(clients),
    )
    await callback.answer()


async def get_clients_keyboard(clients: list) -> str:
    """Get clients selection keyboard."""
    builder = InlineKeyboardBuilder()

    for client in clients:
        status = "✅" if client.is_active else "❌"
        admin_badge = "👑" if client.is_admin else ""
        builder.button(
            text=f"{status} {admin_badge} {client.name}",
            callback_data=f"sub_client_select_{client.id}",
        )

    builder.adjust(1)
    return builder.as_markup()


@router.callback_query(SubscriptionManagement.waiting_for_client_selection, F.data.startswith("sub_client_select_"))
async def select_client_for_subscription(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle client selection for subscription."""
    client_id = int(callback.data.split("_")[-1])
    await state.update_data(client_id=client_id)

    async with async_session_factory() as session:
        service = XUIService(session)
        servers = await service.get_active_servers()

    if not servers:
        await callback.answer("❌ Нет активных серверов. Сначала добавьте сервер.", show_alert=True)
        return

    await state.set_state(SubscriptionManagement.waiting_for_server_selection)
    await callback.message.edit_text(
        "Выберите сервер:",
        reply_markup=get_servers_keyboard(servers, action="sub_select"),
    )
    await callback.answer()


@router.callback_query(SubscriptionManagement.waiting_for_server_selection, F.data.startswith("server_sub_select_"))
async def select_server_for_subscription(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle server selection for subscription."""
    server_id = int(callback.data.split("_")[-1])
    await state.update_data(server_id=server_id)

    async with async_session_factory() as session:
        service = XUIService(session)
        inbounds = await service.get_server_inbounds(server_id)

    if not inbounds:
        await callback.answer("❌ У сервера нет активных inbounds. Сначала синхронизируйте сервер.", show_alert=True)
        return

    await state.set_state(SubscriptionManagement.waiting_for_inbound_selection)
    await state.update_data(selected_inbounds=set())

    await callback.message.edit_text(
        "📢 Выберите inbounds (можно выбрать несколько):\n\n"
        "Нажмите '➡️ Создать подписку' когда выбор готов:",
        reply_markup=await get_inbounds_selection_keyboard(inbounds, mode="create"),
    )
    await callback.answer()


@router.callback_query(SubscriptionManagement.waiting_for_inbound_selection, F.data.startswith("toggle_inbound_"))
async def toggle_inbound_selection(callback: CallbackQuery, state: FSMContext) -> None:
    """Toggle inbound selection."""
    inbound_id = int(callback.data.split("_")[-1])
    data = await state.get_data()
    selected_inbounds = data.get("selected_inbounds", set())

    if inbound_id in selected_inbounds:
        selected_inbounds.remove(inbound_id)
    else:
        selected_inbounds.add(inbound_id)

    await state.update_data(selected_inbounds=selected_inbounds)

    # Get inbounds for updating keyboard
    server_id = data["server_id"]
    async with async_session_factory() as session:
        service = XUIService(session)
        inbounds = await service.get_server_inbounds(server_id)

    # Determine mode: "add" if subscription_id exists, otherwise "create"
    mode = "add" if data.get("subscription_id") else "create"

    # Update keyboard with selection state
    builder = InlineKeyboardBuilder()

    for inbound in inbounds:
        status = "✅" if inbound.is_active else "❌"
        selected = "🔘" if inbound.id in selected_inbounds else "⭕"
        builder.button(
            text=f"{selected} {status} {inbound.remark} ({inbound.protocol})",
            callback_data=f"toggle_inbound_{inbound.id}",
        )

    if mode == "create":
        builder.button(text="➡️ Создать подписку", callback_data="confirm_inbounds")
    else:
        builder.button(text="➡️ Добавить inbounds", callback_data="confirm_add_inbounds")

    builder.adjust(1)

    await callback.message.edit_reply_markup(reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(SubscriptionManagement.waiting_for_inbound_selection, F.data == "confirm_inbounds")
async def confirm_inbound_selection(callback: CallbackQuery, state: FSMContext) -> None:
    """Confirm inbound selection and ask for parameters."""
    data = await state.get_data()
    selected_inbounds = data.get("selected_inbounds", set())

    if not selected_inbounds:
        await callback.answer("❌ Выберите хотя бы один inbound.", show_alert=True)
        return

    await state.set_state(SubscriptionManagement.waiting_for_subscription_name)
    await callback.message.edit_text(
        f"Выбрано {len(selected_inbounds)} inbounds\n\n"
        "Введите название подписки:",
        reply_markup=get_back_keyboard("admin_create_subscription"),
    )
    await callback.answer()


@router.message(SubscriptionManagement.waiting_for_subscription_name)
async def process_subscription_name(message: Message, state: FSMContext) -> None:
    """Process subscription name input."""
    data = await state.get_data()

    # Check if this is editing all parameters flow
    if data.get("editing_all"):
        name = message.text.strip()

        if not name:
            await message.answer("❌ Название не может быть пустым.")
            return

        if len(name) > 100:
            await message.answer("❌ Название не должно превышать 100 символов.")
            return

        await state.update_data(name=name)
        await state.set_state(SubscriptionManagement.waiting_for_traffic_limit)
        traffic = data.get("total_gb", 0)
        traffic_str = f"{traffic} GB" if traffic > 0 else "Безлимит"
        await message.answer(
            f"Текущий трафик: {traffic_str}\n"
            "Введите новый лимит трафика в GB (0 для безлимита):",
            reply_markup=get_back_keyboard("admin_sub_edit"),
        )
        return

    # Original creation flow
    name = message.text.strip()

    if not name:
        await message.answer("❌ Название не может быть пустым.")
        return

    if len(name) > 100:
        await message.answer("❌ Название не должно превышать 100 символов.")
        return

    await state.update_data(subscription_name=name)
    await state.set_state(SubscriptionManagement.waiting_for_traffic_limit)
    await message.answer(
        "Введите лимит трафика в GB (0 для безлимита):",
        reply_markup=get_back_keyboard("admin_create_subscription"),
    )


@router.message(SubscriptionManagement.waiting_for_traffic_limit)
async def process_traffic_limit(message: Message, state: FSMContext) -> None:
    """Process traffic limit."""
    data = await state.get_data()

    # Check if this is editing all parameters flow
    if data.get("editing_all"):
        try:
            total_gb = int(message.text)
            if total_gb < 0:
                raise ValueError("Negative value")
        except ValueError:
            await message.answer("❌ Введите неотрицательное число.")
            return

        await state.update_data(total_gb=total_gb)
        await state.set_state(SubscriptionManagement.waiting_for_expiry_days)
        expiry_date = data.get("expiry_date")
        expiry_str = f"{expiry_date.strftime('%d.%m.%Y')}" if expiry_date else "Бессрочно"
        await message.answer(
            f"Текущий срок: {expiry_str}\n"
            "Введите новый срок действия в днях (0 для бессрочной):",
            reply_markup=get_back_keyboard("admin_sub_edit"),
        )
        return

    # Original creation flow
    try:
        total_gb = int(message.text)
        if total_gb < 0:
            raise ValueError("Negative value")
    except ValueError:
        await message.answer("❌ Введите неотрицательное число.")
        return

    await state.update_data(total_gb=total_gb)

    await state.set_state(SubscriptionManagement.waiting_for_expiry_days)
    await message.answer(
        "Введите срок действия в днях (0 для бессрочной):",
        reply_markup=get_back_keyboard("admin_create_subscription"),
    )


@router.message(SubscriptionManagement.waiting_for_expiry_days)
async def process_expiry_days(message: Message, state: FSMContext) -> None:
    """Process expiry days and show confirmation."""
    data = await state.get_data()

    # Check if this is editing all parameters flow
    if data.get("editing_all"):
        try:
            expiry_days = int(message.text)
            if expiry_days < 0:
                raise ValueError("Negative value")
        except ValueError:
            await message.answer("❌ Введите неотрицательное число.")
            return

        subscription_id = data["subscription_id"]
        expiry_days_param = expiry_days if expiry_days > 0 else None

        # Update subscription with all new parameters
        async with async_session_factory() as session:
            from app.services.new_subscription_service import NewSubscriptionService
            service = NewSubscriptionService(session)
            subscription = await service.update_subscription(
                subscription_id,
                name=data.get("name"),
                total_gb=data.get("total_gb"),
                expiry_days=expiry_days_param,
                notes=data.get("notes"),
            )
            await session.commit()

        await state.clear()
        expiry_str = f"{expiry_days} дней" if expiry_days > 0 else "Бессрочно"
        await message.answer(
            f"✅ Все параметры обновлены для подписки '{subscription.name}'\n\n"
            f"📝 Название: {subscription.name}\n"
            f"📊 Трафик: {'Безлимит' if subscription.total_gb == 0 else f'{subscription.total_gb} GB'}\n"
            f"⏰ Срок: {expiry_str}",
            reply_markup=get_back_keyboard(f"admin_sub_detail_{subscription_id}"),
        )
        return

    # Original creation flow
    try:
        expiry_days = int(message.text)
        if expiry_days < 0:
            raise ValueError("Negative value")
    except ValueError:
        await message.answer("❌ Введите неотрицательное число.")
        return

    data = await state.get_data()
    expiry_days = expiry_days if expiry_days > 0 else None
    await state.update_data(expiry_days=expiry_days)

    # Get info for confirmation
    async with async_session_factory() as session:
        client_service = ClientService(session)
        xui_service = XUIService(session)

        client = await client_service.get_client_by_id(data["client_id"])
        server = await xui_service.get_server_by_id(data["server_id"])
        inbounds = await xui_service.get_server_inbounds(data["server_id"])
        selected_inbounds = [ib for ib in inbounds if ib.id in data["selected_inbounds"]]

    traffic_str = f"{data['total_gb']} GB" if data["total_gb"] > 0 else "Безлимит"
    expiry_str = f"{expiry_days} дней" if expiry_days else "Бессрочно"

    text = (
        "📝 Подтверждение создания подписки:\n\n"
        f"👤 Клиент: {client.name}\n"
        f"🖥️ Сервер: {server.name}\n"
        f"📦 Inbounds: {', '.join(ib.remark for ib in selected_inbounds)}\n"
        f"📊 Трафик: {traffic_str}\n"
        f"⏰ Срок: {expiry_str}"
    )

    await state.set_state(SubscriptionManagement.confirm_creation)
    await message.answer(
        text,
        reply_markup=get_confirm_keyboard("create_subscription", "admin_create_subscription"),
    )


@router.callback_query(SubscriptionManagement.confirm_creation, F.data == "confirm_create_subscription")
async def create_subscription(callback: CallbackQuery, state: FSMContext) -> None:
    """Create subscription with inbound connections."""
    data = await state.get_data()

    async with async_session_factory() as session:
        client_service = ClientService(session)
        xui_service = XUIService(session)

        try:
            # Create subscription in database
            from app.services.new_subscription_service import NewSubscriptionService

            sub_service = NewSubscriptionService(session)
            subscription = await sub_service.create_subscription(
                client_id=data["client_id"],
                name=data["subscription_name"],
                total_gb=data["total_gb"],
                expiry_days=data["expiry_days"],
            )

            # Get server and inbounds
            server = await xui_service.get_server_by_id(data["server_id"])
            inbounds = await xui_service.get_server_inbounds(data["server_id"])
            selected_inbounds = [ib for ib in inbounds if ib.id in data["selected_inbounds"]]

            # Create clients in XUI for each selected inbound
            created_connections = []
            for inbound in selected_inbounds:
                connection = await sub_service.add_inbound_to_subscription(
                    subscription.id,
                    inbound.id,
                )
                created_connections.append(connection)

            await session.commit()

            # Show success message
            inbound_names = ", ".join([ib.remark for ib in selected_inbounds])
            traffic_str = f"{data['total_gb']} GB" if data["total_gb"] > 0 else "Безлимит"
            expiry_str = f"{data['expiry_days']} дней" if data["expiry_days"] else "Бессрочно"

            await callback.message.edit_text(
                f"✅ Подписка успешно создана!\n\n"
                f"📝 Название: {subscription.name}\n"
                f"👤 Клиент: {subscription.client.name}\n"
                f"🖥️ Сервер: {server.name}\n"
                f"📦 Inbounds: {inbound_names}\n"
                f"📊 Трафик: {traffic_str}\n"
                f"⏰ Срок: {expiry_str}\n"
                f"🔑 Токен: {subscription.subscription_token}\n"
                f"📝 Создано подключений: {len(created_connections)}",
                reply_markup=get_back_keyboard("admin_menu"),
            )

        except Exception as e:
            logger.error(f"Error creating subscription: {e}", exc_info=True)
            await callback.answer(f"❌ Ошибка: {e}", show_alert=True)
            await callback.message.edit_text(
                f"❌ Ошибка при создании подписки: {e}",
                reply_markup=get_back_keyboard("admin_create_subscription"),
            )

        finally:
            await xui_service.close_all_clients()

    await state.clear()
    await callback.answer()


# Additional subscription management handlers
async def list_all_subscriptions(callback: CallbackQuery, is_admin: bool) -> None:
    """Show all subscriptions for admin."""
    if not is_admin:
        await callback.answer("❌ У вас нет прав администратора.", show_alert=True)
        return

    async with async_session_factory() as session:
        from app.services.new_subscription_service import NewSubscriptionService
        service = NewSubscriptionService(session)
        subscriptions = await service.get_all_subscriptions()

    logger.info(f"Loading subscriptions: found {len(subscriptions) if subscriptions else 0} subscriptions")

    if not subscriptions:
        await callback.message.edit_text(
            "📝 Список подписок пуст.\n\n"
            "Создайте первую подписку через 'Создать подписку'.",
            reply_markup=get_back_keyboard("admin_menu"),
        )
        await callback.answer()
        return

    text = f"📝 Все подписки ({len(subscriptions)}):\n\n"

    builder = InlineKeyboardBuilder()

    for sub in subscriptions:
        status = "✅" if sub.is_active else "❌"
        expiry = sub.expiry_date.strftime("%d.%m.%Y") if sub.expiry_date else "Бессрочно"
        traffic = "Безлимит" if sub.is_unlimited else f"{sub.total_gb} GB"

        text += (
            f"{status} <b>{sub.name}</b>\n"
            f"   Клиент: {sub.client.name}\n"
            f"   Трафик: {traffic}\n"
            f"   Срок: {expiry}\n"
            f"   Подключений: {len(sub.inbound_connections)}\n\n"
        )

        # Add button for each subscription
        builder.button(text=f"📝 {sub.name}", callback_data=f"admin_sub_detail_{sub.id}")

    builder.button(text="➕ Создать подписку", callback_data="admin_create_subscription")
    builder.button(text="🔙 Назад", callback_data="admin_menu")
    builder.adjust(1)

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("admin_sub_detail_"))
async def show_subscription_details(callback: CallbackQuery, is_admin: bool) -> None:
    """Show detailed subscription information."""
    if not is_admin:
        await callback.answer("❌ У вас нет прав администратора.", show_alert=True)
        return

    subscription_id = int(callback.data.split("_")[-1])

    async with async_session_factory() as session:
        from app.services.new_subscription_service import NewSubscriptionService
        service = NewSubscriptionService(session)
        subscription = await service.get_subscription(subscription_id)

    if not subscription:
        await callback.answer("❌ Подписка не найдена.", show_alert=True)
        return

    status = "✅ Активна" if subscription.is_active else "❌ Неактивна"
    expiry = subscription.expiry_date.strftime("%d.%m.%Y") if subscription.expiry_date else "Бессрочно"
    traffic = "Безлимит" if subscription.is_unlimited else f"{subscription.total_gb} GB"

    text = (
        f"📝 Подписка: <b>{subscription.name}</b>\n\n"
        f"ID: {subscription.id}\n"
        f"Клиент: {subscription.client.name} (ID: {subscription.client_id})\n"
        f"Токен: <code>{subscription.subscription_token}</code>\n"
        f"Статус: {status}\n"
        f"Трафик: {traffic}\n"
        f"Срок: {expiry}\n"
        f"Создана: {subscription.created_at.strftime('%d.%m.%Y %H:%M')}\n"
        f"Подключений: {len(subscription.inbound_connections)}\n\n"
    )

    if subscription.notes:
        text += f"📝 Заметки: {subscription.notes}\n\n"

    builder = InlineKeyboardBuilder()
    builder.button(text="📢 Inbounds", callback_data=f"admin_sub_inbounds_{subscription_id}")
    builder.button(text="✏️ Редактировать", callback_data=f"admin_sub_edit_{subscription_id}")
    if subscription.is_active:
        builder.button(text="❌ Отключить", callback_data=f"admin_sub_disable_{subscription_id}")
    else:
        builder.button(text="✅ Включить", callback_data=f"admin_sub_enable_{subscription_id}")
    builder.button(text="🗑️ Удалить", callback_data=f"admin_sub_delete_{subscription_id}")
    builder.button(text="🔙 Назад", callback_data="admin_menu")
    builder.adjust(1)

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("admin_sub_inbounds_"))
async def show_subscription_inbounds(callback: CallbackQuery, is_admin: bool) -> None:
    """Show inbounds for subscription with management options."""
    if not is_admin:
        await callback.answer("❌ У вас нет прав администратора.", show_alert=True)
        return

    subscription_id = int(callback.data.split("_")[-1])

    async with async_session_factory() as session:
        from app.services.new_subscription_service import NewSubscriptionService
        service = NewSubscriptionService(session)
        connections = await service.get_subscription_inbounds(subscription_id)

    if not connections:
        builder = InlineKeyboardBuilder()
        builder.button(text="🔙 Назад", callback_data=f"admin_sub_inbounds_{subscription_id}")
        builder.adjust(1)

        await callback.message.edit_text(
            "❌ У подписки нет подключений.\n\n"
            "Добавьте первый inbound для использования подписки.",
            reply_markup=builder.as_markup()
        )
        await callback.answer()
        return

    text = f"📢 Inbounds подписки (ID: {subscription_id}):\n\n"

    builder = InlineKeyboardBuilder()

    for conn in connections:
        status = "✅" if conn.is_enabled else "❌"
        inbound = conn.inbound
        server = inbound.server

        text += (
            f"{status} {inbound.remark} ({inbound.protocol})\n"
            f"   Сервер: {server.name}\n"
            f"   Порт: {inbound.port}\n"
            f"   Email: {conn.email}\n"
            f"   UUID: {conn.uuid}\n"
            f"   ID подключения: {conn.id}\n\n"
        )

        # Add buttons for each inbound
        if conn.is_enabled:
            builder.button(text=f"✅ {inbound.remark}", callback_data=f"toggle_conn_{conn.id}")
        else:
            builder.button(text=f"🔌 {inbound.remark}", callback_data=f"toggle_conn_{conn.id}")
        builder.button(text="🗑️", callback_data=f"delete_conn_{conn.id}")
        builder.adjust(2)

    # Add action buttons once at the bottom
    builder.button(text="✅ Множественный выбор", callback_data=f"inbounds_multi_select_{subscription_id}")
    builder.button(text="➕ Добавить inbound", callback_data=f"admin_sub_add_inbound_{subscription_id}")
    builder.button(text="🔙 Назад", callback_data=f"admin_sub_detail_{subscription_id}")
    builder.adjust(1)

    try:
        await callback.message.edit_text(text, reply_markup=builder.as_markup())
    except Exception as e:
        logger.warning(f"Failed to edit message in show_subscription_inbounds: {e}")
        # Try to edit reply_markup only as fallback
        try:
            await callback.message.edit_reply_markup(reply_markup=builder.as_markup())
        except Exception as e2:
            logger.error(f"Failed to edit reply_markup: {e2}")
    await callback.answer()


@router.callback_query(F.data.startswith("admin_sub_add_inbound_"))
async def start_add_inbound_to_subscription(callback: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    """Start adding inbound to existing subscription."""
    if not is_admin:
        await callback.answer("❌ У вас нет прав администратора.", show_alert=True)
        return

    subscription_id = int(callback.data.split("_")[-1])
    await state.update_data(subscription_id=subscription_id)

    async with async_session_factory() as session:
        service = XUIService(session)
        servers = await service.get_active_servers()

    if not servers:
        await callback.answer("❌ Нет активных серверов.", show_alert=True)
        return

    await state.set_state(SubscriptionManagement.waiting_for_server_selection)
    await callback.message.edit_text(
        "📢 Добавление inbound к подписке\n\n"
        "Выберите сервер:",
        reply_markup=get_servers_keyboard(servers, action="sub_add_inbound"),
    )
    await callback.answer()


@router.callback_query(SubscriptionManagement.waiting_for_server_selection, F.data.startswith("server_sub_add_inbound_"))
async def select_server_for_add_inbound(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle server selection for adding inbound."""
    server_id = int(callback.data.split("_")[-1])
    await state.update_data(server_id=server_id)

    async with async_session_factory() as session:
        service = XUIService(session)
        inbounds = await service.get_server_inbounds(server_id)

    if not inbounds:
        await callback.answer("❌ У сервера нет активных inbounds.", show_alert=True)
        return

    await state.set_state(SubscriptionManagement.waiting_for_inbound_selection)
    await state.update_data(selected_inbounds=set())

    await callback.message.edit_text(
        "📢 Выберите inbounds (можно выбрать несколько):\n\n"
        "Нажмите '➡️ Добавить inbounds' когда выбор готов:",
        reply_markup=await get_inbounds_selection_keyboard(inbounds, mode="add"),
    )
    await callback.answer()


@router.callback_query(F.data == "confirm_add_inbounds")
async def confirm_add_inbounds(callback: CallbackQuery, state: FSMContext) -> None:
    """Confirm and add inbounds to subscription."""
    data = await state.get_data()
    selected_inbounds = data.get("selected_inbounds", set())
    subscription_id = data.get("subscription_id")

    if not subscription_id:
        # Creating new subscription flow - use existing handler
        from app.bot.handlers.admin.subscriptions import confirm_inbound_selection as original_confirm
        await original_confirm(callback, state)
        return

    if not selected_inbounds:
        await callback.answer("❌ Выберите хотя бы один inbound.", show_alert=True)
        return

    async with async_session_factory() as session:
        from app.services.new_subscription_service import NewSubscriptionService
        service = NewSubscriptionService(session)

        try:
            added_count = 0
            for inbound_id in selected_inbounds:
                try:
                    await service.add_inbound_to_subscription(subscription_id, inbound_id)
                    added_count += 1
                except Exception as e:
                    logger.warning(f"Failed to add inbound {inbound_id}: {e}")

            await session.commit()

            await callback.message.edit_text(
                f"✅ Успешно добавлено {added_count} inbounds к подписке!",
                reply_markup=get_back_keyboard(f"admin_sub_inbounds_{subscription_id}"),
            )
            await callback.answer(f"Добавлено {added_count} inbounds", show_alert=True)

        except Exception as e:
            logger.error(f"Error adding inbounds: {e}", exc_info=True)
            await callback.answer(f"❌ Ошибка: {e}", show_alert=True)
            await callback.message.edit_text(
                f"❌ Ошибка при добавлении inbounds: {e}",
                reply_markup=get_back_keyboard(f"admin_sub_inbounds_{subscription_id}"),
            )
        finally:
            await service.close_all_clients()

    await state.clear()




async def get_inbounds_selection_keyboard(inbounds: list, mode: str = "create") -> str:
    """Get inbounds selection keyboard with checkboxes.

    Args:
        inbounds: List of inbound objects
        mode: "create" for new subscription, "add" for adding to existing subscription

    Returns:
        Inline keyboard markup
    """
    builder = InlineKeyboardBuilder()

    for inbound in inbounds:
        status = "✅" if inbound.is_active else "❌"
        builder.button(
            text=f"📦 {status} {inbound.remark} ({inbound.protocol})",
            callback_data=f"toggle_inbound_{inbound.id}",
        )

    if mode == "create":
        builder.button(text="➡️ Создать подписку", callback_data="confirm_inbounds")
    else:
        builder.button(text="➡️ Добавить inbounds", callback_data="confirm_add_inbounds")

    builder.adjust(1)
    return builder.as_markup()


@router.callback_query(F.data.startswith("toggle_conn_"))
async def toggle_inbound_connection(callback: CallbackQuery, is_admin: bool) -> None:
    """Toggle inbound connection (enable/disable)."""
    if not is_admin:
        await callback.answer("❌ У вас нет прав администратора.", show_alert=True)
        return

    connection_id = int(callback.data.split("_")[-1])

    async with async_session_factory() as session:
        from app.services.new_subscription_service import NewSubscriptionService
        service = NewSubscriptionService(session)

        try:
            # Get current connection
            from app.database.models import InboundConnection
            result = await session.execute(
                select(InboundConnection).where(InboundConnection.id == connection_id)
                .options(selectinload(InboundConnection.inbound).selectinload(Inbound.server))
            )
            connection = result.scalar_one_or_none()

            if not connection:
                await callback.answer("❌ Подключение не найдено.", show_alert=True)
                return

            # Toggle connection
            await service.toggle_inbound_connection(connection_id, not connection.is_enabled)
            await session.commit()

            status = "отключено" if not connection.is_enabled else "включено"
            await callback.answer(f"✅ Подключение {status}", show_alert=True)

            # Refresh only the buttons, not the whole interface
            # Get updated connections and rebuild keyboard
            async with async_session_factory() as session2:
                from app.services.new_subscription_service import NewSubscriptionService
                service2 = NewSubscriptionService(session2)
                connections = await service2.get_subscription_inbounds(connection.subscription_id)

            # Rebuild text and keyboard
            text = f"📢 Inbounds подписки (ID: {connection.subscription_id}):\n\n"
            builder = InlineKeyboardBuilder()

            for conn in connections:
                conn_status = "✅" if conn.is_enabled else "❌"
                inbound = conn.inbound
                server = inbound.server

                text += (
                    f"{conn_status} {inbound.remark} ({inbound.protocol})\n"
                    f"   Сервер: {server.name}\n"
                    f"   Порт: {inbound.port}\n"
                    f"   Email: {conn.email}\n"
                    f"   UUID: {conn.uuid}\n"
                    f"   ID подключения: {conn.id}\n\n"
                )

                # Add buttons for each inbound
                if conn.is_enabled:
                    builder.button(text=f"✅ {inbound.remark}", callback_data=f"toggle_conn_{conn.id}")
                else:
                    builder.button(text=f"🔌 {inbound.remark}", callback_data=f"toggle_conn_{conn.id}")
                builder.button(text="🗑️", callback_data=f"delete_conn_{conn.id}")
                builder.adjust(2)

            # Add action buttons once at the bottom
            builder.button(text="➕ Добавить inbound", callback_data=f"admin_sub_add_inbound_{connection.subscription_id}")
            builder.button(text="🔙 Назад", callback_data=f"admin_sub_detail_{connection.subscription_id}")
            builder.adjust(1)

            await callback.message.edit_text(text, reply_markup=builder.as_markup())
            # await show_subscription_inbounds(callback, is_admin)  # Закомментировано

        except Exception as e:
            logger.error(f"Error toggling connection: {e}", exc_info=True)
            await callback.answer(f"❌ Ошибка: {e}", show_alert=True)
        finally:
            await service.close_all_clients()


@router.callback_query(F.data.startswith("inbounds_multi_select_"))
async def enter_multi_select_mode(callback: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    """Enter multi-select mode for inbounds."""
    if not is_admin:
        await callback.answer("❌ У вас нет прав администратора.", show_alert=True)
        return

    subscription_id = int(callback.data.split("_")[-1])
    await state.update_data(subscription_id=subscription_id, selected_connections=set())
    await state.set_state(SubscriptionManagement.inbounds_multi_select_mode)

    # Get connections for this subscription
    async with async_session_factory() as session:
        from app.services.new_subscription_service import NewSubscriptionService
        service = NewSubscriptionService(session)
        connections = await service.get_subscription_inbounds(subscription_id)

    if not connections:
        builder = InlineKeyboardBuilder()
        builder.button(text="🔙 Назад", callback_data=f"admin_sub_inbounds_{subscription_id}")
        builder.adjust(1)
        await callback.message.edit_text(
            "❌ У подписки нет подключений.",
            reply_markup=builder.as_markup()
        )
        await callback.answer()
        return

    # Show multi-select keyboard
    await callback.message.edit_text(
        f"✅ Режим множественного выбора\n\n"
        f"Выберите inbounds для массовых действий:\n"
        f"(Выбрано: 0/{len(connections)})",
        reply_markup=get_multi_select_keyboard(connections, set()),
    )
    await callback.answer()


@router.callback_query(SubscriptionManagement.inbounds_multi_select_mode, F.data.startswith("multi_select_conn_"))
async def toggle_multi_selection(callback: CallbackQuery, state: FSMContext) -> None:
    """Toggle connection selection in multi-select mode."""
    connection_id = int(callback.data.split("_")[-1])
    data = await state.get_data()
    selected_connections = data.get("selected_connections", set())

    if connection_id in selected_connections:
        selected_connections.remove(connection_id)
    else:
        selected_connections.add(connection_id)

    await state.update_data(selected_connections=selected_connections)

    # Get subscription ID and connections
    subscription_id = data["subscription_id"]
    async with async_session_factory() as session:
        from app.services.new_subscription_service import NewSubscriptionService
        service = NewSubscriptionService(session)
        connections = await service.get_subscription_inbounds(subscription_id)

    await callback.message.edit_text(
        f"✅ Режим множественного выбора\n\n"
        f"Выберите inbounds для массовых действий:\n"
        f"(Выбрано: {len(selected_connections)}/{len(connections)})",
        reply_markup=get_multi_select_keyboard(connections, selected_connections),
    )
    await callback.answer()


@router.callback_query(SubscriptionManagement.inbounds_multi_select_mode, F.data == "multi_select_enable_all")
async def enable_selected_connections(callback: CallbackQuery, state: FSMContext) -> None:
    """Enable all selected connections."""
    data = await state.get_data()
    selected_connections = data.get("selected_connections", set())

    if not selected_connections:
        await callback.answer("❌ Выберите хотя бы один inbound.", show_alert=True)
        return

    await state.update_data(action="enable")
    await state.set_state(SubscriptionManagement.inbounds_multi_confirm_action)

    await callback.message.edit_text(
        f"⚠️ Включить {len(selected_connections)} подключений?\n\n"
        "Все выбранные inbounds будут включены.",
        reply_markup=get_multi_select_confirm_keyboard(),
    )
    await callback.answer()


@router.callback_query(SubscriptionManagement.inbounds_multi_select_mode, F.data == "multi_select_disable_all")
async def disable_selected_connections(callback: CallbackQuery, state: FSMContext) -> None:
    """Disable all selected connections."""
    data = await state.get_data()
    selected_connections = data.get("selected_connections", set())

    if not selected_connections:
        await callback.answer("❌ Выберите хотя бы один inbound.", show_alert=True)
        return

    await state.update_data(action="disable")
    await state.set_state(SubscriptionManagement.inbounds_multi_confirm_action)

    await callback.message.edit_text(
        f"⚠️ Отключить {len(selected_connections)} подключений?\n\n"
        "Все выбранные inbounds будут отключены.",
        reply_markup=get_multi_select_confirm_keyboard(),
    )
    await callback.answer()


@router.callback_query(SubscriptionManagement.inbounds_multi_confirm_action, F.data == "multi_select_confirm")
async def confirm_multi_select_action(callback: CallbackQuery, state: FSMContext) -> None:
    """Confirm multi-select action."""
    data = await state.get_data()
    selected_connections = data.get("selected_connections", set())
    action = data.get("action")
    subscription_id = data["subscription_id"]

    if not selected_connections or not action:
        await callback.answer("❌ Ошибка: нет выбранных подключений или действия.", show_alert=True)
        await state.clear()
        return

    # Now perform the action using the service
    async with async_session_factory() as session:
        from app.services.new_subscription_service import NewSubscriptionService
        from app.xui_client import XUIClient
        from app.services.xui_service import XUIService
        from cryptography.fernet import Fernet
        from app.config import get_settings
        from app.database.models import InboundConnection
        from sqlalchemy.orm import selectinload
        import asyncio

        # Get all connections with their inbound and server info in THIS session
        result = await session.execute(
            select(InboundConnection)
            .where(InboundConnection.id.in_(list(selected_connections)))
            .options(
                selectinload(InboundConnection.inbound).selectinload(Inbound.server)
            )
        )
        connections = result.scalars().all()

        if not connections:
            await callback.answer("❌ Подключения не найдены.", show_alert=True)
            await state.clear()
            return

        service = NewSubscriptionService(session)

        try:
            success_count = 0
            xui_service = XUIService(session)

            # Process each connection
            for conn in connections:
                try:
                    new_state = action == "enable"
                    inbound = conn.inbound
                    server = inbound.server

                    # Get XUI client
                    xui_client = await xui_service._get_client(server)

                    # Update in XUI
                    await xui_client.enable_client(inbound.xui_id, conn.uuid, new_state)

                    # Update in database
                    conn.is_enabled = new_state
                    success_count += 1

                except Exception as e:
                    logger.warning(f"Failed to {action} connection {conn.id}: {e}")

            await session.commit()

            action_text = "включено" if action == "enable" else "отключено"

            # Update interface with current data
            await state.clear()

            # Refresh inbounds list with updated statuses
            async with async_session_factory() as session2:
                from app.services.new_subscription_service import NewSubscriptionService
                service2 = NewSubscriptionService(session2)
                updated_connections = await service2.get_subscription_inbounds(subscription_id)

            text = f"📢 Inbounds подписки (ID: {subscription_id}):\n\n"
            builder = InlineKeyboardBuilder()

            for conn in updated_connections:
                status = "✅" if conn.is_enabled else "❌"
                inbound = conn.inbound
                server = inbound.server

                text += (
                    f"{status} {inbound.remark} ({inbound.protocol})\n"
                    f"   Сервер: {server.name}\n"
                    f"   Порт: {inbound.port}\n"
                    f"   Email: {conn.email}\n"
                    f"   UUID: {conn.uuid}\n"
                    f"   ID подключения: {conn.id}\n\n"
                )

                # Add buttons for each inbound
                if conn.is_enabled:
                    builder.button(text=f"✅ {inbound.remark}", callback_data=f"toggle_conn_{conn.id}")
                else:
                    builder.button(text=f"🔌 {inbound.remark}", callback_data=f"toggle_conn_{conn.id}")
                builder.button(text="🗑️", callback_data=f"delete_conn_{conn.id}")
                builder.adjust(2)

            # Add action buttons once at the bottom
            builder.button(text="✅ Множественный выбор", callback_data=f"inbounds_multi_select_{subscription_id}")
            builder.button(text="➕ Добавить inbound", callback_data=f"admin_sub_add_inbound_{subscription_id}")
            builder.button(text="🔙 Назад", callback_data=f"admin_sub_detail_{subscription_id}")
            builder.adjust(1)

            await callback.message.edit_text(text, reply_markup=builder.as_markup())
            await callback.answer(f"Успешно {action_text} {success_count}/{len(selected_connections)} подключений", show_alert=True)

        except Exception as e:
            logger.error(f"Error in multi-select action: {e}", exc_info=True)
            await callback.answer(f"❌ Ошибка: {e}", show_alert=True)
            await callback.message.edit_text(
                f"❌ Ошибка при выполнении действия: {e}",
                reply_markup=get_back_keyboard(f"admin_sub_inbounds_{subscription_id}"),
            )
        finally:
            await service.close_all_clients()


@router.callback_query(SubscriptionManagement.inbounds_multi_confirm_action, F.data == "multi_select_cancel")
async def cancel_multi_select_action(callback: CallbackQuery, state: FSMContext) -> None:
    """Cancel multi-select action and return to selection mode."""
    data = await state.get_data()
    subscription_id = data["subscription_id"]

    # Get connections for this subscription
    async with async_session_factory() as session:
        from app.services.new_subscription_service import NewSubscriptionService
        service = NewSubscriptionService(session)
        connections = await service.get_subscription_inbounds(subscription_id)

    selected_connections = data.get("selected_connections", set())

    await state.set_state(SubscriptionManagement.inbounds_multi_select_mode)
    await callback.message.edit_text(
        f"✅ Режим множественного выбора\n\n"
        f"Выберите inbounds для массовых действий:\n"
        f"(Выбрано: {len(selected_connections)}/{len(connections)})",
        reply_markup=get_multi_select_keyboard(connections, selected_connections),
    )
    await callback.answer()


@router.callback_query(SubscriptionManagement.inbounds_multi_select_mode, F.data == "multi_select_cancel")
async def exit_multi_select_mode(callback: CallbackQuery, state: FSMContext) -> None:
    """Exit multi-select mode."""
    data = await state.get_data()
    subscription_id = data["subscription_id"]

    await state.clear()
    # Redirect back to inbounds list by calling the handler directly
    # We need to create a proper callback query for the inbounds list
    async with async_session_factory() as session:
        from app.services.new_subscription_service import NewSubscriptionService
        service = NewSubscriptionService(session)
        connections = await service.get_subscription_inbounds(subscription_id)

    if not connections:
        await callback.answer("❌ У подписки нет подключений.")
        await callback.message.edit_text(
            "❌ У подписки нет подключений.\n\n"
            "Добавьте первый inbound для использования подписки.",
            reply_markup=get_back_keyboard("admin_menu"),
        )
        return

    text = f"📢 Inbounds подписки (ID: {subscription_id}):\n\n"
    builder = InlineKeyboardBuilder()

    for conn in connections:
        status = "✅" if conn.is_enabled else "❌"
        inbound = conn.inbound
        server = inbound.server

        text += (
            f"{status} {inbound.remark} ({inbound.protocol})\n"
            f"   Сервер: {server.name}\n"
            f"   Порт: {inbound.port}\n"
            f"   Email: {conn.email}\n"
            f"   UUID: {conn.uuid}\n"
            f"   ID подключения: {conn.id}\n\n"
        )

        # Add buttons for each inbound
        if conn.is_enabled:
            builder.button(text=f"✅ {inbound.remark}", callback_data=f"toggle_conn_{conn.id}")
        else:
            builder.button(text=f"🔌 {inbound.remark}", callback_data=f"toggle_conn_{conn.id}")
        builder.button(text="🗑️", callback_data=f"delete_conn_{conn.id}")
        builder.adjust(2)

    # Add action buttons once at the bottom
    builder.button(text="✅ Множественный выбор", callback_data=f"inbounds_multi_select_{subscription_id}")
    builder.button(text="➕ Добавить inbound", callback_data=f"admin_sub_add_inbound_{subscription_id}")
    builder.button(text="🔙 Назад", callback_data=f"admin_sub_detail_{subscription_id}")
    builder.adjust(1)

    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()


def get_multi_select_keyboard(connections: list, selected_ids: set) -> InlineKeyboardMarkup:
    """Get multi-select keyboard with checkboxes."""
    builder = InlineKeyboardBuilder()

    for conn in connections:
        selected = "✅" if conn.id in selected_ids else "⭕"
        status = "🟢" if conn.is_enabled else "🔴"
        inbound = conn.inbound
        builder.button(
            text=f"{selected} {status} {inbound.remark} ({inbound.protocol})",
            callback_data=f"multi_select_conn_{conn.id}",
        )

    builder.adjust(1)
    builder.button(text="✅ Включить выбранные", callback_data="multi_select_enable_all")
    builder.button(text="❌ Отключить выбранные", callback_data="multi_select_disable_all")
    builder.button(text="🔙 Выход", callback_data="multi_select_cancel")
    builder.adjust(1)

    return builder.as_markup()


def get_multi_select_confirm_keyboard() -> InlineKeyboardMarkup:
    """Get confirmation keyboard for multi-select action."""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить", callback_data="multi_select_confirm")
    builder.button(text="❌ Отмена", callback_data="multi_select_cancel")
    builder.adjust(1)
    return builder.as_markup()


@router.callback_query(F.data.startswith("delete_conn_"))
async def confirm_delete_inbound_connection(callback: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    """Confirm deletion of inbound connection."""
    if not is_admin:
        await callback.answer("❌ У вас нет прав администратора.", show_alert=True)
        return

    connection_id = int(callback.data.split("_")[-1])
    await state.update_data(connection_id=connection_id)

    await callback.message.edit_text(
        "⚠️ Вы уверены, что хотите удалить это подключение?\n\n"
        "Клиент будет удален из XUI панели!",
        reply_markup=get_confirm_keyboard(f"delete_conn_{connection_id}", "cancel"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("confirm_delete_conn_"))
async def delete_inbound_connection(callback: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    """Delete inbound connection."""
    if not is_admin:
        await callback.answer("❌ У вас нет прав администратора.", show_alert=True)
        return

    data = await state.get_data()
    connection_id = data["connection_id"]

    async with async_session_factory() as session:
        from app.services.new_subscription_service import NewSubscriptionService
        service = NewSubscriptionService(session)

        try:
            # Get connection info
            from app.database.models import InboundConnection
            from sqlalchemy.orm import selectinload
            result = await session.execute(
                select(InboundConnection)
                .where(InboundConnection.id == connection_id)
                .options(selectinload(InboundConnection.subscription))
            )
            connection = result.scalar_one_or_none()

            if not connection:
                await callback.answer("❌ Подключение не найдено.", show_alert=True)
                await state.clear()
                return

            subscription_id = connection.subscription_id

            # Remove from subscription
            success = await service.remove_inbound_from_subscription(subscription_id, connection.inbound_id)
            await session.commit()

            await state.clear()
            await callback.answer("✅ Подключение удалено", show_alert=True)

            # Don't refresh interface, just show alert
            # await show_subscription_inbounds(callback, is_admin)

        except Exception as e:
            logger.error(f"Error deleting connection: {e}", exc_info=True)
            await callback.answer(f"❌ Ошибка: {e}", show_alert=True)

            # Show error with back button to inbounds list
            from aiogram.utils.keyboard import InlineKeyboardBuilder
            builder = InlineKeyboardBuilder()
            builder.button(text="🔙 Назад", callback_data=f"admin_sub_inbounds_{subscription_id}")
            await callback.message.edit_text(
                f"❌ Ошибка при удалении: {e}",
                reply_markup=builder.as_markup(),
            )
            await state.clear()
        finally:
            await service.close_all_clients()


@router.callback_query(F.data.startswith("admin_sub_edit_"))
async def start_edit_subscription(callback: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    """Start editing subscription."""
    if not is_admin:
        await callback.answer("❌ У вас нет прав администратора.", show_alert=True)
        return

    subscription_id = int(callback.data.split("_")[-1])
    await state.clear()  # Clear any previous state
    await state.update_data(subscription_id=subscription_id)

    builder = InlineKeyboardBuilder()
    builder.button(text="✏️ Название", callback_data="edit_sub_name")
    builder.button(text="📊 Трафик", callback_data="edit_sub_traffic")
    builder.button(text="⏰ Срок", callback_data="edit_sub_expiry")
    builder.button(text="📝 Заметки", callback_data="edit_sub_notes")
    builder.button(text="🔄 Изменить все пункты", callback_data="edit_sub_all")
    builder.button(text="🔙 Назад", callback_data=f"admin_sub_detail_{subscription_id}")
    builder.adjust(1)

    await callback.message.edit_text(
        "✏️ Редактирование подписки\n\n"
        "Выберите параметр для изменения:",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("edit_sub_"))
async def process_edit_subscription_field(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle edit field selection."""
    field = callback.data.split("_")[-1]
    await state.update_data(edit_field=field)

    prompts = {
        "name": "Введите новое название подписки:",
        "traffic": "Введите новый лимит трафика в GB (0 для безлимита):",
        "expiry": "Введите новый срок в днях (0 для бессрочной):",
        "notes": "Введите заметки (или '-' для очистки):",
    }

    from app.bot.states import SubscriptionManagement

    if field == "name":
        await state.set_state(SubscriptionManagement.editing_name)
    elif field == "traffic":
        await state.set_state(SubscriptionManagement.editing_traffic)
    elif field == "expiry":
        await state.set_state(SubscriptionManagement.editing_expiry)
    elif field == "notes":
        await state.set_state(SubscriptionManagement.editing_notes)

    await callback.message.edit_text(
        prompts[field],
        reply_markup=get_back_keyboard("admin_sub_edit"),
    )
    await callback.answer()


# Edit subscription name
@router.message(SubscriptionManagement.editing_name)
async def process_edit_subscription_name(message, state: FSMContext) -> None:
    """Process subscription name edit."""
    name = message.text.strip()

    if not name:
        await message.answer("❌ Название не может быть пустым.")
        return

    if len(name) > 100:
        await message.answer("❌ Название не должно превышать 100 символов.")
        return

    data = await state.get_data()
    subscription_id = data["subscription_id"]

    async with async_session_factory() as session:
        from app.services.new_subscription_service import NewSubscriptionService
        service = NewSubscriptionService(session)
        subscription = await service.update_subscription(subscription_id, name=name)
        await session.commit()

    await state.clear()
    await message.answer(
        f"✅ Название изменено на '{subscription.name}'",
        reply_markup=get_back_keyboard(f"admin_sub_detail_{subscription_id}"),
    )


# Edit subscription traffic
@router.message(SubscriptionManagement.editing_traffic)
async def process_edit_subscription_traffic(message, state: FSMContext) -> None:
    """Process subscription traffic limit edit."""
    try:
        total_gb = int(message.text)
        if total_gb < 0:
            raise ValueError("Negative value")
    except ValueError:
        await message.answer("❌ Введите неотрицательное число.")
        return

    data = await state.get_data()
    subscription_id = data["subscription_id"]

    async with async_session_factory() as session:
        from app.services.new_subscription_service import NewSubscriptionService
        service = NewSubscriptionService(session)
        subscription = await service.update_subscription(subscription_id, total_gb=total_gb)
        await session.commit()

    await state.clear()
    traffic_str = f"{total_gb} GB" if total_gb > 0 else "Безлимит"
    await message.answer(
        f"✅ Трафик изменен на {traffic_str}",
        reply_markup=get_back_keyboard(f"admin_sub_detail_{subscription_id}"),
    )


# Edit subscription expiry
@router.message(SubscriptionManagement.editing_expiry)
async def process_edit_subscription_expiry(message, state: FSMContext) -> None:
    """Process subscription expiry edit."""
    try:
        expiry_days = int(message.text)
        if expiry_days < 0:
            raise ValueError("Negative value")
    except ValueError:
        await message.answer("❌ Введите неотрицательное число.")
        return

    data = await state.get_data()
    subscription_id = data["subscription_id"]

    async with async_session_factory() as session:
        from app.services.new_subscription_service import NewSubscriptionService
        service = NewSubscriptionService(session)
        expiry_days_param = expiry_days if expiry_days > 0 else 0
        subscription = await service.update_subscription(subscription_id, expiry_days=expiry_days_param)
        await session.commit()

    await state.clear()
    expiry_str = f"{expiry_days} дней" if expiry_days > 0 else "Бессрочно"
    await message.answer(
        f"✅ Срок изменен на {expiry_str}",
        reply_markup=get_back_keyboard(f"admin_sub_detail_{subscription_id}"),
    )


# Edit subscription notes
@router.message(SubscriptionManagement.editing_notes)
async def process_subscription_notes(message, state: FSMContext) -> None:
    """Process subscription notes edit."""
    notes = message.text.strip()
    if notes == "-":
        notes = None

    data = await state.get_data()
    subscription_id = data["subscription_id"]

    async with async_session_factory() as session:
        from app.services.new_subscription_service import NewSubscriptionService
        service = NewSubscriptionService(session)
        subscription = await service.update_subscription(subscription_id, notes=notes)
        await session.commit()

    await state.clear()
    await message.answer(
        f"✅ Заметки обновлены для подписки '{subscription.name}'",
        reply_markup=get_back_keyboard(f"admin_sub_detail_{subscription_id}"),
    )


# Edit all subscription parameters
@router.callback_query(F.data == "edit_sub_all")
async def start_edit_all_subscription_params(callback: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    """Start editing all subscription parameters."""
    if not is_admin:
        await callback.answer("❌ У вас нет прав администратора.", show_alert=True)
        return

    data = await state.get_data()
    subscription_id = data["subscription_id"]

    async with async_session_factory() as session:
        from app.services.new_subscription_service import NewSubscriptionService
        service = NewSubscriptionService(session)
        subscription = await service.get_subscription(subscription_id)

    if not subscription:
        await callback.answer("❌ Подписка не найдена.", show_alert=True)
        return

    await state.clear()
    await state.update_data(
        subscription_id=subscription_id,
        editing_all=True,
        name=subscription.name,
        total_gb=subscription.total_gb,
        expiry_date=subscription.expiry_date,
        notes=subscription.notes,
    )

    await state.set_state(SubscriptionManagement.waiting_for_subscription_name)
    await callback.message.edit_text(
        "✏️ Редактирование всех параметров подписки\n\n"
        f"Текущее название: {subscription.name}\n"
        f"Введите новое название:",
        reply_markup=get_back_keyboard("admin_sub_edit"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_sub_enable_"))
async def enable_subscription(callback: CallbackQuery, is_admin: bool) -> None:
    """Enable subscription."""
    if not is_admin:
        await callback.answer("❌ У вас нет прав администратора.", show_alert=True)
        return

    subscription_id = int(callback.data.split("_")[-1])

    async with async_session_factory() as session:
        from app.services.new_subscription_service import NewSubscriptionService
        service = NewSubscriptionService(session)
        subscription = await service.update_subscription(subscription_id, is_active=True)
        await session.commit()

    await callback.answer("✅ Подписка включена.")
    await show_subscription_details(callback, is_admin)


@router.callback_query(F.data.startswith("admin_sub_disable_"))
async def disable_subscription(callback: CallbackQuery, is_admin: bool) -> None:
    """Disable subscription."""
    if not is_admin:
        await callback.answer("❌ У вас нет прав администратора.", show_alert=True)
        return

    subscription_id = int(callback.data.split("_")[-1])

    async with async_session_factory() as session:
        from app.services.new_subscription_service import NewSubscriptionService
        service = NewSubscriptionService(session)
        subscription = await service.update_subscription(subscription_id, is_active=False)
        await session.commit()

    await callback.answer("✅ Подписка отключена.")
    await show_subscription_details(callback, is_admin)


@router.callback_query(F.data.startswith("admin_sub_delete_"))
async def confirm_delete_subscription(callback: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    """Confirm subscription deletion."""
    if not is_admin:
        await callback.answer("❌ У вас нет прав администратора.", show_alert=True)
        return

    subscription_id = int(callback.data.split("_")[-1])
    await state.update_data(subscription_id=subscription_id)

    await callback.message.edit_text(
        "⚠️ Вы уверены, что хотите удалить эту подписку?\n\n"
        "Все подключения в XUI будут удалены!",
        reply_markup=get_confirm_keyboard(f"admin_sub_delete_{subscription_id}", "admin_menu"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("confirm_admin_sub_delete_"))
async def delete_subscription(callback: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    """Delete subscription."""
    if not is_admin:
        await callback.answer("❌ У вас нет прав администратора.", show_alert=True)
        return

    data = await state.get_data()
    subscription_id = data["subscription_id"]

    async with async_session_factory() as session:
        from app.services.new_subscription_service import NewSubscriptionService
        service = NewSubscriptionService(session)

        try:
            await service.delete_subscription(subscription_id)
            await session.commit()

            await state.clear()
            await callback.answer("✅ Подписка удалена.")
            await list_all_subscriptions(callback, is_admin)

        except Exception as e:
            logger.error(f"Error deleting subscription: {e}", exc_info=True)
            await callback.answer(f"❌ Ошибка: {e}", show_alert=True)
            await callback.message.edit_text(
                f"❌ Ошибка при удалении подписки: {e}",
                reply_markup=get_back_keyboard(f"admin_sub_detail_{subscription_id}"),
            )
        finally:
            await service.close_all_clients()
