"""FSM states for user flows."""

from aiogram.fsm.state import State, StatesGroup


class UserSubscription(StatesGroup):
    """User subscription viewing states."""

    viewing_groups = State()
    viewing_group_details = State()
    viewing_profile = State()
