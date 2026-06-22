"""Модель pending_divergences."""

import pytest
from sqlalchemy import select

from app.database.models import PendingDivergence, Server


@pytest.mark.asyncio
async def test_create_pending_divergence(test_session):
    server = Server(name="S", ip_address="1.2.3.4", is_active=True)
    test_session.add(server)
    await test_session.flush()

    pd = PendingDivergence(
        server_id=server.id,
        kind="missing_on_panel",
        email="user@x",
        subscription_id=None,
        details_json={"uuid": "u1", "inbound_ids": [5]},
        batch_id="ab12cd34",
    )
    test_session.add(pd)
    await test_session.flush()

    row = (await test_session.execute(select(PendingDivergence))).scalar_one()
    assert row.status == "open"
    assert row.details_json["inbound_ids"] == [5]
    assert row.resolved_at is None
