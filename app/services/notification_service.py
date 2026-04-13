"""Notification service for sending Telegram notifications."""

import html

from aiogram import Bot
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database.models import Client, InboundConnection, Subscription


class NotificationService:
    """Service for sending notifications to clients."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize service with database session.

        Args:
            session: Async database session
        """
        self.session = session
        self.bot_token = get_settings().bot_token

    async def _get_bot(self) -> Bot:
        """Get or create bot instance.

        Returns:
            Bot instance
        """
        return Bot(token=self.bot_token)

    async def notify_subscription_created(
        self,
        client: Client,
        subscription: Subscription,
        connections: list[InboundConnection],
    ) -> bool:
        """Send notification when subscription is created.

        Args:
            client: Client that received subscription
            subscription: Created subscription
            connections: List of created inbound connections

        Returns:
            True if notification sent, False if not (no telegram_id)
        """
        if not client.telegram_id:
            return False

        try:
            async with await self._get_bot() as bot:
                safe_client_name = html.escape(client.name) if client.name else "Не указан"
                safe_sub_name = html.escape(subscription.name) if subscription.name else "Не указана"

                # Build message
                message = (
                    f"🎉 <b>Новая подписка создана!</b>\n\n"
                    f"👤 <b>Клиент:</b> {safe_client_name}\n"
                    f"📦 <b>Подписка:</b> {safe_sub_name}\n\n"
                    f"<b>Подключения:</b>\n"
                )

                for i, conn in enumerate(connections, 1):
                    inbound = conn.inbound
                    server = inbound.server
                    status = "✅" if conn.is_enabled else "❌"
                    safe_remark = html.escape(inbound.remark) if inbound.remark else "Без названия"
                    safe_server_name = html.escape(server.name) if server.name else "Неизвестный"
                    message += (
                        f"{i}. {status} <b>{safe_remark}</b>\n"
                        f"   Сервер: {safe_server_name}\n"
                        f"   Протокол: {inbound.protocol}\n"
                    )

                # Add subscription details
                traffic_limit = (
                    f"{subscription.total_gb} ГБ" if subscription.total_gb > 0 else "Безлимитный"
                )
                expiry_text = (
                    f"{subscription.remaining_days} дн." if subscription.expiry_date else "Бессрочная"
                )

                message += (
                    f"\n📊 <b>Лимит трафика:</b> {traffic_limit}\n"
                    f"📅 <b>Срок действия:</b> {expiry_text}\n"
                )

                # Add subscription URLs
                if connections:
                    from urllib.parse import urljoin

                    servers = {conn.inbound.server for conn in connections}
                    urls = []
                    for server in servers:
                        # Prioritize JSON URL, fallback to standard URL
                        subscription_path = getattr(server, "subscription_json_path", None)
                        if not subscription_path:
                            subscription_path = getattr(server, "subscription_path", "/sub/")

                        url = urljoin(
                            server.url, f"{subscription_path}{subscription.subscription_token}"
                        )
                        urls.append(url)

                    if urls:
                        message += "\n🔗 <b>Все URL подписки:</b>\n"
                        message += "\n".join([f"<code>{u}</code>" for u in urls])

                await bot.send_message(
                    chat_id=client.telegram_id,
                    text=message,
                    parse_mode="HTML",
                )

                logger.info(
                    f"✅ Notification sent to client {client.name} "
                    f"(Telegram ID: {client.telegram_id}) "
                    f"for subscription {subscription.name}"
                )

            return True

        except Exception as e:
            logger.error(
                f"❌ Failed to send notification to client {client.name} "
                f"(Telegram ID: {client.telegram_id}): {e}",
                exc_info=True,
            )
            return False

    async def notify_subscription_updated(
        self,
        client: Client,
        subscription: Subscription,
    ) -> bool:
        """Send notification when subscription is updated.

        Args:
            client: Client that owns subscription
            subscription: Updated subscription

        Returns:
            True if notification sent, False if not (no telegram_id)
        """
        if not client.telegram_id:
            return False

        try:
            async with await self._get_bot() as bot:
                safe_client_name = html.escape(client.name) if client.name else "Не указан"
                safe_sub_name = html.escape(subscription.name) if subscription.name else "Не указана"

                # Build message
                message = (
                    f"🔄 <b>Подписка обновлена!</b>\n\n"
                    f"👤 <b>Клиент:</b> {safe_client_name}\n"
                    f"📦 <b>Подписка:</b> {safe_sub_name}\n"
                    f"✅ <b>Статус:</b> {'Активна' if subscription.is_active else 'Отключена'}\n"
                )

                # Add subscription details
                traffic_limit = (
                    f"{subscription.total_gb} ГБ" if subscription.total_gb > 0 else "Безлимитный"
                )
                expiry_text = (
                    f"{subscription.remaining_days} дн." if subscription.expiry_date else "Бессрочная"
                )

                message += (
                    f"📊 <b>Лимит трафика:</b> {traffic_limit}\n"
                    f"📅 <b>Срок действия:</b> {expiry_text}\n"
                )

                await bot.send_message(
                    chat_id=client.telegram_id,
                    text=message,
                    parse_mode="HTML",
                )

                logger.info(
                    f"✅ Update notification sent to client {client.name} "
                    f"(Telegram ID: {client.telegram_id}) "
                    f"for subscription {subscription.name}"
                )

            return True

        except Exception as e:
            logger.error(
                f"❌ Failed to send update notification to client {client.name} "
                f"(Telegram ID: {client.telegram_id}): {e}",
                exc_info=True,
            )
            return False

    async def notify_subscription_deleted(
        self,
        client: Client,
        subscription_name: str,
    ) -> bool:
        """Send notification when subscription is deleted.

        Args:
            client: Client that owned subscription
            subscription_name: Name of deleted subscription

        Returns:
            True if notification sent, False if not (no telegram_id)
        """
        if not client.telegram_id:
            return False

        try:
            async with await self._get_bot() as bot:
                safe_client_name = html.escape(client.name) if client.name else "Не указан"
                safe_sub_name = html.escape(subscription_name) if subscription_name else "Не указана"

                message = (
                    f"❌ <b>Подписка удалена</b>\n\n"
                    f"👤 <b>Клиент:</b> {safe_client_name}\n"
                    f"📦 <b>Подписка:</b> {safe_sub_name}\n\n"
                    f"Если это ошибка, обратитесь к администратору."
                )

                await bot.send_message(
                    chat_id=client.telegram_id,
                    text=message,
                    parse_mode="HTML",
                )

                logger.info(
                    f"✅ Deletion notification sent to client {client.name} "
                    f"(Telegram ID: {client.telegram_id}) "
                    f"for subscription {subscription_name}"
                )

            return True

        except Exception as e:
            logger.error(
                f"❌ Failed to send deletion notification to client {client.name} "
                f"(Telegram ID: {client.telegram_id}): {e}",
                exc_info=True,
            )
            return False

    async def notify_inbound_added(
        self,
        client: Client,
        subscription: Subscription,
        connection: InboundConnection,
    ) -> bool:
        """Send notification when inbound is added to subscription.

        Args:
            client: Client that owns subscription
            subscription: Subscription
            connection: Added inbound connection

        Returns:
            True if notification sent, False if not (no telegram_id)
        """
        if not client.telegram_id:
            return False

        try:
            async with await self._get_bot() as bot:
                inbound = connection.inbound
                server = inbound.server

                safe_client_name = html.escape(client.name) if client.name else "Не указан"
                safe_sub_name = html.escape(subscription.name) if subscription.name else "Не указана"
                safe_remark = html.escape(inbound.remark) if inbound.remark else "Без названия"
                safe_server_name = html.escape(server.name) if server.name else "Неизвестный"

                message = (
                    f"➕ <b>Новое подключение добавлено!</b>\n\n"
                    f"👤 <b>Клиент:</b> {safe_client_name}\n"
                    f"📦 <b>Подписка:</b> {safe_sub_name}\n\n"
                    f"🔌 <b>Подключение:</b> {safe_remark}\n"
                    f"🖥️ <b>Сервер:</b> {safe_server_name}\n"
                    f"⚙️ <b>Протокол:</b> {inbound.protocol}\n"
                    f"📡 <b>Порт:</b> {inbound.port}\n"
                )

                # Add subscription URL
                from urllib.parse import urljoin

                # Prioritize JSON URL, fallback to standard URL
                subscription_path = getattr(server, "subscription_json_path", None)
                if not subscription_path:
                    subscription_path = getattr(server, "subscription_path", "/sub/")

                url = urljoin(server.url, f"{subscription_path}{subscription.subscription_token}")

                message += f"\n🔗 <b>URL подписки:</b>\n<code>{url}</code>"

                await bot.send_message(
                    chat_id=client.telegram_id,
                    text=message,
                    parse_mode="HTML",
                )

                logger.info(
                    f"✅ Inbound added notification sent to client {client.name} "
                    f"(Telegram ID: {client.telegram_id}) "
                    f"for subscription {subscription.name}"
                )

            return True

        except Exception as e:
            logger.error(
                f"❌ Failed to send inbound added notification to client {client.name} "
                f"(Telegram ID: {client.telegram_id}): {e}",
                exc_info=True,
            )
            return False

    async def notify_inbound_removed(
        self,
        client: Client,
        subscription_name: str,
        inbound_remark: str,
    ) -> bool:
        """Send notification when inbound is removed from subscription.

        Args:
            client: Client that owns subscription
            subscription_name: Subscription name
            inbound_remark: Inbound remark that was removed

        Returns:
            True if notification sent, False if not (no telegram_id)
        """
        if not client.telegram_id:
            return False

        try:
            async with await self._get_bot() as bot:
                safe_client_name = html.escape(client.name) if client.name else "Не указан"
                safe_sub_name = html.escape(subscription_name) if subscription_name else "Не указана"
                safe_remark = html.escape(inbound_remark) if inbound_remark else "Без названия"

                message = (
                    f"➖ <b>Подключение удалено</b>\n\n"
                    f"👤 <b>Клиент:</b> {safe_client_name}\n"
                    f"📦 <b>Подписка:</b> {safe_sub_name}\n"
                    f"🔌 <b>Удалено подключение:</b> {safe_remark}\n\n"
                    f"Если это ошибка, обратитесь к администратору."
                )

                await bot.send_message(
                    chat_id=client.telegram_id,
                    text=message,
                    parse_mode="HTML",
                )

                logger.info(
                    f"✅ Inbound removed notification sent to client {client.name} "
                    f"(Telegram ID: {client.telegram_id}) "
                    f"for subscription {subscription_name}"
                )

            return True

        except Exception as e:
            logger.error(
                f"❌ Failed to send inbound removed notification to client {client.name} "
                f"(Telegram ID: {client.telegram_id}): {e}",
                exc_info=True,
            )
            return False

    async def notify_expiry_warning(
        self,
        client: Client,
        notification_type: str,
        message: str,
    ) -> bool:
        """Send expiry warning notification.

        Args:
            client: Client to notify
            notification_type: Type of expiry warning (24h, 12h, 1h)
            message: Formatted message

        Returns:
            True if notification sent, False if not (no telegram_id)
        """
        if not client.telegram_id:
            return False

        try:
            async with await self._get_bot() as bot:
                await bot.send_message(
                    chat_id=client.telegram_id,
                    text=message,
                    parse_mode="HTML",
                )

                logger.info(
                    f"✅ Expiry warning sent to client {client.name} "
                    f"(Telegram ID: {client.telegram_id}) "
                    f"type: {notification_type}"
                )

            return True

        except Exception as e:
            logger.error(
                f"❌ Failed to send expiry warning to client {client.name} "
                f"(Telegram ID: {client.telegram_id}): {e}",
                exc_info=True,
            )
            return False

    async def notify_traffic_warning(
        self,
        client: Client,
        message: str,
    ) -> bool:
        """Send traffic warning notification.

        Args:
            client: Client to notify
            message: Formatted message

        Returns:
            True if notification sent, False if not (no telegram_id)
        """
        if not client.telegram_id:
            return False

        try:
            async with await self._get_bot() as bot:
                await bot.send_message(
                    chat_id=client.telegram_id,
                    text=message,
                    parse_mode="HTML",
                )

                logger.info(
                    f"✅ Traffic warning sent to client {client.name} "
                    f"(Telegram ID: {client.telegram_id})"
                )

            return True

        except Exception as e:
            logger.error(
                f"❌ Failed to send traffic warning to client {client.name} "
                f"(Telegram ID: {client.telegram_id}): {e}",
                exc_info=True,
            )
            return False

    async def notify_admin_of_new_user(self, client: Client) -> None:
        """Send notification to admins about new user registration.

        Args:
            client: The newly registered client
        """
        settings = get_settings()
        admin_ids = settings.admin_ids
        if not admin_ids:
            logger.warning("No admin Telegram IDs configured, skipping new user notification.")
            return

        safe_name = html.escape(client.name) if client.name else "Не указан"
        safe_email = html.escape(client.email) if client.email else "Не указан"

        message = (
            f"👤 <b>Новый пользователь зарегистрирован!</b>\n\n"
            f"<b>ID:</b> {client.id}\n"
            f"<b>Имя:</b> {safe_name}\n"
            f"<b>Telegram ID:</b> {client.telegram_id}\n"
            f"<b>Email:</b> {safe_email}"
        )

        try:
            async with await self._get_bot() as bot:
                for admin_id in admin_ids:
                    try:
                        await bot.send_message(
                            chat_id=admin_id,
                            text=message,
                            parse_mode="HTML",
                        )
                        logger.info(
                            f"✅ Admin notification sent to {admin_id} for new user {safe_name}"
                        )
                    except Exception as e:
                        logger.error(
                            f"❌ Failed to send admin notification to {admin_id} for new user {safe_name}: {e}"
                        )
        except Exception as e:
            logger.error(
                f"❌ Failed to send admin notifications for new user {client.name}: {e}",
                exc_info=True,
            )
