"""Admin filter for checking if user is admin."""

from aiogram.filters import BaseFilter
from aiogram.types import Message, CallbackQuery


class AdminFilter(BaseFilter):
    """Filter to check if user is admin."""

    async def __call__(self, event: Message | CallbackQuery) -> bool:
        """Check if user is admin.

        Args:
            event: Message or CallbackQuery

        Returns:
            True if user is admin
        """
        # Get is_admin from middleware data
        if isinstance(event, CallbackQuery):
            # For callback queries, check from middleware
            return event.data is not None

        # For messages, this will be checked via middleware data
        return True


def is_admin_user(data: dict) -> bool:
    """Check if user is admin from handler data.

    Args:
        data: Handler data from middleware

    Returns:
        True if user is admin
    """
    return data.get("is_admin", False)
