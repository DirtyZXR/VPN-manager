"""Subscription request service."""

from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import Client, SubscriptionRequest, SubscriptionTemplate


class SubscriptionRequestService:
    """Service for managing subscription requests."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize service with database session.

        Args:
            session: Async database session
        """
        self.session = session

    async def get_pending_requests_count(self, client_id: int) -> int:
        """Get the count of pending subscription requests for a client.

        Args:
            client_id: Client ID

        Returns:
            Number of pending requests
        """
        result = await self.session.execute(
            select(func.count(SubscriptionRequest.id)).where(
                SubscriptionRequest.client_id == client_id,
            )
        )
        return result.scalar_one_or_none() or 0

    async def create_request(
        self, client_id: int, template_id: int, requested_name: str | None = None
    ) -> SubscriptionRequest:
        """Create a new subscription request.

        Args:
            client_id: Client ID
            template_id: Template ID
            requested_name: Optional requested name for the subscription

        Returns:
            Created subscription request
        """
        request = SubscriptionRequest(
            client_id=client_id,
            template_id=template_id,
            requested_name=requested_name,
        )
        self.session.add(request)
        await self.session.flush()

        # Reload with relationships
        loaded_request = await self.get_request(request.id)
        if not loaded_request:
            raise RuntimeError("Failed to load created request")
        return loaded_request

    async def get_request(self, request_id: int) -> SubscriptionRequest | None:
        """Get a subscription request by ID.

        Args:
            request_id: Request ID

        Returns:
            Subscription request with eagerly loaded template and client, or None if not found
        """
        result = await self.session.execute(
            select(SubscriptionRequest)
            .where(SubscriptionRequest.id == request_id)
            .options(
                selectinload(SubscriptionRequest.template),
                selectinload(SubscriptionRequest.client),
            )
        )
        return result.scalar_one_or_none()

    async def delete_request(self, request_id: int) -> bool:
        """Delete a subscription request.

        Args:
            request_id: Request ID

        Returns:
            True if deleted, False if not found
        """
        request = await self.session.get(SubscriptionRequest, request_id)
        if not request:
            return False

        await self.session.delete(request)
        await self.session.flush()
        return True
