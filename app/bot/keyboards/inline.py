"""Inline keyboards for bot."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def get_main_menu_keyboard(is_admin: bool, is_registered: bool = True) -> InlineKeyboardMarkup:
    """Get main menu keyboard.

    Args:
        is_admin: Whether client is admin
        is_registered: Whether client is registered (default: True)

    Returns:
        Inline keyboard markup
    """
    builder = InlineKeyboardBuilder()

    if is_registered:
        builder.button(text="Мои подписки", callback_data="my_subscriptions")
        builder.button(text="Все subscription URLs", callback_data="all_sub_urls")

        if is_admin:
            builder.button(text="Управление серверами", callback_data="admin_servers")
            builder.button(text="Управление клиентами", callback_data="admin_clients")
            builder.button(text="📋 Шаблоны подписок", callback_data="admin_templates")
            builder.button(text="🔄 Синхронизация", callback_data="admin_sync")
            builder.button(text="Экспорт БД", callback_data="admin_export")
    else:
        builder.button(text="📝 Регистрация", callback_data="start_registration")

    builder.adjust(2)
    return builder.as_markup()


def get_servers_keyboard(servers: list, action: str = "select") -> InlineKeyboardMarkup:
    """Get servers list keyboard.

    Args:
        servers: List of Server objects
        action: Action prefix for callback data

    Returns:
        Inline keyboard markup
    """
    builder = InlineKeyboardBuilder()

    for server in servers:
        status = "Активен" if server.is_active else "Неактивен"
        builder.button(
            text=f"{status} {server.name}",
            callback_data=f"server_{action}_{server.id}",
        )

    builder.button(text="Добавить сервер", callback_data="server_add")
    builder.button(text="Назад", callback_data="admin_menu")
    builder.adjust(1)
    return builder.as_markup()


def get_users_keyboard(users: list) -> InlineKeyboardMarkup:
    """Get users list keyboard.

    Args:
        users: List of User objects

    Returns:
        Inline keyboard markup
    """
    builder = InlineKeyboardBuilder()

    for user in users:
        status = "Активен" if user.is_active else "Неактивен"
        admin_badge = "Админ" if user.is_admin else ""
        builder.button(
            text=f"{status} {admin_badge} {user.name}",
            callback_data=f"user_select_{user.id}",
        )

    builder.button(text="Добавить пользователя", callback_data="user_add")
    builder.button(text="Назад", callback_data="admin_menu")
    builder.adjust(1)
    return builder.as_markup()


def get_inbounds_keyboard(inbounds: list) -> InlineKeyboardMarkup:
    """Get inbounds list keyboard.

    Args:
        inbounds: List of Inbound objects

    Returns:
        Inline keyboard markup
    """
    builder = InlineKeyboardBuilder()

    for inbound in inbounds:
        status = "Активен" if inbound.is_active else "Неактивен"
        builder.button(
            text=f"{status} {inbound.remark} ({inbound.protocol})",
            callback_data=f"inbound_select_{inbound.id}",
        )

    builder.button(text="Назад", callback_data="admin_menu")
    builder.adjust(1)
    return builder.as_markup()


def get_confirm_keyboard(
    confirm_action: str,
    cancel_action: str = "cancel",
) -> InlineKeyboardMarkup:
    """Get confirmation keyboard.

    Args:
        confirm_action: Callback data for confirm button
        cancel_action: Callback data for cancel button

    Returns:
        Inline keyboard markup
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="Подтвердить", callback_data=f"confirm_{confirm_action}")
    builder.button(text="Отмена", callback_data=cancel_action)
    builder.adjust(2)
    return builder.as_markup()


def get_user_actions_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Get user actions keyboard.

    Args:
        user_id: User ID

    Returns:
        Inline keyboard markup
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="Переименовать", callback_data=f"user_rename_{user_id}")
    builder.button(text="Включить", callback_data=f"user_enable_{user_id}")
    builder.button(text="Отключить", callback_data=f"user_disable_{user_id}")
    builder.button(text="Удалить", callback_data=f"user_delete_{user_id}")
    builder.button(text="Назад", callback_data="admin_users")
    builder.adjust(2)
    return builder.as_markup()


def get_back_keyboard(callback_data: str = "admin_menu") -> InlineKeyboardMarkup:
    """Get back button keyboard.

    Args:
        callback_data: Callback data for back button

    Returns:
        Inline keyboard markup
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="Назад", callback_data=callback_data)
    return builder.as_markup()


def get_clients_keyboard(clients: list) -> InlineKeyboardMarkup:
    """Get clients list keyboard.

    Args:
        clients: List of Client objects

    Returns:
        Inline keyboard markup
    """
    builder = InlineKeyboardBuilder()

    for client in clients:
        status = "Активен" if client.is_active else "Неактивен"
        admin_badge = "Админ" if client.is_admin else ""
        builder.button(
            text=f"{status} {admin_badge} {client.name}",
            callback_data=f"client_select_{client.id}",
        )

    builder.button(text="Добавить клиента", callback_data="client_add")
    builder.button(text="Поиск клиентов", callback_data="client_search")
    builder.button(text="Назад", callback_data="admin_menu")
    builder.adjust(1)
    return builder.as_markup()


def get_client_search_keyboard() -> InlineKeyboardMarkup:
    """Get client search options keyboard.

    Returns:
        Inline keyboard markup with search field options
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="👤 По имени", callback_data="search_field_name")
    builder.button(text="📧 По email", callback_data="search_field_email")
    builder.button(text="📱 По Telegram ID", callback_data="search_field_telegram_id")
    builder.button(text="🔗 По XUI email", callback_data="search_field_xui_email")
    builder.button(text="🔍 Комплексный поиск", callback_data="search_field_all")
    builder.button(text="Назад", callback_data="admin_clients")
    builder.adjust(2)
    return builder.as_markup()


