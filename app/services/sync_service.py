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
from app.services.protocol_sync import for_inbound
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
                logger.error(f"[ERROR] Ошибка цикла синхронизации: {type(e).__name__} - {str(e)}", exc_info=True)
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
                logger.error(f"[ERROR] Ошибка в цикле синхронизации: {type(e).__name__} - {str(e)}", exc_info=True)
                return {"servers": 0, "error": f"{type(e).__name__}: {str(e)}"}

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
            select(Server)
            .where(Server.is_active)
            .options(
                selectinload(Server.xui_panel),
                selectinload(Server.awg_service),
                selectinload(Server.mtproxy_service),
                selectinload(Server.inbounds),
            )
        )
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
                    f"[ERROR] Ошибка синхронизации сервера {server.id}: {type(e).__name__} - {str(e)}",
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

            # Ping the server to update its online status
            if server.ip_address:
                from app.services.server_monitor import ServerMonitor
                host = server.ip_address
                if host.startswith("http://"):
                    host = host[7:]
                elif host.startswith("https://"):
                    host = host[8:]
                if ":" in host:
                    host = host.split(":")[0]
                is_online = await ServerMonitor.ping(host)
                server.is_online = is_online
                logger.debug(f"[SYNC] Сервер {server.id} ping: {'Успешно' if is_online else 'Неудачно'}")

                # Зафиксируем изменение статуса (is_online) в БД сразу же.
                # Это освободит блокировку базы данных (SQLite write lock),
                # чтобы параллельные запросы от пользователей не падали с ошибкой
                # "database is locked" во время долгих сетевых запросов ниже.
                await self.session.commit()

            xui_client = None
            if server.is_online and server.xui_panel and server.xui_panel.url and server.xui_panel.username:
                # Получить XUI клиент
                xui_client = await self._xui_service._get_client(server)
                # Синхронизировать inbounds
                await self._sync_server_inbounds(server, xui_client)
                
                # Фиксируем inbounds, чтобы освободить SQLite перед запросами клиентов
                await self.session.commit()
            else:
                logger.debug(f"Сервер {server.id} не имеет XUI панели (или не настроена), пропуск XUI inbounds синхронизации")

            # Синхронизация клиентов для всех inbounds этого сервера
            from sqlalchemy import select
            from sqlalchemy.orm import with_polymorphic

            conn_poly = with_polymorphic(InboundConnection, "*")
            inbound_poly = with_polymorphic(Inbound, "*")

            inbounds_result = await self.session.execute(
                select(inbound_poly).where(
                    inbound_poly.server_id == server.id, inbound_poly.is_active
                ).options(
                    selectinload(inbound_poly.client_connections.of_type(conn_poly))
                    .selectinload(conn_poly.subscription)
                    .selectinload(Subscription.client)
                )
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
                    synced = await self._sync_inbound_clients(inbound)
                    clients_synced += synced
                    logger.info(f"[OK] Inbound {inbound.id}: {synced} клиентов синхронизировано")
                    
                    # Фиксируем каждого inbound, чтобы не держать SQLite write lock
                    await self.session.commit()
                except Exception as e:
                    logger.error(
                        f"[ERROR] Ошибка синхронизации клиентов для inbound {inbound.id}: {type(e).__name__} - {str(e)}",
                        exc_info=True,
                    )
                    await self.session.commit()

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
            server.sync_error = f"Unexpected: {type(e).__name__} - {str(e)}"
            logger.error(
                f"[ERROR] Неожиданная ошибка сервера {server.id}: {type(e).__name__} - {str(e)}",
                exc_info=True,
            )
            return False

        finally:
            # Освобождаем блокировку БД (SQLite write lock) после обработки сервера,
            # независимо от того, успешной была синхронизация или упала с ошибкой.
            await self.session.commit()

        # Don't close clients - keep them cached for reuse
        # finally:
        #     if xui_service:
        #         await xui_service.close_all_clients()

    async def sync_all_clients(self) -> int:
        """Синхронизировать всех клиентов на всех активных inbounds.

        Returns:
            Количество синхронизированных клиентов
        """
        from sqlalchemy import select
        from sqlalchemy.orm import with_polymorphic

        inbound_poly = with_polymorphic(Inbound, "*")
        conn_poly_load = with_polymorphic(InboundConnection, "*")

        # Получить все активные inbounds с серверами
        result = await self.session.execute(
            select(inbound_poly)
            .where(inbound_poly.is_active)
            .options(
                selectinload(inbound_poly.server).selectinload(Server.xui_panel),
                selectinload(inbound_poly.client_connections.of_type(conn_poly_load))
                .selectinload(conn_poly_load.subscription)
                .selectinload(Subscription.client),
            )
        )
        inbounds = result.scalars().all()

        total_synced = 0

        try:
            for inbound in inbounds:
                try:
                    synced = await self._sync_inbound_clients(inbound)
                    total_synced += synced
                    
                    # Фиксируем каждого inbound
                    await self.session.commit()

                except Exception as e:
                    logger.error(
                        f"[ERROR] Ошибка синхронизации клиентов для inbound {inbound.id}: {type(e).__name__} - {str(e)}",
                        exc_info=True,
                    )
                    await self.session.commit()

        except Exception as e:
            logger.error(f"[ERROR] Ошибка в sync_all_clients: {type(e).__name__} - {str(e)}", exc_info=True)

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
        from sqlalchemy.orm import with_polymorphic

        # Получить сервер
        server = await self.session.get(
            Server,
            server_id,
            options=[
                selectinload(Server.xui_panel),
                selectinload(Server.awg_service),
                selectinload(Server.mtproxy_service),
                selectinload(Server.inbounds),
            ],
        )
        if not server:
            logger.warning(f"Сервер {server_id} не найден")
            return 0

        inbound_poly = with_polymorphic(Inbound, "*")
        conn_poly_load = with_polymorphic(InboundConnection, "*")

        result = await self.session.execute(
            select(inbound_poly).where(inbound_poly.server_id == server_id, inbound_poly.is_active)
            .options(
                selectinload(inbound_poly.client_connections.of_type(conn_poly_load))
                .selectinload(conn_poly_load.subscription)
                .selectinload(Subscription.client),
            )
        )
        inbounds = result.scalars().all()

        total_synced = 0

        try:
            for inbound in inbounds:
                try:
                    synced = await self._sync_inbound_clients(inbound)
                    total_synced += synced
                    
                    # Фиксируем каждого inbound
                    await self.session.commit()
                except Exception as e:
                    logger.error(
                        f"[ERROR] Ошибка синхронизации клиентов для inbound {inbound.id}: {type(e).__name__} - {str(e)}",
                        exc_info=True,
                    )
                    await self.session.commit()

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
        # Используем __dict__, чтобы не вызывать lazy loading (MissingGreenlet в SQLAlchemy)
        model_dict = getattr(model, "__dict__", {})

        sync_status = model_dict.get("sync_status")
        if sync_status == "offline" or sync_status == "error":
            return True  # Попробовать снова

        if "last_sync_at" in model_dict:
            last_sync_at = model_dict["last_sync_at"]
            if last_sync_at is None:
                return True  # Никогда не синхронизировали

            # Если прошло больше интервала (с учетом timezone-aware и timezone-naive)
            now = datetime.now(UTC)

            # Если last_sync не имеет timezone, добавим ему UTC timezone
            if last_sync_at.tzinfo is None:
                last_sync_at = last_sync_at.replace(tzinfo=UTC)

            if now - last_sync_at > self.SYNC_INTERVAL:
                return True
        else:
            # Если поля нет даже в __dict__ (например, не загружено), считаем что нужна синхронизация
            # Но для безопасности лучше просто вернуть True
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

        from sqlalchemy.orm import with_polymorphic

        inbound_poly = with_polymorphic(Inbound, "*")

        # Сопоставить с существующими
        existing_inbounds = await self.session.execute(
            select(inbound_poly)
            .where(inbound_poly.server_id == server.id)
            .options(selectinload(inbound_poly.server))
        )
        existing_map = {
            getattr(ib, "xui_id", None): ib
            for ib in existing_inbounds.scalars().all()
            if getattr(ib, "xui_id", None) is not None
        }

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
                from app.database.models import XUIInbound
                new_ib = XUIInbound(
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

    async def _sync_inbound_clients(self, inbound: Inbound, xui_client: object | None = None) -> int:
        """Dispatch client sync to the appropriate protocol handler.

        Args:
            inbound: Inbound model.
            xui_client: XUI client instance (kept for backward compat, not used directly).

        Returns:
            Number of synchronized clients.
        """
        handler = for_inbound(inbound)
        if handler is None:
            logger.debug(f"[SYNC] No handler for inbound type '{inbound.type}', skipping {inbound.id}")
            return 0
        return await handler.sync_clients(self.session, inbound, xui_service=self._xui_service)

    # === INTEGRITY CHECK ===

    async def verify_connections_integrity(self) -> bool:
        """Проверить целостность всех подключений.

        Returns:
            True если целостность в порядке
        """
        from sqlalchemy import select
        from sqlalchemy.orm import with_polymorphic

        conn_poly = with_polymorphic(InboundConnection, "*")
        inbound_poly = with_polymorphic(Inbound, "*")

        result = await self.session.execute(
            select(conn_poly).options(
                selectinload(conn_poly.inbound.of_type(inbound_poly))
                .selectinload(inbound_poly.server)
                .selectinload(Server.xui_panel),
                selectinload(conn_poly.subscription).selectinload(Subscription.client)
            )
        )
        connections = result.scalars().all()

        stats = {"total": len(connections), "synced": 0, "error": 0, "offline": 0}

        for connection in connections:
            conn_dict = getattr(connection, "__dict__", {})
            status = conn_dict.get("sync_status", "synced")
            stats[status] = stats.get(status, 0) + 1

            # Дополнительная проверка: клиент существует в XUI?
            if status == "synced":
                try:
                    inbound = connection.inbound
                    if inbound:
                        handler = for_inbound(inbound)
                        if handler is None:
                            continue

                        valid = await handler.verify_connection(
                            self.session, connection, xui_service=self._xui_service
                        )
                        if not valid:
                            stats["error"] += 1

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
                        server = await self.session.get(
                            Server,
                            entity_id,
                            options=[
                                selectinload(Server.xui_panel),
                                selectinload(Server.awg_service),
                                selectinload(Server.mtproxy_service),
                                selectinload(Server.inbounds),
                            ],
                        )
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
                logger.error(f"[ERROR] Ошибка ручной синхронизации: {type(e).__name__} - {str(e)}", exc_info=True)
                results["errors"] += 1
                results["details"].append(f"{type(e).__name__}: {str(e)}")

        logger.info(f"[LOG] manual_sync завершен, финальные results={results}")
        return results


# Импорт asyncio для использования в start_background_sync
