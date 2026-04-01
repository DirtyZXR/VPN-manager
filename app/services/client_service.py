"""Client service for managing VPN clients."""

from typing import Sequence
from loguru import logger
import re

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import Client
from app.utils import generate_email


def _normalize_search_query(query: str, is_email: bool = False) -> str:
    """Normalize search query by removing extra spaces and special chars.

    Args:
        query: Raw search query
        is_email: Whether this is an email search (preserves @ and .)

    Returns:
        Normalized query
    """
    # Remove extra whitespace
    query = " ".join(query.split())

    # Remove common punctuation except @ and . for emails
    if not is_email:
        query = re.sub(r'[,.!?:;\'"()\[\]{}<>|\\/~^$*+?@]', " ", query)
        # Remove extra spaces again after removing punctuation
        query = " ".join(query.split())

    return query.strip()


def _split_query_into_words(query: str) -> list[str]:
    """Split query into individual words for multi-word search.

    Args:
        query: Search query

    Returns:
        List of words
    """
    normalized = _normalize_search_query(query, is_email=False)
    words = normalized.split()
    return [word for word in words if len(word) > 1]  # Skip single characters


class ClientService:
    """Service for client management."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize service with database session.

        Args:
            session: Async database session
        """
        self.session = session

    async def get_all_clients(self) -> Sequence[Client]:
        """Get all clients.

        Returns:
            List of all clients
        """
        result = await self.session.execute(
            select(Client)
            .options(selectinload(Client.subscriptions))
            .order_by(Client.created_at.desc())
        )
        return result.scalars().all()

    async def get_active_clients(self) -> Sequence[Client]:
        """Get all active clients.

        Returns:
            List of active clients
        """
        result = await self.session.execute(
            select(Client)
            .where(Client.is_active == True)
            .options(selectinload(Client.subscriptions))
            .order_by(Client.created_at.desc())
        )
        return result.scalars().all()

    async def get_clients_paginated(
        self, page: int = 0, per_page: int = 5
    ) -> tuple[Sequence[Client], int]:
        """Get clients with pagination.

        Args:
            page: Page number (0-indexed)
            per_page: Number of clients per page

        Returns:
            Tuple of (clients for this page, total client count)
        """
        count_result = await self.session.execute(select(Client).where(Client.is_active == True))
        total_count = len(count_result.scalars().all())

        offset = page * per_page
        result = await self.session.execute(
            select(Client)
            .where(Client.is_active == True)
            .options(selectinload(Client.subscriptions))
            .order_by(Client.created_at.desc())
            .offset(offset)
            .limit(per_page)
        )
        clients = result.scalars().all()

        return clients, total_count

    async def get_client_by_id(self, client_id: int) -> Client | None:
        """Get client by ID.

        Args:
            client_id: Client ID

        Returns:
            Client or None if not found
        """
        result = await self.session.execute(
            select(Client).where(Client.id == client_id).options(selectinload(Client.subscriptions))
        )
        return result.scalar_one_or_none()

    async def get_client_by_email(self, email: str) -> Client | None:
        """Get client by email.

        Args:
            email: Client email

        Returns:
            Client or None if not found
        """
        result = await self.session.execute(select(Client).where(Client.email == email))
        return result.scalar_one_or_none()

    async def get_client_by_telegram_id(self, telegram_id: int) -> Client | None:
        """Get client by Telegram ID.

        Args:
            telegram_id: Client Telegram ID

        Returns:
            Client or None if not found
        """
        result = await self.session.execute(select(Client).where(Client.telegram_id == telegram_id))
        return result.scalar_one_or_none()

    async def get_client_by_telegram_username(self, telegram_username: str) -> Client | None:
        """Get client by Telegram username (case-insensitive).

        Args:
            telegram_username: Client Telegram username (@example)

        Returns:
            Client or None if not found
        """
        username = telegram_username.lstrip("@").lower()
        result = await self.session.execute(
            select(Client).where(Client.telegram_username_lower == username)
        )
        return result.scalar_one_or_none()

    async def create_client(
        self,
        name: str,
        email: str | None = None,
        telegram_id: int | None = None,
        telegram_username: str | None = None,
        notes: str | None = None,
        is_admin: bool = False,
    ) -> Client:
        """Create a new client.

        Args:
            name: Client name
            email: Client email (generated if not provided)
            telegram_id: Optional Telegram ID
            telegram_username: Optional Telegram username (@example)
            notes: Optional notes
            is_admin: Whether client is admin

        Returns:
            Created client
        """
        if email is None:
            email = generate_email(name, "vpn", "client")

        clean_username = telegram_username.lstrip("@") if telegram_username else None
        client = Client(
            name=name,
            name_lower=name.lower(),
            email=email,
            telegram_id=telegram_id,
            telegram_username=clean_username,
            telegram_username_lower=clean_username.lower() if clean_username else None,
            notes=notes,
            is_active=True,
            is_admin=is_admin,
        )
        self.session.add(client)
        await self.session.flush()
        return client

    async def update_client(
        self,
        client_id: int,
        name: str | None = None,
        email: str | None = None,
        telegram_id: int | None = None,
        telegram_username: str | None = None,
        notes: str | None = None,
        is_active: bool | None = None,
        is_admin: bool | None = None,
    ) -> Client | None:
        """Update client.

        Args:
            client_id: Client ID
            name: New name (optional)
            email: New email (optional)
            telegram_id: New Telegram ID (optional)
            notes: New notes (optional)
            is_active: New active status (optional)
            is_admin: New admin status (optional)

        Returns:
            Updated client or None if not found
        """
        client = await self.get_client_by_id(client_id)
        if not client:
            return None

        # Track if Telegram ID is being updated
        telegram_id_changed = False
        if telegram_id is not None and telegram_id != client.telegram_id:
            telegram_id_changed = True

        if name is not None:
            client.name = name
            client.name_lower = name.lower()
        if email is not None:
            client.email = email
        if telegram_id is not None:
            client.telegram_id = telegram_id
        if telegram_username is not None:
            clean_username = telegram_username.lstrip("@")
            client.telegram_username = clean_username
            client.telegram_username_lower = clean_username.lower() if clean_username else None
        if notes is not None:
            client.notes = notes
        if is_active is not None:
            client.is_active = is_active
        if is_admin is not None:
            client.is_admin = is_admin

        await self.session.flush()

        # Sync Telegram ID to XUI if changed
        if telegram_id_changed:
            try:
                from app.services.new_subscription_service import NewSubscriptionService

                sub_service = NewSubscriptionService(self.session)
                updated = await sub_service.sync_client_telegram_id(client_id)
                logger.info(
                    f"✅ Synced Telegram ID for client {client_id}, updated {updated} connections in XUI"
                )
                await sub_service.close_all_clients()
            except Exception as e:
                logger.error(
                    f"Failed to sync Telegram ID for client {client_id}: {e}", exc_info=True
                )

        return client

    async def delete_client(self, client_id: int) -> bool:
        """Delete client.

        Args:
            client_id: Client ID

        Returns:
            True if deleted, False if not found
        """
        client = await self.get_client_by_id(client_id)
        if not client:
            return False

        await self.session.delete(client)
        await self.session.flush()
        return True

    async def set_client_active(self, client_id: int, is_active: bool) -> Client | None:
        """Set client active status.

        Args:
            client_id: Client ID
            is_active: Active status

        Returns:
            Updated client or None if not found
        """
        return await self.update_client(client_id, is_active=is_active)

    async def rename_client(self, client_id: int, new_name: str) -> Client | None:
        """Rename client.

        Args:
            client_id: Client ID
            new_name: New name

        Returns:
            Updated client or None if not found
        """
        return await self.update_client(client_id, name=new_name)

    async def set_client_admin(self, client_id: int, is_admin: bool) -> Client | None:
        """Set client admin status.

        Args:
            client_id: Client ID
            is_admin: Admin status

        Returns:
            Updated client or None if not found
        """
        return await self.update_client(client_id, is_admin=is_admin)

    async def search_clients(
        self,
        name: str | None = None,
        email: str | None = None,
        telegram_id: int | None = None,
        xui_email: str | None = None,
        search_all_fields: bool = False,
    ) -> Sequence[Client]:
        """Search clients by various criteria with smart text processing.

        Uses pre-lowered columns (name_lower, telegram_username_lower) for
        case-insensitive search that works correctly with Cyrillic text.

        Args:
            name: Partial name match (case-insensitive, multi-word support)
            email: Partial email match (case-insensitive, normalized)
            telegram_id: Exact Telegram ID match
            xui_email: Partial XUI connection email match (case-insensitive, normalized)
            search_all_fields: If True, searches all fields with OR logic

        Returns:
            List of matching clients
        """
        from sqlalchemy import or_, and_, text
        from app.database.models import InboundConnection, Subscription

        conditions = []

        # telegram_id is always an exact AND filter, never OR with text fields
        if telegram_id:
            query = select(Client).where(Client.telegram_id == telegram_id)
        else:
            query = select(Client)

        query = query.options(selectinload(Client.subscriptions))

        if name:
            normalized_name = _normalize_search_query(name, is_email=False)
            name_lower_query = normalized_name.lower()

            name_words = _split_query_into_words(normalized_name)

            if len(name_words) > 1:
                name_conditions = []
                for word in name_words:
                    name_conditions.append(Client.name_lower.like(f"%{word.lower()}%"))

                conditions.append(or_(*name_conditions))
            else:
                conditions.append(Client.name_lower.like(f"%{name_lower_query}%"))

        if email:
            normalized_email = _normalize_search_query(email, is_email=True).lower()
            conditions.append(Client.email.like(f"%{normalized_email}%"))

        if xui_email:
            normalized_xui_email = _normalize_search_query(xui_email, is_email=True).lower()

            query = (
                query.join(Subscription, Client.id == Subscription.client_id)
                .join(InboundConnection, Subscription.id == InboundConnection.subscription_id)
                .where(InboundConnection.email.like(f"%{normalized_xui_email}%"))
            )

        if conditions:
            if xui_email:
                query = query.where(and_(*conditions))
            else:
                query = query.where(or_(*conditions))

        query = query.order_by(Client.created_at.desc())
        query = query.distinct()

        result = await self.session.execute(query)
        return result.scalars().all()

    async def search_clients_all_fields(self, query: str) -> Sequence[Client]:
        """Search clients across all fields with OR logic.

        Searches: name, email, telegram_id, telegram_username, XUI email.
        Uses pre-lowered columns for case-insensitive Cyrillic support.

        When query is purely numeric, searches ONLY by telegram_id (exact match)
        to avoid false positives from substring matching in UUID-based emails.

        Args:
            query: Search term to match across all fields

        Returns:
            List of matching clients
        """
        from sqlalchemy import or_
        from app.database.models import InboundConnection, Subscription

        # If query is purely numeric, search only by telegram_id
        if query.strip().isdigit():
            search_query = (
                select(Client)
                .options(selectinload(Client.subscriptions))
                .where(Client.telegram_id == int(query))
                .order_by(Client.created_at.desc())
            )
            result = await self.session.execute(search_query)
            return result.scalars().all()

        # Text query: search across all text fields
        normalized_query = _normalize_search_query(query, is_email=False)
        query_lower = normalized_query.lower()

        all_conditions = []

        name_words = _split_query_into_words(normalized_query)
        if len(name_words) > 1:
            word_conditions = []
            for word in name_words:
                word_conditions.append(Client.name_lower.like(f"%{word.lower()}%"))
            all_conditions.append(or_(*word_conditions))
        else:
            all_conditions.append(Client.name_lower.like(f"%{query_lower}%"))

        normalized_email = _normalize_search_query(query, is_email=True).lower()
        all_conditions.append(Client.email.like(f"%{normalized_email}%"))

        all_conditions.append(Client.telegram_username_lower.like(f"%{query_lower}%"))

        xui_email_condition = InboundConnection.email.like(f"%{normalized_email}%")

        search_query = select(Client).options(selectinload(Client.subscriptions))

        search_query = search_query.join(Subscription, Client.id == Subscription.client_id).join(
            InboundConnection, Subscription.id == InboundConnection.subscription_id
        )

        direct_conditions = or_(*all_conditions)
        final_condition = or_(direct_conditions, xui_email_condition)

        search_query = search_query.where(final_condition)
        search_query = search_query.distinct()
        search_query = search_query.order_by(Client.created_at.desc())

        result = await self.session.execute(search_query)
        return result.scalars().all()
