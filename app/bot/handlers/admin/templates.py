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
        "Введите лимит трафика по умолчанию в ГБ (0 = безлимитный):"
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

    text = (
        f"📊 <b>Лимит трафика:</b> {traffic} ГБ {'(безлимитный)' if traffic == 0 else ''}\n\n"
        "Введите срок действия по умолчанию в днях (0 = бессрочный, отправьте /skip для пропуска):"
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
            await message.answer("⚠️ Введите корректное число (0 = бессрочный):")
            return

        if expiry == 0:
            expiry = None

    await state.update_data(default_expiry=expiry)
    await state.set_state(TemplateManagement.waiting_for_template_notes)

    text = (
        f"📅 <b>Срок действия:</b> {expiry} дн." if expiry else "📅 <b>Срок действия:</b> Бессрочный"
    )
    text += "\n\nВведите заметки (необязательно, отправьте /skip для пропуска):"

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

    async with async_session_factory() as session:
        template_service = SubscriptionTemplateService(session)
        template = await template_service.create_template(
            name=data["template_name"],
            description=data.get("template_description"),
            default_total_gb=data["default_traffic"],
            default_expiry_days=data.get("default_expiry"),
            notes=notes,
        )
        await session.commit()

        logger.info(f"✅ Template created: {template.name} (ID: {template.id})")

    await state.clear()

    # Show templates list
    async with async_session_factory() as session:
        template_service = SubscriptionTemplateService(session)
        templates = await template_service.get_all_templates()
        text = f"✅ <b>Шаблон создан!</b>\n\n{template.name}\n{template.description or ''}"
        keyboard = get_templates_keyboard(templates)

    await message.answer(text, reply_markup=keyboard)


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
            f"✅ <b>Статус:</b> {'Активен' if template.is_active else 'Неактивен'}\n"
        )

        if template.notes:
            text += f"\n📌 <b>Заметки:</b> {template.notes}"

        keyboard = get_template_actions_keyboard(template_id)

    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("template_edit_"))
async def start_template_editing(callback: CallbackQuery, state: FSMContext, is_admin: bool):
    """Start template editing."""
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

    await state.update_data(template_id=template_id)
    await state.set_state(TemplateManagement.editing_template_name)

    text = (
        f"✏️ <b>Редактирование шаблона: {template.name}</b>\n\n"
        f"Текущее название: {template.name}\n"
        f"Введите новое название:"
    )

    await callback.message.edit_text(text, reply_markup=get_back_keyboard("admin_templates"))
    await callback.answer()


@router.message(TemplateManagement.editing_template_name)
async def handle_edit_template_name(message: Message, state: FSMContext):
    """Handle template name editing."""
    name = message.text.strip()

    if not name:
        await message.answer("⚠️ Название не может быть пустым. Введите название:")
        return

    if len(name) > 100:
        await message.answer("⚠️ Название слишком длинное. Максимум 100 символов. Введите название:")
        return

    await state.update_data(new_name=name)
    await state.set_state(TemplateManagement.editing_template_description)

    text = (
        f"✅ <b>Новое название:</b> {name}\n\n"
        f"Текущее описание: {message.text or 'Нет описания'}\n\n"
        f"Введите новое описание (необязательно, отправьте /skip для пропуска):"
    )

    await message.answer(text)


@router.message(TemplateManagement.editing_template_description)
async def handle_edit_template_description(message: Message, state: FSMContext):
    """Handle template description editing."""
    if message.text == "/skip":
        description = None
    else:
        description = message.text.strip()
        if len(description) > 500:
            await message.answer("⚠️ Описание слишком длинное. Максимум 500 символов. Введите описание:")
            return

    await state.update_data(new_description=description)
    await state.set_state(TemplateManagement.editing_default_traffic)

    data = await state.get_data()

    async with async_session_factory() as session:
        template_service = SubscriptionTemplateService(session)
        template = await template_service.get_template(data["template_id"])

        current_traffic = template.default_total_gb
        traffic_text = f"{current_traffic} ГБ {'(безлимитный)' if current_traffic == 0 else ''}"

        text = (
            f"📝 <b>Новое описание:</b> {description or 'Нет описания'}\n\n"
            f"📊 <b>Текущий лимит трафика:</b> {traffic_text}\n\n"
            f"Введите новый лимит трафика в ГБ (0 = безлимитный):"
        )

        await message.answer(text)


@router.message(TemplateManagement.editing_default_traffic)
async def handle_edit_default_traffic(message: Message, state: FSMContext):
    """Handle default traffic limit editing."""
    try:
        traffic = int(message.text.strip())
        if traffic < 0:
            await message.answer("⚠️ Лимит трафика не может быть отрицательным. Введите число:")
            return
    except ValueError:
        await message.answer("⚠️ Введите корректное число (0 = безлимитный):")
        return

    await state.update_data(new_traffic=traffic)
    await state.set_state(TemplateManagement.editing_default_expiry)

    data = await state.get_data()

    async with async_session_factory() as session:
        template_service = SubscriptionTemplateService(session)
        template = await template_service.get_template(data["template_id"])

        current_expiry = template.default_expiry_days
        expiry_text = f"{current_expiry} дн." if current_expiry else "Бессрочный"

        text = (
            f"📊 <b>Новый лимит трафика:</b> {traffic} ГБ {'(безлимитный)' if traffic == 0 else ''}\n\n"
            f"📅 <b>Текущий срок действия:</b> {expiry_text}\n\n"
            f"Введите новый срок действия в днях (0 = бессрочный, отправьте /skip для пропуска):"
        )

        await message.answer(text)


