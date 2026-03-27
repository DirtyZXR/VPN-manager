"""Notification checker for subscription expiry and traffic warnings."""

import hashlib
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING

from loguru import logger
from sqlalchemy import and_, delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import (
    Client,
    Inbound,
    InboundConnection,
    NotificationLog,
    Subscription,
)
from app.database.models.notification_log import (
    NotificationLevel,
    NotificationType,
)
from app.services import NotificationService

if TYPE_CHECKING:
    from app.xui_client import XUIClient


class NotificationChecker:
    """Service for checking subscriptions and sending expiry/traffic notifications."""

    # Time thresholds for expiry notifications
    EXPIRY_THRESHOLDS = {
        NotificationType.EXPIRY_24H: timedelta(hours=24),
        NotificationType.EXPIRY_12H: timedelta(hours=12),
        NotificationType.EXPIRY_1H: timedelta(hours=1),
    }

    # Traffic threshold (GB)
    TRAFFIC_THRESHOLD_GB = 5

    # Grouping tolerances
    TIME_TOLERANCE_MINUTES = 30
    TRAFFIC_TOLERANCE_GB = 5

    def __init__(self, session: AsyncSession) -> None:
        """Initialize checker with database session.

        Args:
            session: Async database session
        """
        self.session = session
        self._notification_service = NotificationService(session)
        self._xui_clients: dict[int, "XUIClient"] = {}

    async def check_and_notify(self) -> None:
        """Check all subscriptions and send notifications if needed."""
        try:
            # Clean up old logs first
            await self._cleanup_old_logs()

            # Get all users with telegram_id and their subscriptions
            users_result = await self.session.execute(
                select(Client)
                .where(Client.telegram_id.isnot(None))
                .where(Client.is_active == True)
            )
            users = list(users_result.scalars())

            for user in users:
                try:
                    # Load subscriptions for this user with eager loading
                    subs_result = await self.session.execute(
                        select(Subscription)
                        .where(Subscription.client_id == user.id)
                        .where(Subscription.is_active == True)
                        .options(
                            selectinload(Subscription.inbound_connections)
                            .selectinload(InboundConnection.inbound)
                            .selectinload(Inbound.server)
                        )
                    )
                    subscriptions = list(subs_result.scalars())

                    if not subscriptions:
                        continue

                    # Build subs_with_conns mapping from eager loaded data
                    subs_with_conns = []
                    for sub in subscriptions:
                        connections = [conn for conn in sub.inbound_connections if conn.is_enabled]
                        subs_with_conns.append({
                            "subscription": sub,
                            "connections": connections
                        })

                    # Check expiry notifications
                    for notification_type, threshold in self.EXPIRY_THRESHOLDS.items():
                        await self._check_expiry_notifications(user, subs_with_conns, notification_type, threshold)

                    # Check traffic notifications
                    await self._check_traffic_notifications(user, subs_with_conns)

                    # Commit after processing this user to minimize transaction time
                    await self.session.commit()

                except Exception as e:
                    logger.error(f"Error checking user {user.id}: {e}", exc_info=True)
                    # Rollback on error to avoid leaving pending transaction
                    try:
                        await self.session.rollback()
                    except Exception:
                        pass

        except Exception as e:
            logger.error(f"Error in notification checker: {e}", exc_info=True)

    async def _cleanup_old_logs(self) -> None:
        """Delete notification logs older than 7 days."""
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(days=7)
            await self.session.execute(
                delete(NotificationLog).where(NotificationLog.sent_at < cutoff)
            )
            await self.session.commit()
            logger.info("Cleaned up notification logs older than 7 days")
        except Exception as e:
            logger.error(f"Failed to clean up old logs: {e}", exc_info=True)
            try:
                await self.session.rollback()
            except Exception:
                pass

    async def _get_active_users(self) -> list[Client]:
        """Get all active users with telegram_id.

        Returns:
            List of users
        """
        result = await self.session.execute(
            select(Client)
            .where(Client.telegram_id.isnot(None))
            .where(Client.is_active == True)
        )
        return list(result.scalars())

    async def _check_user(self, user: Client) -> None:
        """Check user's subscriptions for expiry/traffic notifications.

        Args:
            user: User to check
        """
        # Load subscriptions manually to avoid lazy loading in async context
        result = await self.session.execute(
            select(Subscription)
            .where(Subscription.client_id == user.id)
            .where(Subscription.is_active == True)
        )
        subscriptions = list(result.scalars())

        if not subscriptions:
            return

        # Check expiry notifications
        for notification_type, threshold in self.EXPIRY_THRESHOLDS.items():
            await self._check_expiry_notifications(user, subscriptions, notification_type, threshold)

        # Check traffic notifications
        await self._check_traffic_notifications(user, subscriptions)

    async def _check_expiry_notifications(
        self,
        user: Client,
        subs_with_conns: list[dict],
        notification_type: str,
        threshold: timedelta,
    ) -> None:
        """Check and send expiry notifications.

        Args:
            user: User to check
            subs_with_conns: List of dictionaries with subscription and connections
            notification_type: Type of expiry notification
            threshold: Time threshold for notification
        """
        # Group subscriptions by expiry time
        expiry_groups = await self._group_subscriptions_by_expiry(subs_with_conns, threshold)

        for group in expiry_groups:
            # Check if notification already sent
            # notification_type is already a string constant from NotificationType
            if await self._notification_sent(user.id, notification_type, group["level"], group["key"]):
                continue

            # Send notification
            await self._send_expiry_notification(
                user,
                notification_type,
                group["subscriptions"],
                group["level"],
            )

    async def _check_traffic_notifications(
        self,
        user: Client,
        subs_with_conns: list[dict],
    ) -> None:
        """Check and send traffic notifications.

        Args:
            user: User to check
            subs_with_conns: List of dictionaries with subscription and connections
        """
        # Get traffic data for all subscriptions
        traffic_groups = await self._group_subscriptions_by_traffic(subs_with_conns)

        for group in traffic_groups:
            # Check if notification already sent
            # NotificationType.TRAFFIC_5GB is already a string constant
            if await self._notification_sent(
                user.id, NotificationType.TRAFFIC_5GB, group["level"], group["key"]
            ):
                continue

            # Send notification
            await self._send_traffic_notification(
                user,
                NotificationType.TRAFFIC_5GB,
                group["subscriptions"],
                group["level"],
                group["traffic_info"],
            )

    async def _group_subscriptions_by_expiry(
        self,
        subs_with_conns: list[dict],
        threshold: timedelta,
    ) -> list[dict]:
        """Group subscriptions by expiry time.

        Args:
            subs_with_conns: List of dictionaries with subscription and connections
            threshold: Time tolerance for grouping

        Returns:
            List of groups with subscriptions and metadata
        """
        now = datetime.now(timezone.utc)
        groups = []

        for sub_data in subs_with_conns:
            subscription = sub_data["subscription"]
            connections = sub_data["connections"]

            if not subscription.expiry_date:
                continue

            # Handle timezone-aware vs naive datetimes
            expiry_date = subscription.expiry_date
            if expiry_date.tzinfo is None:
                expiry_date = expiry_date.replace(tzinfo=timezone.utc)

            # Check if within threshold
            if expiry_date < now or expiry_date > now + threshold:
                continue

            # Find matching group
            matching_group = None
            for group in groups:
                if self._expiry_times_in_range(
                    subscription.expiry_date,
                    group["expiry_times"],
                    threshold,
                ):
                    matching_group = group
                    break

            if matching_group:
                matching_group["subscriptions"].append(subscription)
                matching_group["expiry_times"].append(subscription.expiry_date)
            else:
                new_group = {
                    "subscriptions": [subscription],
                    "expiry_times": [subscription.expiry_date],
                }
                groups.append(new_group)

        # Determine level and key for each group
        result = []
        for group in groups:
            if len(group["subscriptions"]) == 1:
                subscription = group["subscriptions"][0]

                # Find connections for this subscription
                connections = next(
                    (sub_data["connections"] for sub_data in subs_with_conns
                     if sub_data["subscription"].id == subscription.id),
                    []
                )

                if len(connections) == 1:
                    # Single connection -> profile level
                    conn = connections[0]
                    level = NotificationLevel.PROFILE
                    key = self._get_group_key([conn.id])
                else:
                    # Multiple connections in one subscription -> subscription level
                    level = NotificationLevel.SUBSCRIPTION
                    key = self._get_group_key([subscription.id])
            else:
                # Multiple subscriptions -> user level
                level = NotificationLevel.USER
                key = self._get_group_key([s.id for s in group["subscriptions"]])

            group["level"] = level
            group["key"] = key
            result.append(group)

        return result

    async def _group_subscriptions_by_traffic(
        self,
        subs_with_conns: list[dict],
    ) -> list[dict]:
        """Group subscriptions by remaining traffic.

        Args:
            subs_with_conns: List of dictionaries with subscription and connections

        Returns:
            List of groups with subscriptions and traffic info
        """
        groups = []

        for sub_data in subs_with_conns:
            subscription = sub_data["subscription"]

            # Get traffic info for subscription using connections
            traffic_info = await self._get_subscription_traffic_info(subscription, sub_data["connections"])

            if not traffic_info or traffic_info["remaining_gb"] > self.TRAFFIC_THRESHOLD_GB:
                continue

            # Find matching group
            matching_group = None
            for group in groups:
                if abs(group["remaining_gb"] - traffic_info["remaining_gb"]) <= self.TRAFFIC_TOLERANCE_GB:
                    matching_group = group
                    break

            if matching_group:
                matching_group["subscriptions"].append(subscription)
                matching_group["remaining_gb"] = min(
                    matching_group["remaining_gb"],
                    traffic_info["remaining_gb"],
                )
            else:
                new_group = {
                    "subscriptions": [subscription],
                    "remaining_gb": traffic_info["remaining_gb"],
                }
                groups.append(new_group)

        # Determine level and key for each group
        result = []
        for group in groups:
            if len(group["subscriptions"]) == 1:
                subscription = group["subscriptions"][0]
                level = NotificationLevel.SUBSCRIPTION
                key = self._get_group_key([subscription.id])
            else:
                level = NotificationLevel.USER
                key = self._get_group_key([s.id for s in group["subscriptions"]])

            group["level"] = level
            group["key"] = key
            group["traffic_info"] = group["remaining_gb"]
            result.append(group)

        return result

    async def _get_subscription_traffic_info(
        self,
        subscription: Subscription,
        connections: list[InboundConnection]
    ) -> dict | None:
        """Get traffic information for subscription.

        Args:
            subscription: Subscription to check
            connections: Pre-loaded inbound connections

        Returns:
            Dictionary with traffic info or None
        """
        if not connections:
            return None

        total_used_gb = 0
        total_limit_gb = 0

        for conn in connections:
            if conn.is_unlimited:
                continue

            # Get traffic from XUI
            traffic_data = await self._get_connection_traffic(conn)
            if traffic_data:
                total_used_gb += traffic_data["used_gb"]
                total_limit_gb += conn.total_gb

        if total_limit_gb == 0:
            return None

        remaining_gb = total_limit_gb - total_used_gb

        return {
            "used_gb": total_used_gb,
            "limit_gb": total_limit_gb,
            "remaining_gb": max(0, remaining_gb),
        }

    async def _get_connection_traffic(self, conn: InboundConnection) -> dict | None:
        """Get traffic data for inbound connection from XUI.

        Args:
            conn: Inbound connection (must have eager loaded inbound and server)

        Returns:
            Traffic info or None
        """
        from app.xui_client import XUIClient

        # Use eager loaded relationships
        if not hasattr(conn, 'inbound') or not conn.inbound:
            logger.warning(f"Connection {conn.id} has no eager loaded inbound")
            return None

        inbound = conn.inbound

        if not hasattr(inbound, 'server') or not inbound.server:
            logger.warning(f"Inbound {inbound.id} has no eager loaded server")
            return None

        server = inbound.server

        try:
            # Get or create XUI client using the cache
            if server.id not in self._xui_clients:
                from app.services.xui_service import XUIService
                xui_service = XUIService(self.session)
                self._xui_clients[server.id] = await xui_service._get_client(server)

            client = self._xui_clients[server.id]

            # Get client stats from XUI
            clients = await client.get_clients(inbound.xui_id)
            for xui_client in clients:
                if xui_client.get("id") == conn.uuid:
                    used_gb = (xui_client.get("up", 0) + xui_client.get("down", 0)) / (1024**3)
                    return {"used_gb": used_gb}

        except Exception as e:
            logger.error(f"Error getting traffic for connection {conn.id}: {e}", exc_info=True)

        return None

    def _expiry_times_in_range(
        self,
        expiry: datetime,
        expiry_times: list[datetime],
        tolerance: timedelta,
    ) -> bool:
        """Check if expiry time is within range of other expiry times.

        Args:
            expiry: Expiry time to check
            expiry_times: List of expiry times
            tolerance: Time tolerance

        Returns:
            True if in range
        """
        # Ensure expiry has timezone
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)

        for other_expiry in expiry_times:
            # Ensure other_expiry has timezone
            other_expiry_tz = other_expiry
            if other_expiry_tz.tzinfo is None:
                other_expiry_tz = other_expiry_tz.replace(tzinfo=timezone.utc)

            if abs(expiry - other_expiry_tz) <= tolerance:
                return True
        return False

    def _get_group_key(self, ids: list[int]) -> str:
        """Generate unique hash key for group of IDs.

        Args:
            ids: List of IDs

        Returns:
            Hash string
        """
        sorted_ids = sorted(ids)
        key_string = ",".join(str(id) for id in sorted_ids)
        return hashlib.sha256(key_string.encode()).hexdigest()[:16]

    async def _notification_sent(
        self,
        user_id: int,
        notification_type: str,
        level: str,
        group_key: str,
    ) -> bool:
        """Check if notification already sent.

        Args:
            user_id: User ID
            notification_type: Type of notification
            level: Level of notification
            group_key: Group key

        Returns:
            True if notification already sent
        """
        # Get last notification for this group
        result = await self.session.execute(
            select(NotificationLog)
            .where(NotificationLog.user_id == user_id)
            .where(NotificationLog.notification_type == notification_type)
            .where(NotificationLog.level == level)
            .where(NotificationLog.group_key == group_key)
            .order_by(NotificationLog.sent_at.desc())
            .limit(1)
        )
        last_log = result.scalar()

        if not last_log:
            return False

        # Check cooldown based on notification type
        now = datetime.now(timezone.utc)

        # Define expiry notification types (as strings)
        expiry_types = {
            NotificationType.EXPIRY_24H,
            NotificationType.EXPIRY_12H,
            NotificationType.EXPIRY_1H,
        }

        if notification_type in expiry_types:
            # For expiry notifications (24h, 12h, 1h), don't use cooldown
            # These are one-time events that should always be sent when the condition is met
            return False
        else:
            # For traffic notifications, use cooldown to avoid spam
            # Traffic can change frequently, so limit to 12 hours between notifications
            cutoff = now - timedelta(hours=12)

        # Handle timezone-aware vs naive datetimes
        sent_at = last_log.sent_at
        if sent_at.tzinfo is None:
            sent_at = sent_at.replace(tzinfo=timezone.utc)

        return sent_at > cutoff

    async def _send_expiry_notification(
        self,
        user: Client,
        notification_type: str,
        subscriptions: list[Subscription],
        level: str,
        subs_with_conns: list[dict] | None = None,
    ) -> None:
        """Send expiry notification.

        Args:
            user: User to notify
            notification_type: Type of notification (already string)
            subscriptions: Subscriptions in group
            level: Notification level
            subs_with_conns: Optional mapping of subscriptions to their connections
        """
        try:
            # Build message
            message = self._build_expiry_message(notification_type, subscriptions, level, subs_with_conns)

            # Send notification
            await self._notification_service.notify_expiry_warning(
                user,
                notification_type,
                message,
            )

            # Log notification
            group_key = self._get_group_key([s.id for s in subscriptions])
            await self._log_notification(
                user.id,
                notification_type,
                level,
                group_key,
            )

            # Commit after logging to avoid transaction conflicts
            await self.session.commit()

            logger.info(
                f"✅ Sent expiry notification to user {user.id} "
                f"(Telegram ID: {user.telegram_id}) "
                f"for {len(subscriptions)} subscription(s)"
            )

        except Exception as e:
            logger.error(
                f"❌ Failed to send expiry notification to user {user.id}: {e}",
                exc_info=True
            )
            # Rollback to avoid leaving pending transaction
            try:
                await self.session.rollback()
            except Exception:
                pass

    async def _send_traffic_notification(
        self,
        user: Client,
        notification_type: str,
        subscriptions: list[Subscription],
        level: str,
        traffic_info: float,
    ) -> None:
        """Send traffic notification.

        Args:
            user: User to notify
            notification_type: Type of notification (already string)
            subscriptions: Subscriptions in group
            level: Notification level
            traffic_info: Remaining traffic in GB
        """
        try:
            # Build message
            message = self._build_traffic_message(subscriptions, level, traffic_info)

            # Send notification
            await self._notification_service.notify_traffic_warning(
                user,
                message,
            )

            # Log notification
            group_key = self._get_group_key([s.id for s in subscriptions])
            await self._log_notification(
                user.id,
                notification_type,
                level,
                group_key,
            )

            # Commit after logging to avoid transaction conflicts
            await self.session.commit()

            logger.info(
                f"✅ Sent traffic notification to user {user.id} "
                f"(Telegram ID: {user.telegram_id}) "
                f"for {len(subscriptions)} subscription(s)"
            )

        except Exception as e:
            logger.error(
                f"❌ Failed to send traffic notification to user {user.id}: {e}",
                exc_info=True
            )
            # Rollback to avoid leaving pending transaction
            try:
                await self.session.rollback()
            except Exception:
                pass

    def _build_expiry_message(
        self,
        notification_type: str,
        subscriptions: list[Subscription],
        level: str,
        subs_with_conns: list[dict] | None = None,
    ) -> str:
        """Build expiry notification message.

        Args:
            notification_type: Type of notification notification (already string)
            subscriptions: Subscriptions in group
            level: Notification level
            subs_with_conns: Optional mapping of subscriptions to their connections

        Returns:
            Formatted message
        """
        # notification_type is already a string
        notification_type_str = notification_type

        if notification_type_str == NotificationType.EXPIRY_24H:
            time_text = "через 24 часа"
        elif notification_type_str == NotificationType.EXPIRY_12H:
            time_text = "через 12 часов"
        else:  # EXPIRY_1H
            time_text = "через 1 час"

        if level == NotificationLevel.PROFILE:
            # Single connection - use eager loaded data
            if subs_with_conns:
                # Find connections for the first subscription
                sub_data = next(
                    (item for item in subs_with_conns if item["subscription"].id == subscriptions[0].id),
                    None
                )
                if sub_data and sub_data["connections"]:
                    conn = sub_data["connections"][0]
                    inbound = conn.inbound if hasattr(conn, 'inbound') else None
                    server = inbound.server if inbound else None

                    message = (
                        f"⚠️ <b>Ваше подключение истекает {time_text}!</b>\n\n"
                        f"🔌 <b>Подключение:</b> {inbound.remark if inbound else 'Не указано'}\n"
                        f"🖥️ <b>Сервер:</b> {server.name if server else 'Не указано'}\n"
                        f"📅 <b>Дата истечения:</b> {conn.expiry_date.strftime('%d.%m.%Y %H:%M') if conn.expiry_date else 'Не указано'}\n\n"
                        f"Если хотите продлить подписку, обратитесь к администратору."
                    )
                else:
                    message = f"⚠️ <b>Ваше подключение истекает {time_text}!</b>\n\nПодключение не найдено."
            else:
                # Fallback if eager loading failed
                sub = subscriptions[0]
                message = (
                    f"⚠️ <b>Ваше подключение истекает {time_text}!</b>\n\n"
                    f"📦 <b>Подписка:</b> {sub.name}\n"
                    f"📅 <b>Дата истечения:</b> {sub.expiry_date.strftime('%d.%m.%Y %H:%M') if sub.expiry_date else 'Не указано'}\n\n"
                    f"Если хотите продлить подписку, обратитесь к администратору."
                )
        elif level == NotificationLevel.SUBSCRIPTION:
            # Single subscription
            sub = subscriptions[0]
            # Use subscription expiry date first, then connection expiry date
            expiry = sub.expiry_date
            if not expiry and subs_with_conns:
                # Try to get expiry from connections
                sub_data = next(
                    (item for item in subs_with_conns if item["subscription"].id == sub.id),
                    None
                )
                if sub_data and sub_data["connections"]:
                    expiry = sub_data["connections"][0].expiry_date

            message = (
                f"⚠️ <b>Ваша подписка истекает {time_text}!</b>\n\n"
                f"📦 <b>Подписка:</b> {sub.name}\n"
                f"🔌 <b>Подключений:</b> {len(sub.inbound_connections) if hasattr(sub, 'inbound_connections') else 1}\n"
                f"📅 <b>Дата истечения:</b> {expiry.strftime('%d.%m.%Y %H:%M') if expiry else 'Не указано'}\n\n"
                f"Если хотите продлить подписку, обратитесь к администратору."
            )
        else:  # USER
            # Multiple subscriptions
            message = (
                f"⚠️ <b>Ваши подписки истекают {time_text}!</b>\n\n"
                f"<b>Подписки:</b>\n"
            )
            for sub in subscriptions:
                expiry = sub.expiry_date
                if not expiry and subs_with_conns:
                    sub_data = next(
                        (item for item in subs_with_conns if item["subscription"].id == sub.id),
                        None
                    )
                    if sub_data and sub_data["connections"]:
                        expiry = sub_data["connections"][0].expiry_date

                expiry_text = expiry.strftime('%d.%m.%Y %H:%M') if expiry else "Не указано"
                message += f"• 📦 {sub.name} - {expiry_text}\n"

            message += (
                f"\nЕсли хотите продлить подписки, обратитесь к администратору."
            )

        return message

    def _build_traffic_message(
        self,
        subscriptions: list[Subscription],
        level: str,
        remaining_gb: float,
    ) -> str:
        """Build traffic notification message.

        Args:
            subscriptions: Subscriptions in group
            level: Notification level
            remaining_gb: Remaining traffic in GB

        Returns:
            Formatted message
        """
        if level == NotificationLevel.SUBSCRIPTION:
            # Single subscription
            sub = subscriptions[0]
            message = (
                f"⚠️ <b>У вас мало оставшегося трафика!</b>\n\n"
                f"📦 <b>Подписка:</b> {sub.name}\n"
                f"📊 <b>Осталось трафика:</b> {remaining_gb:.2f} ГБ\n"
                f"🔌 <b>Подключений:</b> {len(sub.inbound_connections)}\n\n"
                f"Если хотите увеличить лимит, обратитесь к администратору."
            )
        else:  # USER
            # Multiple subscriptions
            message = (
                f"⚠️ <b>У вас мало оставшегося трафика!</b>\n\n"
                f"📊 <b>Осталось трафика:</b> {remaining_gb:.2f} ГБ\n\n"
                f"<b>Подписки:</b>\n"
            )
            for sub in subscriptions:
                message += f"• 📦 {sub.name}\n"

            message += (
                f"\nЕсли хотите увеличить лимит, обратитесь к администратору."
            )

        return message

    async def _log_notification(
        self,
        user_id: int,
        notification_type: str,
        level: str,
        group_key: str,
    ) -> None:
        """Log sent notification.

        Note: This method adds the log to the session but does not commit.
        The commit should be handled by the caller to avoid transaction conflicts.

        Args:
            user_id: User ID
            notification_type: Type of notification
            level: Level of notification
            group_key: Group key
        """
        try:
            log = NotificationLog(
                user_id=user_id,
                notification_type=notification_type,
                level=level,
                group_key=group_key,
            )
            self.session.add(log)
            # Note: Not committing here to avoid transaction conflicts
            # The caller should commit after all operations
        except Exception as e:
            logger.error(f"Failed to log notification: {e}", exc_info=True)
            # Don't rollback - let the caller handle it

    async def close(self) -> None:
        """Close all XUI clients."""
        for client in self._xui_clients.values():
            try:
                await client.close()
            except Exception as e:
                logger.error(f"Error closing XUI client: {e}", exc_info=True)
        self._xui_clients.clear()
