"""Service for synchronizing data between bot database and XUI panels."""

import asyncio
from datetime import UTC, datetime, timedelta

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

# Глобальная блокировка для предотвращения конфликтов между всеми экземплярами SyncService
_global_sync_lock = asyncio.Lock()


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
        # Используем глобальную блокировку вместо локальной
        self._sync_lock = _global_sync_lock

        # Initialize centralized XUIService for connection pooling and proper cleanup
        self._xui_service = XUIService(session)

    # === CORE METHODS ===

    async def start_background_sync(self) -> None:
        """Запустить фоновую синхронизацию."""
        if self._is_running:
            logger.warning("[WARN] Фоновая синхронизация уже запущена")
            return

        self._is_running = True
        logger.info("[SYNC] Запуск фоновой синхронизации данных")

        while self._is_running:
            try:
                await self._sync_cycle(force=False)
                # Wait for SYNC_INTERVAL (5 minutes) between cycles
                logger.debug("Waiting for next sync cycle...")
                await asyncio.sleep(self.SYNC_INTERVAL.total_seconds())
            except Exception as e:
                logger.error(f"[ERROR] Ошибка цикла синхронизации: {e}", exc_info=True)
                await asyncio.sleep(60)  # 1 минута при ошибке

        logger.info("[STOP] Фоновая синхронизация остановлена")

    async def stop_background_sync(self) -> None:
        """Остановить фоновую синхронизацию."""
        self._is_running = False
        logger.info("[STOP] Остановка фоновой синхронизации")

    async def close_xui_clients(self) -> None:
        """Закрыть все XUI клиенты для предотвращения утечек ресурсов."""
        if hasattr(self, "_xui_service") and self._xui_service:
            await self._xui_service.close_all_clients()
        logger.debug("XUI clients closed")

    async def _sync_cycle(self, force: bool = False) -> dict:
        """Один цикл синхронизации.

        Args:
            force: Принудительная синхронизация (для ручной синхронизации)

        Returns:
            Словарь с результатами синхронизации
        """
        # Проверить, есть ли другая активная синхронизация
        if self._sync_lock.locked():
            logger.debug(
                "[PAUSE] Пропуск цикла синхронизации - другая синхронизация уже выполняется"
            )
            return {"servers": 0, "clients": 0}

        async with self._sync_lock:
            start_time = datetime.now(UTC)
            logger.info(f"[SYNC] Начало цикла синхронизации в {start_time} (force={force})")

            try:
                # 1. Синхронизировать сервера и inbounds (включая клиентов)
                servers_synced = await self.sync_all_servers(force=force)

                # 2. Синхронизировать клиентов (только если sync_server не сделал этого)
                # sync_server уже синхронизирует клиентов, поэтому вызов sync_all_clients будет дублировать
                # Поэтому мы не вызываем sync_all_clients здесь

                # 3. Проверить целостность подключений
                integrity_ok = await self.verify_connections_integrity()

                # 4. Логировать результаты
                duration = (datetime.now(UTC) - start_time).total_seconds()
                logger.info(
                    f"[OK] Цикл синхронизации завершен за {duration:.2f}s. "
                    f"Серверов: {servers_synced}, Целостность: {integrity_ok}"
                )

                return {"servers": servers_synced}

            except Exception as e:
                logger.error(f"[ERROR] Ошибка в цикле синхронизации: {e}", exc_info=True)
                return {"servers": 0, "error": str(e)}

    # === SERVER SYNC ===

    async def sync_all_servers(self, force: bool = False) -> int:
        """Синхронизировать все активные сервера.

        Args:
            force: Принудительная синхронизация

        Returns:
            Количество синхронизированных серверов
        """
        from sqlalchemy import select

        result = await self.session.execute(select(Server).where(Server.is_active))
        servers = result.scalars().all()

        logger.info(
            f"[LOG] sync_all_servers: найдено {len(servers)} активных серверов, force={force}"
        )

        synced_count = 0
        for i, server in enumerate(servers, 1):
            try:
                logger.info(
                    f"[LOG] sync_all_servers: сервер {i}/{len(servers)} - {server.name} (ID: {server.id})"
                )
                result = await self.sync_server(server, force=force)
                if result:
                    synced_count += 1
                    logger.info(f"[OK] Сервер {server.name} успешно синхронизирован")
                else:
                    logger.info(
                        f"[SKIP] Сервер {server.name} пропущен (не нужна синхронизация или ошибка)"
                    )
            except Exception as e:
                logger.error(
                    f"[ERROR] Ошибка синхронизации сервера {server.id}: {e}",
                    exc_info=True,
                )

        logger.info(
            f"[LOG] sync_all_servers завершен: {synced_count}/{len(servers)} серверов синхронизировано"
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

            logger.info(f"[SYNC] Синхронизация сервера {server.id}: {server.name}")

            # Получить XUI клиент
            xui_client = await self._xui_service._get_client(server)

            # Синхронизировать inbounds
            await self._sync_server_inbounds(server, xui_client)

            # Синхронизировать клиентов для всех inbounds этого сервера
            from sqlalchemy import select

            inbounds_result = await self.session.execute(
                select(Inbound).where(Inbound.server_id == server.id, Inbound.is_active)
            )
            inbounds = inbounds_result.scalars().all()

            clients_synced = 0
            logger.info(
                f"[LOG] sync_server: найдено {len(inbounds)} активных inbounds для сервера {server.id}"
            )
            for inbound in inbounds:
                try:
                    logger.info(
                        f"[LOG] sync_server: синхронизация клиентов для inbound {inbound.id} ({inbound.remark})"
                    )
                    synced = await self._sync_inbound_clients(inbound, xui_client)
                    clients_synced += synced
                    logger.info(f"[OK] Inbound {inbound.id}: {synced} клиентов синхронизировано")
                except Exception as e:
                    logger.error(
                        f"[ERROR] Ошибка синхронизации клиентов для inbound {inbound.id}: {e}",
                        exc_info=True,
                    )

            # Обновить статус синхронизации
            server.last_sync_at = datetime.now(UTC)
            server.sync_status = "synced"
            server.sync_error = None

            await self.session.flush()
            logger.info(f"[OK] Сервер {server.id} синхронизирован (клиентов: {clients_synced})")
            return True

        except XUIConnectionError as e:
            server.sync_status = "offline"
            server.sync_error = f"Connection failed: {str(e)}"
            logger.warning(f"[WARN] Сервер {server.id} недоступен")
            return False

        except XUIError as e:
            server.sync_status = "error"
            server.sync_error = str(e)
            logger.error(f"[ERROR] Ошибка XUI сервера {server.id}: {e}")
            return False

        except Exception as e:
            # Check for Amnezia errors without importing at top level
            if type(e).__name__ == "AmneziaConnectionError":
                server.sync_status = "offline"
                server.sync_error = f"Connection failed: {str(e)}"
                logger.warning(f"[WARN] Сервер {server.id} недоступен (Amnezia)")
                return False
            elif type(e).__name__ == "AmneziaError":
                server.sync_status = "error"
                server.sync_error = str(e)
                logger.error(f"[ERROR] Ошибка Amnezia сервера {server.id}: {e}")
                return False

            server.sync_status = "error"
            server.sync_error = f"Unexpected: {str(e)}"
            logger.error(f"[ERROR] Неожиданная ошибка сервера {server.id}: {e}", exc_info=True)
            return False

        # Don't close clients - keep them cached for reuse
        # finally:
        #     if xui_service:
        #         await xui_service.close_all_clients()

    async def sync_all_clients(self) -> int:
        """Синхронизировать всех клиентов со всех активных inbounds.

        Returns:
            Количество синхронизированных клиентов
        """
        from sqlalchemy import select

        # Получить все активные inbounds с серверами
        result = await self.session.execute(
            select(Inbound).where(Inbound.is_active).options(selectinload(Inbound.server))
        )
        inbounds = result.scalars().all()

        total_synced = 0

        try:
            for inbound in inbounds:
                try:
                    if getattr(inbound.server, "panel_type", "xui") == "amnezia":
                        logger.debug(
                            f"Пропуск синхронизации клиентов для Amnezia inbound {inbound.id}"
                        )
                        continue

                    # Получить XUI клиент для сервера
                    xui_client = await self._xui_service._get_client(inbound.server)

                    # Синхронизировать клиентов для этого inbound
                    synced = await self._sync_inbound_clients(inbound, xui_client)
                    total_synced += synced

                except Exception as e:
                    logger.error(
                        f"[ERROR] Ошибка синхронизации клиентов для inbound {inbound.id}: {e}",
                        exc_info=True,
                    )

        except Exception as e:
            logger.error(f"[ERROR] Ошибка в sync_all_clients: {e}", exc_info=True)

        # Don't close clients - keep them cached for reuse
        # finally:
        #     if xui_service:
        #         await xui_service.close_all_clients()

        logger.info(f"Синхронизировано {total_synced} клиентов")
        return total_synced

    async def sync_server_clients(self, server_id: int) -> int:
        """Синхронизировать клиентов для конкретного сервера.

        Args:
            server_id: ID сервера

        Returns:
            Количество синхронизированных клиентов
        """
        from sqlalchemy import select

        # Получить сервер
        server = await self.session.get(Server, server_id)
        if not server:
            logger.warning(f"Сервер {server_id} не найден")
            return 0

        if getattr(server, "panel_type", "xui") == "amnezia":
            logger.info(f"[LOG] Пропуск синхронизации клиентов для Amnezia сервера {server_id}")
            return 0

        # Получить все активные inbounds этого сервера
        result = await self.session.execute(
            select(Inbound).where(Inbound.server_id == server_id, Inbound.is_active)
        )
        inbounds = result.scalars().all()

        total_synced = 0

        try:
            # Получить XUI клиент для сервера
            xui_client = await self._xui_service._get_client(server)

            for inbound in inbounds:
                try:
                    synced = await self._sync_inbound_clients(inbound, xui_client)
                    total_synced += synced
                except Exception as e:
                    logger.error(
                        f"[ERROR] Ошибка синхронизации клиентов для inbound {inbound.id}: {e}",
                        exc_info=True,
                    )

        except Exception as e:
            logger.error(f"[ERROR] Ошибка в sync_server_clients: {e}", exc_info=True)

        # Don't close clients - keep them cached for reuse
        # finally:
        #     if xui_service:
        #         await xui_service.close_all_clients()

        logger.info(f"[OK] Синхронизировано {total_synced} клиентов на сервере {server_id}")
        return total_synced

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

        # Если прошло больше интервала (с учетом timezone-aware и timezone-naive)
        if hasattr(model, "last_sync_at") and model.last_sync_at is not None:
            now = datetime.now(UTC)
            last_sync = model.last_sync_at

            # Если last_sync не имеет timezone, добавим ему UTC timezone
            if last_sync.tzinfo is None:
                last_sync = last_sync.replace(tzinfo=UTC)

            if now - last_sync > self.SYNC_INTERVAL:
                return True

        return False

    async def _sync_server_inbounds(self, server: Server, xui_client: object) -> None:
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
        existing_map = {ib.xui_id: ib for ib in existing_inbounds.scalars().all()}

        # Обновить или создать inbounds
        for xui_ib in xui_inbounds:
            xui_id = xui_ib.id

            # Parse settings JSON to get client count
            import json

            client_count = 0
            if xui_ib.settings:
                try:
                    settings_dict = json.loads(xui_ib.settings)
                    client_count = len(settings_dict.get("clients", []))
                except (json.JSONDecodeError, TypeError):
                    client_count = 0

            if xui_id in existing_map:
                # Обновить существующий
                db_ib = existing_map[xui_id]
                if xui_ib.settings != db_ib.settings_json or xui_ib.remark != db_ib.remark:
                    db_ib.settings_json = xui_ib.settings or "{}"
                    db_ib.remark = xui_ib.remark
                    db_ib.client_count = client_count
                    db_ib.updated_at = datetime.now(UTC)
                    db_ib.sync_status = "synced"
                    db_ib.last_sync_at = datetime.now(UTC)
                    logger.info(f"[SYNC] Inbound {db_ib.id} обновлен из XUI")
                else:
                    logger.debug(f"✓ Inbound {db_ib.id} актуален")
                    db_ib.sync_status = "synced"
                    db_ib.last_sync_at = datetime.now(UTC)
            else:
                # Создать новый inbound
                new_ib = Inbound(
                    server_id=server.id,
                    xui_id=xui_id,
                    remark=xui_ib.remark,
                    protocol=xui_ib.protocol,
                    port=xui_ib.port,
                    settings_json=xui_ib.settings or "{}",
                    client_count=client_count,
                    is_active=True,
                    sync_status="synced",
                    last_sync_at=datetime.now(UTC),
                )
                self.session.add(new_ib)
                logger.info(f"➕ Inbound {new_ib.id} создан из XUI")

        await self.session.flush()

    async def _sync_inbound_clients(self, inbound: Inbound, xui_client: object) -> int:
        """Синхронизировать клиентов inbound из XUI.

        Args:
            inbound: Inbound model
            xui_client: XUI client instance

        Returns:
            Количество синхронизированных клиентов
        """
        logger.info(
            f"[LOG] _sync_inbound_clients: начало для inbound {inbound.id} (xui_id: {inbound.xui_id}, remark: {inbound.remark})"
        )

        # Получить inbound с клиентами из settings
        xui_inbound = await xui_client.get_inbound(inbound.xui_id)

        if not xui_inbound:
            logger.warning(f"[WARN] Inbound {inbound.xui_id} не найден на панели")
            return 0

        if not xui_inbound or not xui_inbound.settings:
            logger.warning(f"Inbound {inbound.id} не имеет настроек клиентов")
            return 0

        # Парсим settings для получения клиентов
        import json

        try:
            settings_dict = json.loads(xui_inbound.settings)
            xui_clients = settings_dict.get("clients", [])
        except (json.JSONDecodeError, TypeError) as e:
            logger.error(f"Ошибка парсинга settings для inbound {inbound.id}: {e}")
            return 0

        logger.info(
            f"[LOG] _sync_inbound_clients: получено {len(xui_clients)} клиентов из inbound {inbound.id} ({inbound.remark})"
        )
        if xui_clients:
            logger.debug(f"Пример данных клиента: {xui_clients[0]}")

        # Сопоставить с существующими в базе по UUID
        existing_connections = await self.session.execute(
            select(InboundConnection)
            .where(InboundConnection.inbound_id == inbound.id)
            .options(selectinload(InboundConnection.subscription).selectinload(Subscription.client))
        )
        existing_map = {conn.uuid: conn for conn in existing_connections.scalars().all()}
        logger.info(
            f"[LOG] _sync_inbound_clients: в базе найдено {len(existing_map)} подключений для inbound {inbound.id}"
        )

        synced_count = 0
        for xui_client_data in xui_clients:
            xui_uuid = xui_client_data.get("id", "")
            if not xui_uuid:
                logger.warning(f"Клиент без UUID: {xui_client_data}")
                continue

            if xui_uuid in existing_map:
                # Обновить существующее подключение
                conn = existing_map[xui_uuid]

                # Получить данные клиента
                xui_enable = xui_client_data.get("enable", True)
                xui_total_gb = xui_client_data.get("totalGB", 0) // (
                    1024 * 1024 * 1024
                )  # bytes to GB
                xui_expiry_time = xui_client_data.get("expiryTime", 0)  # ms timestamp

                logger.debug(
                    f"Синхронизация клиента {conn.uuid}: enable={xui_enable}, totalGB={xui_total_gb}, expiry={xui_expiry_time}"
                )

                # Обновить статус подключения
                if conn.is_enabled != xui_enable:
                    old_status = conn.is_enabled
                    conn.is_enabled = xui_enable
                    logger.info(
                        f"[SYNC] Подключение {conn.id} ({conn.uuid}): is_enabled={old_status} → {xui_enable}"
                    )

                # Обновить per-connection total_gb и expiry_date
                if conn.total_gb != xui_total_gb:
                    old_gb = conn.total_gb
                    conn.total_gb = xui_total_gb
                    logger.info(
                        f"[SYNC] Подключение {conn.id} ({conn.uuid}): total_gb {old_gb}GB → {xui_total_gb}GB"
                    )

                # Обновить per-connection expiry_date
                new_expiry = None
                if xui_expiry_time > 0:
                    new_expiry = datetime.fromtimestamp(xui_expiry_time / 1000, tz=UTC)

                if conn.expiry_date != new_expiry:
                    old_expiry = conn.expiry_date
                    conn.expiry_date = new_expiry
                    logger.info(
                        f"[SYNC] Подключение {conn.id} ({conn.uuid}): expiry {old_expiry} → {new_expiry}"
                    )

                # Обновить подписку (если есть) - для обратной совместимости
                if conn.subscription:
                    subscription = conn.subscription

                    # Обновить total_gb (для старых подключений без per-connection данных)
                    if subscription.total_gb != xui_total_gb:
                        old_gb = subscription.total_gb
                        subscription.total_gb = xui_total_gb
                        logger.info(
                            f"[SYNC] Подписка {subscription.id}: total_gb {old_gb}GB → {xui_total_gb}GB"
                        )

                    # Обновить expiry_date (для старых подключений без per-connection данных)
                    if subscription.expiry_date != new_expiry:
                        old_expiry = subscription.expiry_date
                        subscription.expiry_date = new_expiry
                        logger.info(
                            f"[SYNC] Подписка {subscription.id}: expiry {old_expiry} → {new_expiry}"
                        )

                # Обновить статус синхронизации
                conn.sync_status = "synced"
                conn.last_sync_at = datetime.now(UTC)
                synced_count += 1
            else:
                logger.info(
                    f"[NEW] Клиент {xui_uuid} найден на панели, но не в базе (создан вручную)"
                )

        await self.session.flush()
        logger.info(f"[OK] Синхронизировано {synced_count} клиентов для inbound {inbound.id}")
        return synced_count

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
                        if getattr(inbound.server, "panel_type", "xui") == "amnezia":
                            # Skip XUI integrity check for Amnezia
                            continue

                        xui_client = await self._xui_service._get_client(inbound.server)
                        xui_data = await xui_client.get_client(inbound.xui_id, connection.uuid)

                        if not xui_data:
                            stats["error"] += 1
                            connection.sync_status = "error"
                            connection.sync_error = "Client missing in XUI (deleted manually?)"
                            logger.warning(f"[WARN] Клиент {connection.uuid} не найден в XUI")

                except Exception as e:
                    logger.debug(f"Не удалось проверить {connection.uuid}: {e}")

        await self.session.flush()
        logger.info(f"[STATS] Статистика целостности: {stats}")
        return stats["error"] == 0

    # === MANUAL SYNC ===

    async def manual_sync(self, entity_type: str, entity_id: int | None = None) -> dict:
        """Ручная синхронизация по запросу админа.

        Args:
            entity_type: Тип сущности ("all", "server", "connection")
            entity_id: ID сущности (опционально)

        Returns:
            Результаты синхронизации
        """
        results = {"synced": 0, "errors": 0, "details": []}

        logger.info(
            f"[LOG] manual_sync вызван с параметрами: entity_type={entity_type}, entity_id={entity_id}"
        )

        if entity_type == "all":
            # Полная синхронизация
            logger.info("[LOG] Запуск _sync_cycle с force=True")
            sync_result = await self._sync_cycle(force=True)
            results["synced"] = sync_result.get("servers", 0)
            logger.info(f"[LOG] _sync_cycle завершен, sync_result={sync_result}")
            return results

        if self._sync_lock.locked():
            logger.warning(
                "[PAUSE] Пропуск ручной синхронизации - другая синхронизация уже выполняется"
            )
            results["errors"] += 1
            results["details"].append("Синхронизация уже выполняется")
            return results

        # Использовать блокировку для предотвращения конфликтов с фоновой синхронизацией
        logger.info("[LOG] Попытка получить блокировку для manual_sync")
        async with self._sync_lock:
            logger.info(f"[LOG] Блокировка получена, начало обработки entity_type={entity_type}")
            try:
                if entity_type == "server":
                    if entity_id:
                        logger.info(f"[LOG] Синхронизация сервера {entity_id} (с клиентами)")
                        server = await self.session.get(Server, entity_id)
                        if server:
                            await self.sync_server(server, force=True)
                            results["synced"] = 1  # Один сервер синхронизирован
                        else:
                            results["errors"] += 1
                    else:
                        logger.info("[LOG] Синхронизация всех серверов (с клиентами)")
                        # sync_all_servers уже синхронизирует клиентов внутри sync_server
                        synced_servers = await self.sync_all_servers(force=True)
                        results["synced"] = synced_servers
                        logger.info(f"[LOG] Синхронизировано {synced_servers} серверов с клиентами")

                elif entity_type == "connection" and entity_id:
                    logger.info(f"[LOG] Синхронизация подключения {entity_id}")
                    connection = await self.session.get(InboundConnection, entity_id)
                    if connection:
                        # TODO: Реализовать двустороннюю синхронизацию подключений
                        connection.sync_status = "synced"
                        connection.last_sync_at = datetime.now(UTC)
                        results["synced"] += 1
                    else:
                        results["errors"] += 1

            except Exception as e:
                logger.error(f"[ERROR] Ошибка ручной синхронизации: {e}", exc_info=True)
                results["errors"] += 1
                results["details"].append(str(e))

        logger.info(f"[LOG] manual_sync завершен, финальные results={results}")
        return results


# Импорт asyncio для использования в start_background_sync
