"""Common handlers for bot."""

import contextlib

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, Message
from loguru import logger

from app.bot.keyboards import (
    get_faq_answer_keyboard,
    get_faq_list_keyboard,
    get_help_main_keyboard,
    get_instruction_menu_keyboard,
    get_main_menu_keyboard,
    get_step_navigation_keyboard,
)
from app.bot.states.user import InstructionViewing
from app.config import load_instructions, reload_instructions
from app.database.models import Client

router = Router()


@router.message(Command("start"))
async def cmd_start(
    message: Message, state: FSMContext, client: Client | None, is_admin: bool
) -> None:
    """Handle /start command."""
    await state.clear()

    text = "👋 Добро пожаловать в VPN Manager!\n\nЭтот бот помогает управлять VPN подписками.\n\n"

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
async def show_admin_menu(callback: CallbackQuery, is_admin: bool, client: Client | None) -> None:
    """Show admin menu or redirect to main menu for non-admins."""
    text = "⚙️ Меню администратора" if is_admin else "Главное меню"
    reply_markup = get_main_menu_keyboard(is_admin, is_registered=client is not None)

    try:
        await callback.message.edit_text(text, reply_markup=reply_markup)
    except Exception:
        with contextlib.suppress(Exception):
            await callback.message.delete()
        await callback.message.answer(text, reply_markup=reply_markup)
    await callback.answer()


# ==================== INSTRUCTION HANDLERS ====================


@router.callback_query(F.data == "instruction_menu")
@router.callback_query(F.data == "help_main")
async def show_instruction_menu(callback: CallbackQuery) -> None:
    """Show instruction selection menu."""
    text = "Выберите операционную систему или раздел:"
    reply_markup = get_help_main_keyboard()

    try:
        await callback.message.edit_text(text, reply_markup=reply_markup)
    except Exception:
        with contextlib.suppress(Exception):
            await callback.message.delete()
        await callback.message.answer(text, reply_markup=reply_markup)
    await callback.answer()


@router.callback_query(F.data.startswith("help_os_"))
async def show_os_instruction_menu(callback: CallbackQuery) -> None:
    """Show instruction formats for specific OS."""
    os_name = callback.data.replace("help_os_", "")
    text = f"Выберите тип инструкции для {os_name}:"
    reply_markup = get_instruction_menu_keyboard(os_name)

    try:
        await callback.message.edit_text(text, reply_markup=reply_markup)
    except Exception:
        with contextlib.suppress(Exception):
            await callback.message.delete()
        await callback.message.answer(text, reply_markup=reply_markup)
    await callback.answer()


@router.callback_query(F.data.startswith("instruction_full_"))
async def show_full_instruction(callback: CallbackQuery) -> None:
    """Show full instruction text."""
    os_name = callback.data.replace("instruction_full_", "")
    instructions = load_instructions()
    text = instructions.get(os_name, {}).get("full_instruction", "⚠️ Инструкция не найдена.")
    reply_markup = get_instruction_menu_keyboard(os_name)

    try:
        await callback.message.edit_text(text, reply_markup=reply_markup, parse_mode="HTML")
    except Exception:
        with contextlib.suppress(Exception):
            await callback.message.delete()
        await callback.message.answer(text, reply_markup=reply_markup, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("instruction_step_by_step_"))
async def start_step_by_step(callback: CallbackQuery, state: FSMContext) -> None:
    """Start step-by-step instruction."""
    os_name = callback.data.replace("instruction_step_by_step_", "")
    instructions = load_instructions()
    steps = instructions.get(os_name, {}).get("step_by_step", {}).get("steps", [])

    if not steps:
        await callback.message.edit_text(
            "⚠️ Пошаговая инструкция не настроена.",
            reply_markup=get_instruction_menu_keyboard(os_name),
        )
        await callback.answer()
        return

    await state.set_state(InstructionViewing.viewing)
    await state.update_data(step=0, os_name=os_name)
    await _render_step(callback, 0, state)


