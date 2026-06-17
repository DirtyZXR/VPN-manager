"""Admin client management handlers."""

import contextlib

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from loguru import logger

from app.bot.filters import AdminFilter
from app.bot.keyboards import (
    get_back_keyboard,
    get_client_search_keyboard,
    get_clients_keyboard,
    get_clients_page_keyboard,
    get_confirm_keyboard,
    get_servers_keyboard,
)
from app.bot.states import ClientManagement, SubscriptionManagement
from app.bot.states.admin import TemplateManagement
from app.database import async_session_factory
from app.services.client_service import ClientService
from app.services.subscription_template_service import SubscriptionTemplateService
from app.utils.texts import t

router = Router()
router.message.filter(AdminFilter())
router.callback_query.filter(AdminFilter())


@router.callback_query(F.data == "admin_clients")
async def show_clients(callback: CallbackQuery, state: FSMContext) -> None:
    """Show clients search menu."""
    current_state = await state.get_state()
    if current_state:
        await state.clear()

    try:
        # Create a custom keyboard for main menu
        from aiogram.utils.keyboard import InlineKeyboardBuilder

        kb = InlineKeyboardBuilder()
        kb.button(
            text=t("admin.clients.btn.all_clients", "📋 Все клиенты"), callback_data="clients_list"
        )
        kb.button(
            text=t("admin.clients.btn.search", "🔍 Поиск клиентов"), callback_data="client_search"
        )
        kb.button(
            text=t("admin.clients.btn.add", "➕ Добавить клиента"), callback_data="client_add"
        )
        kb.button(text=t("admin.clients.btn.back", "🔙 Назад"), callback_data="admin_clients_menu")
        kb.adjust(1)

        await callback.message.edit_text(
            t(
                "admin.clients.main_menu",
                "👥 Управление клиентами\n\nДля эффективной работы с большим количеством клиентов используйте поиск по различным критериям.",
            ),
            reply_markup=kb.as_markup(),
        )
    except Exception:
        # Message hasn't changed, skip edit
        pass
    await callback.answer()


@router.callback_query(F.data == "client_add")
async def start_add_client(callback: CallbackQuery, state: FSMContext) -> None:
    """Start adding new client."""
    await state.set_state(ClientManagement.waiting_for_name)
    with contextlib.suppress(Exception):
        await callback.message.edit_text(
            t("admin.clients.add.title", "➕ Добавление нового клиента\n\nВведите имя клиента:"),
            reply_markup=get_back_keyboard("admin_clients"),
        )
    await callback.answer()


@router.message(ClientManagement.waiting_for_name)
async def process_client_name(message: Message, state: FSMContext) -> None:
    """Process client name input."""
    name = message.text.strip()

    if not name:
        await message.answer(
            t("admin.clients.add.empty_name", "❌ Имя не может быть пустым."),
            reply_markup=get_back_keyboard("admin_clients"),
        )
        return

    if len(name) > 100:
        await message.answer(
            t("admin.clients.add.name_too_long", "❌ Имя не должно превышать 100 символов."),
            reply_markup=get_back_keyboard("admin_clients"),
        )
        return

    await state.update_data(name=name)
    await state.set_state(ClientManagement.waiting_for_email)
    await message.answer(
        t(
            "admin.clients.add.email_prompt",
            "Введите email клиента (или отправьте '-' для автоматической генерации):",
        ),
        reply_markup=get_back_keyboard("admin_clients"),
    )


@router.message(ClientManagement.waiting_for_email)
async def process_client_email(message: Message, state: FSMContext) -> None:
    """Process client email input."""
    email = message.text.strip()

    if email != "-" and ("@" not in email or "." not in email):
        await message.answer(
            t("admin.clients.add.invalid_email", "❌ Некорректный формат email."),
            reply_markup=get_back_keyboard("admin_clients"),
        )
        return

    await state.update_data(email=email if email != "-" else None)
    await state.set_state(ClientManagement.waiting_for_telegram_id)
    await message.answer(
        t(
            "admin.clients.add.telegram_prompt",
            "Введите Telegram ID клиента (число) или отправьте '-' для пропуска.\n\nПримечание: Telegram ID будет использоваться для синхронизации с XUI панелями.",
        ),
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
                t(
                    "admin.clients.add.invalid_telegram",
                    "❌ Telegram ID должен быть числом или '-'.",
                ),
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
                t(
                    "admin.clients.add.success",
                    "✅ Клиент '{name}' успешно создан!\n\nID: {id}\nEmail: {email}\nTelegram ID: {telegram_id}",
                    name=client.name,
                    id=client.id,
                    email=client.email,
                    telegram_id=client.telegram_id
                    or t("admin.clients.add.not_specified", "Не указан"),
                ),
                reply_markup=get_back_keyboard("admin_clients"),
            )
        except Exception as e:
            logger.error("Ошибка создания клиента: {}", e, exc_info=True)
            await session.rollback()
            await message.answer(
                t("admin.clients.add.error", "❌ Ошибка при создании клиента: {e}", e=str(e)),
                reply_markup=get_back_keyboard("admin_clients"),
            )
            await state.clear()


