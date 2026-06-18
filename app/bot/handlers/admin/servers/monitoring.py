"""Мониторинг/диагностика сервера: синхронизация, тест, inbounds, статистика, очистка."""

import contextlib

from aiogram import F, Router
from aiogram.types import CallbackQuery
from loguru import logger

from app.bot.keyboards import get_back_keyboard
from app.database import async_session_factory
from app.services.xui_service import XUIService
from app.utils.texts import t

router = Router()


@router.callback_query(F.data.startswith("server_sync_"))
async def sync_server(callback: CallbackQuery) -> None:
    """Sync server inbounds and clients."""
    server_id = int(callback.data.split("_")[-1])

    await callback.answer(
        t("admin.servers.sync_started", "🔄 Синхронизация запущена..."),
        show_alert=False,
    )

    async with async_session_factory() as session:
        from app.services import SyncService

        sync_service = SyncService(session)
        try:
            from sqlalchemy.orm import selectinload

            from app.database.models import Server

            server = await session.get(
                Server,
                server_id,
                options=[
                    selectinload(Server.xui_panel),
                    selectinload(Server.awg_service),
                    selectinload(Server.mtproxy_service),
                    selectinload(Server.inbounds),
                ]
            )
            if server:
                result = await sync_service.sync_server(server, force=True)
                await session.commit()
                if result:
                    await callback.message.answer(
                        "✅ Синхронизация завершена! Inbounds и клиенты синхронизированы",
                    )
                else:
                    await callback.message.answer(
                        "⚠️ Синхронизация завершена с ошибкой. Проверьте статус сервера.",
                    )
            else:
                await callback.message.answer(
                    t("admin.servers.errors.not_found", "❌ Сервер не найден")
                )
        except Exception as e:
            logger.error("Error syncing server {}: {}", server_id, e, exc_info=True)
            with contextlib.suppress(Exception):
                await callback.message.answer(
                    f"❌ Ошибка при синхронизации: {str(e)[:200]}",
                )


@router.callback_query(F.data.startswith("server_test_"))
async def test_server(callback: CallbackQuery) -> None:
    """Test server connection."""
    server_id = int(callback.data.split("_")[-1])

    async with async_session_factory() as session:
        service = XUIService(session)
        server = await service.get_server_by_id(server_id)
        if not server:
            await callback.answer(
                t("admin.servers.errors.not_found", "❌ Сервер не найден."), show_alert=True
            )
            return

        success, message = await service.test_server_connection(server_id)

        await service.close_all_clients()

    if success:
        await callback.answer(
            t("admin.servers.test.success", "✅ {message}", message=message), show_alert=True
        )
    else:
        await callback.answer(
            t("admin.servers.test.error", "❌ {message}", message=message), show_alert=True
        )


@router.callback_query(F.data.startswith("server_inbounds_"))
async def show_server_inbounds(callback: CallbackQuery) -> None:
    """Show inbounds for a server with detailed information."""
    server_id = int(callback.data.split("_")[-1])

    async with async_session_factory() as session:
        service = XUIService(session)
        server = await service.get_server_by_id(server_id)
        if not server:
            await callback.answer(
                t("admin.servers.errors.not_found", "❌ Сервер не найден."), show_alert=True
            )
            return

        inbounds = await service.get_server_inbounds_all_status(server_id)

        if not inbounds:
            await callback.message.edit_text(
                t(
                    "admin.servers.inbounds.empty",
                    "📊 Inbounds сервера {name}\n\n❌ Нет доступных inbounds.\n\nНажмите '🔄 Синхронизировать' для получения inbounds с панели.",
                    name=server.name,
                ),
                reply_markup=get_back_keyboard(f"server_select_{server_id}"),
            )
            await callback.answer()
            return

        from aiogram.utils.keyboard import InlineKeyboardBuilder

        text = t(
            "admin.servers.inbounds.title",
            "📊 Inbounds сервера <b>{name}</b>\n\n",
            name=server.name,
        )

        for ib in inbounds:
            status = "✅" if ib.is_active else "❌"
            line = f"{status} <b>{ib.remark}</b> ({ib.protocol})"
            if ib.port:
                line += f"\n   Порт: {ib.port}"
            if hasattr(ib, "client_count"):
                line += f"\n   Клиентов: {ib.client_count}"
            text += line + "\n\n"

        kb = InlineKeyboardBuilder()
        kb.button(
            text=t("admin.servers.buttons.stats", "📊 Статистика"),
            callback_data=f"inbound_stats_{server_id}",
        )
        kb.button(
            text=t("admin.servers.buttons.cleanup_inbounds", "🧹 Очистить неактивные"),
            callback_data=f"cleanup_inbounds_{server_id}",
        )
        kb.button(
            text=t("admin.servers.buttons.sync", "🔄 Синхронизировать"),
            callback_data=f"server_sync_{server_id}",
        )
        kb.button(
            text=t("admin.servers.buttons.back", "🔙 Назад"),
            callback_data=f"server_select_{server_id}",
        )
        kb.adjust(1)

        await callback.message.edit_text(
            text,
            reply_markup=kb.as_markup(),
            parse_mode="HTML",
        )
        await callback.answer()


