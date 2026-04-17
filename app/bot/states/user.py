"""FSM states for user flows."""

from aiogram.fsm.state import State, StatesGroup


class UserSubscription(StatesGroup):
    """User subscription viewing states."""

    viewing_groups = State()
    viewing_group_details = State()
    viewing_profile = State()


class UserRegistration(StatesGroup):
    """User self-registration states."""

    choosing_name_source = State()
    entering_custom_name = State()


class InstructionViewing(StatesGroup):
    """States for step-by-step instruction viewing."""

    viewing = State()


class UserRequestSubscription(StatesGroup):
    """States for requesting a new subscription."""

    waiting_for_name = State()