@router.callback_query(F.data.startswith("client_select_"))
async def select_client(callback: CallbackQuery, state: FSMContext) -> None:
    """Show client details and actions."""
    await state.clear()
    client_id = int(callback.data.split("_")[-1])

    async with async_session_factory() as session:
        service = ClientService(session)
        client = await service.get_client_by_id(client_id)

    if not client:
        await callback.answer(t("admin.clients.not_found", "❌ Клиент не найден."), show_alert=True)
        return

    status = (
        t("admin.clients.details.active", "✅ Активен")
        if client.is_active
        else t("admin.clients.details.inactive", "❌ Неактивен")
    )
    admin_status = (
        t("admin.clients.details.admin", "✅ Админ")
        if client.is_admin
        else t("admin.clients.details.client", "👤 Клиент")
    )

    text = t(
        "admin.clients.details.text",
        "👤 Клиент: {name}\n\nID: {id}\nEmail: {email}\nTelegram ID: {telegram_id}\nСтатус: {status}\nРоль: {admin_status}\nПодписок: {sub_count}\nСоздан: {created_at}",
        name=client.name,
        id=client.id,
        email=client.email,
        telegram_id=client.telegram_id or t("admin.clients.add.not_specified", "Не указан"),
        status=status,
        admin_status=admin_status,
        sub_count=len(client.subscriptions),
        created_at=client.created_at.strftime("%d.%m.%Y %H:%M"),
    )
    if client.notes:
        text += t("admin.clients.details.notes", "\n📝 Заметки: {notes}", notes=client.notes)

    kb = InlineKeyboardBuilder()
    kb.button(
        text=t("admin.clients.btn.subscriptions", "📝 Подписки клиента"),
        callback_data=f"client_subscriptions_{client_id}",
    )
    kb.button(
        text=t("admin.clients.btn.create_from_template", "📋 Создать подписку по шаблону"),
        callback_data=f"client_create_from_template_{client_id}",
    )
    kb.button(
        text=t("admin.clients.btn.edit_notes", "📝 Изменить заметки"),
        callback_data=f"client_edit_notes_{client_id}",
    )
    kb.button(
        text=t("admin.clients.btn.rename_name", "✏️ Изменить имя"),
        callback_data=f"client_rename_name_{client_id}",
    )
    kb.button(
        text=t("admin.clients.btn.rename_telegram", "📱 Изменить Telegram ID"),
        callback_data=f"client_rename_telegram_{client_id}",
    )
    if client.is_admin:
        kb.button(
            text=t("admin.clients.btn.unadmin", "⬇️ Снять админа"),
            callback_data=f"client_unadmin_{client_id}",
        )
    else:
        kb.button(
            text=t("admin.clients.btn.make_admin", "⬆️ Сделать админом"),
            callback_data=f"client_make_admin_{client_id}",
        )
    if client.is_active:
        kb.button(
            text=t("admin.clients.btn.disable", "❌ Отключить"),
            callback_data=f"client_disable_{client_id}",
        )
    else:
        kb.button(
            text=t("admin.clients.btn.enable", "✅ Включить"),
            callback_data=f"client_enable_{client_id}",
        )
    kb.button(
        text=t("admin.clients.btn.delete", "🗑️ Удалить"), callback_data=f"client_delete_{client_id}"
    )
    kb.button(text=t("admin.clients.btn.back", "🔙 Назад"), callback_data="admin_clients")
    kb.adjust(1)

    with contextlib.suppress(Exception):
        await callback.message.edit_text(text, reply_markup=kb.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("client_subscriptions_"))
