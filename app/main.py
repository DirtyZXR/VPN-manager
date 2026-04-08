"""Main entry point for VPN Manager bot."""

import asyncio
import contextlib
import sys
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from loguru import logger

from app.bot.middlewares import AuthMiddleware
from app.bot.router import create_router
from app.config import get_settings
from app.database import async_session_factory, init_db
from app.services import SyncService
from app.services.notification_checker import NotificationChecker

# Flags to control background tasks
_background_sync_running = False
_background_notification_running = False

# Global lock to prevent concurrent database access between sync and notification tasks
_global_db_lock = asyncio.Lock()


async def background_sync_wrapper() -> None:
    """Wrapper for background sync that creates new sessions per cycle."""
    global _background_sync_running
    _background_sync_running = True

    try:
        logger.info("Starting background sync wrapper...")
        while _background_sync_running:
            try:
                # Use global lock to prevent concurrent database access
                async with _global_db_lock, async_session_factory() as session:
                    sync_service = SyncService(session)
                    try:
                        # Run one sync cycle with force=True to sync immediately
                        await sync_service._sync_cycle(force=True)
                        # Commit changes to make them persistent
                        await session.commit()
                    finally:
                        # Close XUI clients to prevent resource leaks
                        await sync_service.close_xui_clients()

                # Wait for SYNC_INTERVAL (5 minutes) between cycles
                logger.debug("Waiting for next sync cycle...")
                await asyncio.sleep(300)  # 5 minutes = 300 seconds
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Error in background sync cycle: {e}", exc_info=True)
                await asyncio.sleep(60)  # Wait 1 minute on error

    except asyncio.CancelledError:
        logger.info("Background sync cancelled")
    except Exception as e:
        logger.error(f"Fatal error in background sync wrapper: {e}", exc_info=True)
    finally:
        _background_sync_running = False
        logger.info("Background sync wrapper stopped")


async def background_notification_wrapper() -> None:
    """Wrapper for background notifications that creates new sessions per cycle."""
    global _background_notification_running
    _background_notification_running = True

    try:
        logger.info("Starting background notification wrapper...")
        while _background_notification_running:
            try:
                # Use global lock to prevent concurrent database access
                async with _global_db_lock, async_session_factory() as session:
                    notification_checker = NotificationChecker(session)
                    try:
                        await notification_checker.check_and_notify()
                    finally:
                        await notification_checker.close()

                # Wait 10 minutes between checks
                logger.debug("Waiting for next notification check...")
                await asyncio.sleep(600)  # 10 minutes = 600 seconds
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Error in background notification cycle: {e}", exc_info=True)
                await asyncio.sleep(60)  # Wait 1 minute on error

    except asyncio.CancelledError:
        logger.info("Background notifications cancelled")
    except Exception as e:
        logger.error(f"Fatal error in background notification wrapper: {e}", exc_info=True)
    finally:
        _background_notification_running = False
        logger.info("Background notification wrapper stopped")


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

    # Start tasks
    logger.info("Starting polling, background sync and notifications...")
    try:
        # Create async tasks
        sync_task = asyncio.create_task(background_sync_wrapper())
        notification_task = asyncio.create_task(background_notification_wrapper())
        polling_task = asyncio.create_task(
            dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
        )

        # Wait for either task to complete (usually polling will run forever)
        done, pending = await asyncio.wait(
            [sync_task, notification_task, polling_task], return_when=asyncio.FIRST_COMPLETED
        )

        # Cancel remaining tasks
        for task in pending:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
    finally:
        # Stop background tasks
        _background_sync_running = False
        _background_notification_running = False
        logger.info("Stopping background tasks...")
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
