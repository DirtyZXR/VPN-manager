"""Inline keyboards for bot."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def get_main_menu_keyboard(is_admin: bool) -> InlineKeyboardMarkup:
    """Get main menu keyboard.

    Args:
        is_admin: Whether client is admin

    Returns:
        Inline keyboard markup
    """
    builder = InlineKeyboardBuilder()

    builder.button(text="Мои подписки", callback_data="my_subscriptions")
    builder.button(text="Все subscription URLs", callback_data="all_sub_urls")

    if is_admin:
        builder.button(text="Управление серверами", callback_data="admin_servers")
        builder.button(text="Управление клиентами", callback_data="admin_clients")
        builder.button(text="🔄 Синхронизация", callback_data="admin_sync")
        builder.button(text="Экспорт БД", callback_data="admin_export")

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
    builder.button(text="Назад", callback_data="admin_menu")
    builder.adjust(1)
    return builder.as_markup()