async def show_client_subscriptions(
    callback: CallbackQuery, state: FSMContext
) -> None:
    """Show client subscriptions."""
    await state.clear()

    # Parse client_id and page
    parts = callback.data.split("_")

    # Format can be: client_subscriptions_123 or client_subscriptions_p_0_123
    page = 0
    if "_p_" in callback.data:
        p_index = parts.index("p")
        page = int(parts[p_index + 1])
        client_id = int(parts[-1])
    else:
        client_id = int(parts[-1])

    from app.services.new_subscription_service import NewSubscriptionService

    async with async_session_factory() as session:
        service = NewSubscriptionService(session)
        subscriptions = await service.get_client_subscriptions(client_id)

    if not subscriptions:
        text = t(
            "admin.clients.subscriptions.empty",
            "📝 У клиента нет подписок.\n\nНажмите '➕ Создать подписку' для добавления первой подписки.",
        )
    else:
        per_page = 5
        total_count = len(subscriptions)
        total_pages = max(1, -(-total_count // per_page))

        if page < 0:
            page = 0
        elif page >= total_pages:
            page = total_pages - 1

        start_idx = page * per_page
        end_idx = start_idx + per_page
        current_subs = subscriptions[start_idx:end_idx]

        if total_pages > 1:
            text = t(
                "admin.clients.subscriptions.title_paginated",
                "📝 Подписки клиента ({count}) | Страница {current} из {total}:\n\n",
                count=total_count,
                current=page + 1,
                total=total_pages
            )
        else:
            text = t(
                "admin.clients.subscriptions.title",
                "📝 Подписки клиента ({count}):\n\n",
                count=total_count
            )

    kb = InlineKeyboardBuilder()

    if subscriptions:
        for sub in current_subs:
            status = "✅" if sub.is_active else "❌"
            expiry = (
                sub.expiry_date.strftime("%d.%m.%Y")
                if sub.expiry_date
                else t("admin.clients.subscriptions.no_expiry", "Бессрочно")
            )
            traffic = (
                t("admin.clients.subscriptions.unlimited", "Безлимит")
                if sub.is_unlimited
                else f"{sub.total_gb} GB"
            )

            text += t(
                "admin.clients.subscriptions.item",
                "{status} <b>{name}</b>\n   Трафик: {traffic}\n   Срок: {expiry}\n   Подключений: {conn_count}\n\n",
                status=status,
                name=sub.name,
                traffic=traffic,
                expiry=expiry,
                conn_count=len(sub.inbound_connections),
            )

            # Add button for each subscription
            kb.row(InlineKeyboardButton(text=f"📝 {sub.name}", callback_data=f"client_sub_detail_{sub.id}"))

        if 'total_pages' in locals() and total_pages > 1:
            pagination_row = []
            if page > 0:
                pagination_row.append(
                    InlineKeyboardButton(
                        text=t(
                            "keyboards.pagination.prev",
                            "⬅️ Назад ({page}/{total_pages})",
                            page=page,
                            total_pages=total_pages
                        ),
                        callback_data=f"client_subscriptions_p_{page - 1}_{client_id}",
                    )
                )
            pagination_row.append(
                InlineKeyboardButton(
                    text=t(
                        "keyboards.pagination.current",
                        "📄 {current}/{total}",
                        current=page + 1,
                        total=total_pages
                    ),
                    callback_data="instruction_page_current",
                )
            )
            if page < total_pages - 1:
                pagination_row.append(
                    InlineKeyboardButton(
                        text=t(
                            "keyboards.pagination.next",
                            "Вперед ➡️ ({next_page}/{total_pages})",
                            next_page=page + 2,
                            total_pages=total_pages
                        ),
                        callback_data=f"client_subscriptions_p_{page + 1}_{client_id}",
                    )
                )
            kb.row(*pagination_row)

    kb.row(InlineKeyboardButton(
        text=t("admin.clients.btn.create_subscription", "➕ Создать подписку"),
        callback_data=f"client_create_subscription_{client_id}",
    ))
    kb.row(InlineKeyboardButton(
        text=t("admin.clients.btn.back", "🔙 Назад"), callback_data=f"client_select_{client_id}"
    ))

    try:
        await callback.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    except Exception as e:
        logger.warning("Не удалось отредактировать сообщение в show_client_subscriptions: {}", e)
        # Try to edit reply_markup only as fallback
        try:
            await callback.message.edit_reply_markup(reply_markup=kb.as_markup())
        except Exception as e2:
            logger.error("Не удалось отредактировать reply_markup: {}", e2)
    await callback.answer()


@router.callback_query(F.data.startswith("client_create_subscription_"))
async def start_create_subscription_for_client(
    callback: CallbackQuery, state: FSMContext
) -> None:
    """Start creating subscription for specific client."""
    client_id = int(callback.data.split("_")[-1])
    await state.update_data(client_id=client_id)

    from app.services.xui_service import XUIService

    async with async_session_factory() as session:
        service = XUIService(session)
        servers = await service.get_active_servers()

    if not servers:
        await callback.answer(
            t("admin.clients.servers.no_active", "❌ Нет активных серверов."), show_alert=True
        )
        return

    await state.set_state(SubscriptionManagement.waiting_for_server_selection)
    with contextlib.suppress(Exception):
        await callback.message.edit_text(
            t("admin.clients.servers.select", "Выберите сервер:"),
            reply_markup=get_servers_keyboard(
                servers, action="sub_select", back_target=f"client_subscriptions_{client_id}"
            ),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("client_create_from_template_"))
async def start_create_subscription_from_template(
    callback: CallbackQuery, state: FSMContext
) -> None:
    """Start creating subscription from template for specific client."""
    client_id = int(callback.data.split("_")[-1])
    await state.update_data(client_id=client_id)

    async with async_session_factory() as session:
        template_service = SubscriptionTemplateService(session)
        templates = await template_service.get_all_templates()

    if not templates:
        await callback.answer(
            t(
                "admin.clients.templates.empty",
                "❌ Нет доступных шаблонов. Сначала создайте шаблон.",
            ),
            show_alert=True,
        )
        return

    await state.set_state(TemplateManagement.waiting_for_template_selection)

    text = t(
        "admin.clients.templates.title",
        "📋 <b>Создание подписки по шаблону</b>\n\nВсего шаблонов: {count}\n\nВыберите шаблон:",
        count=len(templates),
    )

    builder = InlineKeyboardBuilder()
    for template in templates:
        status = "✅" if template.is_active else "❌"
        inbounds_count = len(template.template_inbounds)
        builder.button(
            text=t(
                "admin.clients.templates.btn",
                "{status} {name} ({count} подключений)",
                status=status,
                name=template.name,
                count=inbounds_count,
            ),
            callback_data=f"template_for_client_{template.id}",
        )
    builder.button(
        text=t("admin.clients.btn.back", "🔙 Назад"), callback_data=f"client_select_{client_id}"
    )
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

    text = t(
        "admin.clients.templates.create",
        "📋 <b>Создание подписки из шаблона</b>\n\n📋 <b>Шаблон:</b> {template_name}\n👤 <b>Клиент:</b> {client_name}\n🔌 <b>Подключений:</b> {conn_count}\n\nВведите название подписки:",
        template_name=template.name,
        client_name=client.name,
        conn_count=len(template.template_inbounds),
    )

    await callback.message.edit_text(text)
    await callback.answer()


@router.callback_query(F.data.startswith("client_rename_name_"))
async def start_rename_client_name(
    callback: CallbackQuery, state: FSMContext
) -> None:
    """Start renaming client name."""
    client_id = int(callback.data.split("_")[-1])
    await state.update_data(client_id=client_id)
    await state.set_state(ClientManagement.waiting_for_new_name)

    with contextlib.suppress(Exception):
        await callback.message.edit_text(
            t("admin.clients.rename.title", "✏️ Изменение имени клиента\n\nВведите новое имя:"),
            reply_markup=get_back_keyboard(f"client_select_{client_id}"),
        )
    await callback.answer()


@router.message(ClientManagement.waiting_for_new_name)
async def process_rename_client_name(message: Message, state: FSMContext) -> None:
    """Process client rename."""
    data = await state.get_data()
    client_id = data["client_id"]
    name = message.text.strip()

    if not name:
        await message.answer(t("admin.clients.add.empty_name", "❌ Имя не может быть пустым."))
        return

    if len(name) > 100:
        await message.answer(
            t("admin.clients.add.name_too_long", "❌ Имя не должно превышать 100 символов.")
        )
        return

    async with async_session_factory() as session:
        service = ClientService(session)
        client = await service.rename_client(client_id, name)
        await session.commit()
    await state.clear()
    await message.answer(
        t("admin.clients.rename.success", "✅ Клиент переименован в '{name}'", name=client.name),
        reply_markup=get_back_keyboard(f"client_select_{client_id}"),
    )


@router.callback_query(F.data.startswith("client_rename_telegram_"))
async def start_rename_client_telegram(
    callback: CallbackQuery, state: FSMContext
) -> None:
    """Start changing client Telegram ID."""
    client_id = int(callback.data.split("_")[-1])
    await state.update_data(client_id=client_id)
    await state.set_state(ClientManagement.waiting_for_new_telegram_id)

    with contextlib.suppress(Exception):
        await callback.message.edit_text(
            t(
                "admin.clients.rename_telegram.title",
                "📱 Изменение Telegram ID\n\nВведите новый Telegram ID (или '-' для удаления):",
            ),
            reply_markup=get_back_keyboard(f"client_select_{client_id}"),
        )
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
            await message.answer(
                t(
                    "admin.clients.add.invalid_telegram",
                    "❌ Telegram ID должен быть числом или '-'.",
                )
            )
            return
    elif telegram_id_input == "-":
        telegram_id = None

    async with async_session_factory() as session:
        service = ClientService(session)
        await service.update_client(
            client_id,
            telegram_id=telegram_id,
        )
        await session.commit()
    await state.clear()
    if telegram_id:
        await message.answer(
            t(
                "admin.clients.rename_telegram.success",
                "✅ Telegram ID изменен на {id}",
                id=telegram_id,
            ),
            reply_markup=get_back_keyboard(f"client_select_{client_id}"),
        )
    else:
        await message.answer(
            t("admin.clients.rename_telegram.removed", "✅ Telegram ID удален"),
            reply_markup=get_back_keyboard(f"client_select_{client_id}"),
        )


@router.callback_query(F.data.startswith("client_enable_"))
async def enable_client(callback: CallbackQuery) -> None:
    """Enable client."""
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

            await callback.answer(
                t(
                    "admin.clients.enable.success",
                    "✅ Клиент включен. Активировано {count} подключений в XUI.",
                    count=toggled,
                )
            )
            await select_client(callback, state=None)  # type: ignore
        except Exception:
            await session.rollback()
            raise
        finally:
            await sub_service.close_all_clients()


@router.callback_query(F.data.startswith("client_disable_"))
async def disable_client(callback: CallbackQuery) -> None:
    """Disable client."""
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
                t(
                    "admin.clients.disable.success",
                    "✅ Клиент отключен. Деактивировано {count} подключений в XUI.",
                    count=toggled,
                )
            )
            await select_client(callback, state=None)  # type: ignore
        except Exception:
            await session.rollback()
            raise
        finally:
            await sub_service.close_all_clients()


# ==================== CLIENT NOTES ====================


@router.callback_query(F.data.startswith("client_edit_notes_"))
async def start_edit_client_notes(
    callback: CallbackQuery, state: FSMContext
) -> None:
    """Start editing client notes."""
    client_id = int(callback.data.split("_")[-1])
    await state.update_data(client_id=client_id)
    await state.set_state(ClientManagement.waiting_for_notes)

    with contextlib.suppress(Exception):
        await callback.message.edit_text(
            t(
                "admin.clients.notes.title",
                "📝 Изменение заметок клиента\n\nВведите новые заметки (для удаления отправьте `-`):",
            ),
            reply_markup=get_back_keyboard(f"client_select_{client_id}"),
        )
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
        t("admin.clients.notes.success", "✅ Заметки клиента обновлены."),
        reply_markup=get_back_keyboard(f"client_select_{client_id}"),
    )


