"""User subscription management handlers."""

from datetime import datetime, timezone
from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from collections import defaultdict
from loguru import logger
from urllib.parse import urljoin

from app.bot.keyboards import get_back_keyboard
from app.bot.states import UserSubscription
from app.database import async_session_factory
from app.services.new_subscription_service import NewSubscriptionService

router = Router()


@router.callback_query(F.data == "my_subscriptions")
async def show_my_subscriptions(callback: CallbackQuery, client) -> None:
    """Show user's subscriptions."""
    if not client:
        await callback.answer("❌ Клиент не найден.", show_alert=True)
        return

    async with async_session_factory() as session:
        from sqlalchemy.orm import selectinload
        from app.services.new_subscription_service import NewSubscriptionService

        service = NewSubscriptionService(session)
        subscriptions = await service.get_client_subscriptions(client.id)

    logger.info(f"User {client.id} subscriptions: found {len(subscriptions) if subscriptions else 0} subscriptions")

    if not subscriptions:
        await callback.message.edit_text(
            "📝 У вас пока нет подписок.\n\n"
            "Свяжитесь с администратором для создания подписки.",
            reply_markup=get_back_keyboard("admin_menu"),
        )
        await callback.answer()
        return

    text = f"📝 Ваши подписки ({len(subscriptions)}):\n\n"

    builder = InlineKeyboardBuilder()

    for sub in subscriptions:
        # Check if subscription has any active connections (data is already eager loaded)
        active_connections = [conn for conn in sub.inbound_connections if conn.is_enabled]
        has_active = len(active_connections) > 0

        # Status is active only if subscription is active AND has active connections
        status = "✅" if (sub.is_active and has_active) else "❌"

        text += (
            f"{status} <b>{sub.name}</b>\n"
            f"   Подключений: {len(active_connections)}/{len(sub.inbound_connections)}\n\n"
        )

        # Add button for each subscription
        builder.button(text=f"📝 {sub.name}", callback_data=f"user_sub_select_{sub.id}")

    builder.button(text="🔗 Subscription URLs", callback_data="all_sub_urls")
    builder.button(text="📋 JSON URLs", callback_data="all_json_urls")
    builder.button(text="📊 Сроки и остатки", callback_data="show_subscription_status")
    builder.button(text="🔙 Назад", callback_data="admin_menu")
    builder.adjust(1)

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "all_sub_urls")
async def show_all_subscription_urls(callback: CallbackQuery, client) -> None:
    """Show all subscription URLs for user."""
    if not client:
        await callback.answer("❌ Клиент не найден.", show_alert=True)
        return

    async with async_session_factory() as session:
        service = NewSubscriptionService(session)
        urls = await service.get_subscription_urls(client.id)

    if not urls:
        await callback.answer("❌ Нет активных подписок.", show_alert=True)
        return

    # Group URLs by subscription ID (unique subscription = subscription_id)
    grouped_subs = defaultdict(list)
    for url_info in urls:
        sub_id = url_info["subscription_id"]
        grouped_subs[sub_id].append(url_info)

    MAX_LENGTH = 4096
    text = "🔗 Subscription URLs:\n\n"

    # Show subscription info with URLs
    for sub_id, url_list in grouped_subs.items():
        sub_name = url_list[0]["subscription_name"]

        section = f"<b>Подписка: {sub_name}</b>\n"

        # Group by URL (different inbounds on same server have same URL)
        # Show unique URLs
        url_map = {}  # url -> server_name
        for url_info in url_list:
            url = url_info['url']
            server_name = url_info['server_name']
            if url not in url_map:
                url_map[url] = server_name

        # Add URLs as text (without code blocks)
        for url, server_name in url_map.items():
            section += f"{url}\n"

        section += "\n"

        # Check if adding this section would exceed limit
        if len(text) + len(section) > MAX_LENGTH:
            section = "\n... (остальные подписки скрыты из-за ограничений Telegram)"
            text += section
            break

        text += section

    builder = InlineKeyboardBuilder()
    builder.button(text="📋 Скопировать все URL", callback_data="copy_all_urls")
    builder.button(text="🔙 Назад", callback_data="my_subscriptions")
    builder.adjust(1)

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "all_json_urls")
async def show_all_json_urls(callback: CallbackQuery, client) -> None:
    """Show all JSON subscription URLs for user."""
    if not client:
        await callback.answer("❌ Клиент не найден.", show_alert=True)
        return

    async with async_session_factory() as session:
        service = NewSubscriptionService(session)
        urls = await service.get_subscription_json_urls(client.id)

    if not urls:
        await callback.answer("❌ Нет активных подписок.", show_alert=True)
        return

    # Group URLs by subscription ID (unique subscription = subscription_id)
    grouped_subs = defaultdict(list)
    for url_info in urls:
        sub_id = url_info["subscription_id"]
        grouped_subs[sub_id].append(url_info)

    MAX_LENGTH = 4096
    text = "📋 JSON Subscription URLs:\n\n"

    # Show subscription info with URLs
    for sub_id, url_list in grouped_subs.items():
        sub_name = url_list[0]["subscription_name"]

        section = f"<b>Подписка: {sub_name}</b>\n"

        # Group by URL (different inbounds on same server have same URL)
        # Show unique URLs
        url_map = {}  # url -> server_name
        for url_info in url_list:
            url = url_info['url']
            server_name = url_info['server_name']
            if url not in url_map:
                url_map[url] = server_name

        # Add URLs as text (without code blocks)
        for url, server_name in url_map.items():
            section += f"{url}\n"

        section += "\n"

        # Check if adding this section would exceed limit
        if len(text) + len(section) > MAX_LENGTH:
            section = "\n... (остальные подписки скрыты из-за ограничений Telegram)"
            text += section
            break

        text += section

    builder = InlineKeyboardBuilder()
    builder.button(text="📋 Скопировать все JSON URL", callback_data="copy_all_json_urls")
    builder.button(text="🔙 Назад", callback_data="my_subscriptions")
    builder.adjust(1)

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "copy_all_urls")
async def copy_all_subscription_urls(callback: CallbackQuery, client) -> None:
    """Copy all subscription URLs to clipboard-friendly format."""
    if not client:
        await callback.answer("❌ Клиент не найден.", show_alert=True)
        return

    async with async_session_factory() as session:
        service = NewSubscriptionService(session)
        urls = await service.get_subscription_urls(client.id)

    if not urls:
        await callback.answer("❌ Нет активных подписок.", show_alert=True)
        return

    # Group URLs by subscription ID (unique subscription = subscription_id)
    from collections import defaultdict
    grouped_subs = defaultdict(list)
    for url_info in urls:
        sub_id = url_info["subscription_id"]
        grouped_subs[sub_id].append(url_info)

    # Build text with all URLs
    MAX_LENGTH = 4096 - 20  # Reserve space for markdown formatting
    text = ""

    for sub_id, url_list in grouped_subs.items():
        # Group unique URLs by server (same URL = same server)
        url_map = {}
        for url_info in url_list:
            url = url_info['url']
            server_name = url_info['server_name']
            if url not in url_map:
                url_map[url] = server_name

        for url, server_name in url_map.items():
            # Check if adding this URL would exceed limit
            if len(text) + len(url) + 1 > MAX_LENGTH:  # +1 for newline
                break
            text += f"{url}\n"

    # Send as new message instead of callback answer for better copy support
    await callback.message.answer(f"```\n{text}\n```", parse_mode="MarkdownV2")


