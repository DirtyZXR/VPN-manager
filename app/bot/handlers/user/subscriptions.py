"""User subscription management handlers."""

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
        # Problem 1: Check if subscription has any active connections
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

    # Group URLs by subscription token (should be one token per subscription)
    grouped_urls = defaultdict(list)
    for url_info in urls:
        grouped_urls[url_info["token"]].append(url_info)

    text = "🔗 Subscription URLs:\n\n"

    # Show subscription info and create URL buttons
    builder = InlineKeyboardBuilder()

    for token, url_list in grouped_urls.items():
        sub_name = url_list[0]["subscription_name"]
        text += f"<b>{sub_name}</b>\n"
        text += f"Token: <code>{token}</code>\n"
        text += f"Серверов: {len(url_list)}\n"

        # Get unique URLs (same URL can be on multiple servers)
        unique_urls = {}
        for url_info in url_list:
            url = url_info['url']
            if url not in unique_urls:
                unique_urls[url] = {
                    'url': url,
                    'server_name': url_info['server_name']
                }

        # Add URL buttons for this subscription
        for url, url_data in unique_urls.items():
            server_name = url_data['server_name']
            builder.button(text=f"📡 {server_name}", url=url)

        text += "\n"

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

    # Group URLs by subscription token (should be one token per subscription)
    grouped_urls = defaultdict(list)
    for url_info in urls:
        grouped_urls[url_info["token"]].append(url_info)

    text = "📋 JSON Subscription URLs:\n\n"

    for token, url_list in grouped_urls.items():
        sub_name = url_list[0]["subscription_name"]
        text += f"<b>{sub_name}</b>\n"
        text += f"Token: <code>{token}</code>\n"
        text += f"JSON URLs ({len(url_list)}):\n"

        for url_info in url_list:
            text += f"  • {url_info['server_name']} - {url_info['inbound_name']}\n"
            text += f"    <code>{url_info['url']}</code>\n"

        text += "\n"

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

    # Group URLs by subscription token
    from collections import defaultdict
    grouped_urls = defaultdict(list)
    for url_info in urls:
        grouped_urls[url_info["token"]].append(url_info)

    text = "📋 Subscription URLs (для копирования):\n\n"

    for token, url_list in grouped_urls.items():
        text += f"{url_list[0]['subscription_name']}:\n"
        for url_info in url_list:
            text += f"{url_info['url']}\n"
        text += "\n"

    await callback.answer(text, show_alert=False)


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

    # Group URLs by subscription token
    from collections import defaultdict
    grouped_urls = defaultdict(list)
    for url_info in urls:
        grouped_urls[url_info["token"]].append(url_info)

    text = "📋 JSON Subscription URLs (для копирования):\n\n"

    for token, url_list in grouped_urls.items():
        text += f"{url_list[0]['subscription_name']}:\n"
        for url_info in url_list:
            text += f"{url_info['url']}\n"
        text += "\n"

    await callback.answer(text, show_alert=False)


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

    # Problem 1: Check if subscription has any active connections
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

    # Problem 3: Group URLs by server to avoid duplicates
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

            # Problem 2: Show per-inbound traffic and expiry
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
        await callback.answer("❌ Клиент не найден.", show_alert=True)
        return

    # Get database file path from config
    from app.config import get_settings
    import os

    settings = get_settings()

    # Extract database path from connection URL
    # sqlite+aiosqlite:///./data/vpn_manager.db -> ./data/vpn_manager.db
    db_path = settings.database_url.replace("sqlite+aiosqlite:///", "")

    # Check if database file exists
    if not os.path.exists(db_path):
        await callback.answer("❌ Файл базы данных не найден.", show_alert=True)
        return

    # Check file size
    file_size = os.path.getsize(db_path)
    if file_size > 50 * 1024 * 1024:  # 50 MB limit for Telegram files
        await callback.answer(
            f"❌ Файл базы данных слишком большой ({file_size / (1024*1024):.1f} MB).",
            show_alert=True
        )
        return

    # Create keyboard with format options
    builder = InlineKeyboardBuilder()
    builder.button(text="📄 Как есть (SQLite)", callback_data="export_sqlite")
    builder.button(text="🔙 Назад", callback_data="admin_menu")
    builder.adjust(1)

    await callback.message.edit_text(
        f"📤 Экспорт базы данных\n\n"
        f"Размер: {file_size / (1024*1024):.2f} MB\n\n"
        f"Выберите формат экспорта:",
        reply_markup=builder.as_markup()
    )
    await callback.answer()


@router.callback_query(F.data == "export_sqlite")
async def export_sqlite(callback: CallbackQuery, client) -> None:
    """Export SQLite database file to user (admin only)."""
    if not client or not client.is_admin:
        await callback.answer("❌ Клиент не найден.", show_alert=True)
        return

    try:
        from app.config import get_settings
        import os
        settings = get_settings()
        db_path = settings.database_url.replace("sqlite+aiosqlite:///", "")

        if not os.path.exists(db_path):
            await callback.answer("❌ Файл базы данных не найден.", show_alert=True)
            return

        # Check file size
        file_size = os.path.getsize(db_path)
        if file_size > 50 * 1024 * 1024:
            await callback.answer(
                f"❌ Файл базы данных слишком большой ({file_size / (1024*1024):.1f} MB).",
                show_alert=True
            )
            return

        # Send database file
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        with open(db_path, "rb") as f:
            await callback.message.answer_document(
                document=f,
                filename=f"vpn_manager_{timestamp}.db",
                caption=f"📄 Экспорт базы данных VPN Manager\n"
                f"Размер: {file_size / (1024*1024):.2f} MB\n"
                f"Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}",
            )

        await callback.answer("✅ База данных отправлена!")
        logger.info(f"Database exported by user {client.id}: {db_path}")

    except Exception as e:
        logger.error(f"Error exporting database for user {client.id}: {e}", exc_info=True)
        await callback.answer("❌ Ошибка при экспорте базы данных.", show_alert=True)