@router.callback_query(F.data.startswith("client_delete_"))
async def confirm_delete_client(callback: CallbackQuery, state: FSMContext) -> None:
    """Confirm client deletion."""
    client_id = int(callback.data.split("_")[-1])
    await state.update_data(client_id=client_id)
    await state.set_state(ClientManagement.confirm_delete)

    with contextlib.suppress(Exception):
        await callback.message.edit_text(
            t(
                "admin.clients.delete.confirm",
                "⚠️ Вы уверены, что хотите удалить этого клиента?\n\nВсе его подписки и подключения будут также удалены!",
            ),
            reply_markup=get_confirm_keyboard(f"client_delete_{client_id}", "admin_clients"),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("confirm_client_delete_"))
async def delete_client(callback: CallbackQuery, state: FSMContext) -> None:
    """Delete client."""
    await callback.answer()
    await callback.message.edit_text(
        "⏳ Удаление клиента, пожалуйста подождите...", reply_markup=None
    )

    data = await state.get_data()
    client_id = data["client_id"]

    async with async_session_factory() as session:
        from app.services.new_subscription_service import NewSubscriptionService

        client_service = ClientService(session)
        sub_service = NewSubscriptionService(session)

        try:
            from sqlalchemy import select
            from sqlalchemy.orm import selectinload

            from app.database.models import Inbound, InboundConnection, Server, Subscription

            result = await sub_service.session.execute(
                select(Subscription)
                .where(Subscription.client_id == client_id)
                .options(
                    selectinload(Subscription.inbound_connections)
                    .selectinload(InboundConnection.inbound)
                    .selectinload(Inbound.server)
                    .selectinload(Server.xui_panel),
                    selectinload(Subscription.inbound_connections)
                    .selectinload(InboundConnection.inbound)
                    .selectinload(Inbound.server)
                    .selectinload(Server.awg_service),
                    selectinload(Subscription.inbound_connections)
                    .selectinload(InboundConnection.inbound)
                    .selectinload(Inbound.server)
                    .selectinload(Server.mtproxy_service),
                )
            )
            subscriptions_before = result.scalars().all()
            connections_to_cleanup = []
            for sub in subscriptions_before:
                for conn in sub.inbound_connections:
                    connections_to_cleanup.append(conn)

            await client_service.delete_client(client_id)
            await session.commit()

            deleted_count = 0
            for conn in connections_to_cleanup:
                try:
                    inbound = conn.inbound
                    server = inbound.server
                    provider = await sub_service._get_provider(server, inbound=inbound)
                    await provider.remove_client(inbound, conn)
                    deleted_count += 1
                except Exception as e:
                    logger.warning("Не удалось удалить VPN-подключение {}: {}", conn.id, e)

            await state.clear()
            await callback.answer(
                t(
                    "admin.clients.delete.success",
                    "✅ Клиент удален. Удалено {count} подключений из XUI.",
                    count=deleted_count,
                )
            )
            await show_clients(callback, state)
        except Exception:
            await session.rollback()
            raise
        finally:
            await sub_service.close_all_clients()