@router.callback_query(F.data == "copy_all_json_urls")
async def copy_all_json_urls(callback: CallbackQuery, client) -> None:
    """Copy all JSON subscription URLs to clipboard-friendly format."""
    if not client:
        await callback.answer("❌ Клиент не найден.", show_alert=True)
        return

    async with async_session_factory() as session:
        service = NewSubscriptionService(session)
        urls = await service.get_subscription_json_urls(client.id)

    if not urls:
        await callback.answer("❌ Нет активных подписок.", show_alert=True)
        return

    # Group URLs by subscription ID (unique subscription = subscription_id)
    from collections import defaultdict
    grouped_subs = defaultdict(list)
    for url_info in urls:
        sub_id = url_info["subscription_id"]
        grouped_subs[sub_id].append(url_info)

    # Build text with all URLs
    MAX_LENGTH = 4096 - 20  # Reserve space for markdown formatting
    text = ""

    for sub_id, url_list in grouped_subs.items():
        # Group unique URLs by server (same URL = same server)
        url_map = {}
        for url_info in url_list:
            url = url_info['url']
            server_name = url_info['server_name']
            if url not in url_map:
                url_map[url] = server_name

        for url, server_name in url_map.items():
            # Check if adding this URL would exceed limit
            if len(text) + len(url) + 1 > MAX_LENGTH:  # +1 for newline
                break
            text += f"{url}\n"

    # Send as new message instead of callback answer for better copy support
    await callback.message.answer(f"```\n{text}\n```", parse_mode="MarkdownV2")


