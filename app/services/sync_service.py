"""Service for synchronizing data between bot database and XUI panels."""

import asyncio
import contextlib
import json
import uuid
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
from app.xui_client.models import ensure_settings_dict

# Глобальная блокировка для предотвращения конфликтов между всеми экземплярами SyncService
_global_sync_lock = asyncio.Lock()

# Зомби-клиенты моложе этого порога НЕ удаляются автоматически —
# защита от гонки с незакоммиченной сагой add_inbound_to_subscription.
ZOMBIE_GRACE_PERIOD = timedelta(minutes=15)


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
            cycle_id = uuid.uuid4().hex[:8]
            with logger.contextualize(cycle=cycle_id):
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
        # Берём только ID активных серверов и перечитываем каждый сервер свежим
        # внутри цикла. Иначе rollback() при ошибке одного сервера обесценивает
        # (expire) ORM-объекты остальных в общей сессии, и обращение к ним в
        # async вызывает MissingGreenlet, роняя весь цикл.
        ids_result = await self.session.execute(select(Server.id).where(Server.is_active))
        server_ids = ids_result.scalars().all()

        logger.info(
            f"[LOG] sync_all_servers: найдено {len(server_ids)} активных серверов, force={force}"
        )

        synced_count = 0
        for i, server_id in enumerate(server_ids, 1):
            with logger.contextualize(server=server_id):
                server = await self._load_server_for_sync(server_id)
                if server is None:
                    continue
                server_name = server.name
                try:
                    logger.info(
                        f"[LOG] sync_all_servers: сервер {i}/{len(server_ids)} - {server_name} (ID: {server_id})"
                    )
                    synced = await self.sync_server(server, force=force)
                    if synced:
                        synced_count += 1
                        logger.info(f"[OK] Сервер {server_name} успешно синхронизирован")
                    else:
                        logger.info(
                            f"[SKIP] Сервер {server_name} пропущен (не нужна синхронизация или ошибка)"
                        )
                except Exception as e:
                    logger.error(
                        f"[ERROR] Ошибка синхронизации сервера {server_id}: {type(e).__name__} - {str(e)}",
                        exc_info=True,
                    )

        logger.info(
            f"[LOG] sync_all_servers завершен: {synced_count}/{len(server_ids)} серверов синхронизировано"
        )
        return synced_count

    async def _load_server_for_sync(self, server_id: int) -> Server | None:
        """Свежо загрузить сервер с eager-связями для синхронизации.

        Перечитывание на каждой итерации цикла гарантирует, что rollback()
        предыдущего сервера не оставит expired-объект (см. sync_all_servers).
        """
        result = await self.session.execute(
            select(Server)
            .where(Server.id == server_id)
            .options(
                selectinload(Server.xui_panel),
                selectinload(Server.awg_service),
                selectinload(Server.mtproxy_service),
                selectinload(Server.inbounds),
            )
        )
        return result.scalar_one_or_none()

    async def sync_server(self, server: Server, force: bool = False) -> bool:
        """Синхронизировать отдельный сервер.

        Транзакционные границы (C5):
        - Один commit() ПОСЛЕ полной успешной синхронизации сервера.
        - При исключении — rollback(), лог, возврат False (одна ошибка не валит весь цикл).
        - Нет finally-commit (не фиксируем частичное состояние при ошибке).

        Args:
            server: Server model
            force: Принудительная синхронизация

        Returns:
            True если успешно, False если ошибка
        """
        # server_id фиксируем ДО возможного rollback: после rollback ORM-объект
        # становится expired, и обращение к server.id в async-обработчиках ошибок
        # вызывало бы MissingGreenlet (неявное IO вне greenlet).
        server_id = server.id
        try:
            # Проверить, нужна ли синхронизация
            if not force and not self._needs_sync(server):
                logger.debug(f"✓ Сервер {server_id} в актуальном состоянии")
                return False

            logger.info(f"[SYNC] Синхронизация сервера {server_id}: {server.name}")

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

            xui_client = None
            if server.is_online and server.xui_panel and server.xui_panel.url and server.xui_panel.username:
                # Получить XUI клиент
                xui_client = await self._xui_service._get_client(server)
                # Синхронизировать inbounds
                await self._sync_server_inbounds(server, xui_client)
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
                except Exception as e:
                    logger.error(
                        f"[ERROR] Ошибка синхронизации клиентов для inbound {inbound.id}: {type(e).__name__} - {str(e)}",
                        exc_info=True,
                    )

            # Реконсиляция зомби/фантомов для XUI-серверов
            if server.is_online and server.xui_panel and xui_client is not None:
                await self._reconcile_xui_server(server, xui_client)

            # Обновить статус синхронизации
            server.last_sync_at = datetime.now(UTC)
            server.sync_status = "synced"
            server.sync_error = None

            await self.session.flush()
            # Единственный commit после полной успешной синхронизации сервера
            await self.session.commit()
            logger.info(f"[OK] Сервер {server_id} синхронизирован (клиентов: {clients_synced})")
            return True

        except XUIConnectionError as e:
            new_status = "offline"
            new_error = f"Connection failed: {str(e)}"
            logger.warning(f"[WARN] Сервер {server_id} недоступен")
            await self.session.rollback()
            await self._save_server_error_status(server_id, new_status, new_error)
            return False

        except XUIError as e:
            new_status = "error"
            new_error = str(e)
            logger.error(f"[ERROR] Ошибка XUI сервера {server_id}: {e}")
            await self.session.rollback()
            await self._save_server_error_status(server_id, new_status, new_error)
            return False

        except Exception as e:
            # Check for Amnezia errors without importing at top level
            if type(e).__name__ == "AmneziaConnectionError":
                new_status = "offline"
                new_error = f"Connection failed: {str(e)}"
                logger.warning(f"[WARN] Сервер {server_id} недоступен (Amnezia)")
                await self.session.rollback()
                await self._save_server_error_status(server_id, new_status, new_error)
                return False
            elif type(e).__name__ == "AmneziaError":
                new_status = "error"
                new_error = str(e)
                logger.error(f"[ERROR] Ошибка Amnezia сервера {server_id}: {e}")
                await self.session.rollback()
                await self._save_server_error_status(server_id, new_status, new_error)
                return False

            logger.error(
                f"[ERROR] Неожиданная ошибка сервера {server_id}: {type(e).__name__} - {str(e)}",
                exc_info=True,
            )
            await self.session.rollback()
            await self._save_server_error_status(server_id, "error", f"{type(e).__name__}: {str(e)}")
            return False

        # Don't close clients - keep them cached for reuse
        # finally:
        #     if xui_service:
        #         await xui_service.close_all_clients()

    async def _save_server_error_status(
        self,
        server_id: int,
        sync_status: str,
        sync_error: str,
    ) -> None:
        """Сохранить диагностический статус ошибки сервера в отдельной транзакции.

        Вызывается ПОСЛЕ rollback() бизнес-транзакции, чтобы статус попал в БД
        независимо от откатанных бизнес-данных.

        Args:
            server_id: ID сервера
            sync_status: Новый статус ('error', 'offline')
            sync_error: Текст ошибки
        """
        try:
            srv = await self.session.get(Server, server_id)
            if srv is not None:
                srv.sync_status = sync_status
                srv.sync_error = sync_error
                srv.last_sync_at = datetime.now(UTC)
                await self.session.commit()
                logger.debug(
                    f"[SYNC] Статус ошибки сервера {server_id} сохранён: {sync_status}"
                )
        except Exception as status_err:
            logger.warning(
                f"[SYNC] Не удалось сохранить статус ошибки сервера {server_id}: {status_err}"
            )
            with contextlib.suppress(Exception):
                await self.session.rollback()

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
            settings_dict = ensure_settings_dict(xui_ib.settings)
            client_count = len(settings_dict.get("clients", []))

            settings_str = xui_ib.settings if isinstance(xui_ib.settings, str) else json.dumps(xui_ib.settings or {})

            if xui_id in existing_map:
                db_ib = existing_map[xui_id]
                if settings_str != db_ib.settings_json or xui_ib.remark != db_ib.remark:
                    db_ib.settings_json = settings_str
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

    async def _reconcile_xui_server(self, server: Server, xui_client: object) -> None:
        """Реконсиляция зомби/фантомов для одного XUI-сервера.

        Единый снимок get_clients():
        - Если get_clients() упал — весь шаг реконсиляции пропускается (ничего
          не удаляется).
        - Если get_clients() вернул пустой список ([] — неотличимо от soft-fail
          панели при истёкшем токене / rate-limit) — реконсиляция тоже пропускается.
          При реально пустой панели нечего удалять; пропуск безопасен.
        - Один снимок используется и для проверки фантомов, и для зомби.

        2a. Фантомы БД: InboundConnection с sync_status='error'
            - Если email клиента НЕ в снимке get_clients() → фантом, удаляем из БД.
            - Если email есть в снимке → восстановить sync_status='synced'.

        2b. XUI bot-зомби (авто-удаление только при надёжной bot-подписи):
            - Панельный клиент с непустым subId, совпадающим с subscription_token
              СУЩЕСТВУЮЩЕЙ подписки в БД, но без InboundConnection для этого
              inbound → наш орфан → удаляем с панели (высокая уверенность).
            - Grace-period: зомби с createdAt моложе ZOMBIE_GRACE_PERIOD НЕ удаляется
              в этом цикле (защита от гонки с незакоммиченной сагой add).
            - Клиент без createdAt или createdAt==0 → не удалять (безопаснее пропустить).
            - subId не совпадает ни с одной подпиской → НЕ удалять, только warning.
            - Клиент без subId → не трогать (debug-лог).
            - Пустой email → пропустить.

        2c. Вручную удалённые на панели (mirror-step):
            - XUIInboundConnection этого сервера со sync_status='synced', чей email
              отсутствует в снимке get_clients() И старше ZOMBIE_GRACE_PERIOD
              (по last_sync_at если есть, иначе created_at) → помечаем sync_status='error'.
              НЕ удаляем в этом проходе — удалит шаг 2a на следующем проходе.
            - Свежие соединения (внутри grace-period) не трогаем.
            - Если что-то помечено — отправляем сводное уведомление администраторам.

        AWG/MTProxy: нет надёжной enumeration всех клиентов — только лог.
        Автоудаление не производится.

        Args:
            server: Server model
            xui_client: Подключённый XUIClient для этого сервера
        """
        from sqlalchemy import select
        from sqlalchemy.orm import with_polymorphic

        from app.database.models import Subscription
        from app.database.models.inbound import XUIInbound
        from app.database.models.inbound_connection import XUIInboundConnection

        logger.info(f"[RECONCILE] Начало реконсиляции для сервера {server.id} ({server.name})")

        # -----------------------------------------------------------------------
        # Единый надёжный снимок панели.
        # Если get_clients() бросил исключение — весь шаг реконсиляции пропускается.
        # -----------------------------------------------------------------------
        try:
            panel_clients = await xui_client.get_clients()
        except Exception as e:
            logger.warning(
                f"[RECONCILE] Не удалось получить список клиентов панели для сервера {server.id}: {e}. "
                f"Реконсиляция пропущена (ничего не удаляется)."
            )
            return

        if panel_clients is None:
            logger.warning(
                f"[RECONCILE] get_clients() вернул None для сервера {server.id}. "
                f"Реконсиляция пропущена."
            )
            return

        # SAFETY GUARD: пустой снимок — пропускаем все деструктивные шаги.
        # Пустой список неотличим от soft-fail панели (истёкший токен / rate-limit
        # возвращает success:false → get_clients() возвращает []).
        # При настоящей пустой панели нечего удалять — пропуск безопасен.
        if not panel_clients:
            logger.warning(
                f"[RECONCILE] get_clients() вернул пустой снимок для сервера {server.id}. "
                f"Реконсиляция пропущена (возможен сбой API или пустая панель). "
                f"Ничего не удаляется."
            )
            return

        # Набор email-адресов, присутствующих на панели (для проверки фантомов)
        panel_emails: set[str] = {
            (c.get("email") or "").lower()
            for c in panel_clients
            if c.get("email")
        }

        # -----------------------------------------------------------------------
        # 2a. Фантомы БД: XUIInboundConnection с sync_status='error'
        # Используем снимок get_clients() — НЕ отдельный get_client_traffic().
        # -----------------------------------------------------------------------
        conn_poly = with_polymorphic(XUIInboundConnection, "*")
        phantom_result = await self.session.execute(
            select(conn_poly)
            .join(XUIInbound, conn_poly.inbound_id == XUIInbound.id)
            .where(
                XUIInbound.server_id == server.id,
                conn_poly.sync_status == "error",
            )
        )
        error_connections = phantom_result.scalars().all()

        logger.info(
            f"[RECONCILE] Найдено {len(error_connections)} соединений со статусом 'error' для сервера {server.id}"
        )

        for conn in error_connections:
            c_email = getattr(conn, "email", None)
            if not c_email:
                logger.debug(f"[RECONCILE] Соединение {conn.id} без email, пропуск")
                continue
            if c_email.lower() not in panel_emails:
                # Клиента нет на панели — фантом, удаляем из БД
                logger.info(
                    f"[RECONCILE] Фантом: соединение {conn.id} (email={c_email}) "
                    f"отсутствует на панели → удаление из БД"
                )
                self.session.delete(conn)
            else:
                # Клиент есть на панели — восстанавливаем статус
                logger.info(
                    f"[RECONCILE] Соединение {conn.id} (email={c_email}) "
                    f"найдено на панели → sync_status='synced'"
                )
                conn.sync_status = "synced"

        await self.session.flush()

        # -----------------------------------------------------------------------
        # 2b. XUI bot-зомби: панельные клиенты без соответствующей InboundConnection
        # -----------------------------------------------------------------------
        # Загружаем все subscription_token из БД (для быстрого поиска)
        sub_result = await self.session.execute(
            select(Subscription.subscription_token, Subscription.id)
        )
        token_to_sub_id: dict[str, int] = {row[0]: row[1] for row in sub_result.all()}

        # Загружаем все XUIInbound для этого сервера: xui_id → inbound.id
        xui_inbound_result = await self.session.execute(
            select(XUIInbound.xui_id, XUIInbound.id).where(XUIInbound.server_id == server.id)
        )
        xui_id_to_inbound_id: dict[int, int] = {row[0]: row[1] for row in xui_inbound_result.all()}

        # Загружаем существующие connections для быстрой проверки (subscription_id, inbound_id)
        conn_result = await self.session.execute(
            select(XUIInboundConnection.subscription_id, XUIInboundConnection.inbound_id)
            .join(XUIInbound, XUIInboundConnection.inbound_id == XUIInbound.id)
            .where(XUIInbound.server_id == server.id)
        )
        existing_pairs: set[tuple[int, int]] = set(conn_result.all())

        now_ms = datetime.now(UTC).timestamp() * 1000
        grace_ms = ZOMBIE_GRACE_PERIOD.total_seconds() * 1000

        orphans_deleted = 0
        warnings_logged = 0

        for panel_client in panel_clients:
            sub_id_field = panel_client.get("subId", "") or ""
            email = panel_client.get("email", "") or ""
            inbound_ids_on_panel: list[int] = panel_client.get("inboundIds") or []

            if not sub_id_field:
                # Нет subId → не бот-клиент, не трогаем
                logger.debug(
                    f"[RECONCILE] Клиент '{email}' без subId — пропуск (не бот-клиент)"
                )
                continue

            if sub_id_field not in token_to_sub_id:
                # subId не совпадает ни с одной подпиской в БД
                # Может быть ручным клиентом или зомби от удалённой подписки — НЕ удалять
                logger.warning(
                    f"[RECONCILE] Клиент '{email}' (subId={sub_id_field!r}) "
                    f"на сервере {server.id}: subId не совпадает ни с одной подпиской в БД. "
                    f"Оставляем (возможно ручной или зомби удалённой подписки). "
                    f"Проверьте вручную."
                )
                warnings_logged += 1
                continue

            # subId совпадает с существующей подпиской в БД
            subscription_id = token_to_sub_id[sub_id_field]

            # Grace-period: проверяем возраст клиента по createdAt (epoch ms).
            # Если createdAt отсутствует, равен 0 или клиент моложе порога — пропускаем.
            created_at_ms = panel_client.get("createdAt") or 0
            if not created_at_ms:
                logger.debug(
                    f"[RECONCILE] Клиент '{email}' (subId={sub_id_field!r}) "
                    f"без createdAt — пропуск (безопаснее не удалять)"
                )
                continue
            age_ms = now_ms - created_at_ms
            if age_ms < grace_ms:
                logger.debug(
                    f"[RECONCILE] Клиент '{email}' (subId={sub_id_field!r}) "
                    f"моложе grace-period ({age_ms/1000:.0f}s < {ZOMBIE_GRACE_PERIOD.total_seconds():.0f}s) — пропуск"
                )
                continue

            # Проверяем для каждого inbound, на котором зарегистрирован клиент
            for xui_inbound_id in inbound_ids_on_panel:
                inbound_db_id = xui_id_to_inbound_id.get(xui_inbound_id)
                if inbound_db_id is None:
                    # Инбаунд не в нашей БД — не трогаем
                    logger.debug(
                        f"[RECONCILE] Инбаунд xui_id={xui_inbound_id} не найден в БД сервера {server.id}, пропуск"
                    )
                    continue

                if (subscription_id, inbound_db_id) not in existing_pairs:
                    # Орфан: наш токен (bot-подпись), но нет InboundConnection
                    if not email:
                        logger.debug(
                            f"[RECONCILE] XUI-зомби (subId={sub_id_field!r}) с пустым email — пропуск"
                        )
                        break
                    logger.info(
                        f"[RECONCILE] XUI-зомби: клиент '{email}' (subId={sub_id_field!r}) "
                        f"на inbound xui_id={xui_inbound_id} сервера {server.id}: "
                        f"подписка {subscription_id} существует в БД, но нет InboundConnection → удаление с панели"
                    )
                    try:
                        await xui_client.delete_client(email)
                        orphans_deleted += 1
                    except Exception as e:
                        logger.error(
                            f"[RECONCILE] Не удалось удалить зомби '{email}' с панели: {e}"
                        )
                    # Удаляем по email — не продолжаем проверять остальные inbounds
                    break

        logger.info(
            f"[RECONCILE] Сервер {server.id}: удалено зомби={orphans_deleted}, "
            f"предупреждений о неизвестных клиентах={warnings_logged}"
        )

        # -----------------------------------------------------------------------
        # 2c. Вручную удалённые на панели: synced-соединения, отсутствующие в снимке.
        # Помечаем sync_status='error' (не удаляем — удалит шаг 2a на след. проходе).
        # Grace-period: возраст по last_sync_at (если задан), иначе по created_at.
        # -----------------------------------------------------------------------
        now_utc = datetime.now(UTC)
        grace = ZOMBIE_GRACE_PERIOD

        synced_result = await self.session.execute(
            select(conn_poly)
            .join(XUIInbound, conn_poly.inbound_id == XUIInbound.id)
            .where(
                XUIInbound.server_id == server.id,
                conn_poly.sync_status == "synced",
            )
        )
        synced_connections = synced_result.scalars().all()

        marked_for_notify: list[dict] = []

        for conn in synced_connections:
            c_email = getattr(conn, "email", None)
            if not c_email:
                continue
            if c_email.lower() in panel_emails:
                # Клиент присутствует на панели — всё в порядке
                continue

            # Клиент отсутствует на панели — проверяем возраст соединения
            ref_ts: datetime | None = getattr(conn, "last_sync_at", None) or getattr(conn, "created_at", None)
            if ref_ts is None:
                # Нет временной метки — пропускаем (безопаснее не трогать)
                logger.debug(
                    f"[RECONCILE] Соединение {conn.id} (email={c_email}) без временной метки — пропуск"
                )
                continue

            # Нормализуем timezone
            if ref_ts.tzinfo is None:
                ref_ts = ref_ts.replace(tzinfo=UTC)

            age = now_utc - ref_ts
            if age < grace:
                # Соединение слишком свежее — могло ещё не синхронизироваться
                logger.debug(
                    f"[RECONCILE] Соединение {conn.id} (email={c_email}) "
                    f"моложе grace-period ({age.total_seconds():.0f}s < {grace.total_seconds():.0f}s) — пропуск"
                )
                continue

            # Помечаем как error (удалит шаг 2a на следующем проходе реконсилятора)
            logger.info(
                f"[RECONCILE] Зеркало: соединение {conn.id} (email={c_email}) "
                f"отсутствует на панели сервера {server.id}, возраст {age.total_seconds():.0f}s "
                f"→ sync_status='error' (удаление — на следующем проходе)"
            )
            conn.sync_status = "error"

            # Собираем информацию для уведомления (email + имя пользователя)
            user_label = "—"
            try:
                sub = getattr(conn, "subscription", None)
                if sub is not None:
                    client = getattr(sub, "client", None)
                    if client is not None:
                        user_label = getattr(client, "name", None) or str(getattr(client, "telegram_id", "—"))
            except Exception:
                pass
            marked_for_notify.append({"email": c_email, "user": user_label})

        if marked_for_notify:
            await self.session.flush()
            logger.info(
                f"[RECONCILE] Сервер {server.id}: помечено как missing-on-panel={len(marked_for_notify)}, "
                f"отправка уведомления администраторам"
            )
            try:
                from app.services.notification_service import NotificationService
                notif = NotificationService(self.session)
                await notif.notify_admins_missing_on_panel(
                    server_name=server.name,
                    marked_connections=marked_for_notify,
                )
            except Exception as e:
                logger.error(
                    f"[RECONCILE] Не удалось отправить уведомление администраторам "
                    f"о пропавших клиентах на сервере {server.id}: {e}"
                )
        else:
            logger.debug(
                f"[RECONCILE] Сервер {server.id}: все synced-соединения присутствуют на панели"
            )

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
                        if inbound.server and getattr(inbound.server, "sync_status", None) != "synced":
                            stats["offline"] += 1
                            continue

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
