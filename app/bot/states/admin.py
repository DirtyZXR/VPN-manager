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


class SubscriptionManagement(StatesGroup):
    """Subscription management states."""

    # Select user
    waiting_for_user_selection = State()

    # Select server
    waiting_for_server_selection = State()

    # Select inbound
    waiting_for_inbound_selection = State()

    # Select or create group
    waiting_for_group_action = State()
    waiting_for_new_group_name = State()

    # Profile parameters
    waiting_for_traffic_limit = State()
    waiting_for_expiry_days = State()
    confirm_creation = State()

    # Profile management
    waiting_for_profile_action = State()
    confirm_profile_delete = State()


class ExportData(StatesGroup):
    """Export data states."""

    waiting_for_format = State()
