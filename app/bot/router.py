"""Main bot router."""

from aiogram import Router

from app.bot.handlers import common, registration
from app.bot.handlers.admin import clients, servers, subscriptions, sync, templates
from app.bot.handlers.user import subscriptions as user_subscriptions


def create_router() -> Router:
    """Create main router with all handlers.

    Returns:
        Configured router
    """
    router = Router()

    # Include all handlers
    router.include_router(common.router)
    router.include_router(registration.router)
    router.include_router(servers.router)
    router.include_router(clients.router)
    router.include_router(subscriptions.router)
    router.include_router(sync.router)
    router.include_router(templates.router)
    router.include_router(user_subscriptions.router)

    return router
