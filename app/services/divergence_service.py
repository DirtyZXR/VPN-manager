"""Сервис обработки расхождений БД ↔ XUI-панель.

Расхождение возникает, когда состояние панели не совпадает с БД:
- missing_on_panel — соединение есть в БД, но клиента нет на панели (ручное удаление);
- extra_on_panel — клиент/привязка есть на панели, но нет соответствующей строки БД
  (ручное добавление).

Вместо немедленного деструктива реконсайлер в режиме ask откладывает расхождение
сюда (`record_findings`) и спрашивает админа. Решение применяется через `resolve`.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from loguru import logger
from sqlalchemy import select

from app.database.models import PendingDivergence

KIND_MISSING = "missing_on_panel"  # в БД есть, на панели нет
KIND_EXTRA = "extra_on_panel"  # на панели есть, в БД нет

STATUS_OPEN = "open"
STATUS_APPLIED = "applied"  # выполнен деструктив (как сделал бы авто)
STATUS_ADOPTED = "adopted"  # ручное изменение сохранено (adopt/restore)
STATUS_IGNORED = "ignored"
STATUS_OBSOLETE = "obsolete"  # расхождение исчезло само до решения

DECISION_APPLY = "apply"  # 🗑 деструктив
DECISION_SAVE = "save"  # 💾 сохранить ручное (adopt для extra / restore для missing)
DECISION_IGNORE = "ignore"  # 💤


@dataclass
class DivergenceFinding:
    """Найденное за проход расхождение (ещё не записанное в БД)."""

    server_id: int
    kind: str
    email: str
    subscription_id: int | None
    details: dict


class DivergenceService:
    """Детект, дедуп и разрешение расхождений."""

    def __init__(self, session) -> None:
        self.session = session

    async def record_findings(
        self, findings: list[DivergenceFinding], batch_id: str
    ) -> list[PendingDivergence]:
        """Записать новые расхождения, дедуплицируя по (server_id, kind, email)
        среди открытых. Вернуть только созданные (для отправки дайджеста)."""
        created: list[PendingDivergence] = []
        for f in findings:
            existing = (
                await self.session.execute(
                    select(PendingDivergence).where(
                        PendingDivergence.server_id == f.server_id,
                        PendingDivergence.kind == f.kind,
                        PendingDivergence.email == f.email,
                        PendingDivergence.status == STATUS_OPEN,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                continue
            pd = PendingDivergence(
                server_id=f.server_id,
                kind=f.kind,
                email=f.email,
                subscription_id=f.subscription_id,
                details_json=f.details or {},
                status=STATUS_OPEN,
                batch_id=batch_id,
            )
            self.session.add(pd)
            created.append(pd)
        await self.session.flush()
        return created

    async def mark_obsolete(
        self, server_id: int, present_keys: set[tuple[str, str]]
    ) -> list[PendingDivergence]:
        """Перевести open-расхождения сервера, которых больше нет в проходе, в obsolete.

        present_keys — множество (kind, email), фактически наблюдаемых в текущем снимке.
        """
        rows = (
            await self.session.execute(
                select(PendingDivergence).where(
                    PendingDivergence.server_id == server_id,
                    PendingDivergence.status == STATUS_OPEN,
                )
            )
        ).scalars().all()
        affected: list[PendingDivergence] = []
        now = datetime.now(UTC)
        for pd in rows:
            if (pd.kind, pd.email) not in present_keys:
                pd.status = STATUS_OBSOLETE
                pd.resolved_at = now
                affected.append(pd)
        if affected:
            await self.session.flush()
        return affected

    async def list_open_for_batch(self, batch_id: str) -> list[PendingDivergence]:
        """Открытые расхождения батча (для разбора по одному / групповых действий)."""
        rows = (
            await self.session.execute(
                select(PendingDivergence)
                .where(
                    PendingDivergence.batch_id == batch_id,
                    PendingDivergence.status == STATUS_OPEN,
                )
                .order_by(PendingDivergence.id)
            )
        ).scalars().all()
        return list(rows)

    async def list_for_batch(self, batch_id: str) -> list[PendingDivergence]:
        """Все расхождения батча (любой статус) — для построения дайджеста."""
        rows = (
            await self.session.execute(
                select(PendingDivergence)
                .where(PendingDivergence.batch_id == batch_id)
                .order_by(PendingDivergence.id)
            )
        ).scalars().all()
        return list(rows)
