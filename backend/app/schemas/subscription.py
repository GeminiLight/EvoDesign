from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import Optional


class SubscriptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: str
    status: str
    price_id: Optional[str] = None
    current_period_end: Optional[datetime] = None
    stripe_customer_id: Optional[str] = None
    stripe_subscription_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class SubscriptionStatus(BaseModel):
    subscription: Optional[SubscriptionResponse] = None
