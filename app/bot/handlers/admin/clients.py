"""Admin client management handlers."""

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from loguru import logger

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.bot.keyboards import (
    get_back_keyboard,
    get_confirm_keyboard,
    get_servers_keyboard,
    get_clients_keyboard,
    get_client_search_keyboard,
    get_clients_page_keyboard,
)
from app.bot.states import ClientManagement, SubscriptionManagement
from app.bot.states.admin import TemplateManagement
from app.database import async_session_factory
from app.services.client_service import ClientService
from app.services.subscription_template_service import SubscriptionTemplateService

router = Router()


@router.callback_query(F.data == "admin_clients")
async def show_clients(callback: CallbackQuery, is_admin: bool) -> None:
    """Show clients search menu."""
    if not is_admin:
        await callback.answer("❌ У вас нет прав администратора.", show_alert=True)
        return

    try:
        # Create a custom keyboard for main menu
        from aiogram.utils.keyboard import InlineKeyboardBuilder

        kb = InlineKeyboardBuilder()
        kb.button(text="📋 Все клиенты", callback_data="clients_list")
        kb.button(text="🔍 Поиск клиентов", callback_data="client_search")
        kb.button(text="➕ Добавить клиента", callback_data="client_add")
        kb.button(text="🔙 Назад", callback_data="admin_menu")
        kb.adjust(1)

        await callback.message.edit_text(
            "👥 Управление клиентами\n\n"
            "Для эффективной работы с большим количеством клиентов "
            "используйте поиск по различным критериям.",
            reply_markup=kb.as_markup(),
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
            "➕ Добавление нового клиента\n\nВведите имя клиента:",
            reply_markup=get_back_keyboard("admin_clients"),
        )
    except Exception:
        pass
    await callback.answer()


@router.message(ClientManagement.waiting_for_name)
async def process_client_name(message: Message, state: FSMContext) -> None:
    """Process client name input."""
    name = message.text.strip()

    if not name:
        await message.answer(
            "❌ Имя не может быть пустым.", reply_markup=get_back_keyboard("admin_clients")
        )
        return

    if len(name) > 100:
        await message.answer(
            "❌ Имя не должно превышать 100 символов.",
            reply_markup=get_back_keyboard("admin_clients"),
        )
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
        if "@" not in email or "." not in email:
            await message.answer(
                "❌ Некорректный формат email.", reply_markup=get_back_keyboard("admin_clients")
            )
            return

    await state.update_data(email=email if email != "-" else None)
    await state.set_state(ClientManagement.waiting_for_telegram_id)
    await message.answer(
        "Введите Telegram ID клиента (число) или отправьте '-' для пропуска.\n\n"
        "Примечание: Telegram ID будет использоваться для синхронизации с XUI панелями.",
        reply_markup=get_back_keyboard("admin_clients"),
    )


@router.message(ClientManagement.waiting_for_telegram_id)
async def process_client_telegram_id(message: Message, state: FSMContext) -> None:
    """Process telegram ID input and create client."""
    data = await state.get_data()

    input_text = message.text.strip()

    # Process input
    telegram_id = None
    if input_text != "-":
        try:
            telegram_id = int(input_text)
        except ValueError:
            await message.answer(
                "❌ Telegram ID должен быть числом или '-'.",
                reply_markup=get_back_keyboard("admin_clients"),
            )
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
            logger.error(f"Failed to create client: {e}", exc_info=True)
            await session.rollback()
            await message.answer(
                f"❌ Ошибка при создании клиента: {e}",
                reply_markup=get_back_keyboard("admin_clients"),
            )
            await state.clear()


