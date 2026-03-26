"""FSM states for admin flows."""

from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup


class ServerManagement(StatesGroup):
    """Server management states."""

    waiting_for_name = State()
    waiting_for_base_url = State()
    waiting_for_panel_path = State()
    waiting_for_subscription_path = State()
    waiting_for_subscription_json_path = State()
    waiting_for_username = State()
    waiting_for_password = State()
    waiting_for_verify_ssl = State()
    confirm_delete = State()

    # Server editing states
    waiting_for_edit_name = State()
    waiting_for_edit_base_url = State()
    waiting_for_edit_panel_path = State()
    waiting_for_edit_subscription_path = State()
    waiting_for_edit_subscription_json_path = State()
    waiting_for_edit_username = State()
    waiting_for_edit_password = State()
    waiting_for_edit_verify_ssl = State()


class UserManagement(StatesGroup):
    """User management states."""

    waiting_for_name = State()
    waiting_for_telegram_id = State()
    confirm_delete = State()
    waiting_for_new_name = State()


class ClientManagement(StatesGroup):
    """Client management states."""

    waiting_for_name = State()
    waiting_for_email = State()
    waiting_for_telegram_id = State()
    waiting_for_telegram_username = State()
    waiting_for_new_name = State()
    waiting_for_new_telegram_id = State()
    confirm_delete = State()

    # Add inbound to subscription states
    waiting_for_inbound_server = State()
    waiting_for_inbound_selection = State()

    # Search states
    waiting_for_search_query = State()
    waiting_for_search_field = State()


class SubscriptionManagement(StatesGroup):
    """Subscription management states."""

    # Select client
    waiting_for_client_selection = State()

    # Select server
    waiting_for_server_selection = State()

    # Select inbound (multiple selection)
    waiting_for_inbound_selection = State()
    inbounds_multi_select_mode = State()  # Multi-selection mode
    inbounds_multi_confirm_action = State()  # Confirm multi-selection action

    # Subscription parameters (creation flow)
    waiting_for_subscription_name = State()
    waiting_for_traffic_limit = State()
    waiting_for_expiry_days = State()
    confirm_creation = State()

    # Subscription editing (separate states to avoid conflict with creation flow)
    editing_name = State()
    editing_traffic = State()
    editing_expiry = State()
    editing_notes = State()


class ExportData(StatesGroup):
    """Export data states."""

    waiting_for_format = State()


class TemplateManagement(StatesGroup):
    """Template management states."""

    # Template creation states
    waiting_for_template_name = State()
    waiting_for_template_description = State()
    waiting_for_default_traffic = State()
    waiting_for_default_expiry = State()
    waiting_for_template_notes = State()

    # Template editing states
    editing_template_name = State()
    editing_template_description = State()
    editing_default_traffic = State()
    editing_default_expiry = State()
    editing_template_notes = State()
    editing_template_menu = State()  # For showing edit menu

    # Template inbound management states
    waiting_for_inbound_selection = State()
    inbounds_multi_select_mode = State()  # Multi-select mode for template inbounds
    confirm_remove_inbounds = State()  # Confirm removing selected inbounds
    waiting_for_inbound_order = State()
    confirm_remove_inbound = State()

    # Template subscription creation states
    waiting_for_client_selection = State()
    waiting_for_template_selection = State()  # For creating subscription from template for specific client
    waiting_for_subscription_name = State()
    waiting_for_custom_traffic = State()
    waiting_for_custom_expiry = State()
    waiting_for_custom_notes = State()
    confirm_template_creation = State()
    waiting_for_search_query = State()  # For client search

    # Template deletion
    confirm_delete_template = State()
