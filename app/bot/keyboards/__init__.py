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
    get_template_actions_keyboard,
    get_template_edit_menu_keyboard,
    get_template_inbounds_keyboard,
    get_template_inbounds_multi_select_keyboard,
    get_templates_keyboard,
    get_inbound_selection_for_template,
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
    "get_templates_keyboard",
    "get_template_actions_keyboard",
    "get_template_edit_menu_keyboard",
    "get_template_inbounds_keyboard",
    "get_template_inbounds_multi_select_keyboard",
    "get_inbound_selection_for_template",
]