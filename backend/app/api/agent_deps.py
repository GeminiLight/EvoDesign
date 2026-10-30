"""Agent credentials are accepted only on the scoped collaboration surface."""

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import security, _load_user_from_token
from app.config import Settings, get_settings
from app.db.session import get_db
from app.services.agent_connection_service import AgentActor, authenticate_connection
from app.services.agent_contract import AgentError


async def get_agent_actor(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings),
) -> AgentActor:
    if credentials is None:
        raise AgentError('authentication_required', 'Sign in or connect an Agent', 401)
    token = credentials.credentials
    if token.startswith('edc_'):
        return await authenticate_connection(db, token)
    user = await _load_user_from_token(token=token, db=db, settings=settings)
    return AgentActor(user.user_id)