@router.callback_query(F.data.startswith("cleanup_inbounds_"))
async def cleanup_inbounds(callback: CallbackQuery) -> None:
    """Cleanup inactive inbounds for a server."""
    server_id = int(callback.data.split("_")[-1])

    async with async_session_factory() as session:
        from sqlalchemy import delete

        from app.database.models import Inbound

        await session.execute(
            delete(Inbound).where(Inbound.server_id == server_id, Inbound.is_active.is_(False))
        )
        await session.commit()

    await callback.answer(
        t("admin.servers.inbounds.cleanup_success", "✅ Удаленные inbounds очищены"),
        show_alert=True,
    )
    await show_server_inbounds(callback)


@router.callback_query(F.data.startswith("inbound_stats_"))
async def show_inbound_stats(callback: CallbackQuery) -> None:
    """Show live statistics for inbounds from XUI panel."""
    server_id = int(callback.data.split("_")[-1])

    async with async_session_factory() as session:
        service = XUIService(session)
        server = await service.get_server_by_id(server_id)
        if not server:
            await callback.answer(
                t("admin.servers.errors.not_found", "❌ Сервер не найден."), show_alert=True
            )
            return

        try:
            from aiogram.utils.keyboard import InlineKeyboardBuilder

            # Get inbounds from database
            inbounds = await service.get_server_inbounds(server_id)

            if not inbounds:
                await callback.answer(
                    t(
                        "admin.servers.inbounds.no_inbounds_to_update",
                        "❌ Нет inbounds для обновления.",
                    ),
                    show_alert=True,
                )
                return

            # Get live stats from XUI panel
            text = t(
                "admin.servers.stats.title",
                "📊 Статистика Inbounds сервера {name}\n\n",
                name=server.name,
            )

            for inbound in inbounds:
                stats = await service.get_inbound_client_stats(inbound.id)
                status = "✅" if inbound.is_active else "❌"

                text += t(
                    "admin.servers.stats.item",
                    "{status} {remark} ({protocol})\n   Порт: {port}\n   Всего клиентов: {total}\n   Активных: {active}\n   Отключенных: {disabled}\n   Использовано трафика: {used:.2f} GB\n\n",
                    status=status,
                    remark=inbound.remark,
                    protocol=inbound.protocol,
                    port=inbound.port,
                    total=stats["total_clients"],
                    active=stats["enabled_clients"],
                    disabled=stats["disabled_clients"],
                    used=stats["total_used_gb"],
                )

            kb = InlineKeyboardBuilder()
            kb.button(
                text=t("admin.servers.buttons.refresh", "🔄 Обновить"),
                callback_data=f"inbound_stats_{server_id}",
            )
            kb.button(
                text=t("admin.servers.buttons.back", "🔙 Назад"),
                callback_data=f"server_select_{server_id}",
            )
            kb.adjust(1)

            await callback.message.edit_text(text, reply_markup=kb.as_markup())
            await callback.answer(t("admin.servers.stats.updated", "✅ Статистика обновлена"))

        except Exception as e:
            logger.error("Error getting inbound stats: {}", e, exc_info=True)
            await callback.answer(
                t("admin.servers.errors.generic", "❌ Ошибка: {error}", error=str(e)),
                show_alert=True,
            )
        finally:
            await service.close_all_clients()
