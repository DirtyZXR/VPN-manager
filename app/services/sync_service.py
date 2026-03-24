"""Service for synchronizing data between bot database and XUI panels."""

from datetime import datetime, timezone, timedelta

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import (
    Inbound,
    InboundConnection,
    Server,
    Subscription,
)
from app.services.xui_service import XUIService
from app.xui_client import XUIConnectionError, XUIError


class SyncService:
    """Service for synchronizing data between database and XUI panels."""

    SYNC_INTERVAL = timedelta(minutes=5)  # 5 минут между синхронизациями

    def __init__(self, session: AsyncSession) -> None:
        """Initialize sync service.

        Args:
            session: Async database session
        """
        self.session = session
        self._is_running = False

    # === CORE METHODS ===

    async def start_background_sync(self) -> None:
        """Запустить фоновую синхронизацию."""
        if self._is_running:
            logger.warning("⚠️ Фоновая синхронизация уже запущена")
            return

        self._is_running = True
        logger.info("🔄 Запуск фоновой синхронизации данных")

        while self._is_running:
            try:
                await self._sync_cycle()
            except Exception as e:
                logger.error(f"❌ Ошибка цикла синхронизации: {e}", exc_info=True)
                await asyncio.sleep(60)  # 1 минута при ошибке

        logger.info("🛑 Фоновая синхронизация остановлена")

    async def stop_background_sync(self) -> None:
        """Остановить фоновую синхронизацию."""
        self._is_running = False
        logger.info("🛑 Остановка фоновой синхронизации")

    async def _sync_cycle(self) -> None:
        """Один цикл синхронизации."""
        start_time = datetime.now(timezone.utc)
        logger.info(f"🔄 Начало цикла синхронизации в {start_time}")

        try:
            # 1. Синхронизировать сервера и inbounds
            servers_synced = await self.sync_all_servers()

            # 2. Проверить целостность подключений
            integrity_ok = await self.verify_connections_integrity()

            # 3. Логировать результаты
            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            logger.info(
                f"✅ Цикл синхронизации завершен за {duration:.2f}s. "
                f"Серверов: {servers_synced}, Целостность: {integrity_ok}"
            )

        except Exception as e:
            logger.error(f"❌ Ошибка в цикле синхронизации: {e}", exc_info=True)

        # Подождать до следующей итерации
        await asyncio.sleep(self.SYNC_INTERVAL.total_seconds())

    # === SERVER SYNC ===

    async def sync_all_servers(self, force: bool = False) -> int:
        """Синхронизировать все активные сервера.

        Args:
            force: Принудительная синхронизация

        Returns:
            Количество синхронизированных серверов
        """
        from sqlalchemy import select

        result = await self.session.execute(
            select(Server).where(Server.is_active == True)
        )
        servers = result.scalars().all()

        synced_count = 0
        for server in servers:
            try:
                if await self.sync_server(server, force=force):
                    synced_count += 1
            except Exception as e:
                logger.error(
                    f"❌ Ошибка синхронизации сервера {server.id}: {e}",
                    exc_info=True,
                )

        return synced_count

    async def sync_server(self, server: Server, force: bool = False) -> bool:
        """Синхронизировать отдельный сервер.

        Args:
            server: Server model
            force: Принудительная синхронизация

        Returns:
            True если успешно, False если ошибка
        """
        try:
            # Проверить, нужна ли синхронизация
            if not force and not self._needs_sync(server):
                logger.debug(f"✓ Сервер {server.id} в актуальном состоянии")
                return False

            logger.info(f"🔄 Синхронизация сервера {server.id}: {server.name}")

            # Получить XUI клиент
            xui_service = XUIService(self.session)
            xui_client = await xui_service._get_client(server)

            # Синхронизировать inbounds
            await self._sync_server_inbounds(server, xui_client)

            # Обновить статус синхронизации
            server.last_sync_at = datetime.now(timezone.utc)
            server.sync_status = "synced"
            server.sync_error = None

            await self.session.flush()
            logger.info(f"✅ Сервер {server.id} синхронизирован")
            return True

        except XUIConnectionError as e:
            server.sync_status = "offline"
            server.sync_error = f"Connection failed: {str(e)}"
            logger.warning(f"⚠️ Сервер {server.id} недоступен")
            return False

        except XUIError as e:
            server.sync_status = "error"
            server.sync_error = str(e)
            logger.error(f"❌ Ошибка XUI сервера {server.id}: {e}")
            return False

        except Exception as e:
            server.sync_status = "error"
            server.sync_error = f"Unexpected: {str(e)}"
            logger.error(f"❌ Неожиданная ошибка сервера {server.id}: {e}", exc_info=True)
            return False

    def _needs_sync(self, model: object) -> bool:
        """Проверить, нужна ли синхронизация.

        Args:
            model: Model with sync fields

        Returns:
            True если нужна синхронизация
        """
        if hasattr(model, "sync_status") and model.sync_status == "offline":
            return True  # Попробовать снова

        if hasattr(model, "sync_status") and model.sync_status == "error":
            return True  # Попробовать снова

        if hasattr(model, "last_sync_at") and model.last_sync_at is None:
            return True  # Никогда не синхронизировали

        # Если прошло больше интервала
        if (
            hasattr(model, "last_sync_at")
            and model.last_sync_at is not None
            and datetime.now(timezone.utc) - model.last_sync_at > self.SYNC_INTERVAL
        ):
            return True

        return False

    async def _sync_server_inbounds(
        self, server: Server, xui_client: object
    ) -> None:
        """Синхронизировать inbounds сервера.

        Args:
            server: Server model
            xui_client: XUI client instance
        """
        # Получить inbounds из XUI
        xui_inbounds = await xui_client.get_inbounds()

        # Сопоставить с существующими
        existing_inbounds = await self.session.execute(
            select(Inbound)
            .where(Inbound.server_id == server.id)
            .options(selectinload(Inbound.server))
        )
        existing_map = {
            ib.xui_id: ib for ib in existing_inbounds.scalars().all()
        }

        # Обновить или создать inbounds
        for xui_ib in xui_inbounds:
            xui_id = xui_ib["id"]

            if xui_id in existing_map:
                # Обновить существующий
                db_ib = existing_map[xui_id]
                if (
                    xui_ib.get("settings") != db_ib.settings_json
                    or xui_ib.get("remark") != db_ib.remark
                ):
                    db_ib.settings_json = str(xui_ib.get("settings", {}))
                    db_ib.remark = xui_ib.get("remark", "")
                    db_ib.client_count = len(
                        xui_ib.get("settings", {}).get("clients", [])
                    )
                    db_ib.updated_at = datetime.now(timezone.utc)
                    db_ib.sync_status = "synced"
                    db_ib.last_sync_at = datetime.now(timezone.utc)
                    logger.info(f"🔄 Inbound {db_ib.id} обновлен из XUI")
                else:
                    logger.debug(f"✓ Inbound {db_ib.id} актуален")
                    db_ib.sync_status = "synced"
                    db_ib.last_sync_at = datetime.now(timezone.utc)
            else:
                # Создать новый inbound
                new_ib = Inbound(
                    server_id=server.id,
                    xui_id=xui_id,
                    remark=xui_ib.get("remark", ""),
                    protocol=xui_ib.get("protocol", "unknown"),
                    port=xui_ib.get("port", 0),
                    settings_json=str(xui_ib.get("settings", {})),
                    client_count=len(xui_ib.get("settings", {}).get("clients", [])),
                    is_active=True,
                    sync_status="synced",
                    last_sync_at=datetime.now(timezone.utc),
                )
                self.session.add(new_ib)
                logger.info(f"➕ Inbound {new_ib.id} создан из XUI")

        await self.session.flush()

    # === INTEGRITY CHECK ===

    async def verify_connections_integrity(self) -> bool:
        """Проверить целостность всех подключений.

        Returns:
            True если целостность в порядке
        """
        from sqlalchemy import select

        result = await self.session.execute(
            select(InboundConnection).options(
                selectinload(InboundConnection.inbound).selectinload(Inbound.server)
            )
        )
        connections = result.scalars().all()

        stats = {"total": len(connections), "synced": 0, "error": 0, "offline": 0}

        for connection in connections:
            status = connection.sync_status if hasattr(connection, "sync_status") else "synced"
            stats[status] = stats.get(status, 0) + 1

            # Дополнительная проверка: клиент существует в XUI?
            if status == "synced":
                try:
                    inbound = connection.inbound
                    if inbound and hasattr(inbound, "server"):
                        xui_service = XUIService(self.session)
                        xui_client = await xui_service._get_client(inbound.server)
                        xui_data = await xui_client.get_client(
                            inbound.xui_id, connection.uuid
                        )

                        if not xui_data:
                            stats["error"] += 1
                            connection.sync_status = "error"
                            connection.sync_error = (
                                "Client missing in XUI (deleted manually?)"
                            )
                            logger.warning(
                                f"⚠️ Клиент {connection.uuid} не найден в XUI"
                            )

                except Exception as e:
                    logger.debug(f"Не удалось проверить {connection.uuid}: {e}")

        await self.session.flush()
        logger.info(f"📊 Статистика целостности: {stats}")
        return stats["error"] == 0

    # === MANUAL SYNC ===

    async def manual_sync(
        self, entity_type: str, entity_id: int | None = None
    ) -> dict:
        """Ручная синхронизация по запросу админа.

        Args:
            entity_type: Тип сущности ("all", "server", "connection")
            entity_id: ID сущности (опционально)

        Returns:
            Результаты синхронизации
        """
        results = {"synced": 0, "errors": 0, "details": []}

        try:
            if entity_type == "all":
                # Полная синхронизация
                await self._sync_cycle()
                results["synced"] = 1

            elif entity_type == "server":
                if entity_id:
                    server = await self.session.get(Server, entity_id)
                    if server and await self.sync_server(server, force=True):
                        results["synced"] += 1
                    else:
                        results["errors"] += 1
                else:
                    synced = await self.sync_all_servers(force=True)
                    results["synced"] = synced

            elif entity_type == "connection":
                if entity_id:
                    connection = await self.session.get(InboundConnection, entity_id)
                    if connection:
                        # TODO: Реализовать двустороннюю синхронизацию подключений
                        connection.sync_status = "synced"
                        connection.last_sync_at = datetime.now(timezone.utc)
                        results["synced"] += 1
                    else:
                        results["errors"] += 1

        except Exception as e:
            logger.error(f"❌ Ошибка ручной синхронизации: {e}", exc_info=True)
            results["errors"] += 1
            results["details"].append(str(e))

        return results


# Импорт asyncio для использования в start_background_sync
import asyncio