@router.callback_query(F.data == "instruction_next")
async def instruction_next_step(callback: CallbackQuery, state: FSMContext) -> None:
    """Go to next instruction step."""
    data = await state.get_data()
    current_step = data.get("step", 0)
    os_name = data.get("os_name", "")

    instructions = load_instructions()
    steps = instructions.get(os_name, {}).get("step_by_step", {}).get("steps", [])

    next_step = min(current_step + 1, len(steps) - 1)
    await state.update_data(step=next_step)
    await _render_step(callback, next_step, state)


@router.callback_query(F.data == "instruction_prev")
async def instruction_prev_step(callback: CallbackQuery, state: FSMContext) -> None:
    """Go to previous instruction step."""
    data = await state.get_data()
    current_step = data.get("step", 0)
    os_name = data.get("os_name", "")

    instructions = load_instructions()
    steps = instructions.get(os_name, {}).get("step_by_step", {}).get("steps", [])

    prev_step = max(current_step - 1, 0)
    await state.update_data(step=prev_step)
    await _render_step(callback, prev_step, state)


@router.callback_query(F.data == "instruction_done")
async def instruction_done(callback: CallbackQuery, state: FSMContext) -> None:
    """Finish step-by-step instruction, return to menu."""
    await state.clear()
    with contextlib.suppress(Exception):
        await callback.message.delete()
    await callback.message.answer(
        "✅ <b>Настройка завершена!</b>\n\nЕсли возникли проблемы — обратитесь к админу.",
        reply_markup=get_help_main_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "instruction_page_current")
async def instruction_page_current(callback: CallbackQuery) -> None:
    """Ignore clicks on page indicator button."""
    await callback.answer()


async def _render_step(callback: CallbackQuery, step_index: int, state: FSMContext) -> None:
    """Render a single instruction step.

    Args:
        callback: Callback query
        step_index: Step index (0-based)
        state: FSM context to get os_name
    """
    data = await state.get_data()
    os_name = data.get("os_name", "")
    instructions = load_instructions()
    steps = instructions.get(os_name, {}).get("step_by_step", {}).get("steps", [])

    if not steps or step_index >= len(steps):
        await callback.answer("⚠️ Шаг не найден.")
        return

    step = steps[step_index]
    text = step.get("text", "")
    title = step.get("title", f"Шаг {step_index + 1}")
    media_path = step.get("media")
    total = len(steps)

    with contextlib.suppress(Exception):
        await callback.message.delete()

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

    text = "Главное меню"
    reply_markup = get_main_menu_keyboard(is_admin, is_registered=client is not None)

    try:
        await callback.message.edit_text(text, reply_markup=reply_markup)
    except Exception:
        with contextlib.suppress(Exception):
            await callback.message.delete()
        await callback.message.answer(text, reply_markup=reply_markup)
    await callback.answer()


@router.callback_query(F.data == "faq_main")
async def faq_main(callback: CallbackQuery) -> None:
    """Show FAQ main menu."""
    faq_list = load_instructions().get("faq", {}).get("faq", [])
    if not faq_list:
        await callback.message.edit_text(
            "Частые вопросы пока не добавлены.", reply_markup=get_help_main_keyboard()
        )
        await callback.answer()
        return

    await callback.message.edit_text(
        "Частые вопросы:",
        reply_markup=get_faq_list_keyboard(faq_list),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("faq_q_"))
async def show_faq_answer(callback: CallbackQuery) -> None:
    """Show FAQ answer."""
    try:
        index = int(callback.data.replace("faq_q_", ""))
        faq_list = load_instructions().get("faq", {}).get("faq", [])
        if 0 <= index < len(faq_list):
            item = faq_list[index]
            text = f"<b>{item['question']}</b>\n\n{item['answer']}"
        else:
            text = "Вопрос не найден."
    except Exception:
        text = "Ошибка при загрузке вопроса."

    await callback.message.edit_text(
        text,
        reply_markup=get_faq_answer_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "admin_reload_instructions")
async def admin_reload_instructions(callback: CallbackQuery, is_admin: bool) -> None:
    """Admin: reload instructions from YAML file."""
    if not is_admin:
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    try:
        reload_instructions()
        await callback.answer(
            "✅ Инструкции перезагружены",
            show_alert=True,
        )
    except Exception as e:
        logger.error(f"Failed to reload instructions: {e}", exc_info=True)
        await callback.answer(f"❌ Ошибка: {e}", show_alert=True)
