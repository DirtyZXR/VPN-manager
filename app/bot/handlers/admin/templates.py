"""Template management handlers for subscription templates."""

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from loguru import logger

from app.bot.states.admin import TemplateManagement
from app.bot.keyboards import (
    get_templates_keyboard,
    get_template_actions_keyboard,
    get_template_inbounds_keyboard,
    get_inbound_selection_for_template,
    get_back_keyboard,
    get_confirm_keyboard,
)
from app.bot.filters import is_admin_user
from app.database import async_session_factory
from app.services.subscription_template_service import SubscriptionTemplateService
from app.services.client_service import ClientService
from app.xui_client.exceptions import XUIError

router = Router()


@router.callback_query(F.data == "admin_templates")
async def show_templates(callback: CallbackQuery, is_admin: bool):
    """Show templates list."""
    if not is_admin:
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    async with async_session_factory() as session:
        template_service = SubscriptionTemplateService(session)
        templates = await template_service.get_all_templates()

        if not templates:
            text = "📋 <b>Шаблоны подписок</b>\n\nШаблонов пока нет. Создайте первый шаблон!"
            # Create keyboard with create template button
            from aiogram.utils.keyboard import InlineKeyboardBuilder
            builder = InlineKeyboardBuilder()
            builder.button(text="➕ Создать шаблон", callback_data="template_add")
            builder.button(text="Назад", callback_data="admin_menu")
            builder.adjust(1)
            keyboard = builder.as_markup()
        else:
            text = f"📋 <b>Шаблоны подписок</b>\n\nВсего шаблонов: {len(templates)}"
            keyboard = get_templates_keyboard(templates)

    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data == "template_add")
async def start_template_creation(callback: CallbackQuery, state: FSMContext, is_admin: bool):
    """Start template creation."""
    if not is_admin:
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    await state.clear()
    await state.set_state(TemplateManagement.waiting_for_template_name)

    text = (
        "📝 <b>Создание шаблона подписки</b>\n\n"
        "Введите название шаблона:"
    )

    await callback.message.edit_text(text)
    await callback.answer()


@router.message(TemplateManagement.waiting_for_template_name)
async def handle_template_name(message: Message, state: FSMContext):
    """Handle template name input."""
    name = message.text.strip()

    if not name:
        await message.answer("⚠️ Название не может быть пустым. Введите название:")
        return

    if len(name) > 100:
        await message.answer("⚠️ Название слишком длинное. Максимум 100 символов. Введите название:")
        return

    await state.update_data(template_name=name)
    await state.set_state(TemplateManagement.waiting_for_template_description)

    text = (
        f"✅ <b>Название:</b> {name}\n\n"
        "Введите описание шаблона (необязательно, отправьте /skip для пропуска):"
    )

    await message.answer(text)


@router.message(TemplateManagement.waiting_for_template_description)
async def handle_template_description(message: Message, state: FSMContext):
    """Handle template description input."""
    if message.text == "/skip":
        description = None
    else:
        description = message.text.strip()
        if len(description) > 500:
            await message.answer("⚠️ Описание слишком длинное. Максимум 500 символов. Введите описание:")
            return

    await state.update_data(template_description=description)
    await state.set_state(TemplateManagement.waiting_for_default_traffic)

    text = (
        f"📝 <b>Описание:</b> {description or 'Нет описания'}\n\n"
        f"Введите лимит трафика по умолчанию в ГБ (0 = безлимитный):"
    )

    await message.answer(text)


@router.message(TemplateManagement.waiting_for_default_traffic)
async def handle_default_traffic(message: Message, state: FSMContext):
    """Handle default traffic limit input."""
    try:
        traffic = int(message.text.strip())
        if traffic < 0:
            await message.answer("⚠️ Лимит трафика не может быть отрицательным. Введите число:")
            return
    except ValueError:
        await message.answer("⚠️ Введите корректное число (0 = безлимитный):")
        return

    await state.update_data(default_traffic=traffic)
    await state.set_state(TemplateManagement.waiting_for_default_expiry)

    traffic_text = f"{traffic} ГБ {'(безлимитный)' if traffic == 0 else ''}"

    text = (
        f"📊 <b>Лимит трафика:</b> {traffic_text}\n\n"
        f"Введите срок действия по умолчанию в днях (0 = бессрочный, отправьте /skip для пропуска):"
    )

    await message.answer(text)


@router.message(TemplateManagement.waiting_for_default_expiry)
async def handle_default_expiry(message: Message, state: FSMContext):
    """Handle default expiry days input."""
    if message.text == "/skip":
        expiry = None
    else:
        try:
            expiry = int(message.text.strip())
            if expiry < 0:
                await message.answer("⚠️ Срок действия не может быть отрицательным. Введите число:")
                return
        except ValueError:
            await message.answer("⚠️ Введите корректное число (0 = бессрочный, /skip = использовать шаблон):")
            return

        if expiry == 0:
            expiry = None

    await state.update_data(default_expiry=expiry)
    await state.set_state(TemplateManagement.waiting_for_template_notes)

    data = await state.get_data()
    traffic = data.get("default_traffic")
    traffic_text = f"{traffic} ГБ {'(безлимитный)' if traffic == 0 else ''}"
    expiry_text = f"{expiry} дн." if expiry else "Бессрочный"

    text = (
        f"📅 <b>Срок действия:</b> {expiry_text}\n\n"
        f"Введите заметки (необязательно, отправьте /skip для пропуска):"
    )

    await message.answer(text)


