from typing import Optional

from pydantic import BaseModel, EmailStr

from app.schemas.user import UserResponse


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    username: Optional[str] = None
    verification_code: str


class AuthResponse(BaseModel):
    token: str
    user: UserResponse


class CodeExchangeRequest(BaseModel):
    code: str
