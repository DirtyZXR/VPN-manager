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
