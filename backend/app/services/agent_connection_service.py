"""Short-lived pairing and revocable, single-project opaque credentials."""

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import AgentConnection
from app.services.agent_contract import AgentError
from app.services.document_service import owned_project


def secret_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@dataclass(frozen=True)
class AgentActor:
    user_id: str
    connection: AgentConnection | None = None

    def require_project(self, project_id: str) -> None:
        if self.connection and self.connection.project_id != project_id:
            raise AgentError('project_forbidden', 'Connection is bound to another project', 403)


async def authenticate_connection(db: AsyncSession, token: str) -> AgentActor:
    row = (await db.execute(select(AgentConnection).where(AgentConnection.token_hash == secret_hash(token)))).scalar_one_or_none()
    if row is None or row.status != 'active' or row.expires_at <= time.time():
        raise AgentError('connection_expired', 'Connection expired or revoked', 401)
    return AgentActor(row.user_id, row)


async def create_connection(db: AsyncSession, name: str) -> tuple[AgentConnection, str]:
    secret = secrets.token_urlsafe(32)
    row = AgentConnection(name=name, user_code=secrets.token_hex(4).upper(), device_hash=secret_hash(secret),
                          expires_at=time.time() + 600)
    db.add(row)
    await db.flush()
    return row, secret


async def approve_connection(db: AsyncSession, connection_id: str, user_id: str,
                             project_id: str, code: str, can_commit: bool) -> None:
    project = await owned_project(db, user_id, project_id)
    if project.canvas_engine != 'excalidraw':
        raise AgentError('unsupported_canvas', 'Agent connections currently support Excalidraw projects', 422)
    result = await db.execute(update(AgentConnection).where(
        AgentConnection.connection_id == connection_id, AgentConnection.status == 'pending',
        AgentConnection.expires_at > time.time(), AgentConnection.user_code == code.upper(),
    ).values(user_id=user_id, project_id=project_id, can_commit=can_commit, status='approved'))
    if result.rowcount != 1:
        raise AgentError('pairing_expired', 'Pairing expired, already used, or code does not match', 409)


async def claim_connection(db: AsyncSession, connection_id: str, secret: str) -> dict:
    row = await db.get(AgentConnection, connection_id)
    if row is None or not hmac.compare_digest(row.device_hash, secret_hash(secret)):
        raise AgentError('pairing_invalid', 'Invalid pairing request', 401)
    if row.expires_at <= time.time() or row.status not in {'pending', 'approved'}:
        raise AgentError('pairing_expired', 'Pairing expired or already claimed', 409)
    if row.status == 'pending':
        return {'status': 'pending', 'interval': 3}
    token = 'edc_' + secrets.token_urlsafe(32)
    expires = time.time() + 86400
    result = await db.execute(update(AgentConnection).where(
        AgentConnection.connection_id == connection_id, AgentConnection.status == 'approved',
        AgentConnection.expires_at > time.time(),
    ).values(status='active', token_hash=secret_hash(token), device_hash='', expires_at=expires))
    if result.rowcount != 1:
        raise AgentError('pairing_expired', 'Pairing already claimed', 409)
    return {'status': 'active', 'access_token': token, 'project_id': row.project_id,
            'connection_id': row.connection_id, 'expires_at': expires, 'can_commit': row.can_commit}
