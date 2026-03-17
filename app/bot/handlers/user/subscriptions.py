"""User subscription handlers."""

from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.keyboards import get_back_keyboard, get_copy_keyboard
from app.database import async_session_factory
from app.database.models import User
from app.services.subscription_service import SubscriptionService

router = Router()


@router.callback_query(F.data == "my_subscriptions")
async def show_my_subscriptions(callback: CallbackQuery) -> None:
    """Show user's subscriptions."""
    user: User | None = callback.conf.get("user")

    if not user:
        await callback.answer(
            "❌ Вы не зарегистрированы в системе. Обратитесь к администратору.",
            show_alert=True,
        )
        return

    async with async_session_factory() as session:
        service = SubscriptionService(session)
        user_data = await service.get_user_with_subscriptions(user.id)

    if not user_data or not user_data.subscription_groups:
        await callback.answer(
            "❌ У вас нет активных подписок.",
            show_alert=True,
        )
        return

    # Build subscription info
    text = "📋 Ваши подписки:\n\n"

    for group in user_data.subscription_groups:
        text += f"📁 Группа: {group.name}\n"

        for server_sub in group.server_subscriptions:
            server = server_sub.server
            text += f"  🌐 {server.name}\n"

            for profile in server_sub.profiles:
                status = "✅" if profile.is_enabled else "❌"
                inbound = profile.inbound
                text += f"    {status} {inbound.remark}\n"

        text += "\n"

    # Create keyboard with actions
    builder = InlineKeyboardBuilder()
    builder.button(text="🔗 Все subscription URLs", callback_data="all_sub_urls")
    builder.button(text="📋 Скопировать все ссылки", callback_data="copy_all_links")
    builder.button(text="🔙 Назад", callback_data="back")
    builder.adjust(1)

    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data == "all_sub_urls")
async def show_all_sub_urls(callback: CallbackQuery) -> None:
    """Show all subscription URLs."""
    user: User | None = callback.conf.get("user")

    if not user:
        await callback.answer("❌ Вы не зарегистрированы.", show_alert=True)
        return

    async with async_session_factory() as session:
        service = SubscriptionService(session)
        urls = await service.get_subscription_urls(user.id)

    if not urls:
        await callback.answer("❌ У вас нет подписок.", show_alert=True)
        return

    # Build URLs text
    text = "🔗 Ваши subscription URLs:\n\n"

    for url_info in urls:
        text += f"📁 {url_info['group_name']} / 🌐 {url_info['server_name']}:\n"
        text += f"`{url_info['url']}`\n\n"

    # Create keyboard with copy button
    all_urls = "\n".join([u["url"] for u in urls])

    builder = InlineKeyboardBuilder()
    builder.button(text="📋 Скопировать все", copy_text=all_urls)
    builder.button(text="🔙 Назад", callback_data="my_subscriptions")
    builder.adjust(1)

    await callback.message.edit_text(
        text,
        reply_markup=builder.as_markup(),
        parse_mode="Markdown",
    )
    await callback.answer()


@router.callback_query(F.data == "copy_all_links")
async def copy_all_links(callback: CallbackQuery) -> None:
    """Send all links as copyable message."""
    user: User | None = callback.conf.get("user")

    if not user:
        await callback.answer("❌ Вы не зарегистрированы.", show_alert=True)
        return

    async with async_session_factory() as session:
        service = SubscriptionService(session)
        urls = await service.get_subscription_urls(user.id)

    if not urls:
        await callback.answer("❌ У вас нет подписок.", show_alert=True)
        return

    # Build plain text for easy copying
    all_urls = "\n".join([u["url"] for u in urls])

    await callback.message.answer(
        f"📋 Все subscription URLs:\n\n```\n{all_urls}\n```",
        parse_mode="Markdown",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("profile_enable_"))
async def enable_profile(callback: CallbackQuery) -> None:
    """Enable profile (admin only)."""
    is_admin = callback.conf.get("is_admin", False)
    if not is_admin:
        await callback.answer("❌ Только администратор может это сделать.", show_alert=True)
        return

    profile_id = int(callback.data.split("_")[-1])

    async with async_session_factory() as session:
        service = SubscriptionService(session)
        profile = await service.enable_profile(profile_id, True)
        await session.commit()

    if profile:
        await callback.answer("✅ Профиль включен.")
    else:
        await callback.answer("❌ Профиль не найден.", show_alert=True)


@router.callback_query(F.data.startswith("profile_disable_"))
async def disable_profile(callback: CallbackQuery) -> None:
    """Disable profile (admin only)."""
    is_admin = callback.conf.get("is_admin", False)
    if not is_admin:
        await callback.answer("❌ Только администратор может это сделать.", show_alert=True)
        return

    profile_id = int(callback.data.split("_")[-1])

    async with async_session_factory() as session:
        service = SubscriptionService(session)
        profile = await service.enable_profile(profile_id, False)
        await session.commit()

    if profile:
        await callback.answer("✅ Профиль отключен.")
    else:
        await callback.answer("❌ Профиль не найден.", show_alert=True)


@router.callback_query(F.data.startswith("profile_delete_"))
async def delete_profile(callback: CallbackQuery) -> None:
    """Delete profile (admin only)."""
    is_admin = callback.conf.get("is_admin", False)
    if not is_admin:
        await callback.answer("❌ Только администратор может это сделать.", show_alert=True)
        return

    profile_id = int(callback.data.split("_")[-1])

    async with async_session_factory() as session:
        service = SubscriptionService(session)
        success = await service.delete_profile(profile_id)
        await session.commit()

    if success:
        await callback.answer("✅ Профиль удален.")
    else:
        await callback.answer("❌ Профиль не найден.", show_alert=True)
