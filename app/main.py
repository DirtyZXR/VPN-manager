"""Main entry point for VPN Manager bot."""

import asyncio
import contextlib
import signal
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
from app.logging_config import setup_logging
from app.services import SyncService
from app.services.notification_checker import NotificationChecker
from app.services.notification_service import close_shared_bot

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
        logger.info("Фоновая синхронизация запущена")
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

                logger.debug("Ожидание следующего цикла синхронизации...")
                await asyncio.sleep(300)  # 5 минут
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("Ошибка в цикле фоновой синхронизации: {}", e, exc_info=True)
                await asyncio.sleep(60)

    except asyncio.CancelledError:
        logger.info("Фоновая синхронизация отменена")
    except Exception as e:
        logger.error("Критическая ошибка в обёртке фоновой синхронизации: {}", e, exc_info=True)
    finally:
        _background_sync_running = False
        logger.info("Фоновая синхронизация остановлена")


async def background_notification_wrapper() -> None:
    """Wrapper for background notifications that creates new sessions per cycle."""
    global _background_notification_running
    _background_notification_running = True

    try:
        logger.info("Фоновая рассылка уведомлений запущена")
        while _background_notification_running:
            try:
                # Use global lock to prevent concurrent database access
                async with _global_db_lock, async_session_factory() as session:
                    notification_checker = NotificationChecker(session)
                    try:
                        await notification_checker.check_and_notify()
                    finally:
                        await notification_checker.close()

                logger.debug("Ожидание следующей проверки уведомлений...")
                await asyncio.sleep(600)  # 10 минут
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("Ошибка в цикле фоновых уведомлений: {}", e, exc_info=True)
                await asyncio.sleep(60)

    except asyncio.CancelledError:
        logger.info("Фоновая рассылка уведомлений отменена")
    except Exception as e:
        logger.error("Критическая ошибка в обёртке фоновых уведомлений: {}", e, exc_info=True)
    finally:
        _background_notification_running = False
        logger.info("Фоновая рассылка уведомлений остановлена")


def build_dispatcher() -> Dispatcher:
    """Собрать Dispatcher: AuthMiddleware как outer (is_admin доступен фильтрам) + роутеры."""
    dp = Dispatcher()
    dp.message.outer_middleware(AuthMiddleware())
    dp.callback_query.outer_middleware(AuthMiddleware())
    dp.include_router(create_router())
    return dp



async def main() -> None:
    """Main async entry point."""
    settings = get_settings()

    # Setup logging
    setup_logging()
    logger.info("Запуск VPN Manager bot...")

    # Initialize database
    logger.info("Инициализация базы данных...")
    await init_db()
    logger.info("База данных инициализирована")

    # Ensure data directory exists for Telethon
    data_path = Path("data")
    data_path.mkdir(exist_ok=True)
    logger.info("Директория data создана/проверена")

    # Create bot instance
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    # Собрать dispatcher (outer-middleware + роутеры)
    dp = build_dispatcher()

    # Start tasks
    logger.info("Запуск polling, фоновой синхронизации и уведомлений...")
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
        logger.info("Остановка фоновых задач...")
        # Close bot session
        await bot.session.close()
        # Close notification singleton Bot (avoids 'Unclosed client session' warnings)
        try:
            await close_shared_bot()
        except Exception as exc:
            logger.warning("Ошибка при закрытии singleton Bot уведомлений: {}", exc)


def _handle_sigterm(signum: int, frame: object) -> None:
    """SIGTERM (docker stop) → KeyboardInterrupt, чтобы отработал graceful-shutdown."""
    raise KeyboardInterrupt


def run() -> None:
    """Run the bot."""
    # SIGTERM от `docker stop` приводим к тому же пути, что и Ctrl+C (SIGINT),
    # чтобы finally в main() корректно закрыл сессии бота.
    signal.signal(signal.SIGTERM, _handle_sigterm)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен (SIGINT/SIGTERM)")
    except Exception as e:
        logger.exception("Бот аварийно завершился: {}", e)
        sys.exit(1)


if __name__ == "__main__":
    run()