@router.message(TemplateManagement.editing_default_expiry)
async def handle_edit_default_expiry(message: Message, state: FSMContext):
    """Handle default expiry days editing."""
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

    await state.update_data(new_expiry=expiry)
    await state.set_state(TemplateManagement.editing_template_notes)

    data = await state.get_data()

    async with async_session_factory() as session:
        template_service = SubscriptionTemplateService(session)
        template = await template_service.get_template(data["template_id"])

        expiry_text = f"{expiry} дн." if expiry else "Бессрочный"
        text = (
            f"📅 <b>Новый срок действия:</b> {expiry_text}\n\n"
            f"Текущие заметки: {template.notes or 'Нет заметок'}\n\n"
            f"Введите новые заметки (необязательно, отправьте /skip для пропуска):"
        )

        await message.answer(text)


@router.message(TemplateManagement.editing_template_notes)
async def handle_edit_template_notes(message: Message, state: FSMContext):
    """Handle template notes editing."""
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
            template = await template_service.update_template(
                template_id=data["template_id"],
                name=data.get("new_name"),
                description=data.get("new_description"),
                default_total_gb=data.get("new_traffic"),
                default_expiry_days=data.get("new_expiry"),
                notes=notes,
            )
            await session.commit()

            logger.info(f"✅ Template updated: {template.name} (ID: {template.id})")

        await state.clear()

        traffic_limit = f"{template.default_total_gb} ГБ" if template.default_total_gb > 0 else "Безлимитный"
        expiry_text = f"{template.default_expiry_days} дн." if template.default_expiry_days else "Бессрочный"
        inbounds_count = len(template.template_inbounds)

        text = (
            f"✅ <b>Шаблон обновлен!</b>\n\n"
            f"📋 <b>{template.name}</b>\n"
            f"📝 {template.description or 'Нет описания'}\n"
            f"📊 <b>Лимит трафика:</b> {traffic_limit}\n"
            f"📅 <b>Срок действия:</b> {expiry_text}\n"
            f"🔌 <b>Подключений:</b> {inbounds_count}\n"
        )

        if template.notes:
            text += f"\n📌 <b>Заметки:</b> {template.notes}"

        keyboard = get_template_actions_keyboard(template.id)

        await message.answer(text, reply_markup=keyboard)

    except Exception as e:
        await state.clear()
        logger.error(f"Error updating template: {e}", exc_info=True)
        await message.answer(f"❌ Произошла ошибка при обновлении шаблона: {str(e)}")


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

        # Get clients
        client_service = ClientService(session)
        clients = await client_service.get_active_clients()

    if not clients:
        await callback.answer("⚠️ Нет клиентов. Сначала создайте клиента.", show_alert=True)
        return

    text = (
        f"📦 <b>Создание подписки из шаблона</b>\n\n"
        f"Шаблон: {template_info}\n\n"
        f"Выберите клиента:"
    )

    from app.bot.keyboards import get_clients_keyboard
    keyboard = get_clients_keyboard(clients)

    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(TemplateManagement.waiting_for_client_selection, F.data.startswith("client_select_"))
async def handle_template_client_selection(callback: CallbackQuery, state: FSMContext, is_admin: bool):
    """Handle client selection for template subscription."""
    if not is_admin:
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    client_id = int(callback.data.split("_")[2])
    await state.update_data(client_id=client_id)

    async with async_session_factory() as session:
        client_service = ClientService(session)
        client = await client_service.get_client_by_id(client_id)

    await state.set_state(TemplateManagement.waiting_for_subscription_name)

    text = (
        f"👤 <b>Клиент:</b> {client.name}\n\n"
        "Введите название подписки:"
    )

    await callback.message.edit_text(text)
    await callback.answer()


