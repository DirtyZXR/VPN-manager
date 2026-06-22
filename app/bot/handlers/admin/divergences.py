"""Хендлеры решений администратора по расхождениям БД ↔ панель."""

import html

from aiogram import F, Router
from aiogram.types import CallbackQuery
from loguru import logger

from app.bot.filters import AdminFilter
from app.bot.keyboards.inline import get_divergence_item_keyboard
from app.database import async_session_factory
from app.database.models import PendingDivergence
from app.services.divergence_service import (
    DECISION_APPLY,
    DECISION_IGNORE,
    DECISION_SAVE,
    KIND_EXTRA,
    KIND_MISSING,
    STATUS_OPEN,
    DivergenceService,
)
from app.services.notification_service import NotificationService

router = Router()
router.callback_query.filter(AdminFilter())

_ACTION = {"apply": DECISION_APPLY, "save": DECISION_SAVE, "ignore": DECISION_IGNORE}


def _item_text(pd: PendingDivergence, idx: int, total: int) -> str:
    """Текст карточки одного расхождения в пошаговом разборе."""
    if pd.kind == KIND_MISSING:
        kind_label = "📉 пропал с панели (в БД есть, на панели нет)"
        apply_desc = "удалить запись из БД"
        save_desc = "восстановить клиента на панели из БД"
    else:
        kind_label = "📈 лишнее на панели (на панели есть, в БД нет)"
        apply_desc = "убрать с панели (detach осиротевшего / delete зомби)"
        save_desc = "принять в БД (создать строки под факт панели)"
    return (
        f"Расхождение {idx + 1} / {total}\n"
        f"Клиент: <code>{html.escape(pd.email)}</code>\n"
        f"Тип: {kind_label}\n\n"
        f"🗑 Применить — {apply_desc}\n"
        f"💾 Сохранить — {save_desc}\n"
        f"💤 Игнорировать — оставить как есть, спросить позже"
    )


async def _client_if_needed(session, pd: PendingDivergence, decision: str, cache: dict):
    """Подключённый XUIClient, если решение требует операции на панели; иначе None.

    Панель нужна только для: extra+apply (detach/delete) и missing+save (restore).
    Для missing+apply (удаление БД) и extra+save (adopt) клиент не требуется.
    """
    needs = (pd.kind == KIND_EXTRA and decision == DECISION_APPLY) or (
        pd.kind == KIND_MISSING and decision == DECISION_SAVE
    )
    if not needs:
        return None
    if pd.server_id in cache:
        return cache[pd.server_id]

    from app.database.models import Server
    from app.services.xui_service import XUIService

    client = None
    server = await session.get(Server, pd.server_id)
    if server is not None:
        try:
            client = await XUIService(session)._get_client(server)
        except Exception as e:
            logger.warning("Не удалось подключиться к панели сервера {}: {}", pd.server_id, e)
    cache[pd.server_id] = client
    return client


@router.callback_query(F.data.startswith("div:item:"))
async def divergence_item(callback: CallbackQuery):
    """Решение по одному расхождению (🗑/💾/💤)."""
    parts = callback.data.split(":")
    if len(parts) != 6:
        await callback.answer()
        return
    action, pid_s, batch = parts[2], parts[3], parts[4]
    decision = _ACTION.get(action)
    if decision is None:
        await callback.answer()
        return

    async with async_session_factory() as session:
        pd = await session.get(PendingDivergence, int(pid_s))
        if pd is not None and pd.status == STATUS_OPEN:
            svc = DivergenceService(session)
            xui = await _client_if_needed(session, pd, decision, {})
            try:
                await svc.resolve(
                    int(pid_s), decision, resolved_by=callback.from_user.id, xui_client=xui
                )
                await session.commit()
            except Exception as e:
                logger.error("Ошибка разрешения расхождения {}: {}", pid_s, e)
                await callback.answer("❌ Ошибка, см. логи", show_alert=True)
                return
        await NotificationService(session).refresh_divergence_digest(batch, session)
    await callback.answer("Готово")


@router.callback_query(F.data.startswith("div:gall:"))
async def divergence_group(callback: CallbackQuery):
    """Групповое решение по всему батчу (поэлементно согласно kind)."""
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer()
        return
    action, batch = parts[2], parts[3]
    decision = _ACTION.get(action)
    if decision is None:
        await callback.answer()
        return

    async with async_session_factory() as session:
        svc = DivergenceService(session)
        cache: dict = {}
        for pd in await svc.list_open_for_batch(batch):
            xui = await _client_if_needed(session, pd, decision, cache)
            try:
                await svc.resolve(
                    pd.id, decision, resolved_by=callback.from_user.id, xui_client=xui
                )
            except Exception as e:
                logger.error("Ошибка группового решения для {}: {}", pd.id, e)
        await session.commit()
        await NotificationService(session).refresh_divergence_digest(batch, session)
    await callback.answer("Готово")


@router.callback_query(F.data.startswith("div:wiz:"))
async def divergence_wizard(callback: CallbackQuery):
    """Открыть/перелистнуть пошаговый разбор расхождений батча."""
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer()
        return
    batch, idx_s = parts[2], parts[3]
    try:
        idx = int(idx_s)
    except ValueError:
        await callback.answer()
        return

    async with async_session_factory() as session:
        pendings = await DivergenceService(session).list_open_for_batch(batch)
        if not pendings:
            await callback.answer("Все расхождения уже разрешены")
            return
        idx = max(0, min(idx, len(pendings) - 1))
        pd = pendings[idx]
        text = _item_text(pd, idx, len(pendings))
        keyboard = get_divergence_item_keyboard(pd.id, batch, idx, len(pendings))
        try:
            await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
        except Exception as e:
            logger.warning("Не удалось показать карточку расхождения: {}", e)
    await callback.answer()
