"""DivergenceService — детект, дедуп, obsolete."""

import pytest
from sqlalchemy import select

from app.database.models import PendingDivergence, Server
from app.services.divergence_service import (
    KIND_EXTRA,
    KIND_MISSING,
    STATUS_OBSOLETE,
    STATUS_OPEN,
    DivergenceFinding,
    DivergenceService,
)


async def _server(session):
    s = Server(name="S", ip_address="1.2.3.4", is_active=True)
    session.add(s)
    await session.flush()
    return s


@pytest.mark.asyncio
async def test_record_findings_creates_and_dedups(test_session):
    s = await _server(test_session)
    svc = DivergenceService(test_session)
    f = DivergenceFinding(s.id, KIND_MISSING, "u@x", None, {"a": 1})

    created = await svc.record_findings([f], batch_id="b1")
    assert len(created) == 1

    # повторный проход — тот же (server, kind, email) уже open → не дублируем
    created2 = await svc.record_findings([f], batch_id="b2")
    assert created2 == []

    rows = (await test_session.execute(select(PendingDivergence))).scalars().all()
    assert len(rows) == 1
    assert rows[0].status == STATUS_OPEN


@pytest.mark.asyncio
async def test_mark_obsolete(test_session):
    s = await _server(test_session)
    svc = DivergenceService(test_session)
    await svc.record_findings(
        [DivergenceFinding(s.id, KIND_EXTRA, "gone@x", None, {})], batch_id="b1"
    )

    # на следующем проходе этого расхождения уже нет в снимке
    affected = await svc.mark_obsolete(s.id, present_keys=set())
    assert len(affected) == 1
    assert affected[0].status == STATUS_OBSOLETE


@pytest.mark.asyncio
async def test_list_open_for_batch(test_session):
    s = await _server(test_session)
    svc = DivergenceService(test_session)
    await svc.record_findings(
        [
            DivergenceFinding(s.id, KIND_MISSING, "a@x", None, {}),
            DivergenceFinding(s.id, KIND_EXTRA, "b@x", None, {}),
        ],
        batch_id="bb",
    )
    opened = await svc.list_open_for_batch("bb")
    assert {p.email for p in opened} == {"a@x", "b@x"}
