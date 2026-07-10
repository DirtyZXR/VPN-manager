"""Экран и мастер импорта созданных вручную клиентов XUI-панели."""

import html

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.bot.filters import AdminFilter
from app.bot.keyboards.inline import (
    get_unmanaged_import_wizard_keyboard,
    get_unmanaged_list_keyboard,
)
from app.bot.states.admin import ManualImport
from app.database import async_session_factory
from app.database.models import Client, Server
from app.services.manual_client_service import ManualClientService

router = Router()
router.message.filter(AdminFilter())
router.callback_query.filter(AdminFilter())

_PER_PAGE = 5


async def _load_xui_server(session, server_id: int) -> Server | None:
    """Сервер с eager-загруженной XUI-панелью (нужно для XUIService._get_client)."""
    server = (
        await session.execute(
            select(Server)
            .where(Server.id == server_id)
            .options(selectinload(Server.xui_panel))
        )
    ).scalar_one_or_none()
    if server is None or server.xui_panel is None:
        return None
    return server


def _servers_keyboard(servers: list):
    builder = InlineKeyboardBuilder()
    for s in servers:
        builder.button(text=f"🖥 {s.name}", callback_data=f"uimp:server:{s.id}")
    builder.button(text="🔙 Назад", callback_data="admin_infra_menu")
    builder.adjust(1)
    return builder.as_markup()


