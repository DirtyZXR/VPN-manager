"""User service for managing users."""

from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import User


class UserService:
    """Service for user management."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize service with database session.

        Args:
            session: Async database session
        """
        self.session = session

    async def get_all_users(self) -> Sequence[User]:
        """Get all users.

        Returns:
            List of all users
        """
        result = await self.session.execute(
            select(User).order_by(User.created_at.desc())
        )
        return result.scalars().all()

    async def get_active_users(self) -> Sequence[User]:
        """Get all active users.

        Returns:
            List of active users
        """
        result = await self.session.execute(
            select(User).where(User.is_active == True).order_by(User.created_at.desc())
        )
        return result.scalars().all()

    async def get_user_by_id(self, user_id: int) -> User | None:
        """Get user by ID.

        Args:
            user_id: User ID

        Returns:
            User or None if not found
        """
        result = await self.session.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_user_by_telegram_id(self, telegram_id: int) -> User | None:
        """Get user by Telegram ID.

        Args:
            telegram_id: Telegram user ID

        Returns:
            User or None if not found
        """
        result = await self.session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()

    async def create_user(
        self,
        name: str,
        telegram_id: int | None = None,
        is_admin: bool = False,
    ) -> User:
        """Create a new user.

        Args:
            name: User name
            telegram_id: Optional Telegram ID
            is_admin: Whether user is admin

        Returns:
            Created user
        """
        user = User(
            name=name,
            telegram_id=telegram_id,
            is_admin=is_admin,
            is_active=True,
        )
        self.session.add(user)
        await self.session.flush()
        return user

    async def update_user(
        self,
        user_id: int,
        name: str | None = None,
        telegram_id: int | None = None,
        is_active: bool | None = None,
    ) -> User | None:
        """Update user.

        Args:
            user_id: User ID
            name: New name (optional)
            telegram_id: New Telegram ID (optional)
            is_active: New active status (optional)

        Returns:
            Updated user or None if not found
        """
        user = await self.get_user_by_id(user_id)
        if not user:
            return None

        if name is not None:
            user.name = name
        if telegram_id is not None:
            user.telegram_id = telegram_id
        if is_active is not None:
            user.is_active = is_active

        await self.session.flush()
        return user

    async def delete_user(self, user_id: int) -> bool:
        """Delete user.

        Args:
            user_id: User ID

        Returns:
            True if deleted, False if not found
        """
        user = await self.get_user_by_id(user_id)
        if not user:
            return False

        await self.session.delete(user)
        await self.session.flush()
        return True

    async def set_user_active(self, user_id: int, is_active: bool) -> User | None:
        """Set user active status.

        Args:
            user_id: User ID
            is_active: Active status

        Returns:
            Updated user or None if not found
        """
        return await self.update_user(user_id, is_active=is_active)

    async def rename_user(self, user_id: int, new_name: str) -> User | None:
        """Rename user.

        Args:
            user_id: User ID
            new_name: New name

        Returns:
            Updated user or None if not found
        """
        return await self.update_user(user_id, name=new_name)
