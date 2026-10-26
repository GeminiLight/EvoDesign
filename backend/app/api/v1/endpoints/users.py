from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.api.deps import get_current_user_id
from app.schemas.user import UserUpdate, UserResponse
from app.schemas.subscription import SubscriptionStatus, SubscriptionResponse
from app.services.user_service import UserService

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("/subscription", response_model=SubscriptionStatus)
async def get_subscription(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db)
):
    """Return the current user's subscription status."""
    user_service = UserService(db)

    subscription = await user_service.get_subscription(user_id)

    return SubscriptionStatus(
        subscription=SubscriptionResponse.model_validate(subscription) if subscription else None
    )


@router.put("/profile", response_model=UserResponse)
async def update_profile(
    data: UserUpdate,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db)
):
    """Update the current user's profile."""
    user_service = UserService(db)

    user = await user_service.update_profile(
        user_id=user_id,
        username=data.username,
        avatar_url=data.avatar_url
    )

    return UserResponse.model_validate(user)
