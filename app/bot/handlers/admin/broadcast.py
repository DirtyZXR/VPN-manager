"""Broadcast handlers for admin."""

import asyncio

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from loguru import logger

from app.bot.keyboards.inline import get_back_keyboard, get_confirm_keyboard
from app.bot.states.admin import BroadcastManagement
from app.database import async_session_factory
from app.services.client_service import ClientService
from app.utils.texts import t

router = Router()


@router.callback_query(F.data == "admin_broadcast")
async def start_broadcast(callback: CallbackQuery, is_admin: bool, state: FSMContext) -> None:
    """Start broadcast flow."""
    if not is_admin:
        await callback.answer(
            t("errors.admin_only", "❌ У вас нет прав администратора."), show_alert=True
        )
        return

    await state.clear()
    await state.set_state(BroadcastManagement.waiting_for_message)

    await callback.message.edit_text(
        t(
            "admin.broadcast.prompt",
            "📢 <b>Рассылка уведомлений</b>\n\n"
            "Введите сообщение, которое будет отправлено всем пользователям бота.\n\n"
            "Вы можете использовать форматирование Telegram (жирный, курсив и т.д.).",
        ),
        reply_markup=get_back_keyboard("admin_clients_menu"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(BroadcastManagement.waiting_for_message)
async def process_broadcast_message(message: Message, state: FSMContext, is_admin: bool) -> None:
    """Process broadcast message input and ask for confirmation."""
    if not is_admin:
        return

    if not message.text and not message.caption:
        await message.answer(
            t(
                "admin.broadcast.error_no_text",
                "❌ Сообщение должно содержать текст. Попробуйте еще раз:",
            ),
            reply_markup=get_back_keyboard("admin_clients_menu"),
        )
        return

    # Store the message_id to forward/copy it later
    await state.update_data(message_id=message.message_id, chat_id=message.chat.id)
    await state.set_state(BroadcastManagement.confirm_broadcast)

    async with async_session_factory() as session:
        client_service = ClientService(session)
        clients = await client_service.get_active_clients()
        # count only clients with telegram_id
        valid_clients = [c for c in clients if c.telegram_id]

    await message.answer(
        t(
            "admin.broadcast.confirm",
            "📢 <b>Подтверждение рассылки</b>\n\n"
            "Это сообщение будет отправлено <b>{count}</b> пользователям.\n"
            "Начать рассылку?",
            count=len(valid_clients),
        ),
        reply_markup=get_confirm_keyboard("start_broadcast", "cancel_broadcast"),
        parse_mode="HTML",
    )


async def _run_broadcast(
    bot,
    admin_chat_id: int,
    status_message_id: int,
    source_chat_id: int,
    source_message_id: int,
    clients: list,
) -> None:
    """Run the broadcast loop in the background and update status when done."""
    success_count = 0
    fail_count = 0

    for client in clients:
        try:
            await bot.copy_message(
                chat_id=client.telegram_id,
                from_chat_id=source_chat_id,
                message_id=source_message_id,
            )
            success_count += 1
        except Exception as e:
            logger.warning(f"Failed to send broadcast to {client.telegram_id}: {e}")
            fail_count += 1

        # Add a small delay to avoid hitting Telegram rate limits (30 msgs/sec max)
        await asyncio.sleep(0.05)

    text = t(
        "admin.broadcast.completed",
        "✅ <b>Рассылка завершена!</b>\n\nУспешно доставлено: {success}\nОшибок: {fail}",
        success=success_count,
        fail=fail_count,
    )

    try:
        await bot.edit_message_text(
            chat_id=admin_chat_id,
            message_id=status_message_id,
            text=text,
            reply_markup=get_back_keyboard("admin_clients_menu"),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"Failed to edit broadcast status message: {e}")
        # Fallback if editing is forbidden (e.g. older than 48h) or not modified
        await bot.send_message(
            chat_id=admin_chat_id,
            text=text,
            reply_markup=get_back_keyboard("admin_clients_menu"),
            parse_mode="HTML",
        )


@router.callback_query(BroadcastManagement.confirm_broadcast, F.data == "confirm_start_broadcast")
async def confirm_broadcast(callback: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    """Confirm and execute broadcast."""
    if not is_admin:
        await callback.answer(
            t("errors.admin_only", "❌ У вас нет прав администратора."), show_alert=True
        )
        return

    data = await state.get_data()
    message_id = data.get("message_id")
    chat_id = data.get("chat_id")

    if not message_id or not chat_id:
        await callback.answer(
            t("errors.unknown", "❌ Произошла неизвестная ошибка."), show_alert=True
        )
        await state.clear()
        return

    # Acknowledge immediately so the Telegram client spinner stops
    await callback.answer()

    # Change text to "in progress"
    await callback.message.edit_text(
        t("admin.broadcast.in_progress", "⏳ Рассылка началась... Пожалуйста, подождите."),
        reply_markup=None,
    )

    async with async_session_factory() as session:
        client_service = ClientService(session)
        clients = await client_service.get_active_clients()

    valid_clients = [c for c in clients if c.telegram_id]

    await state.clear()

    # Launch background task
    asyncio.create_task(
        _run_broadcast(
            bot=callback.bot,
            admin_chat_id=callback.message.chat.id,
            status_message_id=callback.message.message_id,
            source_chat_id=chat_id,
            source_message_id=message_id,
            clients=valid_clients,
        )
    )


@router.callback_query(BroadcastManagement.confirm_broadcast, F.data == "cancel_broadcast")
async def cancel_broadcast(callback: CallbackQuery, state: FSMContext) -> None:
    """Cancel broadcast."""
    await state.clear()
    await callback.message.edit_text(
        t("common.cancelled", "❌ Действие отменено."),
        reply_markup=get_back_keyboard("admin_clients_menu"),
    )
    await callback.answer()
