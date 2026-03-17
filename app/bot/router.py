"""Main bot router."""

from aiogram import Router

from app.bot.handlers.admin import servers, subscriptions, users
from app.bot.handlers.user import subscriptions as user_subscriptions
from app.bot.handlers import common


def create_router() -> Router:
    """Create main router with all handlers.

    Returns:
        Configured router
    """
    router = Router()

    # Include all handlers
    router.include_router(common.router)
    router.include_router(user_subscriptions.router)
    router.include_router(servers.router)
    router.include_router(users.router)
    router.include_router(subscriptions.router)

    return router
