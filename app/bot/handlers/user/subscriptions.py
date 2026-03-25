"""User subscription management handlers."""

from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from loguru import logger
from urllib.parse import urlparse

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
        status = "✅" if sub.is_active else "❌"
        expiry = sub.expiry_date.strftime("%d.%m.%Y") if sub.expiry_date else "Бессрочно"
        traffic = "Безлимит" if sub.is_unlimited else f"{sub.total_gb} GB"

        text += (
            f"{status} <b>{sub.name}</b>\n"
            f"   Трафик: {traffic}\n"
            f"   Срок: {expiry}\n"
            f"   Подключений: {len(sub.inbound_connections)}\n\n"
        )

        # Add button for each subscription
        builder.button(text=f"📝 {sub.name}", callback_data=f"user_sub_select_{sub.id}")

    builder.button(text="🔗 Все subscription URLs", callback_data="all_sub_urls")
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
    from collections import defaultdict
    grouped_urls = defaultdict(list)
    for url_info in urls:
        grouped_urls[url_info["token"]].append(url_info)

    text = "🔗 Subscription URLs:\n\n"

    for token, url_list in grouped_urls.items():
        sub_name = url_list[0]["subscription_name"]
        text += f"<b>{sub_name}</b>\n"
        text += f"Token: <code>{token}</code>\n"
        text += f"URLs ({len(url_list)}):\n"

        for url_info in url_list:
            text += f"  • {url_info['server_name']} - {url_info['inbound_name']}\n"

        text += "\n"

    builder = InlineKeyboardBuilder()
    builder.button(text="📋 Скопировать все URL", callback_data="copy_all_urls")
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

    status = "✅ Активна" if subscription.is_active else "❌ Неактивна"
    expiry = subscription.expiry_date.strftime("%d.%m.%Y") if subscription.expiry_date else "Бессрочно"
    traffic = "Безлимит" if subscription.is_unlimited else f"{subscription.total_gb} GB"

    text = (
        f"📝 Подписка: <b>{subscription.name}</b>\n\n"
        f"Статус: {status}\n"
        f"Трафик: {traffic}\n"
        f"Срок: {expiry}\n"
        f"Создана: {subscription.created_at.strftime('%d.%m.%Y %H:%M')}\n"
        f"Подключений: {len(subscription.inbound_connections)}\n"
        f"Токен: <code>{subscription.subscription_token}</code>\n\n"
    )

    if subscription.inbound_connections:
        text += "📢 Активные подключения:\n\n"
        for conn in subscription.inbound_connections:
            if conn.is_enabled:
                server = conn.inbound.server
                host = urlparse(server.url).netloc
                text += (
                    f"  • {conn.inbound.remark} ({conn.inbound.protocol})\n"
                    f"    Сервер: {server.name}\n"
                    f"    URL: https://{host}/sub/{subscription.subscription_token}\n\n"
                )

    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад к подпискам", callback_data="my_subscriptions")
    builder.adjust(1)

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()
