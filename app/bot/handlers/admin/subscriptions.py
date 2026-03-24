"""Admin subscription management handlers."""

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from loguru import logger
from typing import Set

from app.bot.keyboards import (
    get_back_keyboard,
    get_confirm_keyboard,
    get_servers_keyboard,
)
from app.bot.states import SubscriptionManagement
from app.database import async_session_factory
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
        reply_markup=await get_inbounds_selection_keyboard(inbounds),
    )
    await callback.answer()


async def get_inbounds_selection_keyboard(inbounds: list) -> str:
    """Get inbounds selection keyboard with checkboxes."""
    builder = InlineKeyboardBuilder()

    for inbound in inbounds:
        status = "✅" if inbound.is_active else "❌"
        builder.button(
            text=f"📦 {status} {inbound.remark} ({inbound.protocol})",
            callback_data=f"toggle_inbound_{inbound.id}",
        )

    builder.button(text="➡️ Создать подписку", callback_data="confirm_inbounds")
    builder.adjust(1)
    return builder.as_markup()


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

    # Update keyboard with selection state
    builder = InlineKeyboardBuilder()

    for inbound in inbounds:
        status = "✅" if inbound.is_active else "❌"
        selected = "🔘" if inbound.id in selected_inbounds else "⭕"
        builder.button(
            text=f"{selected} {status} {inbound.remark} ({inbound.protocol})",
            callback_data=f"toggle_inbound_{inbound.id}",
        )

    builder.button(text="➡️ Создать подписку", callback_data="confirm_inbounds")
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
