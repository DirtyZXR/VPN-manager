"""Admin user management handlers."""

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext

from app.bot.keyboards import (
    get_back_keyboard,
    get_confirm_keyboard,
    get_user_actions_keyboard,
    get_users_keyboard,
)
from app.bot.states import UserManagement
from app.database import async_session_factory
from app.services.user_service import UserService

router = Router()


async def check_admin(callback: CallbackQuery) -> bool:
    """Check if user is admin."""
    is_admin = callback.conf.get("is_admin", False)
    if not is_admin:
        await callback.answer("❌ У вас нет прав администратора.", show_alert=True)
    return is_admin


@router.callback_query(F.data == "admin_users")
async def show_users(callback: CallbackQuery) -> None:
    """Show users list."""
    if not await check_admin(callback):
        return

    async with async_session_factory() as session:
        service = UserService(session)
        users = await service.get_all_users()

    if not users:
        await callback.message.edit_text(
            "👥 Список пользователей пуст.\n\n"
            "Нажмите '➕ Добавить пользователя' для добавления.",
            reply_markup=get_users_keyboard([]),
        )
    else:
        await callback.message.edit_text(
            f"👥 Список пользователей ({len(users)}):",
            reply_markup=get_users_keyboard(users),
        )
    await callback.answer()


@router.callback_query(F.data == "user_add")
async def start_add_user(callback: CallbackQuery, state: FSMContext) -> None:
    """Start adding new user."""
    if not await check_admin(callback):
        return

    await state.set_state(UserManagement.waiting_for_name)
    await callback.message.edit_text(
        "➕ Добавление нового пользователя\n\n"
        "Введите имя пользователя:",
        reply_markup=get_back_keyboard("admin_users"),
    )
    await callback.answer()


@router.message(UserManagement.waiting_for_name)
async def process_user_name(message: Message, state: FSMContext) -> None:
    """Process user name input."""
    await state.update_data(name=message.text)
    await state.set_state(UserManagement.waiting_for_telegram_id)
    await message.answer(
        "Введите Telegram ID пользователя (число) или отправьте '-' чтобы пропустить:",
        reply_markup=get_back_keyboard("admin_users"),
    )


@router.message(UserManagement.waiting_for_telegram_id)
async def process_user_telegram_id(message: Message, state: FSMContext) -> None:
    """Process telegram ID input and create user."""
    data = await state.get_data()

    telegram_id = None
    if message.text != "-":
        try:
            telegram_id = int(message.text)
        except ValueError:
            await message.answer("❌ Telegram ID должен быть числом или '-'.")
            return

    async with async_session_factory() as session:
        service = UserService(session)
        user = await service.create_user(
            name=data["name"],
            telegram_id=telegram_id,
        )
        await session.commit()

    await state.clear()
    await message.answer(
        f"✅ Пользователь '{user.name}' успешно создан!\n\n"
        f"ID: {user.id}\n"
        f"Telegram ID: {user.telegram_id or 'Не указан'}",
        reply_markup=get_back_keyboard("admin_users"),
    )


@router.callback_query(F.data.startswith("user_select_"))
async def select_user(callback: CallbackQuery) -> None:
    """Show user details and actions."""
    if not await check_admin(callback):
        return

    user_id = int(callback.data.split("_")[-1])

    async with async_session_factory() as session:
        service = UserService(session)
        user = await service.get_user_by_id(user_id)

    if not user:
        await callback.answer("❌ Пользователь не найден.", show_alert=True)
        return

    status = "✅ Активен" if user.is_active else "❌ Неактивен"
    admin_badge = " 👑" if user.is_admin else ""

    text = (
        f"👤 Пользователь: {user.name}{admin_badge}\n\n"
        f"ID: {user.id}\n"
        f"Telegram ID: {user.telegram_id or 'Не указан'}\n"
        f"Статус: {status}\n"
        f"Создан: {user.created_at.strftime('%d.%m.%Y %H:%M')}"
    )

    await callback.message.edit_text(
        text,
        reply_markup=get_user_actions_keyboard(user_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("user_rename_"))
async def start_rename_user(callback: CallbackQuery, state: FSMContext) -> None:
    """Start renaming user."""
    if not await check_admin(callback):
        return

    user_id = int(callback.data.split("_")[-1])
    await state.update_data(user_id=user_id)
    await state.set_state(UserManagement.waiting_for_new_name)

    await callback.message.edit_text(
        "Введите новое имя пользователя:",
        reply_markup=get_back_keyboard(f"user_select_{user_id}"),
    )
    await callback.answer()


@router.message(UserManagement.waiting_for_new_name)
async def process_rename_user(message: Message, state: FSMContext) -> None:
    """Process user rename."""
    data = await state.get_data()
    user_id = data["user_id"]

    async with async_session_factory() as session:
        service = UserService(session)
        user = await service.rename_user(user_id, message.text)
        await session.commit()

    await state.clear()
    await message.answer(
        f"✅ Пользователь переименован в '{user.name}'",
        reply_markup=get_back_keyboard(f"user_select_{user_id}"),
    )


@router.callback_query(F.data.startswith("user_enable_"))
async def enable_user(callback: CallbackQuery) -> None:
    """Enable user."""
    if not await check_admin(callback):
        return

    user_id = int(callback.data.split("_")[-1])

    async with async_session_factory() as session:
        service = UserService(session)
        await service.set_user_active(user_id, True)
        await session.commit()

    await callback.answer("✅ Пользователь включен.")
    # Re-select to refresh view
    callback.data = f"user_select_{user_id}"
    await select_user(callback)


@router.callback_query(F.data.startswith("user_disable_"))
async def disable_user(callback: CallbackQuery) -> None:
    """Disable user."""
    if not await check_admin(callback):
        return

    user_id = int(callback.data.split("_")[-1])

    async with async_session_factory() as session:
        service = UserService(session)
        await service.set_user_active(user_id, False)
        await session.commit()

    await callback.answer("✅ Пользователь отключен.")
    callback.data = f"user_select_{user_id}"
    await select_user(callback)


@router.callback_query(F.data.startswith("user_delete_"))
async def confirm_delete_user(callback: CallbackQuery, state: FSMContext) -> None:
    """Confirm user deletion."""
    if not await check_admin(callback):
        return

    user_id = int(callback.data.split("_")[-1])
    await state.update_data(user_id=user_id)
    await state.set_state(UserManagement.confirm_delete)

    await callback.message.edit_text(
        "⚠️ Вы уверены, что хотите удалить этого пользователя?\n\n"
        "Все его подписки будут также удалены!",
        reply_markup=get_confirm_keyboard(f"user_delete_{user_id}", "admin_users"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("confirm_user_delete_"))
async def delete_user(callback: CallbackQuery, state: FSMContext) -> None:
    """Delete user."""
    if not await check_admin(callback):
        return

    user_id = int(callback.data.split("_")[-1])

    async with async_session_factory() as session:
        service = UserService(session)
        await service.delete_user(user_id)
        await session.commit()

    await state.clear()
    await callback.answer("✅ Пользователь удален.")
    await show_users(callback)
