from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class UserUpdate(BaseModel):
    username: Optional[str] = None
    avatar_url: Optional[str] = None


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: str
    email: str
    username: Optional[str] = None
    avatar_url: Optional[str] = None
    auth_provider: str
    created_at: datetime
