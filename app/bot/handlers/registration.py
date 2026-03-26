"""Registration handlers for user self-registration."""

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from loguru import logger

from app.bot.states.user import UserRegistration
from app.bot.keyboards import get_registration_keyboard
from app.database import async_session_factory
from app.services.client_service import ClientService
from app.config import get_settings

router = Router()


@router.callback_query(F.data == "start_registration")
async def start_registration(callback: CallbackQuery, state: FSMContext, client):
    """Handle registration button click."""
    if client:
        await callback.answer("Вы уже зарегистрированы!", show_alert=True)
        return

    await state.clear()
    await state.set_state(UserRegistration.choosing_name_source)

    text = (
        "📝 Регистрация в VPN Manager\n\n"
        "Выберите, как вас называть:\n\n"
        "✏️ Ввести имя - вы можете ввести любое имя\n"
        "📱 Использовать Telegram - будет использовано ваше имя из Telegram"
    )

    await callback.message.edit_text(
        text,
        reply_markup=get_registration_keyboard(),
    )
    await callback.answer()


@router.callback_query(UserRegistration.choosing_name_source, F.data == "reg_enter_name")
async def choose_enter_name(callback: CallbackQuery, state: FSMContext):
    """Handle choice to enter custom name."""
    await state.set_state(UserRegistration.entering_custom_name)

    text = (
        "✏️ Введите ваше имя\n\n"
        "Вы можете ввести любое имя, которое будет использоваться в системе."
    )

    await callback.message.edit_text(text)
    await callback.answer()


@router.callback_query(UserRegistration.choosing_name_source, F.data == "reg_use_telegram")
async def choose_use_telegram(
    callback: CallbackQuery,
    state: FSMContext,
    event_from_user
):
    """Handle choice to use Telegram data."""
    # Get Telegram user data
    tg_user = event_from_user
    name = tg_user.full_name or "User"
    telegram_id = tg_user.id
    telegram_username = tg_user.username

    logger.info(f"User registration via Telegram: name={name}, telegram_id={telegram_id}, username={telegram_username}")

    async with async_session_factory() as session:
        client_service = ClientService(session)

        # Check if user already exists (should not happen, but double-check)
        existing_client = await client_service.get_client_by_telegram_id(telegram_id)
        if existing_client:
            await state.clear()
            await callback.answer("Вы уже зарегистрированы!", show_alert=True)
            return

        # Create client with Telegram data
        client = await client_service.create_client(
            name=name,
            telegram_id=telegram_id,
            telegram_username=telegram_username,
            is_admin=False,
        )
        await session.commit()

        logger.info(f"✅ Client created: {client.name} (ID: {client.id}, email: {client.email})")

    await state.clear()

    text = (
        f"✅ Регистрация успешна!\n\n"
        f"👤 Имя: {client.name}\n"
        f"📧 Email: {client.email}\n"
        f"📱 Telegram ID: {client.telegram_id}"
    )

    await callback.message.edit_text(text)
    await callback.answer()


@router.message(UserRegistration.entering_custom_name)
async def handle_custom_name(message: Message, state: FSMContext, event_from_user):
    """Handle custom name input."""
    name = message.text.strip()

    # Basic validation
    if not name:
        await message.answer("⚠️ Имя не может быть пустым. Пожалуйста, введите имя:")
        return

    if len(name) < 2:
        await message.answer("⚠️ Имя слишком короткое. Пожалуйста, введите имя (минимум 2 символа):")
        return

    if len(name) > 100:
        await message.answer("⚠️ Имя слишком длинное. Пожалуйста, введите имя (максимум 100 символов):")
        return

    # Get Telegram data
    tg_user = event_from_user
    telegram_id = tg_user.id
    telegram_username = tg_user.username

    logger.info(f"User registration with custom name: name={name}, telegram_id={telegram_id}, username={telegram_username}")

    async with async_session_factory() as session:
        client_service = ClientService(session)

        # Check if user already exists
        existing_client = await client_service.get_client_by_telegram_id(telegram_id)
        if existing_client:
            await state.clear()
            await message.answer("⚠️ Вы уже зарегистрированы!")
            return

        # Create client with custom name
        client = await client_service.create_client(
            name=name,
            telegram_id=telegram_id,
            telegram_username=telegram_username,
            is_admin=False,
        )
        await session.commit()

        logger.info(f"✅ Client created: {client.name} (ID: {client.id}, email: {client.email})")

    await state.clear()

    text = (
        f"✅ Регистрация успешна!\n\n"
        f"👤 Имя: {client.name}\n"
        f"📧 Email: {client.email}\n"
        f"📱 Telegram ID: {client.telegram_id}"
    )

    await message.answer(text)