@router.message(TemplateManagement.waiting_for_template_notes)
async def handle_template_notes(message: Message, state: FSMContext):
    """Handle template notes input."""
    if message.text == "/skip":
        notes = None
    else:
        notes = message.text.strip()
        if len(notes) > 500:
            await message.answer("⚠️ Заметки слишком длинные. Максимум 500 символов. Введите заметки:")
            return

    data = await state.get_data()

    try:
        async with async_session_factory() as session:
            template_service = SubscriptionTemplateService(session)
            template = await template_service.create_template(
                name=data["template_name"],
                description=data["template_description"],
                default_total_gb=data["default_traffic"],
                default_expiry_days=data["default_expiry"],
                notes=notes,
            )
            await session.commit()

            logger.info(f"✅ Template created: {template.name} (ID: {template.id})")

        await state.clear()

        traffic_limit = f"{template.default_total_gb} ГБ" if template.default_total_gb > 0 else "Безлимитный"
        expiry_text = f"{template.default_expiry_days} дн." if template.default_expiry_days else "Бессрочный"

        text = (
            f"✅ <b>Шаблон создан!</b>\n\n"
            f"📋 <b>{template.name}</b>\n"
            f"📝 {template.description or 'Нет описания'}\n"
            f"📊 <b>Лимит трафика:</b> {traffic_limit}\n"
            f"📅 <b>Срок действия:</b> {expiry_text}\n"
        )

        if template.notes:
            text += f"\n📌 <b>Заметки:</b> {template.notes}"

        keyboard = get_back_keyboard("admin_templates")

        await message.answer(text, reply_markup=keyboard)

    except Exception as e:
        await state.clear()
        logger.error(f"Error creating template: {e}", exc_info=True)
        await message.answer(f"❌ Произошла ошибка при создании шаблона: {str(e)}")


@router.callback_query(F.data.startswith("template_select_"))
async def show_template_details(callback: CallbackQuery, is_admin: bool):
    """Show template details."""
    if not is_admin:
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    template_id = int(callback.data.split("_")[2])

    async with async_session_factory() as session:
        template_service = SubscriptionTemplateService(session)
        template = await template_service.get_template(template_id)

        if not template:
            await callback.answer("⚠️ Шаблон не найден", show_alert=True)
            return

        traffic_limit = f"{template.default_total_gb} ГБ" if template.default_total_gb > 0 else "Безлимитный"
        expiry_text = f"{template.default_expiry_days} дн." if template.default_expiry_days else "Бессрочный"
        inbounds_count = len(template.template_inbounds)

        text = (
            f"📋 <b>{template.name}</b>\n\n"
            f"📝 {template.description or 'Нет описания'}\n"
            f"📊 <b>Лимит трафика:</b> {traffic_limit}\n"
            f"📅 <b>Срок действия:</b> {expiry_text}\n"
            f"🔌 <b>Подключений:</b> {inbounds_count}\n"
        )

        if template.notes:
            text += f"\n📌 <b>Заметки:</b> {template.notes}"

        keyboard = get_template_actions_keyboard(template_id)

        await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("template_create_subscription_"))
async def start_subscription_from_template(callback: CallbackQuery, state: FSMContext, is_admin: bool):
    """Start subscription creation from template."""
    if not is_admin:
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    template_id = int(callback.data.split("_")[3])

    await state.update_data(template_id=template_id)
    await state.set_state(TemplateManagement.waiting_for_client_selection)

    # Get template info
    async with async_session_factory() as session:
        template_service = SubscriptionTemplateService(session)
        template = await template_service.get_template(template_id)
        template_info = f"<b>{template.name}</b> ({len(template.template_inbounds)} подключений)"

    text = (
        f"📦 <b>Создание подписки из шаблона</b>\n\n"
        f"Шаблон: {template_info}\n\n"
        "Выберите способ поиска клиента:"
    )

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    builder.button(text="🔍 Поиск клиента", callback_data=f"template_client_search_{template_id}")
    builder.button(text="👤 Все клиенты", callback_data="template_show_all_clients")
    builder.button(text="Назад", callback_data=f"template_select_{template_id}")
    builder.adjust(2)

    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data == "template_show_all_clients")
