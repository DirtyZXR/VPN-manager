"""Common handlers for bot."""

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.fsm.context import FSMContext

from app.database.models import Client
from app.bot.filters import is_admin_user
from loguru import logger
from app.config import load_instructions, reload_instructions
from app.bot.keyboards import (
    get_main_menu_keyboard,
    get_instruction_menu_keyboard,
    get_step_navigation_keyboard,
)
from app.bot.states.user import InstructionViewing

router = Router()


@router.message(Command("start"))
async def cmd_start(
    message: Message, state: FSMContext, client: Client | None, is_admin: bool
) -> None:
    """Handle /start command."""
    await state.clear()

    text = f"👋 Добро пожаловать в VPN Manager!\n\nЭтот бот помогает управлять VPN подписками.\n\n"

    if client is None:
        text += "Для начала работы, пожалуйста, зарегистрируйтесь:"
    elif is_admin:
        text += "Вы администратор 👑"
    else:
        text += "Выберите действие в меню:"

    await message.answer(
        text,
        reply_markup=get_main_menu_keyboard(is_admin, is_registered=client is not None),
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
    """Show admin menu or redirect to main menu for non-admins."""
    if not is_admin:
        await callback.message.edit_text(
            "Главное меню",
            reply_markup=get_main_menu_keyboard(is_admin),
        )
        await callback.answer()
        return

    await callback.message.edit_text(
        "⚙️ Меню администратора",
        reply_markup=get_main_menu_keyboard(is_admin),
    )
    await callback.answer()


# ==================== INSTRUCTION HANDLERS ====================


@router.callback_query(F.data == "instruction_menu")
async def show_instruction_menu(callback: CallbackQuery) -> None:
    """Show instruction selection menu."""
    await callback.message.edit_text(
        "📖 <b>Инструкция по настройке VPN</b>\n\nВыберите формат:",
        reply_markup=get_instruction_menu_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "instruction_full")
async def show_full_instruction(callback: CallbackQuery) -> None:
    """Show full instruction text."""
    instructions = load_instructions()
    text = instructions.get("full_instruction", "⚠️ Инструкция не найдена.")

    await callback.message.edit_text(
        text,
        reply_markup=get_instruction_menu_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "instruction_step_by_step")
async def start_step_by_step(callback: CallbackQuery, state: FSMContext) -> None:
    """Start step-by-step instruction."""
    instructions = load_instructions()
    steps = instructions.get("step_by_step", {}).get("steps", [])

    if not steps:
        await callback.message.edit_text(
            "⚠️ Пошаговая инструкция не настроена.",
            reply_markup=get_instruction_menu_keyboard(),
        )
        await callback.answer()
        return

    await state.set_state(InstructionViewing.viewing)
    await state.update_data(step=0)
    await _render_step(callback, 0, steps)


@router.callback_query(F.data == "instruction_next")
async def instruction_next_step(callback: CallbackQuery, state: FSMContext) -> None:
    """Go to next instruction step."""
    data = await state.get_data()
    current_step = data.get("step", 0)

    instructions = load_instructions()
    steps = instructions.get("step_by_step", {}).get("steps", [])

    next_step = min(current_step + 1, len(steps) - 1)
    await state.update_data(step=next_step)
    await _render_step(callback, next_step, steps)


@router.callback_query(F.data == "instruction_prev")
async def instruction_prev_step(callback: CallbackQuery, state: FSMContext) -> None:
    """Go to previous instruction step."""
    data = await state.get_data()
    current_step = data.get("step", 0)

    instructions = load_instructions()
    steps = instructions.get("step_by_step", {}).get("steps", [])

    prev_step = max(current_step - 1, 0)
    await state.update_data(step=prev_step)
    await _render_step(callback, prev_step, steps)


@router.callback_query(F.data == "instruction_done")
async def instruction_done(callback: CallbackQuery, state: FSMContext) -> None:
    """Finish step-by-step instruction, return to menu."""
    await state.clear()
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(
        "✅ <b>Настройка завершена!</b>\n\nЕсли возникли проблемы — обратитесь к админу.",
        reply_markup=get_instruction_menu_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "instruction_page_current")
async def instruction_page_current(callback: CallbackQuery) -> None:
    """Ignore clicks on page indicator button."""
    await callback.answer()


async def _render_step(callback: CallbackQuery, step_index: int, steps: list) -> None:
    """Render a single instruction step.

    Args:
        callback: Callback query
        step_index: Step index (0-based)
        steps: List of step dicts from config
    """
    if not steps or step_index >= len(steps):
        await callback.answer("⚠️ Шаг не найден.")
        return

    step = steps[step_index]
    text = step.get("text", "")
    title = step.get("title", f"Шаг {step_index + 1}")
    media_path = step.get("media")
    total = len(steps)

    try:
        await callback.message.delete()
    except Exception:
        pass

    keyboard = get_step_navigation_keyboard(step_index, total)

    if media_path:
        try:
            photo = FSInputFile(media_path)
            await callback.message.answer_photo(
                photo,
                caption=f"{title}\n\n{text}",
                reply_markup=keyboard,
                parse_mode="HTML",
            )
        except Exception as e:
            logger.warning(f"Failed to send instruction media '{media_path}': {e}")
            await callback.message.answer(
                f"<b>{title}</b>\n\n{text}",
                reply_markup=keyboard,
                parse_mode="HTML",
            )
    else:
        await callback.message.answer(
            f"<b>{title}</b>\n\n{text}",
            reply_markup=keyboard,
            parse_mode="HTML",
        )

    await callback.answer()


@router.callback_query(F.data == "back")
async def go_back(callback: CallbackQuery, state: FSMContext, is_admin: bool, client) -> None:
    """Handle back button."""
    current_state = await state.get_state()

    if current_state:
        await state.clear()

    await callback.message.edit_text(
        "Главное меню",
        reply_markup=get_main_menu_keyboard(is_admin, is_registered=client is not None),
    )
    await callback.answer()


@router.callback_query(F.data == "admin_reload_instructions")
async def admin_reload_instructions(callback: CallbackQuery, is_admin: bool) -> None:
    """Admin: reload instructions from YAML file."""
    if not is_admin:
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    try:
        instructions = reload_instructions()
        full_len = len(instructions.get("full_instruction", ""))
        steps_count = len(instructions.get("step_by_step", {}).get("steps", []))
        await callback.answer(
            f"✅ Инструкция обновлена. Полная: {full_len} символов, Шагов: {steps_count}",
            show_alert=True,
        )
    except Exception as e:
        logger.error(f"Failed to reload instructions: {e}", exc_info=True)
        await callback.answer(f"❌ Ошибка: {e}", show_alert=True)