@router.message(TemplateManagement.waiting_for_subscription_name)
async def handle_template_subscription_name(message: Message, state: FSMContext):
    """Handle subscription name input for template."""
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
        data = await state.get_data()
        async with async_session_factory() as session:
            template_service = SubscriptionTemplateService(session)
            template = await template_service.get_template(data["template_id"])
            expiry = template.default_expiry_days
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

    if expiry:
        text = f"📅 <b>Срок действия:</b> {expiry} дн."
    else:
        text = "📅 <b>Срок действия:</b> Бессрочный"

    text += "\n\nВведите заметки (необязательно, отправьте /skip для пропуска):"

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

    async with async_session_factory() as session:
        template_service = SubscriptionTemplateService(session)
        client_service = ClientService(session)

        template = await template_service.get_template(data["template_id"])
        client = await client_service.get_client_by_id(data["client_id"])

        traffic = data.get("custom_traffic")
        expiry = data.get("custom_expiry")

        traffic_text = f"{traffic} ГБ {'(безлимитный)' if traffic == 0 else ''}"
        expiry_text = f"{expiry} дн." if expiry else "Бессрочный"

        text = (
            f"🔍 <b>Подтверждение создания подписки</b>\n\n"
            f"👤 <b>Клиент:</b> {client.name}\n"
            f"📦 <b>Шаблон:</b> {template.name}\n"
            f"📋 <b>Название подписки:</b> {data['subscription_name']}\n"
            f"📊 <b>Лимит трафика:</b> {traffic_text}\n"
            f"📅 <b>Срок действия:</b> {expiry_text}\n"
            f"🔌 <b>Подключений:</b> {len(template.template_inbounds)}\n"
        )

        if notes:
            text += f"\n📌 <b>Заметки:</b> {notes}"

    keyboard = get_confirm_keyboard("confirm_template_creation")

    await message.answer(text, reply_markup=keyboard)


@router.callback_query(F.data == "confirm_template_creation")
async def confirm_template_subscription_creation(callback: CallbackQuery, state: FSMContext, is_admin: bool):
    """Confirm and create subscription from template."""
    if not is_admin:
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

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

            logger.info(
                f"✅ Subscription created from template: {subscription.name} "
                f"for client {client.name} with {len(connections)} connections"
            )

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

        await callback.message.edit_text(text, reply_markup=keyboard)
        await callback.answer()

    except XUIError as e:
        await state.clear()
        await callback.message.edit_text(f"❌ Ошибка при создании подписки: {str(e)}")
        await callback.answer()
    except Exception as e:
        await state.clear()
        logger.error(f"Error creating subscription from template: {e}", exc_info=True)
        await callback.message.edit_text(f"❌ Произошла ошибка при создании подписки")
        await callback.answer()


@router.callback_query(F.data.startswith("template_add_inbound_"))
async def start_add_inbound_to_template(callback: CallbackQuery, state: FSMContext, is_admin: bool):
    """Start adding inbound to template."""
    if not is_admin:
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    template_id = int(callback.data.split("_")[3])

    async with async_session_factory() as session:
        template_service = SubscriptionTemplateService(session)

        # Get available inbounds (not yet in template)
        from app.services.xui_service import XUIService
        xui_service = XUIService(session)
        inbounds = await xui_service.get_all_inbounds()

        # Filter out inbounds already in template
        template_inbounds = await template_service.get_template_inbounds(template_id)
        existing_inbound_ids = {ti.inbound_id for ti in template_inbounds}
        available_inbounds = [ib for ib in inbounds if ib.id not in existing_inbound_ids]

        if not available_inbounds:
            await callback.answer("⚠️ Все доступные подключения уже добавлены в шаблон", show_alert=True)
            return

    await state.update_data(template_id=template_id)
    await state.set_state(TemplateManagement.waiting_for_inbound_selection)

    text = (
        f"📋 <b>Добавление подключения к шаблону</b>\n\n"
        f"Выберите подключение:"
    )

    keyboard = get_inbound_selection_for_template(template_id, available_inbounds)

    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("template_select_inbound_"))
async def select_inbound_for_template(callback: CallbackQuery, state: FSMContext, is_admin: bool):
    """Select inbound and add to template."""
    if not is_admin:
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    template_id = int(callback.data.split("_")[3])
    inbound_id = int(callback.data.split("_")[4])

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

        # Show template details with updated inbounds
        traffic_limit = f"{template.default_total_gb} ГБ" if template.default_total_gb > 0 else "Безлимитный"
        expiry_text = f"{template.default_expiry_days} дн." if template.default_expiry_days else "Бессрочный"

        text = (
            f"📋 <b>{template.name}</b>\n\n"
            f"📊 <b>Лимит трафика:</b> {traffic_limit}\n"
            f"📅 <b>Срок действия:</b> {expiry_text}\n"
            f"🔌 <b>Подключений:</b> {len(template_inbounds)}\n"
        )

        keyboard = get_template_actions_keyboard(template_id)

        await callback.message.edit_text(text, reply_markup=keyboard)
        await callback.answer("✅ Подключение добавлено")

    except XUIError as e:
        await callback.answer(f"⚠️ {str(e)}", show_alert=True)
    except Exception as e:
        logger.error(f"Error adding inbound to template: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка", show_alert=True)


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
        f"<b>Внимание!</b> Это действие необратимо."
    )

    keyboard = get_confirm_keyboard("confirm_delete_template")

    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data == "confirm_delete_template")
async def confirm_delete_template(callback: CallbackQuery, state: FSMContext, is_admin: bool):
    """Confirm and delete template."""
    if not is_admin:
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    data = await state.get_data()

    try:
        async with async_session_factory() as session:
            template_service = SubscriptionTemplateService(session)
            deleted = await template_service.delete_template(data["template_id"])
            await session.commit()

        if deleted:
            logger.info(f"✅ Template deleted: {data['template_name']}")

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