async def show_all_clients_for_template(callback: CallbackQuery, state: FSMContext):
    """Show all clients for template subscription creation."""
    data = await state.get_data()
    template_id = data.get("template_id")

    async with async_session_factory() as session:
        template_service = SubscriptionTemplateService(session)
        template = await template_service.get_template(template_id)
        template_info = f"<b>{template.name}</b> ({len(template.template_inbounds)} подключений)"

        client_service = ClientService(session)
        clients = await client_service.get_active_clients()

    if not clients:
        await callback.answer("⚠️ Нет активных клиентов. Сначала создайте клиента.", show_alert=True)
        return

    await state.set_state(TemplateManagement.waiting_for_client_selection)

    text = (
        f"📦 <b>Создание подписки из шаблона</b>\n\n"
        f"Шаблон: {template_info}\n\n"
        f"Всего клиентов: {len(clients)}\n\n"
        "Выберите клиента:"
    )

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    for client in clients[:10]:  # Limit to 10 clients
        builder.button(text=f"👤 {client.name}", callback_data=f"template_client_select_{client.id}")
    builder.button(text="🔍 Поиск клиента", callback_data=f"template_client_search_{template_id}")
    builder.button(text="Назад", callback_data=f"template_select_{template_id}")
    builder.adjust(1)

    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(TemplateManagement.waiting_for_client_selection, F.data.startswith("template_client_select_"))
async def handle_template_client_selection(callback: CallbackQuery, state: FSMContext):
    """Handle client selection for template."""
    client_id = int(callback.data.split("_")[3])
    await state.update_data(client_id=client_id)
    await state.set_state(TemplateManagement.waiting_for_subscription_name)

    async with async_session_factory() as session:
        client_service = ClientService(session)
        client = await client_service.get_client_by_id(client_id)

    text = (
        f"👤 <b>Клиент:</b> {client.name}\n\n"
        "Введите название подписки:"
    )

    await callback.message.edit_text(text)
    await callback.answer()


@router.message(TemplateManagement.waiting_for_subscription_name)
async def handle_template_subscription_name(message: Message, state: FSMContext):
    """Handle subscription name input."""
    name = message.text.strip()

    if not name:
        await message.answer("⚠️ Название не может быть пустым. Введите название:")
        return

    if len(name) > 100:
        await message.answer("⚠️ Название слишком длинное. Максимум 100 символов. Введите название:")
        return

    await state.update_data(subscription_name=name)
    await state.set_state(TemplateManagement.waiting_for_custom_traffic)

    data = await state.get_data()

    async with async_session_factory() as session:
        template_service = SubscriptionTemplateService(session)
        template = await template_service.get_template(data["template_id"])
        default_traffic = template.default_total_gb

    traffic_text = f"{default_traffic} ГБ {'(безлимитный)' if default_traffic == 0 else ''}"

    text = (
        f"📦 <b>Название подписки:</b> {name}\n\n"
        f"Введите лимит трафика в ГБ (текущее: {traffic_text}):"
    )

    await message.answer(text)


@router.message(TemplateManagement.waiting_for_custom_traffic)
async def handle_template_custom_traffic(message: Message, state: FSMContext):
    """Handle custom traffic limit input."""
    try:
        traffic = int(message.text.strip())
        if traffic < 0:
            await message.answer("⚠️ Лимит трафика не может быть отрицательным. Введите число:")
            return
    except ValueError:
        await message.answer("⚠️ Введите корректное число (используйте /skip для использования значения шаблона):")
        return

    if message.text == "/skip":
        data = await state.get_data()
        async with async_session_factory() as session:
            template_service = SubscriptionTemplateService(session)
            template = await template_service.get_template(data["template_id"])
            traffic = template.default_total_gb
    else:
        traffic = int(message.text.strip())

    await state.update_data(custom_traffic=traffic)
    await state.set_state(TemplateManagement.waiting_for_custom_expiry)

    data = await state.get_data()

    async with async_session_factory() as session:
        template_service = SubscriptionTemplateService(session)
        template = await template_service.get_template(data["template_id"])
        default_expiry = template.default_expiry_days

        expiry_text = f"{default_expiry} дн." if default_expiry else "Бессрочный"

        text = (
            f"📊 <b>Лимит трафика:</b> {traffic} ГБ {'(безлимитный)' if traffic == 0 else ''}\n\n"
            f"Введите срок действия в днях (текущее: {expiry_text}, 0 = бессрочный, /skip = использовать шаблон):"
        )

        await message.answer(text)


@router.message(TemplateManagement.waiting_for_custom_expiry)
async def handle_template_custom_expiry(message: Message, state: FSMContext):
    """Handle custom expiry days input."""
    if message.text == "/skip":
        expiry = None
    else:
        try:
            expiry = int(message.text.strip())
            if expiry < 0:
                await message.answer("⚠️ Срок действия не может быть отрицательным. Введите число:")
                return
        except ValueError:
            await message.answer("⚠️ Введите корректное число (0 = бессрочный, /skip = использовать шаблон):")
            return

        if expiry == 0:
            expiry = None

    await state.update_data(custom_expiry=expiry)
    await state.set_state(TemplateManagement.waiting_for_custom_notes)

    data = await state.get_data()

    async with async_session_factory() as session:
        template_service = SubscriptionTemplateService(session)
        template = await template_service.get_template(data["template_id"])
        default_traffic = template.default_total_gb

        traffic_text = f"{default_traffic} ГБ {'(безлимитный)' if default_traffic == 0 else ''}"
        expiry_text = f"{expiry} дн." if expiry else "Бессрочный"

        text = (
            f"📅 <b>Срок действия:</b> {expiry_text}\n\n"
            f"Введите заметки (необязательно, отправьте /skip для пропуска):"
        )

        await message.answer(text)


