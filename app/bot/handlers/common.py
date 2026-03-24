"""Common handlers for bot."""

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from app.database.models import Client
from app.bot.filters import is_admin_user
from app.bot.keyboards import get_main_menu_keyboard

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext, client: Client | None, is_admin: bool) -> None:
    """Handle /start command."""
    await state.clear()

    text = (
        f"👋 Добро пожаловать в VPN Manager!\n\n"
        f"Этот бот помогает управлять VPN подписками.\n\n"
        f"{'Вы администратор 👑' if is_admin else 'Выберите действие в меню:'}"
    )

    await message.answer(
        text,
        reply_markup=get_main_menu_keyboard(is_admin),
    )


@router.message(Command("cancel"))
@router.callback_query(F.data == "cancel")
async def cmd_cancel(event: Message | CallbackQuery, state: FSMContext) -> None:
    """Handle cancel command."""
    await state.clear()

    if isinstance(event, CallbackQuery):
        await event.message.edit_text(
            "❌ Действие отменено.",
        )
        await event.answer()
    else:
        await event.answer("❌ Действие отменено.")


@router.callback_query(F.data == "admin_menu")
async def show_admin_menu(callback: CallbackQuery, is_admin: bool) -> None:
    """Show admin menu."""
    if not is_admin:
        await callback.answer("❌ У вас нет прав администратора.", show_alert=True)
        return

    await callback.message.edit_text(
        "⚙️ Меню администратора",
        reply_markup=get_main_menu_keyboard(is_admin),
    )
    await callback.answer()


@router.callback_query(F.data == "back")
async def go_back(callback: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    """Handle back button."""
    current_state = await state.get_state()

    if current_state:
        await state.clear()

    await callback.message.edit_text(
        "Главное меню",
        reply_markup=get_main_menu_keyboard(is_admin),
    )
    await callback.answer()
