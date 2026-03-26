"""Keyboards package."""

from app.bot.keyboards.inline import (
    get_back_keyboard,
    get_clients_keyboard,
    get_client_search_keyboard,
    get_confirm_keyboard,
    get_inbounds_keyboard,
    get_main_menu_keyboard,
    get_registration_keyboard,
    get_servers_keyboard,
    get_user_actions_keyboard,
    get_users_keyboard,
)

__all__ = [
    "get_main_menu_keyboard",
    "get_servers_keyboard",
    "get_clients_keyboard",
    "get_client_search_keyboard",
    "get_users_keyboard",
    "get_inbounds_keyboard",
    "get_confirm_keyboard",
    "get_user_actions_keyboard",
    "get_back_keyboard",
    "get_registration_keyboard",
]