@router.message(TemplateManagement.waiting_for_custom_notes)
async def handle_template_custom_notes(message: Message, state: FSMContext):
    """Handle custom notes input."""
    if message.text == "/skip":
        notes = None
    else:
        notes = message.text.strip()
        if len(notes) > 500:
            await message.answer("⚠️ Заметки слишком длинные. Максимум 500 символов. Введите заметки:")
            return

    await state.update_data(custom_notes=notes)
    await state.set_state(TemplateManagement.confirm_template_creation)

    data = await state.get_data()

    try:
        async with async_session_factory() as session:
            template_service = SubscriptionTemplateService(session)
            client_service = ClientService(session)

            # Create subscription from template
            subscription, connections = await template_service.create_subscription_from_template(
                template_id=data["template_id"],
                client_id=data["client_id"],
                subscription_name=data["subscription_name"],
                total_gb=data.get("custom_traffic"),
                expiry_days=data.get("custom_expiry"),
                notes=data.get("custom_notes"),
            )

            # Get client for notification
            client = await client_service.get_client_by_id(data["client_id"])

            # Send notification if client has telegram_id
            if client.telegram_id:
                from app.services.notification_service import NotificationService
                notification_service = NotificationService(session)
                await notification_service.notify_subscription_created(
                    client=client,
                    subscription=subscription,
                    connections=connections,
                )

            await session.commit()

        await state.clear()

        traffic_text = f"{subscription.total_gb} ГБ" if subscription.total_gb > 0 else "Безлимитный"
        expiry_text = f"{subscription.remaining_days} дн." if subscription.expiry_date else "Бессрочный"

        text = (
            f"✅ <b>Подписка создана!</b>\n\n"
            f"👤 <b>Клиент:</b> {client.name}\n"
            f"📦 <b>Подписка:</b> {subscription.name}\n"
            f"📊 <b>Лимит трафика:</b> {traffic_text}\n"
            f"📅 <b>Срок действия:</b> {expiry_text}\n"
            f"🔌 <b>Создано подключений:</b> {len(connections)}\n"
        )

        if client.telegram_id:
            text += f"\n📱 <b>Уведомление отправлено:</b> Да"

        keyboard = get_back_keyboard("admin_menu")

        await message.answer(text, reply_markup=keyboard)

    except XUIError as e:
        await state.clear()
        await message.answer(f"❌ Ошибка при создании подписки: {str(e)}")
    except Exception as e:
        await state.clear()
        logger.error(f"Error creating subscription from template: {e}", exc_info=True)
        await message.answer(f"❌ Произошла ошибка при создании подписки")


@router.callback_query(F.data.startswith("template_add_inbound_"))
async def start_add_inbound_to_template(callback: CallbackQuery, state: FSMContext, is_admin: bool):
    """Start adding inbound to template."""
    if not is_admin:
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    template_id = int(callback.data.split("_")[3])

    async with async_session_factory() as session:
        template_service = SubscriptionTemplateService(session)
        template = await template_service.get_template(template_id)

        if not template:
            await callback.answer("⚠️ Шаблон не найден", show_alert=True)
            return

        async with async_session_factory() as session2:
            from app.services.xui_service import XUIService
            xui_service = XUIService(session2)
            inbounds = await xui_service.get_all_inbounds()

        # Filter out inbounds already in template
        template_inbounds = await template_service.get_template_inbounds(template_id)
        existing_inbound_ids = {ti.inbound_id for ti in template_inbounds}
        available_inbounds = [ib for ib in inbounds if ib.id not in existing_inbound_ids]

        if not available_inbounds:
            await callback.answer("⚠️ Все доступные подключения уже добавлены в шаблон", show_alert=True)
            return

        keyboard = get_inbound_selection_for_template(template_id, available_inbounds)

        await callback.message.edit_text(
            f"📋 <b>Добавление подключения к шаблону</b>\n\n"
            f"Шаблон: {template.name}\n\n"
            f"Выберите подключение:",
            reply_markup=keyboard,
        )
        await callback.answer()


