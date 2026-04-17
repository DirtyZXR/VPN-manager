import asyncio
from sqlalchemy import select
from sqlalchemy.orm import selectinload

# Import local modules
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app.database import async_session_factory
from app.database.models import InboundConnection, Subscription, Inbound
from app.services.xui_service import XUIService
from loguru import logger


async def main():
    logger.info("Начало миграции email (названий) клиентов...")

    async with async_session_factory() as session:
        xui_service = XUIService(session)

        used_emails = {}  # server_id: set(emails)

        # Получаем все текущие подключения
        result = await session.execute(
            select(InboundConnection).options(
                selectinload(InboundConnection.subscription).selectinload(Subscription.client),
                selectinload(InboundConnection.inbound).selectinload(Inbound.server),
            )
        )
        connections = result.scalars().all()

        logger.info(f"Найдено {len(connections)} VPN-подключений в базе.")

        # Предзаполняем словарь уже существующих email в панели
        for conn in connections:
            server_id = conn.inbound.server_id
            if server_id not in used_emails:
                used_emails[server_id] = set()
            used_emails[server_id].add(conn.email)

        success_count = 0
        error_count = 0
        skipped_count = 0

        for conn in connections:
            try:
                sub = conn.subscription
                if not sub:
                    logger.warning(f"Пропуск {conn.id}: нет привязанной подписки.")
                    skipped_count += 1
                    continue
                client = sub.client
                if not client:
                    logger.warning(f"Пропуск {conn.id}: нет привязанного клиента.")
                    skipped_count += 1
                    continue

                # Новый формат
                base_email = f"{sub.name}-{client.name}"

                # Если уже соответствует, пропускаем
                # Но если формат совпадает, но есть цифры (тест-Денис_1), это тоже норм.
                # Сначала проверяем на полное совпадение с идеальным base_email
                if conn.email == base_email or conn.email.startswith(f"{base_email}_"):
                    # Мы оставляем его как есть, чтобы не переименовывать тест-Денис_1 в тест-Денис_2
                    logger.debug(f"Пропуск {conn.id}: имя '{conn.email}' уже в нужном формате.")
                    skipped_count += 1
                    continue

                server_id = conn.inbound.server_id

                # Освобождаем старый email из трекера
                used_emails[server_id].discard(conn.email)

                # Генерация уникального нового email
                base_name = base_email
                domain_part = ""
                if "@" in base_email:
                    base_name, domain_part = base_email.rsplit("@", 1)
                    domain_part = f"@{domain_part}"

                unique_email = None
                for attempt in range(100):
                    test_email = (
                        base_email if attempt == 0 else f"{base_name}_{attempt}{domain_part}"
                    )
                    if test_email not in used_emails[server_id]:
                        unique_email = test_email
                        break

                if not unique_email:
                    logger.error(f"Не удалось сгенерировать уникальный email для {conn.id}")
                    error_count += 1
                    continue

                logger.info(
                    f"Обновление клиента {conn.id} (UUID: {conn.uuid}) | '{conn.email}' -> '{unique_email}'"
                )

                # Обновление в XUI-панели (без потери трафика и сроков)
                xui_client = await xui_service._get_client(conn.inbound.server)
                await xui_client.update_client_email(conn.inbound.xui_id, conn.uuid, unique_email)

                # Обновление в локальной БД
                conn.email = unique_email
                used_emails[server_id].add(unique_email)

                await session.commit()
                success_count += 1

            except Exception as e:
                logger.error(f"Ошибка при обновлении подключения {conn.id}: {e}")
                error_count += 1

        # Закрываем все открытые сессии aiohttp
        await xui_service.close_all_clients()

    logger.info(
        f"Миграция завершена! Успешно: {success_count}, Пропущено: {skipped_count}, Ошибок: {error_count}"
    )


if __name__ == "__main__":
    asyncio.run(main())
