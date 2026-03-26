"""Subscription template service for managing subscription templates."""

from typing import Sequence
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import (
    Inbound,
    SubscriptionTemplate,
    SubscriptionTemplateInbound,
    Subscription,
    InboundConnection,
)
from app.xui_client.exceptions import XUIError


class SubscriptionTemplateService:
    """Service for subscription template management."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize service with database session.

        Args:
            session: Async database session
        """
        self.session = session

    # Template CRUD operations

    async def get_all_templates(self) -> Sequence[SubscriptionTemplate]:
        """Get all subscription templates.

        Returns:
            List of all templates
        """
        result = await self.session.execute(
            select(SubscriptionTemplate)
            .options(
                selectinload(SubscriptionTemplate.template_inbounds)
                .selectinload(SubscriptionTemplateInbound.inbound)
                .selectinload(Inbound.server)
            )
            .where(SubscriptionTemplate.is_active == True)
            .order_by(SubscriptionTemplate.created_at.desc())
        )
        return result.scalars().all()

    async def get_template(self, template_id: int) -> SubscriptionTemplate | None:
        """Get template by ID.

        Args:
            template_id: Template ID

        Returns:
            Template or None if not found
        """
        result = await self.session.execute(
            select(SubscriptionTemplate)
            .where(SubscriptionTemplate.id == template_id)
            .options(
                selectinload(SubscriptionTemplate.template_inbounds)
                .selectinload(SubscriptionTemplateInbound.inbound)
                .selectinload(Inbound.server)
            )
        )
        return result.scalar_one_or_none()

    async def create_template(
        self,
        name: str,
        description: str | None = None,
        default_total_gb: int = 0,
        default_expiry_days: int | None = None,
        notes: str | None = None,
    ) -> SubscriptionTemplate:
        """Create a new subscription template.

        Args:
            name: Template name
            description: Template description
            default_total_gb: Default traffic limit in GB (0 = unlimited)
            default_expiry_days: Default expiry in days (None = never)
            notes: Optional notes

        Returns:
            Created template
        """
        template = SubscriptionTemplate(
            name=name,
            description=description,
            default_total_gb=default_total_gb,
            default_expiry_days=default_expiry_days,
            notes=notes,
            is_active=True,
        )
        self.session.add(template)
        await self.session.flush()

        # Reload with relationships
        return await self.get_template(template.id)

    async def update_template(
        self,
        template_id: int,
        name: str | None = None,
        description: str | None = None,
        default_total_gb: int | None = None,
        default_expiry_days: int | None = None,
        notes: str | None = None,
        is_active: bool | None = None,
    ) -> SubscriptionTemplate | None:
        """Update template.

        Args:
            template_id: Template ID
            name: New name (optional)
            description: New description (optional)
            default_total_gb: New traffic limit (optional)
            default_expiry_days: New expiry days (optional)
            notes: New notes (optional)
            is_active: New active status (optional)

        Returns:
            Updated template or None if not found
        """
        template = await self.get_template(template_id)
        if not template:
            return None

        if name is not None:
            template.name = name
        if description is not None:
            template.description = description
        if default_total_gb is not None:
            template.default_total_gb = default_total_gb
        if default_expiry_days is not None:
            template.default_expiry_days = default_expiry_days
        if notes is not None:
            template.notes = notes
        if is_active is not None:
            template.is_active = is_active

        await self.session.flush()

        # Reload with relationships
        return await self.get_template(template_id)

    async def delete_template(self, template_id: int) -> bool:
        """Delete template.

        Args:
            template_id: Template ID

        Returns:
            True if deleted, False if not found
        """
        template = await self.session.get(SubscriptionTemplate, template_id)
        if not template:
            return False

        await self.session.delete(template)
        await self.session.flush()
        return True

    # Template inbound management

    async def add_inbound_to_template(
        self,
        template_id: int,
        inbound_id: int,
        order: int = 0,
    ) -> SubscriptionTemplateInbound:
        """Add inbound to template.

        Args:
            template_id: Template ID
            inbound_id: Inbound ID
            order: Order index (default: 0)

        Returns:
            Created template inbound relationship

        Raises:
            XUIError: If inbound already exists in template
        """
        # Check if inbound already exists in template
        existing = await self.session.execute(
            select(SubscriptionTemplateInbound).where(
                SubscriptionTemplateInbound.template_id == template_id,
                SubscriptionTemplateInbound.inbound_id == inbound_id,
            )
        )
        if existing.scalar_one_or_none():
            raise XUIError("Inbound already exists in this template")

        # Create template inbound relationship
        template_inbound = SubscriptionTemplateInbound(
            template_id=template_id,
            inbound_id=inbound_id,
            order=order,
        )
        self.session.add(template_inbound)
        await self.session.flush()

        # Reload with relationships
        result = await self.session.execute(
            select(SubscriptionTemplateInbound)
            .where(SubscriptionTemplateInbound.id == template_inbound.id)
            .options(
                selectinload(SubscriptionTemplateInbound.inbound)
                .selectinload(Inbound.server)
            )
        )
        return result.scalar_one()

    async def remove_inbound_from_template(
        self,
        template_id: int,
        inbound_id: int,
    ) -> bool:
        """Remove inbound from template.

        Args:
            template_id: Template ID
            inbound_id: Inbound ID

        Returns:
            True if removed, False if not found
        """
        template_inbound = await self.session.execute(
            select(SubscriptionTemplateInbound).where(
                SubscriptionTemplateInbound.template_id == template_id,
                SubscriptionTemplateInbound.inbound_id == inbound_id,
            )
        )
        template_inbound = template_inbound.scalar_one_or_none()
        if not template_inbound:
            return False

        await self.session.delete(template_inbound)
        await self.session.flush()
        return True

    async def reorder_inbounds_in_template(
        self,
        template_id: int,
        inbound_orders: dict[int, int],
    ) -> bool:
        """Reorder inbounds in template.

        Args:
            template_id: Template ID
            inbound_orders: Dictionary mapping inbound_id to order

        Returns:
            True if updated, False if template not found
        """
        template = await self.get_template(template_id)
        if not template:
            return False

        for template_inbound in template.template_inbounds:
            if template_inbound.inbound_id in inbound_orders:
                template_inbound.order = inbound_orders[template_inbound.inbound_id]

        await self.session.flush()
        return True

    # Template subscription creation

    async def create_subscription_from_template(
        self,
        template_id: int,
        client_id: int,
        subscription_name: str,
        total_gb: int | None = None,
        expiry_days: int | None = None,
        notes: str | None = None,
    ) -> tuple[Subscription, list[InboundConnection]]:
        """Create subscription from template.

        Args:
            template_id: Template ID
            client_id: Client ID
            subscription_name: Subscription name
            total_gb: Override traffic limit (None = use template default)
            expiry_days: Override expiry days (None = use template default)
            notes: Optional notes

        Returns:
            Tuple of (created subscription, list of created connections)

        Raises:
            XUIError: If template not found or has no inbounds
        """
        template = await self.get_template(template_id)
        if not template:
            raise XUIError("Template not found")

        if not template.template_inbounds:
            raise XUIError("Template has no inbounds configured")

        # Use template defaults if not overridden
        if total_gb is None:
            total_gb = template.default_total_gb
        if expiry_days is None:
            expiry_days = template.default_expiry_days

        # Import NewSubscriptionService for subscription creation
        from app.services.new_subscription_service import NewSubscriptionService
        sub_service = NewSubscriptionService(self.session)

        # Create subscription
        subscription = await sub_service.create_subscription(
            client_id=client_id,
            name=subscription_name,
            total_gb=total_gb,
            expiry_days=expiry_days,
            notes=notes,
        )

        # Add all inbounds from template
        connections = []
        for template_inbound in template.template_inbounds:
            try:
                connection = await sub_service.add_inbound_to_subscription(
                    subscription_id=subscription.id,
                    inbound_id=template_inbound.inbound_id,
                )
                connections.append(connection)
                logger.info(
                    f"✅ Added inbound {template_inbound.inbound.remark} "
                    f"to subscription {subscription.name} from template {template.name}"
                )
            except Exception as e:
                logger.error(
                    f"❌ Failed to add inbound {template_inbound.inbound.remark} "
                    f"to subscription {subscription.name}: {e}"
                )
                # Continue with other inbounds even if one fails

        if not connections:
            # If all inbounds failed, delete the subscription
            await sub_service.delete_subscription(subscription.id)
            raise XUIError("Failed to create any connections from template")

        return subscription, connections

    # Helper methods

    async def get_template_inbound(
        self,
        template_id: int,
        inbound_id: int,
    ) -> SubscriptionTemplateInbound | None:
        """Get specific template-inbound relationship.

        Args:
            template_id: Template ID
            inbound_id: Inbound ID

        Returns:
            Template inbound relationship or None if not found
        """
        result = await self.session.execute(
            select(SubscriptionTemplateInbound)
            .where(
                SubscriptionTemplateInbound.template_id == template_id,
                SubscriptionTemplateInbound.inbound_id == inbound_id,
            )
            .options(
                selectinload(SubscriptionTemplateInbound.inbound)
                .selectinload(Inbound.server)
            )
        )
        return result.scalar_one_or_none()

    async def get_template_inbounds(self, template_id: int) -> Sequence[SubscriptionTemplateInbound]:
        """Get all inbounds for template.

        Args:
            template_id: Template ID

        Returns:
            List of template inbound relationships
        """
        result = await self.session.execute(
            select(SubscriptionTemplateInbound)
            .where(SubscriptionTemplateInbound.template_id == template_id)
            .options(
                selectinload(SubscriptionTemplateInbound.inbound)
                .selectinload(Inbound.server)
            )
            .order_by(SubscriptionTemplateInbound.order)
        )
        return result.scalars().all()