def _client_pick_keyboard(clients: list, page: int, total: int, per_page: int = _PER_PAGE):
    builder = InlineKeyboardBuilder()
    for c in clients:
        builder.button(text=f"👤 {c.name}", callback_data=f"uimp:pick:{c.id}")
    builder.adjust(1)
    total_pages = max(1, -(-total // per_page))
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"uimp:pickpage:{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"uimp:pickpage:{page + 1}"))
    if nav:
        builder.row(*nav)
    return builder.as_markup()


@router.callback_query(F.data == "unmanaged_menu")
async def unmanaged_menu(callback: CallbackQuery) -> None:
    """Список XUI-серверов для сканирования неуправляемых клиентов."""
    async with async_session_factory() as session:
        servers = (
            await session.execute(
                select(Server)
                .where(Server.is_active)
                .options(selectinload(Server.xui_panel))
                .order_by(Server.name)
            )
        ).scalars().all()
        xui_servers = [s for s in servers if s.xui_panel is not None]

    if not xui_servers:
        await callback.message.edit_text(
            "Нет активных XUI-серверов.", reply_markup=_servers_keyboard([])
        )
        await callback.answer()
        return

    await callback.message.edit_text(
        "🔍 Выберите сервер для поиска неуправляемых клиентов:",
        reply_markup=_servers_keyboard(xui_servers),
    )
    await callback.answer()


async def _show_unmanaged_list(callback: CallbackQuery, state: FSMContext, server_id: int, page: int):
    async with async_session_factory() as session:
        server = await _load_xui_server(session, server_id)
        if server is None:
            await callback.answer("Сервер не найден или не XUI", show_alert=True)
            return
        items = await ManualClientService(session).list_unmanaged(server)

    # Запоминаем email по индексу — действия accept/del работают по индексу.
    await state.update_data(
        umc_server_id=server_id, umc_emails=[it.email for it in items]
    )

    if not items:
        await callback.message.edit_text(
            f"✅ На сервере «{server.name}» неуправляемых клиентов нет.",
            reply_markup=_servers_keyboard([]),
        )
        await callback.answer()
        return

    await callback.message.edit_text(
        f"🔍 Неуправляемые клиенты сервера «{server.name}»: {len(items)}\n"
        "✅ — можно импортировать, ⚠️ — inbound вне БД (только удалить).",
        reply_markup=get_unmanaged_list_keyboard(server_id, items, page=page, per_page=_PER_PAGE),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("uimp:server:"))
async def unmanaged_server(callback: CallbackQuery, state: FSMContext) -> None:
    server_id = int(callback.data.split(":")[2])
    await _show_unmanaged_list(callback, state, server_id, page=0)


@router.callback_query(F.data.startswith("uimp:page:"))
async def unmanaged_page(callback: CallbackQuery, state: FSMContext) -> None:
    _, _, server_id, page = callback.data.split(":")
    await _show_unmanaged_list(callback, state, int(server_id), page=int(page))


@router.callback_query(F.data.startswith("uimp:noop:"))
async def unmanaged_noop(callback: CallbackQuery) -> None:
    await callback.answer()


async def _email_by_idx(state: FSMContext, idx: int) -> str | None:
    data = await state.get_data()
    emails = data.get("umc_emails") or []
    if 0 <= idx < len(emails):
        return emails[idx]
    return None


@router.callback_query(F.data.startswith("uimp:accept:"))
async def unmanaged_accept(callback: CallbackQuery, state: FSMContext) -> None:
    """Начать импорт: выбрать/создать клиента."""
    _, _, server_id, idx = callback.data.split(":")
    email = await _email_by_idx(state, int(idx))
    if email is None:
        await callback.answer("Список устарел, откройте заново", show_alert=True)
        return
    await state.update_data(umc_server_id=int(server_id), umc_panel_email=email)
    await callback.message.edit_text(
        f"Импорт клиента <code>{html.escape(email)}</code>\nК кому привязать подписку?",
        parse_mode="HTML",
        reply_markup=get_unmanaged_import_wizard_keyboard(int(server_id), int(idx)),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("uimp:new:"))
async def unmanaged_new_client(callback: CallbackQuery, state: FSMContext) -> None:
    """Создать нового клиента — спросить имя."""
    await state.set_state(ManualImport.entering_new_name)
    await callback.message.edit_text("Введите имя нового клиента:")
    await callback.answer()


@router.message(ManualImport.entering_new_name)
async def unmanaged_new_client_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if not name:
        await message.answer("Имя не может быть пустым. Введите имя:")
        return
    data = await state.get_data()
    server_id = data.get("umc_server_id")
    panel_email = data.get("umc_panel_email")
    await state.clear()
    if not server_id or not panel_email:
        await message.answer("❌ Контекст импорта устарел, начните заново.")
        return

    try:
        async with async_session_factory() as session:
            server = await _load_xui_server(session, int(server_id))
            if server is None:
                await message.answer("❌ Сервер не найден.")
                return
            svc = ManualClientService(session)
            client = await svc.create_import_client(name)
            sub = await svc.import_client(server, panel_email, client.id)
            await session.commit()
    except Exception as e:
        logger.error("Ошибка импорта '{}': {}", panel_email, e)
        await message.answer("❌ Ошибка импорта, см. логи.")
        return

    await _import_result(message, sub, panel_email)


@router.callback_query(F.data.startswith("uimp:existing:"))
async def unmanaged_existing(callback: CallbackQuery, state: FSMContext) -> None:
    await _show_client_pick(callback, page=0)
    await callback.answer()


@router.callback_query(F.data.startswith("uimp:pickpage:"))
async def unmanaged_pick_page(callback: CallbackQuery) -> None:
    page = int(callback.data.split(":")[2])
    await _show_client_pick(callback, page=page)
    await callback.answer()


async def _show_client_pick(callback: CallbackQuery, page: int):
    async with async_session_factory() as session:
        total = (
            await session.execute(select(func.count()).select_from(Client).where(Client.is_active))
        ).scalar() or 0
        clients = (
            await session.execute(
                select(Client)
                .where(Client.is_active)
                .order_by(Client.id)
                .limit(_PER_PAGE)
                .offset(page * _PER_PAGE)
            )
        ).scalars().all()
    await callback.message.edit_text(
        "Выберите клиента для привязки:",
        reply_markup=_client_pick_keyboard(clients, page, total),
    )


@router.callback_query(F.data.startswith("uimp:pick:"))
async def unmanaged_pick_client(callback: CallbackQuery, state: FSMContext) -> None:
    client_id = int(callback.data.split(":")[2])
    data = await state.get_data()
    server_id = data.get("umc_server_id")
    panel_email = data.get("umc_panel_email")
    if not server_id or not panel_email:
        await callback.answer("Контекст устарел, начните заново", show_alert=True)
        return

    try:
        async with async_session_factory() as session:
            server = await _load_xui_server(session, int(server_id))
            if server is None:
                await callback.answer("Сервер не найден", show_alert=True)
                return
            sub = await ManualClientService(session).import_client(server, panel_email, client_id)
            await session.commit()
    except Exception as e:
        logger.error("Ошибка импорта '{}': {}", panel_email, e)
        await callback.answer("❌ Ошибка импорта, см. логи", show_alert=True)
        return

    await _import_result(callback.message, sub, panel_email)
    await callback.answer()


@router.callback_query(F.data.startswith("uimp:del:"))
async def unmanaged_delete_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    _, _, server_id, idx = callback.data.split(":")
    email = await _email_by_idx(state, int(idx))
    if email is None:
        await callback.answer("Список устарел, откройте заново", show_alert=True)
        return
    builder = InlineKeyboardBuilder()
    builder.button(text="🗑 Удалить", callback_data=f"uimp:delok:{server_id}:{idx}")
    builder.button(text="🔙 Отмена", callback_data=f"uimp:server:{server_id}")
    builder.adjust(1)
    await callback.message.edit_text(
        f"Удалить клиента <code>{html.escape(email)}</code> с панели? Действие необратимо.",
        parse_mode="HTML",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("uimp:delok:"))
async def unmanaged_delete(callback: CallbackQuery, state: FSMContext) -> None:
    _, _, server_id, idx = callback.data.split(":")
    email = await _email_by_idx(state, int(idx))
    if email is None:
        await callback.answer("Список устарел", show_alert=True)
        return
    async with async_session_factory() as session:
        server = await _load_xui_server(session, int(server_id))
        if server is None:
            await callback.answer("Сервер не найден", show_alert=True)
            return
        try:
            await ManualClientService(session).delete_from_panel(server, email)
            await session.commit()
        except Exception as e:
            logger.error("Ошибка удаления '{}' с панели: {}", email, e)
            await callback.answer("❌ Ошибка, см. логи", show_alert=True)
            return
    await _show_unmanaged_list(callback, state, int(server_id), page=0)


async def _import_result(message: Message, sub, panel_email: str) -> None:
    """Отправить итог импорта новым сообщением (edit недоступен для message пользователя)."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 К инфраструктуре", callback_data="admin_infra_menu")
    builder.adjust(1)
    if sub is None:
        await message.answer(
            f"❌ Клиент <code>{html.escape(panel_email)}</code> больше не найден на панели.",
            parse_mode="HTML",
            reply_markup=builder.as_markup(),
        )
        return
    await message.answer(
        f"✅ Клиент <code>{html.escape(panel_email)}</code> импортирован "
        f"(подписка «{html.escape(sub.name or '')}», "
        f"токен <code>{html.escape(sub.subscription_token or '')}</code>).",
        parse_mode="HTML",
        reply_markup=builder.as_markup(),
    )