@router.callback_query(F.data.startswith("client_select_"))
async def select_client(callback: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    """Show client details and actions."""
    if not is_admin:
        await callback.answer("❌ У вас нет прав администратора.", show_alert=True)
        return

    await state.clear()
    client_id = int(callback.data.split("_")[-1])

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
    if client.notes:
        text += f"\n📝 Заметки: {client.notes}"

    from aiogram.utils.keyboard import InlineKeyboardBuilder

    kb = InlineKeyboardBuilder()
    kb.button(text="📝 Подписки клиента", callback_data=f"client_subscriptions_{client_id}")
    kb.button(
        text="📋 Создать подписку по шаблону",
        callback_data=f"client_create_from_template_{client_id}",
    )
    kb.button(text="📝 Изменить заметки", callback_data=f"client_edit_notes_{client_id}")
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
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("client_subscriptions_"))
async def show_client_subscriptions(
    callback: CallbackQuery, state: FSMContext, is_admin: bool
) -> None:
    """Show client subscriptions."""
    if not is_admin:
        await callback.answer("❌ У вас нет прав администратора.", show_alert=True)
        return

    await state.clear()
    client_id = int(callback.data.split("_")[-1])

    from app.services.new_subscription_service import NewSubscriptionService

    async with async_session_factory() as session:
        service = NewSubscriptionService(session)
        subscriptions = await service.get_client_subscriptions(client_id)

    if not subscriptions:
        text = (
            "📝 У клиента нет подписок.\n\n"
            "Нажмите '➕ Создать подписку' для добавления первой подписки."
        )
    else:
        text = "📝 Подписки клиента:\n\n"

    from aiogram.utils.keyboard import InlineKeyboardBuilder

    kb = InlineKeyboardBuilder()

    if subscriptions:
        for sub in subscriptions:
            status = "✅" if sub.is_active else "❌"
            expiry = sub.expiry_date.strftime("%d.%m.%Y") if sub.expiry_date else "Бессрочно"
            traffic = "Безлимит" if sub.is_unlimited else f"{sub.total_gb} GB"

            text += (
                f"{status} <b>{sub.name}</b>\n"
                f"   Трафик: {traffic}\n"
                f"   Срок: {expiry}\n"
                f"   Подключений: {len(sub.inbound_connections)}\n\n"
            )

            # Add button for each subscription
            kb.button(text=f"📝 {sub.name}", callback_data=f"client_sub_detail_{sub.id}")

    kb.button(text="➕ Создать подписку", callback_data=f"client_create_subscription_{client_id}")
    kb.button(text="🔙 Назад", callback_data=f"client_select_{client_id}")
    kb.adjust(1)

    try:
        await callback.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    except Exception as e:
        logger.warning(f"Failed to edit message in show_client_subscriptions: {e}")
        # Try to edit reply_markup only as fallback
        try:
            await callback.message.edit_reply_markup(reply_markup=kb.as_markup())
        except Exception as e2:
            logger.error(f"Failed to edit reply_markup: {e2}")
    await callback.answer()


@router.callback_query(F.data.startswith("client_sub_detail_"))
async def show_client_subscription_detail(callback: CallbackQuery, is_admin: bool) -> None:
    """Show subscription details from client view."""
    if not is_admin:
        await callback.answer("❌ У вас нет прав администратора.", show_alert=True)
        return

    subscription_id = int(callback.data.split("_")[-1])

    from app.services.new_subscription_service import NewSubscriptionService
    from app.database.models import Subscription

    async with async_session_factory() as session:
        service = NewSubscriptionService(session)

        result = await session.execute(
            select(Subscription)
            .where(Subscription.id == subscription_id)
            .options(
                selectinload(Subscription.client),
                selectinload(Subscription.inbound_connections),
            )
        )
        subscription = result.scalar_one_or_none()

    if not subscription:
        await callback.answer("❌ Подписка не найдена.", show_alert=True)
        return

    status = "✅ Активна" if subscription.is_active else "❌ Неактивна"
    expiry = (
        subscription.expiry_date.strftime("%d.%m.%Y") if subscription.expiry_date else "Бессрочно"
    )
    traffic = "Безлимит" if subscription.is_unlimited else f"{subscription.total_gb} GB"

    text = (
        f"📝 Подписка: <b>{subscription.name}</b>\n\n"
        f"Клиент: {subscription.client.name}\n"
        f"Токен: <code>{subscription.subscription_token}</code>\n"
        f"Статус: {status}\n"
        f"Трафик: {traffic}\n"
        f"Срок: {expiry}\n"
        f"Создана: {subscription.created_at.strftime('%d.%m.%Y %H:%M')}\n"
        f"Подключений: {len(subscription.inbound_connections)}"
    )

    if subscription.notes:
        text += f"\n📝 Заметки: {subscription.notes}"

    from aiogram.utils.keyboard import InlineKeyboardBuilder

    builder = InlineKeyboardBuilder()
    builder.button(text="📢 Inbounds", callback_data=f"admin_sub_inbounds_{subscription_id}")
    builder.button(text="✏️ Редактировать", callback_data=f"admin_sub_edit_{subscription_id}")
    if subscription.is_active:
        builder.button(text="❌ Отключить", callback_data=f"admin_sub_disable_{subscription_id}")
    else:
        builder.button(text="✅ Включить", callback_data=f"admin_sub_enable_{subscription_id}")
    builder.button(text="🗑️ Удалить", callback_data=f"admin_sub_delete_{subscription_id}")
    builder.button(text="🔙 Назад", callback_data=f"client_subscriptions_{subscription.client_id}")
    builder.adjust(1)

    try:
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    except Exception as e:
        logger.warning(f"Failed to edit message in show_client_subscription_detail: {e}")
        # Try to edit reply_markup only as fallback
        try:
            await callback.message.edit_reply_markup(reply_markup=builder.as_markup())
        except Exception as e2:
            logger.error(f"Failed to edit reply_markup: {e2}")
    await callback.answer()