@router.callback_query(F.data.startswith("template_select_inbound_"))
async def select_inbound_for_template(callback: CallbackQuery, state: FSMContext, is_admin: bool):
    """Select inbound and add to template."""
    if not is_admin:
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    parts = callback.data.split("_")
    template_id = int(parts[3])
    inbound_id = int(parts[4])

    try:
        async with async_session_factory() as session:
            template_service = SubscriptionTemplateService(session)

            # Get current inbounds count for order
            template_inbounds = await template_service.get_template_inbounds(template_id)
            order = len(template_inbounds)

            # Add inbound to template
            await template_service.add_inbound_to_template(
                template_id=template_id,
                inbound_id=inbound_id,
                order=order,
            )
            await session.commit()

            # Get updated template info
            template = await template_service.get_template(template_id)
            template_inbounds = await template_service.get_template_inbounds(template_id)

            logger.info(f"✅ Inbound {inbound_id} added to template {template.name}")

        await state.clear()

        # Show template details with updated inbounds
        traffic_limit = f"{template.default_total_gb} ГБ" if template.default_total_gb > 0 else "Безлимитный"
        expiry_text = f"{template.default_expiry_days} дн." if template.default_expiry_days else "Бессрочный"
        inbounds_count = len(template.template_inbounds)

        text = (
            f"📋 <b>{template.name}</b>\n\n"
            f"📝 {template.description or 'Нет описания'}\n"
            f"📊 <b>Лимит трафика:</b> {traffic_limit}\n"
            f"📅 <b>Срок действия:</b> {expiry_text}\n"
            f"🔌 <b>Подключений:</b> {inbounds_count}\n"
        )

        if template.notes:
            text += f"\n📌 <b>Заметки:</b> {template.notes}"

        keyboard = get_template_actions_keyboard(template.id)

        await callback.message.edit_text(text, reply_markup=keyboard)
        await callback.answer("✅ Подключение добавлено")

    except XUIError as e:
        await state.clear()
        await callback.message.edit_text(f"❌ Ошибка при добавлении подключения: {str(e)}")
        await callback.answer()
    except Exception as e:
        await state.clear()
        logger.error(f"Error adding inbound to template: {e}", exc_info=True)
        await callback.message.edit_text("❌ Произошла ошибка при добавлении подключения")
        await callback.answer()


@router.callback_query(F.data.startswith("template_delete_"))
async def start_delete_template(callback: CallbackQuery, state: FSMContext, is_admin: bool):
    """Start template deletion."""
    if not is_admin:
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    template_id = int(callback.data.split("_")[2])

    async with async_session_factory() as session:
        template_service = SubscriptionTemplateService(session)
        template = await template_service.get_template(template_id)

        if not template:
            await callback.answer("⚠️ Шаблон не найден", show_alert=True)
            return

    await state.update_data(template_id=template_id, template_name=template.name)
    await state.set_state(TemplateManagement.confirm_delete_template)

    text = (
        f"❌ <b>Удаление шаблона</b>\n\n"
        f"Вы уверены, что хотите удалить шаблон <b>{template.name}</b>?\n\n"
        f"<b>Внимание!</b> Это действие необратимо. Все подписки, созданные с использованием этого шаблона, сохранятся."
    )

    keyboard = get_confirm_keyboard("confirm_delete_template", "admin_templates")

    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data == "confirm_delete_template")
async def confirm_delete_template(callback: CallbackQuery, state: FSMContext, is_admin: bool):
    """Confirm and delete template."""
    if not is_admin:
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    data = await state.get_data()
    template_id = data["template_id"]

    try:
        async with async_session_factory() as session:
            template_service = SubscriptionTemplateService(session)
            deleted = await template_service.delete_template(template_id)
            await session.commit()

        if deleted:
            logger.info(f"✅ Template deleted: {data.get('template_name')}")

        await state.clear()

        # Show templates list
        async with async_session_factory() as session:
            template_service = SubscriptionTemplateService(session)
            templates = await template_service.get_all_templates()

            if not templates:
                text = "📋 <b>Шаблоны подписок</b>\n\nШаблонов пока нет. Создайте первый шаблон!"
                keyboard = get_back_keyboard("admin_menu")
            else:
                text = f"📋 <b>Шаблоны подписок</b>\n\nВсего шаблонов: {len(templates)}"
                keyboard = get_templates_keyboard(templates)

        await callback.message.edit_text(text, reply_markup=keyboard)
        await callback.answer("✅ Шаблон удален")

    except Exception as e:
        await state.clear()
        logger.error(f"Error deleting template: {e}", exc_info=True)
        await callback.message.edit_text("❌ Произошла ошибка при удалении шаблона")
        await callback.answer()


