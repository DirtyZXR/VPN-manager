"""Main bot router."""

from aiogram import Router

from app.bot.handlers.admin import servers, clients, subscriptions, sync
from app.bot.handlers import common


def create_router() -> Router:
    """Create main router with all handlers.

    Returns:
        Configured router
    """
    router = Router()

    # Include all handlers
    router.include_router(common.router)
    router.include_router(servers.router)
    router.include_router(clients.router)
    router.include_router(subscriptions.router)
    router.include_router(sync.router)

    return router
