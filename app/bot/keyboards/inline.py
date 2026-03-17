"""Inline keyboards for bot."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def get_main_menu_keyboard(is_admin: bool) -> InlineKeyboardMarkup:
    """Get main menu keyboard.

    Args:
        is_admin: Whether user is admin

    Returns:
        Inline keyboard markup
    """
    builder = InlineKeyboardBuilder()

    builder.button(text="📋 Мои подписки", callback_data="my_subscriptions")
    builder.button(text="🔗 Все subscription URLs", callback_data="all_sub_urls")

    if is_admin:
        builder.button(text="⚙️ Управление серверами", callback_data="admin_servers")
        builder.button(text="👥 Управление пользователями", callback_data="admin_users")
        builder.button(text="📝 Создать подписку", callback_data="admin_create_subscription")
        builder.button(text="📊 Экспорт БД", callback_data="admin_export")

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
        status = "✅" if server.is_active else "❌"
        builder.button(
            text=f"{status} {server.name}",
            callback_data=f"server_{action}_{server.id}",
        )

    builder.button(text="➕ Добавить сервер", callback_data="server_add")
    builder.button(text="🔙 Назад", callback_data="admin_menu")
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
        status = "✅" if user.is_active else "❌"
        admin_badge = "👑" if user.is_admin else ""
        builder.button(
            text=f"{status} {admin_badge} {user.name}",
            callback_data=f"user_select_{user.id}",
        )

    builder.button(text="➕ Добавить пользователя", callback_data="user_add")
    builder.button(text="🔙 Назад", callback_data="admin_menu")
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
        status = "✅" if inbound.is_active else "❌"
        builder.button(
            text=f"{status} {inbound.remark} ({inbound.protocol})",
            callback_data=f"inbound_select_{inbound.id}",
        )

    builder.button(text="🔙 Назад", callback_data="admin_menu")
    builder.adjust(1)
    return builder.as_markup()


def get_subscription_groups_keyboard(groups: list) -> InlineKeyboardMarkup:
    """Get subscription groups keyboard.

    Args:
        groups: List of SubscriptionGroup objects

    Returns:
        Inline keyboard markup
    """
    builder = InlineKeyboardBuilder()

    for group in groups:
        builder.button(
            text=f"📁 {group.name}",
            callback_data=f"group_select_{group.id}",
        )

    builder.button(text="➕ Новая группа", callback_data="group_new")
    builder.button(text="🔙 Назад", callback_data="admin_menu")
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
    builder.button(text="✅ Подтвердить", callback_data=f"confirm_{confirm_action}")
    builder.button(text="❌ Отмена", callback_data=cancel_action)
    builder.adjust(2)
    return builder.as_markup()


def get_profile_actions_keyboard(profile_id: int) -> InlineKeyboardMarkup:
    """Get profile actions keyboard.

    Args:
        profile_id: Profile ID

    Returns:
        Inline keyboard markup
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Включить", callback_data=f"profile_enable_{profile_id}")
    builder.button(text="❌ Отключить", callback_data=f"profile_disable_{profile_id}")
    builder.button(text="🗑️ Удалить", callback_data=f"profile_delete_{profile_id}")
    builder.button(text="🔙 Назад", callback_data="back")
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
    builder.button(text="✏️ Переименовать", callback_data=f"user_rename_{user_id}")
    builder.button(text="✅ Включить", callback_data=f"user_enable_{user_id}")
    builder.button(text="❌ Отключить", callback_data=f"user_disable_{user_id}")
    builder.button(text="🗑️ Удалить", callback_data=f"user_delete_{user_id}")
    builder.button(text="🔙 Назад", callback_data="admin_users")
    builder.adjust(2)
    return builder.as_markup()


def get_copy_keyboard(text: str, callback_data: str) -> InlineKeyboardMarkup:
    """Get keyboard with copy button.

    Args:
        text: Text to copy
        callback_data: Callback data for back button

    Returns:
        Inline keyboard markup
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="📋 Скопировать", copy_text=text)
    builder.button(text="🔙 Назад", callback_data=callback_data)
    builder.adjust(1)
    return builder.as_markup()


def get_back_keyboard(callback_data: str = "admin_menu") -> InlineKeyboardMarkup:
    """Get back button keyboard.

    Args:
        callback_data: Callback data for back button

    Returns:
        Inline keyboard markup
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data=callback_data)
    return builder.as_markup()