@router.callback_query(F.data.startswith("template_edit_"))
async def start_edit_template(callback: CallbackQuery, state: FSMContext, is_admin: bool):
    """Start editing template."""
    if not is_admin:
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    parts = callback.data.split("_")
    edit_field = parts[2]
    template_id = int(parts[3])

    async with async_session_factory() as session:
        template_service = SubscriptionTemplateService(session)
        template = await template_service.get_template(template_id)

        if not template:
            await callback.answer("⚠️ Шаблон не найден", show_alert=True)
            return

    await state.update_data(template_id=template_id)

    # Map edit_field to state
    state_mapping = {
        "name": TemplateManagement.editing_template_name,
        "description": TemplateManagement.editing_template_description,
        "traffic": TemplateManagement.editing_default_traffic,
        "expiry": TemplateManagement.editing_default_expiry,
        "notes": TemplateManagement.editing_template_notes,
    }

    if edit_field not in state_mapping:
        await callback.answer("⚠️ Неизвестное поле для редактирования", show_alert=True)
        return

    await state.set_state(state_mapping[edit_field])

    # Get current value message
    current_value_messages = {
        "name": f"Текущее название: <b>{template.name}</b>",
        "description": f"Текущее описание: <b>{template.description or 'Нет описания'}</b>",
        "traffic": f"Текущий лимит трафика: <b>{template.default_total_gb} ГБ {'(безлимитный)' if template.default_total_gb == 0 else ''}</b>",
        "expiry": f"Текущий срок действия: <b>{template.default_expiry_days} дн." if template.default_expiry_days else f"<b>Бессрочный</b>",
        "notes": f"Текущие заметки: <b>{template.notes or 'Нет заметок'}</b>",
    }

    prompt_messages = {
        "name": "Введите новое название (или /skip чтобы оставить текущее):",
        "description": "Введите новое описание (или /skip чтобы оставить текущее):",
        "traffic": "Введите новый лимит трафика в ГБ (0 = безлимитный, /skip = использовать текущее):",
        "expiry": "Введите новый срок действия в днях (0 = бессрочный, /skip = использовать текущее):",
        "notes": "Введите новые заметки (или /skip чтобы оставить текущие):",
    }

    text = (
        f"✏️ <b>Редактирование шаблона</b>\n\n"
        f"{current_value_messages[edit_field]}\n\n"
        f"{prompt_messages[edit_field]}"
    )

    keyboard = get_back_keyboard(f"template_select_{template_id}")

    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@router.message(TemplateManagement.editing_template_name)
async def process_edit_template_name(message: Message, state: FSMContext):
    """Process template name edit."""
    new_name = message.text.strip()

    if new_name == "/skip":
        await show_template_details_edit_menu(message, state)
        return

    if not new_name:
        await message.answer("⚠️ Название не может быть пустым. Введите название:")
        return

    if len(new_name) > 100:
        await message.answer("⚠️ Название слишком длинное. Максимум 100 символов. Введите название:")
        return

    data = await state.get_data()
    template_id = data["template_id"]

    try:
        async with async_session_factory() as session:
            template_service = SubscriptionTemplateService(session)
            template = await template_service.update_template(
                template_id=template_id,
                name=new_name,
            )
            await session.commit()

        logger.info(f"✅ Template name updated: {template.name}")

        await message.answer(f"✅ Название изменено на: {new_name}")
        await show_template_details_edit_menu(message, state)

    except Exception as e:
        logger.error(f"Error updating template name: {e}", exc_info=True)
        await message.answer("❌ Произошла ошибка при изменении названия")
        await show_template_details_edit_menu(message, state)


@router.message(TemplateManagement.editing_template_description)
async def process_edit_template_description(message: Message, state: FSMContext):
    """Process template description edit."""
    new_description = message.text.strip()

    if new_description == "/skip":
        await show_template_details_edit_menu(message, state)
        return

    if len(new_description) > 500:
        await message.answer("⚠️ Описание слишком длинное. Максимум 500 символов. Введите описание:")
        return

    data = await state.get_data()
    template_id = data["template_id"]

    try:
        async with async_session_factory() as session:
            template_service = SubscriptionTemplateService(session)
            template = await template_service.update_template(
                template_id=template_id,
                description=new_description,
            )
            await session.commit()

        logger.info(f"✅ Template description updated: {template.name}")

        await message.answer("✅ Описание изменено")
        await show_template_details_edit_menu(message, state)

    except Exception as e:
        logger.error(f"Error updating template description: {e}", exc_info=True)
        await message.answer("❌ Произошла ошибка при изменении описания")
        await show_template_details_edit_menu(message, state)


@router.message(TemplateManagement.editing_default_traffic)
async def process_edit_default_traffic(message: Message, state: FSMContext):
    """Process default traffic edit."""
    traffic_input = message.text.strip()

    if traffic_input == "/skip":
        await show_template_details_edit_menu(message, state)
        return

    try:
        traffic = int(traffic_input)
        if traffic < 0:
            await message.answer("⚠️ Лимит трафика не может быть отрицательным. Введите число:")
            return
    except ValueError:
        await message.answer("⚠️ Введите корректное число (0 = безлимитный, /skip = использовать текущее):")
        return

    data = await state.get_data()
    template_id = data["template_id"]

    try:
        async with async_session_factory() as session:
            template_service = SubscriptionTemplateService(session)
            template = await template_service.update_template(
                template_id=template_id,
                default_total_gb=traffic,
            )
            await session.commit()

        logger.info(f"✅ Template traffic updated: {template.name}")

        traffic_text = f"{traffic} ГБ {'(безлимитный)' if traffic == 0 else ''}"
        await message.answer(f"✅ Лимит трафика изменен на: {traffic_text}")
        await show_template_details_edit_menu(message, state)

    except Exception as e:
        logger.error(f"Error updating template traffic: {e}", exc_info=True)
        await message.answer("❌ Произошла ошибка при изменении лимита трафика")
        await show_template_details_edit_menu(message, state)


