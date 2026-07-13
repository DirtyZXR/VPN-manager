"""Импорт/удаление созданных вручную клиентов XUI-панели.

Клиенты, заведённые на панели не ботом, бот раньше только замечал в логах. Этот
сервис даёт on-demand механизм: перечислить «неуправляемых» клиентов сервера,
импортировать их в бота (создать подписку + соединения, переиспользуя панельный
subId) или удалить с панели.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from loguru import logger
from sqlalchemy import select


@dataclass
class UnmanagedClient:
    """Клиент панели, не управляемый ботом (создан вручную)."""

    email: str
    uuid: str
    sub_id: str
    inbound_db_ids: list[int]  # известные боту inbound'ы (доступные к импорту)
    expiry_ms: int
    total_gb: int  # в ГБ (из байтов панели)
    enable: bool
    importable: bool  # есть хотя бы один inbound_db_id


class ManualClientService:
    """Детект, импорт и удаление ручных клиентов панели."""

    def __init__(self, session) -> None:
        self.session = session

    async def list_unmanaged(self, server) -> list[UnmanagedClient]:
        """Список панельных клиентов сервера, не управляемых ботом."""
        from app.database.models import XUIInboundConnection
        from app.database.models.inbound import XUIInbound
        from app.services.xui_service import XUIService

        rows = (
            await self.session.execute(
                select(XUIInboundConnection.email, XUIInboundConnection.uuid)
                .select_from(XUIInboundConnection)
                .join(XUIInbound, XUIInbound.id == XUIInboundConnection.inbound_id)
                .where(XUIInbound.server_id == server.id)
            )
        ).all()
        bot_emails = {(r[0] or "").lower() for r in rows if r[0]}
        bot_uuids = {r[1] for r in rows if r[1]}

        xui_rows = (
            await self.session.execute(
                select(XUIInbound.xui_id, XUIInbound.id).where(XUIInbound.server_id == server.id)
            )
        ).all()
        xui_to_db = {r[0]: r[1] for r in xui_rows}

        try:
            client = await XUIService(self.session)._get_client(server)
            snapshot = await client.get_clients() or []
        except Exception as e:
            logger.warning("list_unmanaged: панель сервера {} недоступна: {}", server.id, e)
            return []

        result: list[UnmanagedClient] = []
        for pc in snapshot:
            email = pc.get("email") or ""
            uuid = pc.get("id") or pc.get("uuid") or ""
            if (email.lower() in bot_emails) or (uuid and uuid in bot_uuids):
                continue  # это наш клиент
            inbound_db_ids = [
                xui_to_db[x] for x in (pc.get("inboundIds") or []) if x in xui_to_db
            ]
            result.append(
                UnmanagedClient(
                    email=email,
                    uuid=uuid,
                    sub_id=pc.get("subId") or "",
                    inbound_db_ids=inbound_db_ids,
                    expiry_ms=int(pc.get("expiryTime") or 0),
                    total_gb=int(pc.get("totalGB") or 0) // (1024**3),
                    enable=bool(pc.get("enable", True)),
                    importable=bool(inbound_db_ids),
                )
            )
        return result

    async def create_import_client(self, name: str):
        """Создать клиента БД под импорт (у ручного нет реального контакта).

        Client.email обязателен и уникален — генерируем синтетический.
        """
        import uuid as _uuid

        from app.database.models import Client

        email = f"imported-{_uuid.uuid4().hex[:10]}@local"
        client = Client(
            name=name,
            name_lower=name.lower(),
            email=email,
            telegram_id=None,
            is_admin=False,
            is_active=True,
        )
        self.session.add(client)
        await self.session.flush()
        return client

    async def import_client(self, server, panel_email: str, client_id: int):
        """Импортировать ручного клиента панели в подписку клиента `client_id`.

        Переиспользует панельный subId как token (если непустой и свободный);
        иначе генерирует token и пушит его на панель через update_client.
        Возвращает созданную подписку или None, если клиент исчез с панели.
        """
        from app.database.models import Subscription, XUIInboundConnection
        from app.database.models.inbound import XUIInbound
        from app.services.xui_service import XUIService
        from app.utils import generate_subscription_token
        from app.xui_client.models import XUIAddClientRequest

        client = await XUIService(self.session)._get_client(server)
        snapshot = await client.get_clients() or []
        pc = next((c for c in snapshot if (c.get("email") or "") == panel_email), None)
        if pc is None:
            logger.warning(
                "import_client: '{}' не найден на панели сервера {}", panel_email, server.id
            )
            return None

        uuid = pc.get("id") or pc.get("uuid") or ""
        sub_id = pc.get("subId") or ""
        expiry_ms = int(pc.get("expiryTime") or 0)
        total_gb = int(pc.get("totalGB") or 0) // (1024**3)
        enable = bool(pc.get("enable", True))
        expiry_date = datetime.fromtimestamp(expiry_ms / 1000, tz=UTC) if expiry_ms else None

        token = sub_id
        if not token:
            token = generate_subscription_token()
        else:
            exists = (
                await self.session.execute(
                    select(Subscription.id).where(Subscription.subscription_token == token)
                )
            ).first()
            if exists is not None:
                token = generate_subscription_token()

        xui_rows = (
            await self.session.execute(
                select(XUIInbound.xui_id, XUIInbound.id).where(XUIInbound.server_id == server.id)
            )
        ).all()
        xui_to_db = {r[0]: r[1] for r in xui_rows}
        inbound_db_ids = [xui_to_db[x] for x in (pc.get("inboundIds") or []) if x in xui_to_db]

        subscription = Subscription(
            client_id=client_id,
            name=panel_email,
            subscription_token=token,
            total_gb=total_gb,
            expiry_date=expiry_date,
            is_active=True,
        )
        self.session.add(subscription)
        await self.session.flush()

        for inbound_db_id in inbound_db_ids:
            self.session.add(
                XUIInboundConnection(
                    subscription_id=subscription.id,
                    inbound_id=inbound_db_id,
                    is_enabled=enable,
                    total_gb=total_gb,
                    expiry_date=expiry_date,
                    sync_status="synced",
                    last_sync_at=datetime.now(UTC),
                    email=panel_email,
                    uuid=uuid,
                    xui_client_id=uuid,
                )
            )

        # Токен изменился относительно панельного subId → проставляем новый на панели.
        if token != sub_id:
            req = XUIAddClientRequest(
                id=uuid or "",
                email=panel_email,
                enable=enable,
                flow=pc.get("flow", "xtls-rprx-vision"),
                totalGB=int(pc.get("totalGB") or 0),
                expiryTime=expiry_ms,
                subId=token,
            )
            try:
                await client.update_client(panel_email, req)
            except Exception as e:
                logger.warning("import_client: не удалось обновить subId на панели: {}", e)

        await self.session.flush()
        return subscription

    async def delete_from_panel(self, server, email: str) -> bool:
        """Удалить клиента с панели (для зачистки чужих/ненужных)."""
        from app.services.xui_service import XUIService

        client = await XUIService(self.session)._get_client(server)
        return await client.delete_client(email)
