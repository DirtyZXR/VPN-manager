"""Main entry point for VPN Manager bot."""

import asyncio
import sys
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from loguru import logger

from app.config import get_settings
from app.database import init_db
from app.bot.middlewares import AuthMiddleware
from app.bot.router import create_router
from app.services.xui_service import XUIService


def setup_logging() -> None:
    """Configure loguru logging."""
    settings = get_settings()

    # Remove default handler
    logger.remove()

    # Add console handler
    logger.add(
        sys.stdout,
        level=settings.log_level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    )

    # Add file handler
    log_path = Path("logs")
    log_path.mkdir(exist_ok=True)

    logger.add(
        log_path / "app.log",
        level=settings.log_level,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
        rotation="10 MB",
        retention="7 days",
    )


async def main() -> None:
    """Main async entry point."""
    settings = get_settings()

    # Setup logging
    setup_logging()
    logger.info("Starting VPN Manager bot...")

    # Initialize database
    logger.info("Initializing database...")
    await init_db()
    logger.info("Database initialized")

    # Ensure data directory exists for Telethon
    data_path = Path("data")
    data_path.mkdir(exist_ok=True)
    logger.info("Data directory created/verified")

    # Create global XUI service instance for client caching
    xui_service = None
    try:
        from app.database import async_session_factory
        async with async_session_factory() as session:
            xui_service = XUIService(session)
            logger.info("XUI service initialized")
    except Exception as e:
        logger.warning(f"Could not initialize XUI service: {e}")

    # Create bot instance
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    # Create dispatcher
    dp = Dispatcher()

    # Setup middleware
    dp.message.middleware(AuthMiddleware())
    dp.callback_query.middleware(AuthMiddleware())

    # Setup router
    router = create_router()
    dp.include_router(router)

    # Start polling (без автоматической синхронизации)
    logger.info("Starting polling...")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        # Close XUI clients
        if xui_service:
            logger.info("Closing XUI clients...")
            await xui_service.close_all_clients()
        # Close bot session
        await bot.session.close()


def run() -> None:
    """Run the bot."""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.exception(f"Bot crashed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    run()