@router.callback_query(F.data.startswith("client_make_admin_"))
async def make_admin(callback: CallbackQuery) -> None:
    """Make client admin."""
    client_id = int(callback.data.split("_")[-1])

    async with async_session_factory() as session:
        service = ClientService(session)
        await service.set_client_admin(client_id, True)
        await session.commit()

    await callback.answer(t("admin.clients.admin.made", "✅ Клиент теперь админ."))
    await select_client(callback, state=None)  # type: ignore


@router.callback_query(F.data.startswith("client_unadmin_"))
async def unmake_admin(callback: CallbackQuery) -> None:
    """Remove admin status from client."""
    client_id = int(callback.data.split("_")[-1])

    async with async_session_factory() as session:
        service = ClientService(session)
        await service.set_client_admin(client_id, False)
        await session.commit()

    await callback.answer(t("admin.clients.admin.removed", "✅ Клиент больше не админ."))
    await select_client(callback, state=None)  # type: ignore


# ==================== CLIENT LIST (PAGINATED) ====================


@router.callback_query(F.data == "clients_list")
async def show_clients_list(callback: CallbackQuery) -> None:
    """Show paginated list of all active clients (first page)."""
    await _render_clients_page(callback, page=0)


@router.callback_query(F.data.startswith("clients_page_"))
async def navigate_clients_page(callback: CallbackQuery) -> None:
    """Navigate between client list pages."""
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
        with contextlib.suppress(Exception):
            await callback.message.edit_text(
                t(
                    "admin.clients.list.empty",
                    "👥 Список клиентов пуст.\n\nНажмите '➕ Добавить клиента' для создания первого клиента.",
                ),
                reply_markup=get_back_keyboard("admin_clients"),
            )
        await callback.answer()
        return

    total_pages = max(1, -(-total_count // per_page))
    text = t(
        "admin.clients.list.title",
        "👥 <b>Список клиентов</b> (страница {page}/{total})\nВсего активных: {count}\n\n",
        page=page + 1,
        total=total_pages,
        count=total_count,
    )

    for client in clients:
        status = "✅" if client.is_active else "❌"
        admin_badge = "🛡️" if client.is_admin else "👤"
        text += f"{admin_badge} {status} <b>{client.name}</b> (ID: {client.id})\n"
        if client.telegram_id:
            text += f"   📱 Telegram: {client.telegram_id}\n"
        text += f"   📧 {client.email}\n"
        text += t(
            "admin.clients.list.subs",
            "   📝 Подписок: {count}\n\n",
            count=len(client.subscriptions),
        )

    keyboard = get_clients_page_keyboard(clients, page, total_count, per_page)

    with contextlib.suppress(Exception):
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


# ==================== CLIENT SEARCH HANDLERS ====================


@router.callback_query(F.data == "client_search")
async def start_client_search(callback: CallbackQuery, state: FSMContext) -> None:
    """Start client search flow."""
    with contextlib.suppress(Exception):
        await callback.message.edit_text(
            t("admin.clients.search.title", "🔍 Поиск клиентов\n\nВыберите критерий поиска:"),
            reply_markup=get_client_search_keyboard(),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("search_field_"))
async def select_search_field(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle search field selection."""
    # Extract field from callback data: "search_field_<field>"
    # e.g. "search_field_name" -> "name", "search_field_xui_email" -> "xui_email"
    field = callback.data.removeprefix("search_field_")
    await state.update_data(search_field=field)
    await state.set_state(ClientManagement.waiting_for_search_query)

    field_messages = {
        "name": t(
            "admin.clients.search.prompt.name", "Введите имя клиента (частичное совпадение):"
        ),
        "email": t(
            "admin.clients.search.prompt.email", "Введите email клиента (частичное совпадение):"
        ),
        "telegram": t(
            "admin.clients.search.prompt.telegram",
            "Введите Telegram ID (цифры) или @username клиента:",
        ),
        "xui_email": t(
            "admin.clients.search.prompt.xui_email",
            "Введите email из XUI inbound (частичное совпадение):",
        ),
        "all": t(
            "admin.clients.search.prompt.all",
            "Введите поисковый запрос (проверит ВСЕ поля одновременно):\n• Имя\n• Email клиента\n• Telegram ID\n• Email из XUI inbound",
        ),
    }

    with contextlib.suppress(Exception):
        await callback.message.edit_text(
            f"🔍 {field_messages.get(field, t('admin.clients.search.prompt.default', 'Введите поисковый запрос:'))}",
            reply_markup=get_back_keyboard("client_search"),
        )
    await callback.answer()


@router.message(ClientManagement.waiting_for_search_query)
async def process_search_query(message: Message, state: FSMContext) -> None:
    """Process search query and display results."""
    from app.services.client_service import _normalize_search_query

    data = await state.get_data()
    field = data.get("search_field", "all")
    query = message.text.strip()

    if not query:
        await message.answer(
            t("admin.clients.search.empty", "❌ Поисковый запрос не может быть пустым.")
        )
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
                t(
                    "admin.clients.search.no_results_all",
                    "🔍 Поиск не дал результатов.\n\nКомплексный поиск проверяет все поля:\n• Имя клиента\n• Email клиента\n• Telegram ID\n• XUI email (из inbound подключений)\n\nПопробуйте изменить поисковый запрос.",
                ),
                reply_markup=get_back_keyboard("client_search"),
            )
        else:
            text = t(
                "admin.clients.search.results_all",
                "🔍 Результаты поиска по всем полям ({count}):\n\n",
                count=len(clients),
            )
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
            t(
                "admin.clients.search.no_results",
                "🔍 Поиск не дал результатов.\n\nСоветы:\n• Для поиска по имени можно использовать несколько слов\n• Для поиска по email используйте символ @\n• Для Telegram ID используйте только цифры",
            ),
            reply_markup=get_back_keyboard("client_search"),
        )
    else:
        text = t(
            "admin.clients.search.results",
            "🔍 Результаты поиска ({count}):\n\n",
            count=len(clients),
        )
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
