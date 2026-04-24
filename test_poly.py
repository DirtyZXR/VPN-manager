import asyncio
from sqlalchemy import select
from app.database import async_session_factory
from app.database.models import InboundConnection, XUIInboundConnection, Inbound, XUIInbound, Server
from sqlalchemy.orm import selectinload, with_polymorphic


async def test():
    async with async_session_factory() as session:
        # We need to eager load the subclass properties for connections and inbounds
        conn_poly = with_polymorphic(InboundConnection, "*")
        inbound_poly = with_polymorphic(Inbound, "*")

        result = await session.execute(
            select(conn_poly)
            .options(
                selectinload(conn_poly.inbound.of_type(inbound_poly))
                .selectinload(inbound_poly.server)
                .selectinload(Server.xui_panel)
            )
            .limit(5)
        )
        conns = result.scalars().all()
        for c in conns:
            if hasattr(c, "uuid"):
                print("UUID:", getattr(c, "uuid", None))
            if hasattr(c, "inbound") and c.inbound and hasattr(c.inbound, "xui_id"):
                print("XUI_ID:", getattr(c.inbound, "xui_id", None))
        print("Success!")


asyncio.run(test())
