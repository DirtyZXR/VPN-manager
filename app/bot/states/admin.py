"""FSM states for admin flows."""

from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup


class ServerManagement(StatesGroup):
    """Server management states."""

    waiting_for_name = State()
    waiting_for_url = State()
    waiting_for_username = State()
    waiting_for_password = State()
    confirm_delete = State()


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


class SubscriptionManagement(StatesGroup):
    """Subscription management states."""

    # Select client
    waiting_for_client_selection = State()

    # Select server
    waiting_for_server_selection = State()

    # Select inbound (multiple selection)
    waiting_for_inbound_selection = State()

    # Subscription parameters
    waiting_for_subscription_name = State()
    waiting_for_traffic_limit = State()
    waiting_for_expiry_days = State()
    confirm_creation = State()


class ExportData(StatesGroup):
    """Export data states."""

    waiting_for_format = State()