@router.callback_query(F.data.startswith("user_sub_select_"))
async def show_user_subscription_details(callback: CallbackQuery, client) -> None:
    """Show subscription details for user."""
    if not client:
        await callback.answer("❌ Клиент не найден.", show_alert=True)
        return

    subscription_id = int(callback.data.split("_")[-1])

    async with async_session_factory() as session:
        service = NewSubscriptionService(session)
        subscription = await service.get_subscription(subscription_id)

    if not subscription or subscription.client_id != client.id:
        await callback.answer("❌ Подписка не найдена.", show_alert=True)
        return

    # Check if subscription has any active connections (data is already eager loaded)
    active_connections = [conn for conn in subscription.inbound_connections if conn.is_enabled]
    has_active = len(active_connections) > 0
    status = "✅ Активна" if (subscription.is_active and has_active) else "❌ Неактивна"

    text = (
        f"📝 Подписка: <b>{subscription.name}</b>\n\n"
        f"Статус: {status}\n"
        f"Создана: {subscription.created_at.strftime('%d.%m.%Y %H:%M')}\n"
        f"Подключений: {len(active_connections)}/{len(subscription.inbound_connections)}\n"
        f"Токен: <code>{subscription.subscription_token}</code>\n\n"
    )

    # Group URLs by server to avoid duplicates
    server_urls = defaultdict(list)
    for conn in active_connections:
        server = conn.inbound.server
        subscription_path = getattr(server, 'subscription_path', '/sub/')
        subscription_url = urljoin(server.url, f"{subscription_path}{subscription.subscription_token}")
        server_urls[subscription_url].append({
            'server_name': server.name,
            'inbound': conn.inbound,
            'connection': conn,
        })

    if server_urls:
        text += "📢 Активные подключения:\n\n"
        for url, conn_list in server_urls.items():
            # Show URL once per group
            text += f"  • URL: {url}\n"

            # Show per-inbound traffic and expiry
            for i, conn_data in enumerate(conn_list):
                conn = conn_data['connection']
                inbound = conn_data['inbound']

                # Per-inbound traffic
                traffic = "Безлимит" if conn.is_unlimited else f"{conn.total_gb} GB"

                # Per-inbound expiry
                if conn.expiry_date:
                    expiry = conn.expiry_date.strftime("%d.%m.%Y")
                    remaining_days = conn.remaining_days
                    if remaining_days is not None:
                        expiry_info = f"{expiry} (осталось {remaining_days} дней)"
                    else:
                        expiry_info = expiry
                else:
                    expiry_info = "Бессрочно"

                # Add empty line before each inbound for better readability (except first)
                if i > 0:
                    text += "\n"

                text += f"    └ {inbound.remark} ({inbound.protocol})\n"
                text += f"      Трафик: {traffic}\n"
                text += f"      Срок: {expiry_info}\n"

            text += "\n"

    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад к подпискам", callback_data="my_subscriptions")
    builder.adjust(1)

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "admin_export")
async def export_database(callback: CallbackQuery, client) -> None:
    """Export database to file and send to user (admin only)."""
    if not client or not client.is_admin:
        await callback.answer("❌ Эта функция доступна только администраторам.", show_alert=True)
        return

    try:
        # Get database file path from config
        from app.config import get_settings
        from pathlib import Path
        import shutil

        settings = get_settings()

        # Extract database path from connection URL
        db_path = Path(settings.database_url.replace("sqlite+aiosqlite:///", ""))

        # Check if database file exists
        if not db_path.exists():
            await callback.answer("❌ Файл базы данных не найден.", show_alert=True)
            return

        # Check file size (max 1.5 GB)
        file_size = db_path.stat().st_size
        if file_size > 1.5 * 1024 * 1024 * 1024:
            await callback.answer(
                f"❌ Файл базы данных слишком большой ({file_size / (1024*1024):.1f} MB). Максимум: 1.5 GB",
                show_alert=True
            )
            return

        # Create temporary copy to avoid file locking issues
        import tempfile
        temp_dir = tempfile.gettempdir()
        temp_db_path = Path(temp_dir) / f"vpn_manager_export_{client.id}.db"

        try:
            # Show preparation message
            await callback.answer("⏳ Подготовка файла базы данных...")

            # Copy database file to avoid locking issues
            shutil.copy2(db_path, temp_db_path)
            logger.info(f"Database copied to {temp_db_path} for export")

            # Send database file
            from datetime import datetime
            from aiogram.types import FSInputFile
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

            document = FSInputFile(path=temp_db_path, filename=f"vpn_manager_{timestamp}.db")
            await callback.message.answer_document(
                document=document,
                caption=f"📄 Экспорт базы данных VPN Manager\n"
                f"Размер: {file_size / (1024*1024):.2f} MB\n"
                f"Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}",
            )

            await callback.answer("✅ База данных отправлена!")
            logger.info(f"Database exported by admin {client.id}: {db_path}")

        finally:
            # Clean up temporary file
            if temp_db_path.exists():
                try:
                    temp_db_path.unlink()
                    logger.debug(f"Temporary database file removed: {temp_db_path}")
                except Exception as e:
                    logger.warning(f"Failed to remove temporary file {temp_db_path}: {e}")

    except Exception as e:
        logger.error(f"Error exporting database for admin {client.id}: {e}", exc_info=True)
        await callback.answer("❌ Ошибка при экспорте базы данных.", show_alert=True)