@router.message(TemplateManagement.editing_default_expiry)
async def process_edit_default_expiry(message: Message, state: FSMContext):
    """Process default expiry edit."""
    expiry_input = message.text.strip()

    if expiry_input == "/skip":
        await show_template_details_edit_menu(message, state)
        return

    try:
        expiry = int(expiry_input)
        if expiry < 0:
            await message.answer("⚠️ Срок действия не может быть отрицательным. Введите число:")
            return
    except ValueError:
        await message.answer("⚠️ Введите корректное число (0 = бессрочный, /skip = использовать текущее):")
        return

    if expiry == 0:
        expiry = None

    data = await state.get_data()
    template_id = data["template_id"]

    try:
        async with async_session_factory() as session:
            template_service = SubscriptionTemplateService(session)
            template = await template_service.update_template(
                template_id=template_id,
                default_expiry_days=expiry,
            )
            await session.commit()

        logger.info(f"✅ Template expiry updated: {template.name}")

        expiry_text = f"{expiry} дн." if expiry else "Бессрочный"
        await message.answer(f"✅ Срок действия изменен на: {expiry_text}")
        await show_template_details_edit_menu(message, state)

    except Exception as e:
        logger.error(f"Error updating template expiry: {e}", exc_info=True)
        await message.answer("❌ Произошла ошибка при изменении срока действия")
        await show_template_details_edit_menu(message, state)


@router.message(TemplateManagement.editing_template_notes)
async def process_edit_template_notes(message: Message, state: FSMContext):
    """Process template notes edit."""
    new_notes = message.text.strip()

    if new_notes == "/skip":
        await show_template_details_edit_menu(message, state)
        return

    if len(new_notes) > 500:
        await message.answer("⚠️ Заметки слишком длинные. Максимум 500 символов. Введите заметки:")
        return

    data = await state.get_data()
    template_id = data["template_id"]

    try:
        async with async_session_factory() as session:
            template_service = SubscriptionTemplateService(session)
            template = await template_service.update_template(
                template_id=template_id,
                notes=new_notes,
            )
            await session.commit()

        logger.info(f"✅ Template notes updated: {template.name}")

        await message.answer("✅ Заметки изменены")
        await show_template_details_edit_menu(message, state)

    except Exception as e:
        logger.error(f"Error updating template notes: {e}", exc_info=True)
        await message.answer("❌ Произошла ошибка при изменении заметок")
        await show_template_details_edit_menu(message, state)


async def show_template_details_edit_menu(message: Message, state: FSMContext):
    """Show template details with edit menu after editing."""
    data = await state.get_data()
    template_id = data["template_id"]

    async with async_session_factory() as session:
        template_service = SubscriptionTemplateService(session)
        template = await template_service.get_template(template_id)

        if not template:
            await message.answer("⚠️ Шаблон не найден")
            return

        traffic_limit = f"{template.default_total_gb} ГБ" if template.default_total_gb > 0 else "Безлимитный"
        expiry_text = f"{template.default_expiry_days} дн." if template.default_expiry_days else "Бессрочный"
        inbounds_count = len(template.template_inbounds)

        text = (
            f"📋 <b>{template.name}</b>\n\n"
            f"📝 {template.description or 'Нет описания'}\n"
            f"📊 <b>Лимит трафика:</b> {traffic_limit}\n"
            f"📅 <b>Срок действия:</b> {expiry_text}\n"
            f"🔌 <b>Подключений:</b> {inbounds_count}\n"
        )

        if template.notes:
            text += f"\n📌 <b>Заметки:</b> {template.notes}"

        keyboard = get_template_actions_keyboard(template.id)

    await message.answer(text, reply_markup=keyboard)


@router.callback_query(F.data.startswith("template_inbound_remove_"))
async def start_remove_inbound_from_template(callback: CallbackQuery, state: FSMContext, is_admin: bool):
    """Start removing inbound from template."""
    if not is_admin:
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    parts = callback.data.split("_")
    template_id = int(parts[3])
    inbound_id = int(parts[4])

    async with async_session_factory() as session:
        template_service = SubscriptionTemplateService(session)
        template = await template_service.get_template(template_id)
        template_inbound = await template_service.get_template_inbound(template_id, inbound_id)

        if not template or not template_inbound:
            await callback.answer("⚠️ Шаблон или подключение не найдены", show_alert=True)
            return

    await state.update_data(template_id=template_id, inbound_id=inbound_id)
    await state.set_state(TemplateManagement.confirm_remove_inbound)

    text = (
        f"❌ <b>Удаление подключения из шаблона</b>\n\n"
        f"Вы уверены, что хотите удалить подключение <b>{template_inbound.inbound.remark}</b> из шаблона <b>{template.name}</b>?\n\n"
        f"<b>Внимание!</b> Это действие необратимо."
    )

    keyboard = get_confirm_keyboard("confirm_remove_inbound", f"template_select_{template_id}")

    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data == "confirm_remove_inbound")
