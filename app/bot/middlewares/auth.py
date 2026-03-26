"""Auth middleware for checking client permissions."""

from typing import Any, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User as TgUser
from loguru import logger

from app.config import get_settings
from app.database import async_session_factory
from app.services.client_service import ClientService


class AuthMiddleware(BaseMiddleware):
    """Middleware for client authentication and registration."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Any],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        """Process request and add client to data.

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

        logger.debug(f"Checking client: ID={tg_user.id}, full_name={tg_user.full_name}")
        settings = get_settings()

        # Check if client is admin by telegram ID from config
        is_admin = settings.is_admin(tg_user.id)
        logger.debug(f"Client is_admin={is_admin}, admin_ids={settings.admin_ids}")

        async with async_session_factory() as session:
            client_service = ClientService(session)

            # Try to find client by telegram ID
            client = await client_service.get_client_by_telegram_id(tg_user.id)

            if not client and is_admin:
                # Auto-create admin client
                logger.info(f"Auto-creating admin client: {tg_user.full_name} (ID: {tg_user.id})")
                client = await client_service.create_client(
                    name=tg_user.full_name,
                    telegram_id=tg_user.id,
                    is_admin=True,
                )
                await session.commit()

            # Update client admin status from database if exists
            if client:
                is_admin = client.is_admin

            # Update data dict with middleware results
            # Note: client can be None for non-registered non-admin users
            data.update({
                "client": client,
                "is_admin": is_admin,
            })

        return await handler(event, data)