def get_registration_keyboard() -> InlineKeyboardMarkup:
    """Get registration method selection keyboard.

    Returns:
        Inline keyboard markup with registration options
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="✏️ Ввести имя", callback_data="reg_enter_name")
    builder.button(text="📱 Использовать Telegram", callback_data="reg_use_telegram")
    builder.button(text="❌ Отмена", callback_data="cancel")
    builder.adjust(2)
    return builder.as_markup()


def get_templates_keyboard(templates: list) -> InlineKeyboardMarkup:
    """Get templates list keyboard.

    Args:
        templates: List of SubscriptionTemplate objects

    Returns:
        Inline keyboard markup
    """
    builder = InlineKeyboardBuilder()

    for template in templates:
        status = "Активен" if template.is_active else "Неактивен"
        builder.button(
            text=f"{status} {template.name}",
            callback_data=f"template_select_{template.id}",
        )

    builder.button(text="➕ Создать шаблон", callback_data="template_add")
    builder.button(text="Назад", callback_data="admin_menu")
    builder.adjust(1)
    return builder.as_markup()


def get_template_actions_keyboard(template_id: int) -> InlineKeyboardMarkup:
    """Get template actions keyboard.

    Args:
        template_id: Template ID

    Returns:
        Inline keyboard markup with 4 buttons: Edit, Add Inbound, Delete, Back
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="✏️ Изменить", callback_data=f"template_edit_menu_{template_id}")
    builder.button(text="➕ Добавить подключение", callback_data=f"template_add_inbound_{template_id}")
    builder.button(text="❌ Удалить", callback_data=f"template_delete_{template_id}")
    builder.button(text="🔙 Назад", callback_data="admin_templates")
    builder.adjust(2)
    return builder.as_markup()


def get_template_edit_menu_keyboard(template_id: int) -> InlineKeyboardMarkup:
    """Get template edit menu keyboard with field selection options.

    Args:
        template_id: Template ID

    Returns:
        Inline keyboard markup with edit field options
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="📝 Название", callback_data=f"template_edit_name_{template_id}")
    builder.button(text="📝 Описание", callback_data=f"template_edit_description_{template_id}")
    builder.button(text="📊 Трафик", callback_data=f"template_edit_traffic_{template_id}")
    builder.button(text="📅 Срок действия", callback_data=f"template_edit_expiry_{template_id}")
    builder.button(text="📌 Заметки", callback_data=f"template_edit_notes_{template_id}")
    builder.button(text="🔙 Назад", callback_data=f"template_select_{template_id}")
    builder.adjust(2)
    return builder.as_markup()


def get_template_inbounds_keyboard(
    template_id: int,
    template_inbounds: list,
    available_inbounds: list
) -> InlineKeyboardMarkup:
    """Get template inbounds management keyboard.

    Args:
        template_id: Template ID
        template_inbounds: List of current template inbounds
        available_inbounds: List of available inbounds to add

    Returns:
        Inline keyboard markup
    """
    builder = InlineKeyboardBuilder()

    # Current inbounds
    if template_inbounds:
        for ti in template_inbounds:
            status = "✅" if ti.inbound.is_active else "❌"
            builder.button(
                text=f"{status} {ti.inbound.remark} ({ti.inbound.server.name})",
                callback_data=f"template_inbound_remove_{template_id}_{ti.inbound_id}",
            )
    else:
        builder.button(text="Нет подключений", callback_data="template_no_inbounds")

    # Add inbound button
    builder.button(text="➕ Добавить подключение", callback_data=f"template_add_inbound_{template_id}")
    builder.button(text="Назад", callback_data=f"template_select_{template_id}")
    builder.adjust(1)
    return builder.as_markup()


def get_inbound_selection_for_template(
    template_id: int,
    inbounds: list
) -> InlineKeyboardMarkup:
    """Get inbound selection keyboard for template.

    Args:
        template_id: Template ID
        inbounds: List of available inbounds

    Returns:
        Inline keyboard markup
    """
    builder = InlineKeyboardBuilder()

    # Group inbounds by server
    from collections import defaultdict
    inbounds_by_server = defaultdict(list)
    for inbound in inbounds:
        inbounds_by_server[inbound.server.name].append(inbound)

    for server_name, server_inbounds in sorted(inbounds_by_server.items()):
        for inbound in server_inbounds:
            status = "✅" if inbound.is_active else "❌"
            builder.button(
                text=f"{status} {inbound.remark} ({server_name})",
                callback_data=f"template_select_inbound_{template_id}_{inbound.id}",
            )

    builder.button(text="Назад", callback_data=f"template_select_{template_id}")
    builder.adjust(1)
    return builder.as_markup()