async def confirm_remove_inbound(callback: CallbackQuery, state: FSMContext, is_admin: bool):
    """Confirm and remove inbound from template."""
    if not is_admin:
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    data = await state.get_data()
    template_id = data["template_id"]
    inbound_id = data["inbound_id"]

    try:
        async with async_session_factory() as session:
            template_service = SubscriptionTemplateService(session)
            removed = await template_service.remove_inbound_from_template(template_id, inbound_id)
            await session.commit()

        if removed:
            logger.info(f"✅ Inbound {inbound_id} removed from template {template_id}")

        await state.clear()

        # Show updated template details
        async with async_session_factory() as session:
            template_service = SubscriptionTemplateService(session)
            template = await template_service.get_template(template_id)

            traffic_limit = f"{template.default_total_gb} ГБ" if template.default_total_gb > 0 else "Безлимитный"
            expiry_text = f"{template.default_expiry_days} дн." if template.default_expiry_days else "Бессрочный"
            inbounds_count = len(template.template_inbounds)

            text = (
                f"📋 <b>{template.name}</b>\n\n"
                f"📝 {template.description or 'Нет описания'}\n"
                f"📊 <b>Лимит трафика:</b> {traffic_limit}\n"
                f"📅 <b>Срок действия:</b> {expiry_text}\n"
                f"🔌 <b>Подключений:</b> {inbounds_count}\n"
            )

            if template.notes:
                text += f"\n📌 <b>Заметки:</b> {template.notes}"

            keyboard = get_template_actions_keyboard(template.id)

        await callback.message.edit_text(text, reply_markup=keyboard)
        await callback.answer("✅ Подключение удалено")

    except Exception as e:
        await state.clear()
        logger.error(f"Error removing inbound from template: {e}", exc_info=True)
        await callback.message.edit_text("❌ Произошла ошибка при удалении подключения")
        await callback.answer()


@router.callback_query(F.data.startswith("template_client_search_"))
async def start_template_client_search(callback: CallbackQuery, state: FSMContext, is_admin: bool):
    """Start client search for template subscription creation."""
    if not is_admin:
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    parts = callback.data.split("_")
    template_id = int(parts[3])

    await state.update_data(template_id=template_id)
    await state.set_state(TemplateManagement.waiting_for_search_query)

    keyboard = get_back_keyboard(f"template_select_{template_id}")

    await callback.message.edit_text(
        "🔍 <b>Поиск клиента</b>\n\n"
        "Введите имя, email или Telegram ID клиента для поиска:",
        reply_markup=keyboard,
    )
    await callback.answer()


@router.message(TemplateManagement.waiting_for_search_query)
async def process_template_client_search(message: Message, state: FSMContext):
    """Process client search for template subscription creation."""
    query = message.text.strip()

    if not query:
        await message.answer("⚠️ Поисковый запрос не может быть пустым. Введите запрос:")
        return

    try:
        async with async_session_factory() as session:
            client_service = ClientService(session)
            from app.services.client_service import _normalize_search_query
            normalized_query = _normalize_search_query(query)

            # Search by multiple fields
            clients = []
            try:
                # Try exact match by telegram_id first
                if normalized_query.isdigit():
                    client = await client_service.get_client_by_telegram_id(int(normalized_query))
                    if client and client.is_active:
                        clients.append(client)

                # Search by other fields
                all_clients = await client_service.get_active_clients()
                for client in all_clients:
                    if client in clients:
                        continue  # Skip if already found

                    # Check name
                    if _normalize_search_query(client.name) in normalized_query:
                        clients.append(client)
                        continue

                    # Check email
                    if client.xui_email and normalized_query in _normalize_search_query(client.xui_email):
                        clients.append(client)
                        continue

                    # Check telegram_username
                    if client.telegram_username and normalized_query in _normalize_search_query(client.telegram_username):
                        clients.append(client)
                        continue

            except Exception as e:
                logger.error(f"Error searching clients: {e}", exc_info=True)

        if not clients:
            await message.answer(
                f"❌ Клиенты не найдены по запросу: <b>{query}</b>\n\n"
                "Попробуйте другой запрос или создайте нового клиента.",
                parse_mode="HTML"
            )
            return

        await state.set_state(TemplateManagement.waiting_for_client_selection)

        text = f"🔍 <b>Результаты поиска</b>\n\nПо запросу: <b>{query}</b>\n\nНайдено клиентов: {len(clients)}\n\nВыберите клиента:"

        # Build keyboard with search results
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        builder = InlineKeyboardBuilder()
        for client in clients[:10]:  # Limit to 10 results
            builder.button(
                text=f"👤 {client.name}",
                callback_data=f"template_client_select_{client.id}",
            )
        builder.button(text="🔍 Новый поиск", callback_data=f"template_client_search_{state.get_data().get('template_id')}")
        builder.button(text="Назад", callback_data=f"template_select_{state.get_data().get('template_id')}")
        builder.adjust(1)

        await message.answer(text, reply_markup=builder.as_markup())

    except Exception as e:
        logger.error(f"Error processing client search: {e}", exc_info=True)
        await message.answer("❌ Произошла ошибка при поиске клиентов")
