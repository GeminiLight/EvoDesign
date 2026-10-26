from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional

from app.db.base import utc_now
from app.models.user import User
from app.models.subscription import Subscription
from app.core.exceptions import UserNotFoundException


class UserService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, user_id: str) -> Optional[User]:
        """Return a user by ID."""
        result = await self.db.execute(
            select(User).where(User.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id_or_raise(self, user_id: str) -> User:
        """Return a user by ID or raise when it does not exist."""
        user = await self.get_by_id(user_id)
        if not user:
            raise UserNotFoundException()
        return user

    async def update_profile(
        self,
        user_id: str,
        username: Optional[str] = None,
        avatar_url: Optional[str] = None
    ) -> User:
        """Update mutable user profile fields."""
        user = await self.get_by_id_or_raise(user_id)

        if username is not None:
            user.username = username
        if avatar_url is not None:
            user.avatar_url = avatar_url

        user.updated_at = utc_now()
        await self.db.flush()
        await self.db.refresh(user)
        return user

    async def get_subscription(self, user_id: str) -> Optional[Subscription]:
        """Return subscription details for a user."""
        result = await self.db.execute(
            select(Subscription).where(Subscription.user_id == user_id)
        )
        return result.scalar_one_or_none()