@router.callback_query(F.data.startswith("client_create_subscription_"))
async def start_create_subscription_for_client(
    callback: CallbackQuery, state: FSMContext, is_admin: bool
) -> None:
    """Start creating subscription for specific client."""
    if not is_admin:
        await callback.answer("❌ У вас нет прав администратора.", show_alert=True)
        return

    client_id = int(callback.data.split("_")[-1])
    await state.update_data(client_id=client_id)

    from app.services.xui_service import XUIService

    async with async_session_factory() as session:
        service = XUIService(session)
        servers = await service.get_active_servers()

    if not servers:
        await callback.answer("❌ Нет активных серверов.", show_alert=True)
        return

    await state.set_state(SubscriptionManagement.waiting_for_server_selection)
    try:
        await callback.message.edit_text(
            "Выберите сервер:",
            reply_markup=get_servers_keyboard(
                servers, action="sub_select", back_target=f"client_subscriptions_{client_id}"
            ),
        )
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("client_create_from_template_"))
async def start_create_subscription_from_template(
    callback: CallbackQuery, state: FSMContext, is_admin: bool
) -> None:
    """Start creating subscription from template for specific client."""
    if not is_admin:
        await callback.answer("❌ У вас нет прав администратора.", show_alert=True)
        return

    client_id = int(callback.data.split("_")[-1])
    await state.update_data(client_id=client_id)

    async with async_session_factory() as session:
        template_service = SubscriptionTemplateService(session)
        templates = await template_service.get_all_templates()

    if not templates:
        await callback.answer(
            "❌ Нет доступных шаблонов. Сначала создайте шаблон.", show_alert=True
        )
        return

    await state.set_state(TemplateManagement.waiting_for_template_selection)

    text = (
        f"📋 <b>Создание подписки по шаблону</b>\n\n"
        f"Всего шаблонов: {len(templates)}\n\n"
        f"Выберите шаблон:"
    )

    from aiogram.utils.keyboard import InlineKeyboardBuilder

    builder = InlineKeyboardBuilder()
    for template in templates:
        status = "✅" if template.is_active else "❌"
        inbounds_count = len(template.template_inbounds)
        builder.button(
            text=f"{status} {template.name} ({inbounds_count} подключений)",
            callback_data=f"template_for_client_{template.id}",
        )
    builder.button(text="🔙 Назад", callback_data=f"client_select_{client_id}")
    builder.adjust(1)

    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(
    TemplateManagement.waiting_for_template_selection, F.data.startswith("template_for_client_")
)
async def select_template_for_client(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle template selection for client subscription."""
    template_id = int(callback.data.split("_")[-1])
    data = await state.get_data()
    client_id = data["client_id"]

    await state.update_data(template_id=template_id)
    await state.set_state(TemplateManagement.waiting_for_subscription_name)

    async with async_session_factory() as session:
        template_service = SubscriptionTemplateService(session)
        template = await template_service.get_template(template_id)
        client_service = ClientService(session)
        client = await client_service.get_client_by_id(client_id)

    text = (
        f"📋 <b>Создание подписки из шаблона</b>\n\n"
        f"📋 <b>Шаблон:</b> {template.name}\n"
        f"👤 <b>Клиент:</b> {client.name}\n"
        f"🔌 <b>Подключений:</b> {len(template.template_inbounds)}\n\n"
        f"Введите название подписки:"
    )

    await callback.message.edit_text(text)
    await callback.answer()


@router.callback_query(F.data.startswith("client_rename_name_"))
async def start_rename_client_name(
    callback: CallbackQuery, state: FSMContext, is_admin: bool
) -> None:
    """Start renaming client name."""
    if not is_admin:
        await callback.answer("❌ У вас нет прав администратора.", show_alert=True)
        return

    client_id = int(callback.data.split("_")[-1])
    await state.update_data(client_id=client_id)
    await state.set_state(ClientManagement.waiting_for_new_name)

    try:
        await callback.message.edit_text(
            "✏️ Изменение имени клиента\n\nВведите новое имя:",
            reply_markup=get_back_keyboard(f"client_select_{client_id}"),
        )
    except Exception:
        pass
    await callback.answer()


@router.message(ClientManagement.waiting_for_new_name)
async def process_rename_client_name(message: Message, state: FSMContext) -> None:
    """Process client rename."""
    data = await state.get_data()
    client_id = data["client_id"]
    name = message.text.strip()

    if not name:
        await message.answer("❌ Имя не может быть пустым.")
        return

    if len(name) > 100:
        await message.answer("❌ Имя не должно превышать 100 символов.")
        return

    async with async_session_factory() as session:
        service = ClientService(session)
        client = await service.rename_client(client_id, name)
        await session.commit()
    await state.clear()
    await message.answer(
        f"✅ Клиент переименован в '{client.name}'",
        reply_markup=get_back_keyboard(f"client_select_{client_id}"),
    )


@router.callback_query(F.data.startswith("client_rename_telegram_"))
async def start_rename_client_telegram(
    callback: CallbackQuery, state: FSMContext, is_admin: bool
) -> None:
    """Start changing client Telegram ID."""
    if not is_admin:
        await callback.answer("❌ У вас нет прав администратора.", show_alert=True)
        return

    client_id = int(callback.data.split("_")[-1])
    await state.update_data(client_id=client_id)
    await state.set_state(ClientManagement.waiting_for_new_telegram_id)

    try:
        await callback.message.edit_text(
            "📱 Изменение Telegram ID\n\nВведите новый Telegram ID (или '-' для удаления):",
            reply_markup=get_back_keyboard(f"client_select_{client_id}"),
        )
    except Exception:
        pass
    await callback.answer()


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
        telegram_id = None

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
            await select_client(callback, is_admin)
        except Exception:
            await session.rollback()
            raise
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

            await callback.answer(
                f"✅ Клиент отключен. Деактивировано {toggled} подключений в XUI."
            )
            await select_client(callback, is_admin)
        except Exception:
            await session.rollback()
            raise
        finally:
            await sub_service.close_all_clients()


# ==================== CLIENT NOTES ====================


@router.callback_query(F.data.startswith("client_edit_notes_"))
async def start_edit_client_notes(
    callback: CallbackQuery, state: FSMContext, is_admin: bool
) -> None:
    """Start editing client notes."""
    if not is_admin:
        await callback.answer("❌ У вас нет прав администратора.", show_alert=True)
        return

    client_id = int(callback.data.split("_")[-1])
    await state.update_data(client_id=client_id)
    await state.set_state(ClientManagement.waiting_for_notes)

    try:
        await callback.message.edit_text(
            "📝 Изменение заметок клиента\n\nВведите новые заметки (для удаления отправьте `-`):",
            reply_markup=get_back_keyboard(f"client_select_{client_id}"),
        )
    except Exception:
        pass
    await callback.answer()


@router.message(ClientManagement.waiting_for_notes)
async def process_client_notes(message: Message, state: FSMContext) -> None:
    """Process client notes input."""
    data = await state.get_data()
    client_id = data["client_id"]
    notes = message.text.strip()

    if notes == "-":
        notes = None

    async with async_session_factory() as session:
        service = ClientService(session)
        await service.update_client(client_id, notes=notes)
        await session.commit()
    await state.clear()
    await message.answer(
        "✅ Заметки клиента обновлены.",
        reply_markup=get_back_keyboard(f"client_select_{client_id}"),
    )


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
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("confirm_client_delete_"))
async def delete_client(callback: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    """Delete client."""
    if not is_admin:
        await callback.answer("❌ У вас нет прав администратора.", show_alert=True)
        return

    data = await state.get_data()
    client_id = data["client_id"]

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
        except Exception:
            await session.rollback()
            raise
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
    await select_client(callback, is_admin)


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
    await select_client(callback, is_admin)


# ==================== CLIENT LIST (PAGINATED) ====================


@router.callback_query(F.data == "clients_list")
async def show_clients_list(callback: CallbackQuery, is_admin: bool) -> None:
    """Show paginated list of all active clients (first page)."""
    if not is_admin:
        await callback.answer("❌ У вас нет прав администратора.", show_alert=True)
        return

    await _render_clients_page(callback, page=0)


@router.callback_query(F.data.startswith("clients_page_"))
async def navigate_clients_page(callback: CallbackQuery, is_admin: bool) -> None:
    """Navigate between client list pages."""
    if not is_admin:
        await callback.answer("❌ У вас нет прав администратора.", show_alert=True)
        return

    # Ignore the "current page" indicator button
    if callback.data == "clients_page_current":
        await callback.answer()
        return

    page = int(callback.data.split("_")[-1])
    await _render_clients_page(callback, page=page)


async def _render_clients_page(callback: CallbackQuery, page: int = 0, per_page: int = 5) -> None:
    """Render a page of clients list.

    Args:
        callback: Callback query to respond to
        page: Page number (0-indexed)
        per_page: Number of clients per page
    """
    async with async_session_factory() as session:
        service = ClientService(session)
        clients, total_count = await service.get_clients_paginated(page=page, per_page=per_page)

    if not clients:
        try:
            await callback.message.edit_text(
                "👥 Список клиентов пуст.\n\n"
                "Нажмите '➕ Добавить клиента' для создания первого клиента.",
                reply_markup=get_back_keyboard("admin_clients"),
            )
        except Exception:
            pass
        await callback.answer()
        return

    total_pages = max(1, -(-total_count // per_page))
    text = (
        f"👥 <b>Список клиентов</b> (страница {page + 1}/{total_pages})\n"
        f"Всего активных: {total_count}\n\n"
    )

    for client in clients:
        status = "✅" if client.is_active else "❌"
        admin_badge = "🛡️" if client.is_admin else "👤"
        text += f"{admin_badge} {status} <b>{client.name}</b> (ID: {client.id})\n"
        if client.telegram_id:
            text += f"   📱 Telegram: {client.telegram_id}\n"
        text += f"   📧 {client.email}\n"
        text += f"   📝 Подписок: {len(client.subscriptions)}\n\n"

    keyboard = get_clients_page_keyboard(clients, page, total_count, per_page)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        pass
    await callback.answer()


# ==================== CLIENT SEARCH HANDLERS ====================


@router.callback_query(F.data == "client_search")
async def start_client_search(callback: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    """Start client search flow."""
    if not is_admin:
        await callback.answer("❌ У вас нет прав администратора.", show_alert=True)
        return

    try:
        await callback.message.edit_text(
            "🔍 Поиск клиентов\n\nВыберите критерий поиска:",
            reply_markup=get_client_search_keyboard(),
        )
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("search_field_"))
async def select_search_field(callback: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    """Handle search field selection."""
    if not is_admin:
        await callback.answer("❌ У вас нет прав администратора.", show_alert=True)
        return

    # Extract field from callback data: "search_field_<field>"
    # e.g. "search_field_name" -> "name", "search_field_xui_email" -> "xui_email"
    field = callback.data.removeprefix("search_field_")
    await state.update_data(search_field=field)
    await state.set_state(ClientManagement.waiting_for_search_query)

    field_messages = {
        "name": "Введите имя клиента (частичное совпадение):",
        "email": "Введите email клиента (частичное совпадение):",
        "telegram": "Введите Telegram ID (цифры) или @username клиента:",
        "xui_email": "Введите email из XUI inbound (частичное совпадение):",
        "all": "Введите поисковый запрос (проверит ВСЕ поля одновременно):\n"
        "• Имя\n"
        "• Email клиента\n"
        "• Telegram ID\n"
        "• Email из XUI inbound",
    }

    try:
        await callback.message.edit_text(
            f"🔍 {field_messages.get(field, 'Введите поисковый запрос:')}",
            reply_markup=get_back_keyboard("client_search"),
        )
    except Exception:
        pass
    await callback.answer()


@router.message(ClientManagement.waiting_for_search_query)
async def process_search_query(message: Message, state: FSMContext) -> None:
    """Process search query and display results."""
    from app.services.client_service import _normalize_search_query

    data = await state.get_data()
    field = data.get("search_field", "all")
    query = message.text.strip()

    if not query:
        await message.answer("❌ Поисковый запрос не может быть пустым.")
        return

    # Prepare search parameters
    search_params = {}

    if field == "name":
        search_params["name"] = _normalize_search_query(query, is_email=False)
    elif field == "email":
        search_params["email"] = _normalize_search_query(query, is_email=True)
    elif field == "telegram":
        stripped = query.lstrip("@")
        if stripped.isdigit():
            search_params["telegram_id"] = int(stripped)
        else:
            search_params["telegram_username"] = stripped.lower()
    elif field == "xui_email":
        search_params["xui_email"] = _normalize_search_query(query, is_email=True)
    elif field == "all":
        # Search across all fields with OR logic
        async with async_session_factory() as session:
            service = ClientService(session)
            clients = await service.search_clients_all_fields(query)

        await state.clear()

        if not clients:
            await message.answer(
                "🔍 Поиск не дал результатов.\n\n"
                "Комплексный поиск проверяет все поля:\n"
                "• Имя клиента\n"
                "• Email клиента\n"
                "• Telegram ID\n"
                "• XUI email (из inbound подключений)\n\n"
                "Попробуйте изменить поисковый запрос.",
                reply_markup=get_back_keyboard("client_search"),
            )
        else:
            text = f"🔍 Результаты поиска по всем полям ({len(clients)}):\n\n"
            for client in clients:
                status = "✅" if client.is_active else "❌"
                admin_badge = "👤" if not client.is_admin else "🛡️"
                text += f"{admin_badge} {status} <b>{client.name}</b>\n"
                text += f"   Email: {client.email}\n"
                if client.telegram_id:
                    text += f"   Telegram ID: {client.telegram_id}\n"
                text += "\n"

            await message.answer(
                text,
                reply_markup=get_clients_keyboard(clients),
                parse_mode="HTML",
            )
        return  # Exit early since we already handled search

    # Perform search for specific fields
    async with async_session_factory() as session:
        service = ClientService(session)
        clients = await service.search_clients(**search_params)

    await state.clear()

    if not clients:
        await message.answer(
            "🔍 Поиск не дал результатов.\n\n"
            "Советы:\n"
            "• Для поиска по имени можно использовать несколько слов\n"
            "• Для поиска по email используйте символ @\n"
            "• Для Telegram ID используйте только цифры",
            reply_markup=get_back_keyboard("client_search"),
        )
    else:
        text = f"🔍 Результаты поиска ({len(clients)}):\n\n"
        for client in clients:
            status = "✅" if client.is_active else "❌"
            admin_badge = "👤" if not client.is_admin else "🛡️"
            text += f"{admin_badge} {status} <b>{client.name}</b>\n"
            text += f"   Email: {client.email}\n"
            if client.telegram_id:
                text += f"   Telegram ID: {client.telegram_id}\n"
            text += "\n"

        await message.answer(
            text,
            reply_markup=get_clients_keyboard(clients),
            parse_mode="HTML",
        )