@router.callback_query(F.data == "show_subscription_status")
async def show_subscription_status(callback: CallbackQuery, client) -> None:
    """Show subscription status including expiry and traffic information."""
    if not client:
        await callback.answer("❌ Клиент не найден.", show_alert=True)
        return

    async with async_session_factory() as session:
        from app.services.new_subscription_service import NewSubscriptionService

        service = NewSubscriptionService(session)
        subscriptions = await service.get_client_subscriptions(client.id)

    if not subscriptions:
        await callback.answer("❌ Нет активных подписок.", show_alert=True)
        return

    text = "📊 <b>Сроки и остатки подписок</b>\n\n"

    # Get XUI service for traffic data
    from app.services import XUIService
    xui_service = None
    xui_clients = {}

    for sub in subscriptions:
        # Get active connections (data is already eager loaded)
        active_connections = [conn for conn in sub.inbound_connections if conn.is_enabled]

        if not active_connections:
            text += f"❌ <b>{sub.name}</b>\n"
            text += f"   Нет активных подключений\n\n"
            continue

        # Subscription-level expiry (from subscription or from connections)
        expiry_text = "Бессрочно"
        if sub.expiry_date:
            expiry_text = (sub.expiry_date + timedelta(hours=3)).strftime('%d.%m.%Y %H:%M')

            # Handle timezone-aware vs naive datetimes
            sub_expiry = sub.expiry_date
            now = datetime.now(timezone.utc)
            if sub_expiry.tzinfo is None:
                sub_expiry = sub_expiry.replace(tzinfo=timezone.utc)

            remaining_days = (sub_expiry - now).days if sub.expiry_date else None
            if remaining_days is not None:
                if remaining_days <= 1:
                    expiry_text += " (истекает в течение 24 часов)"
                elif remaining_days <= 7:
                    expiry_text += f" (осталось {remaining_days} дн.)"

        text += f"📦 <b>{sub.name}</b>\n"
        text += f"   📅 Срок: {expiry_text}\n"
        text += f"   🔌 Подключений: {len(active_connections)}\n\n"

        # Show per-connection details
        text += "   <b>Подключения:</b>\n"

        for conn in active_connections:
            inbound = conn.inbound
            server = inbound.server

            # Connection expiry
            conn_expiry = "Бессрочно"
            if conn.expiry_date:
                conn_expiry = (conn.expiry_date + timedelta(hours=3)).strftime('%d.%m.%Y %H:%M')

                # Handle timezone-aware vs naive datetimes
                conn_expiry_date = conn.expiry_date
                now = datetime.now(timezone.utc)
                if conn_expiry_date.tzinfo is None:
                    conn_expiry_date = conn_expiry_date.replace(tzinfo=timezone.utc)

                conn_remaining = (conn_expiry_date - now).days if conn.expiry_date else None
                if conn_remaining is not None and conn_remaining <= 7:
                    conn_expiry += f" ({conn_remaining} дн.)"

            # Connection traffic
            if conn.is_unlimited:
                traffic_text = "Безлимит"
            else:
                traffic_text = f"{conn.total_gb} ГБ"

                # Get actual traffic from XUI
                try:
                    async with async_session_factory() as traffic_session:
                        xui_service = XUIService(traffic_session)
                        if server.id not in xui_clients:
                            xui_clients[server.id] = await xui_service._get_client(server)

                        xui_client = xui_clients[server.id]
                        clients = await xui_client.get_clients(inbound.xui_id)

                        for xui_conn in clients:
                            if xui_conn.get("id") == conn.uuid:
                                used_gb = (xui_conn.get("up", 0) + xui_conn.get("down", 0)) / (1024**3)
                                remaining_gb = conn.total_gb - used_gb

                                if remaining_gb <= 5:
                                    traffic_text += f" (⚠️ осталось {remaining_gb:.2f} ГБ)"
                                else:
                                    traffic_text += f" (осталось {remaining_gb:.2f} ГБ)"
                                break
                except Exception as e:
                    logger.warning(f"Failed to get traffic for connection {conn.id}: {e}")
                    traffic_text += " (ошибка получения данных)"

            text += f"      • {inbound.remark} ({server.name})\n"
            text += f"        📅 Срок: {conn_expiry}\n"
            text += f"        📊 Трафик: {traffic_text}\n"

        text += "\n"

    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад к подпискам", callback_data="my_subscriptions")
    builder.adjust(1)

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()

    # Close XUI clients
    for client_obj in xui_clients.values():
        try:
            await client_obj.close()
        except Exception as e:
            logger.warning(f"Error closing XUI client: {e}")

