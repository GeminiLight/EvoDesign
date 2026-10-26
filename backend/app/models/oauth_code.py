import secrets
from sqlalchemy import Column, String, Float
from app.db.base import Base


class OAuthCode(Base):
    __tablename__ = "oauth_codes"

    code = Column(String, primary_key=True, default=lambda: secrets.token_urlsafe(48))
    token = Column(String, nullable=False)
    expires_at = Column(Float, nullable=False)  # Unix timestamp
