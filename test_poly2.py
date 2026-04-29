import asyncio
from sqlalchemy import select
from app.database import async_session_factory
from app.database.models import InboundConnection, Inbound, Subscription
from sqlalchemy.orm import selectinload, with_polymorphic


async def test():
    async with async_session_factory() as session:
        conn_poly = with_polymorphic(InboundConnection, "*")

        existing_connections = await session.execute(
            select(conn_poly)
            .where(conn_poly.inbound_id == 1)
            .options(selectinload(conn_poly.subscription).selectinload(Subscription.client))
        )
        existing_map = {
            getattr(conn, "uuid", None): conn
            for conn in existing_connections.scalars().all()
            if getattr(conn, "uuid", None)
        }
        print(len(existing_map))


asyncio.run(test())
