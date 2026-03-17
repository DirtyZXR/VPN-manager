"""Auth middleware for checking user permissions."""

from typing import Callable, Awaitable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User as TgUser

from app.config import get_settings
from app.database import async_session_factory
from app.services.user_service import UserService


class AuthMiddleware(BaseMiddleware):
    """Middleware for user authentication and registration."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, any]], Awaitable[any]],
        event: TelegramObject,
        data: dict[str, any],
    ) -> any:
        """Process request and add user to data.

        Args:
            handler: Next handler
            event: Telegram event
            data: Handler data

        Returns:
            Handler result
        """
        tg_user: TgUser | None = data.get("event_from_user")

        if not tg_user:
            return await handler(event, data)

        settings = get_settings()

        # Check if user is admin by telegram ID
        is_admin = settings.is_admin(tg_user.id)

        async with async_session_factory() as session:
            user_service = UserService(session)

            # Try to find user by telegram ID
            user = await user_service.get_user_by_telegram_id(tg_user.id)

            if not user and is_admin:
                # Auto-create admin user
                user = await user_service.create_user(
                    name=tg_user.full_name,
                    telegram_id=tg_user.id,
                    is_admin=True,
                )
                await session.commit()

            # Add user to data
            data["user"] = user
            data["is_admin"] = is_admin

        return await handler(event, data)
