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


TOKEN_TTL_SECONDS = 86400
# A lost claim response may be retried by the same device for this long; the
# first authenticated use of the issued token closes the window early.
CLAIM_RETRY_SECONDS = 60


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
    if row.device_hash:
        row.device_hash = ''  # The claim response evidently arrived; no re-claims from now on.
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


def _claim_payload(row: AgentConnection, token: str, expires: float) -> dict:
    return {'status': 'active', 'access_token': token, 'project_id': row.project_id,
            'connection_id': row.connection_id, 'expires_at': expires, 'can_commit': row.can_commit}


async def _reissue_claim(db: AsyncSession, row: AgentConnection, now: float) -> dict:
    """Re-issue the token to the paired device whose claim response was lost.

    Rotating the token invalidates the undelivered one, and only the holder of
    the device secret can do it, briefly, before the token is first used.
    """
    claimed_at = row.expires_at - TOKEN_TTL_SECONDS
    if now - claimed_at > CLAIM_RETRY_SECONDS:
        raise AgentError('pairing_expired', 'Pairing expired or already claimed', 409)
    token = 'edc_' + secrets.token_urlsafe(32)
    result = await db.execute(update(AgentConnection).where(
        AgentConnection.connection_id == row.connection_id, AgentConnection.status == 'active',
        AgentConnection.device_hash == row.device_hash, AgentConnection.token_hash == row.token_hash,
    ).values(token_hash=secret_hash(token)))
    if result.rowcount != 1:
        raise AgentError('pairing_expired', 'Pairing already claimed', 409)
    return _claim_payload(row, token, row.expires_at)


async def claim_connection(db: AsyncSession, connection_id: str, secret: str) -> dict:
    # Re-read: the decision depends on the committed status and token, not a cached row.
    row = await db.get(AgentConnection, connection_id, populate_existing=True)
    if row is None or not row.device_hash or not hmac.compare_digest(row.device_hash, secret_hash(secret)):
        raise AgentError('pairing_invalid', 'Invalid pairing request', 401)
    now = time.time()
    if row.status == 'active':
        return await _reissue_claim(db, row, now)
    if row.expires_at <= now or row.status not in {'pending', 'approved'}:
        raise AgentError('pairing_expired', 'Pairing expired or already claimed', 409)
    if row.status == 'pending':
        return {'status': 'pending', 'interval': 3}
    token = 'edc_' + secrets.token_urlsafe(32)
    expires = now + TOKEN_TTL_SECONDS
    # device_hash is kept so a lost response can be re-claimed (see _reissue_claim).
    result = await db.execute(update(AgentConnection).where(
        AgentConnection.connection_id == connection_id, AgentConnection.status == 'approved',
        AgentConnection.expires_at > now,
    ).values(status='active', token_hash=secret_hash(token), expires_at=expires))
    if result.rowcount != 1:
        raise AgentError('pairing_expired', 'Pairing already claimed', 409)
    return _claim_payload(row, token, expires)
