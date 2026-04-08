"""Admin filter for checking if user is admin."""

from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message


class AdminFilter(BaseFilter):
    """Filter to check if user is admin."""

    async def __call__(self, event: Message | CallbackQuery, **kwargs) -> bool:
        """Check if user is admin.

        Args:
            event: Message or CallbackQuery
            **kwargs: Additional data from middleware (including is_admin)

        Returns:
            True if user is admin
        """
        # Get is_admin from middleware data passed via kwargs
        return kwargs.get("is_admin", False)


def is_admin_user(data: dict) -> bool:
    """Check if user is admin from handler data.

    Args:
        data: Handler data from middleware

    Returns:
        True if user is admin
    """
    return data.get("is_admin", False)
