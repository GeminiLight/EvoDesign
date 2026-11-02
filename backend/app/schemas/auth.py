from typing import Optional

from pydantic import BaseModel, EmailStr, Field

from app.schemas.user import UserResponse


# PBKDF2 cost grows with input length, so an unbounded password is a DoS vector.
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 1024


class LoginRequest(BaseModel):
    email: EmailStr
    # Login keeps no minimum so accounts created under older rules can sign in.
    password: str = Field(..., max_length=PASSWORD_MAX_LENGTH)


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)
    username: Optional[str] = Field(default=None, max_length=255)
    verification_code: str = Field(..., max_length=256)


class AuthResponse(BaseModel):
    token: str
    user: UserResponse


class CodeExchangeRequest(BaseModel):
    code: str = Field(..., max_length=256)
