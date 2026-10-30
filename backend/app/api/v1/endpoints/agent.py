"""Project-scoped Agent connection, document and proposal API."""

import copy
import asyncio
from pathlib import Path
import time
from urllib.parse import quote
from uuid import uuid4

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import FileResponse
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer, load_only

from app.api.agent_deps import get_agent_actor
from app.api.deps import get_current_user_id
from app.config import Settings, get_settings
from app.core.rate_limit import limiter
from app.db.session import get_db
from app.models.agent import AgentConnection, AgentProposal
from app.models.snapshot import Snapshot
from app.services.agent_connection_service import AgentActor, approve_connection, claim_connection, create_connection
from app.services.agent_contract import (AgentError, ApprovalRequest, ClaimRequest, ConnectionRequest,
    ContextRequest, ProposalRequest, RestoreRequest, envelope)
from app.services.agent_proposal_service import (artifact_root, commit_proposal, create_proposal,
    get_proposal, prepare_preview, render_candidate, restore_proposal)
from app.services.document_service import digest, effective_constraints, node_index, owned_project

router = APIRouter(tags=['Agent collaboration'])


def proposal_view(row: AgentProposal) -> dict:
    return {k: getattr(row, k) for k in ('proposal_id', 'project_id', 'base_version', 'status', 'changed_ids',
            'report', 'committed_version', 'committed_snapshot_id', 'expires_at', 'author_kind')}


def connection_view(row: AgentConnection) -> dict:
    return {k: getattr(row, k) for k in ('connection_id', 'project_id', 'name', 'status',
                                       'can_commit', 'expires_at', 'context_version')}


@router.post('/agent/connections', status_code=201)
@limiter.limit('10/minute')
async def start_connection(request: Request, body: ConnectionRequest, db: AsyncSession = Depends(get_db),
                           settings: Settings = Depends(get_settings)):
    row, secret = await create_connection(db, body.name)
    return envelope({**connection_view(row), 'device_secret': secret, 'user_code': row.user_code,
        'interval': 3, 'web_origin': settings.frontend_url.rstrip('/'),
        'verification_url': settings.frontend_url.rstrip('/') + '/agent/connect?id=' + quote(row.connection_id)})


@router.post('/agent/connections/{connection_id}/claim')
@limiter.limit('30/minute')
async def claim(request: Request, connection_id: str, body: ClaimRequest, db: AsyncSession = Depends(get_db)):
    return envelope(await claim_connection(db, connection_id, body.device_secret))


@router.get('/agent/connections')
async def connections(project_id: str, user_id: str = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    await owned_project(db, user_id, project_id)
    rows = (await db.execute(select(AgentConnection).where(AgentConnection.user_id == user_id,
        AgentConnection.project_id == project_id).order_by(AgentConnection.created_at.desc()).limit(50))).scalars()
    return envelope([connection_view(r) for r in rows])


@router.get('/agent/connections/{connection_id}')
async def connection_status(connection_id: str, actor: AgentActor = Depends(get_agent_actor), db: AsyncSession = Depends(get_db)):
    row = await db.get(AgentConnection, connection_id)
    if row is None or (actor.connection and row.connection_id != actor.connection.connection_id) or (row.user_id and row.user_id != actor.user_id):
        raise AgentError('connection_missing', 'Connection not found', 404)
    return envelope(connection_view(row))


@router.post('/agent/connections/{connection_id}/approve')
async def approve(connection_id: str, body: ApprovalRequest, user_id: str = Depends(get_current_user_id),
                  db: AsyncSession = Depends(get_db)):
    await approve_connection(db, connection_id, user_id, body.project_id, body.user_code, body.can_commit)
    return envelope({'status': 'approved', 'project_id': body.project_id})


@router.delete('/agent/connections/{connection_id}')
async def revoke(connection_id: str, actor: AgentActor = Depends(get_agent_actor), db: AsyncSession = Depends(get_db)):
    row = await db.get(AgentConnection, connection_id)
    if row is None or row.user_id != actor.user_id or (actor.connection and row.connection_id != actor.connection.connection_id):
        raise AgentError('connection_missing', 'Connection not found', 404)
    await db.execute(update(AgentConnection).where(AgentConnection.connection_id == connection_id).values(status='revoked', token_hash=None))
    return envelope({'status': 'revoked'})


@router.put('/agent/connections/{connection_id}/context')
async def publish_context(connection_id: str, body: ContextRequest, user_id: str = Depends(get_current_user_id),
                          db: AsyncSession = Depends(get_db)):
    row = await db.get(AgentConnection, connection_id)
    if row is None or row.user_id != user_id or row.status != 'active' or row.expires_at <= time.time():
        raise AgentError('connection_expired', 'Connection expired or revoked', 409)
    project = await owned_project(db, user_id, row.project_id)
    if project.version != body.version:
        raise AgentError('version_conflict', 'Save the current document before sharing', current_version=project.version)
    ids = {e['id'] for e in (project.latest_schema or {}).get('elements', []) if not e.get('isDeleted')}
    if (set(body.selected_ids) | set(body.locked_ids)) - ids:
        raise AgentError('context_stale', 'Selection contains missing elements')
    row.context_version += 1
    row.context_json = {**body.model_dump(), 'expires_at': time.time()+600}
    return envelope({'context_version': row.context_version, **row.context_json})


@router.get('/projects/{project_id}/document/head')
async def document_head(project_id: str, actor: AgentActor = Depends(get_agent_actor), db: AsyncSession = Depends(get_db)):
    actor.require_project(project_id)
    project = await owned_project(db, actor.user_id, project_id)
    return envelope({'project_id': project_id, 'version': project.version, 'snapshot_id': project.current_snapshot_id})


@router.get('/projects/{project_id}/document')
async def document(project_id: str, actor: AgentActor = Depends(get_agent_actor), db: AsyncSession = Depends(get_db),
                   settings: Settings = Depends(get_settings)):
    actor.require_project(project_id)
    project = await owned_project(db, actor.user_id, project_id)
    schema = project.latest_schema or {'elements': []}
    snapshot = await db.get(Snapshot, project.current_snapshot_id) if project.current_snapshot_id else None
    constraints = await effective_constraints(db, project)
    version = await db.scalar(select(type(project).version).where(type(project).project_id == project_id))
    if version != project.version:
        raise AgentError('version_conflict', 'Document changed while reading; read it again', current_version=version)
    return envelope({'project_id': project_id, 'title': project.title, 'version': project.version,
        'snapshot_id': project.current_snapshot_id, 'canvas_library': project.canvas_engine,
        'schema': schema, 'nodes': node_index(schema), 'constraints': constraints,
        'metrics_scores': snapshot.metrics_scores if snapshot else None,
        'capabilities': {'semantic_edit': project.canvas_engine == 'excalidraw',
                         'operations': ['add_node', 'connect', 'set_text', 'move_node', 'set_style', 'delete_node'] if project.canvas_engine == 'excalidraw' else []},
        'web_url': settings.frontend_url.rstrip('/') + '/workspace?project=' + quote(project_id)})


@router.get('/projects/{project_id}/document/preview')
@limiter.limit('20/minute')
async def document_preview(request: Request, project_id: str, version: int,
                           actor: AgentActor = Depends(get_agent_actor), db: AsyncSession = Depends(get_db)):
    actor.require_project(project_id)
    project = await owned_project(db, actor.user_id, project_id)
    if project.version != version:
        raise AgentError('version_conflict', 'The saved design changed; refresh the comparison', current_version=project.version)
    if project.canvas_engine != 'excalidraw':
        raise AgentError('unsupported_canvas', 'Preview currently supports Excalidraw', 422)
    schema = copy.deepcopy(project.latest_schema or {'elements': []})
    directory = artifact_root() / 'formal' / project_id
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    output = directory / f'{version}-{digest(schema)[:16]}.png'
    if not output.is_file():
        temporary = directory / (str(uuid4()) + '.png')
        try:
            await asyncio.wait_for(asyncio.to_thread(render_candidate, schema, temporary), timeout=45)
            temporary.replace(output)
        except asyncio.TimeoutError as exc:
            raise AgentError('render_failed', 'Preview timed out; the saved document is unchanged', 503) from exc
    return FileResponse(output, media_type='image/png', headers={'Cache-Control': 'private, no-store',
                        'X-EvoDesign-Version': str(version)})


@router.get('/projects/{project_id}/agent-context')
async def context(project_id: str, actor: AgentActor = Depends(get_agent_actor), db: AsyncSession = Depends(get_db)):
    actor.require_project(project_id)
    project = await owned_project(db, actor.user_id, project_id)
    shared = actor.connection.context_json if actor.connection else None
    valid = bool(shared and shared['expires_at'] > time.time() and shared['version'] == project.version)
    return envelope({'project_id': project_id, 'version': project.version,
        **await effective_constraints(db, project), 'selection_status': 'current' if valid else 'stale' if shared else 'missing',
        'context_version': actor.connection.context_version if actor.connection else None,
        'selection': shared if valid else None})


@router.get('/projects/{project_id}/agent-history')
async def history(project_id: str, limit: int = 20, actor: AgentActor = Depends(get_agent_actor), db: AsyncSession = Depends(get_db)):
    actor.require_project(project_id)
    await owned_project(db, actor.user_id, project_id)
    rows = (await db.execute(select(Snapshot).options(load_only(Snapshot.snapshot_id, Snapshot.parent_id,
        Snapshot.is_checkpoint, Snapshot.edit_source, Snapshot.timestamp)).where(Snapshot.project_id == project_id)
             .order_by(Snapshot.timestamp.desc(), Snapshot.snapshot_id.desc()).limit(max(1, min(limit, 100))))).scalars()
    return envelope([{'snapshot_id': r.snapshot_id, 'parent_id': r.parent_id, 'is_checkpoint': r.is_checkpoint,
                      'edit_source': r.edit_source, 'created_at': r.timestamp.isoformat()} for r in rows])


@router.post('/projects/{project_id}/agent-proposals', status_code=status.HTTP_202_ACCEPTED)
async def propose(project_id: str, body: ProposalRequest, actor: AgentActor = Depends(get_agent_actor), db: AsyncSession = Depends(get_db)):
    return envelope(proposal_view(await create_proposal(db, actor, project_id, body)))


@router.get('/projects/{project_id}/agent-proposals')
async def proposals(project_id: str, actor: AgentActor = Depends(get_agent_actor), db: AsyncSession = Depends(get_db)):
    actor.require_project(project_id)
    await owned_project(db, actor.user_id, project_id)
    rows = (await db.execute(select(AgentProposal).options(defer(AgentProposal.base_schema),
        defer(AgentProposal.candidate_schema)).where(AgentProposal.project_id == project_id,
            AgentProposal.user_id == actor.user_id).order_by(AgentProposal.created_at.desc()).limit(30))).scalars()
    return envelope([proposal_view(r) for r in rows])


@router.get('/projects/{project_id}/agent-proposals/{proposal_id}')
async def proposal_status(project_id: str, proposal_id: str, actor: AgentActor = Depends(get_agent_actor), db: AsyncSession = Depends(get_db)):
    proposal = await get_proposal(db, actor, project_id, proposal_id)
    return envelope(proposal_view(await prepare_preview(db, proposal)))


@router.get('/projects/{project_id}/agent-proposals/{proposal_id}/preview')
async def preview(project_id: str, proposal_id: str, actor: AgentActor = Depends(get_agent_actor), db: AsyncSession = Depends(get_db)):
    proposal = await get_proposal(db, actor, project_id, proposal_id)
    if not proposal.preview_path:
        raise AgentError('proposal_not_ready', 'Preview is not ready', 409)
    path = Path(proposal.preview_path).resolve()
    if not path.is_relative_to(artifact_root().resolve()) or not path.is_file():
        raise AgentError('preview_missing', 'Preview is unavailable', 404)
    return FileResponse(path, media_type='image/png', headers={'Cache-Control': 'private, no-store'})


@router.post('/projects/{project_id}/agent-proposals/{proposal_id}/commit')
async def commit(project_id: str, proposal_id: str, actor: AgentActor = Depends(get_agent_actor), db: AsyncSession = Depends(get_db)):
    return envelope(proposal_view(await commit_proposal(db, actor, project_id, proposal_id)))


@router.post('/projects/{project_id}/agent-proposals/{proposal_id}/reject')
async def reject(project_id: str, proposal_id: str, actor: AgentActor = Depends(get_agent_actor), db: AsyncSession = Depends(get_db)):
    proposal = await get_proposal(db, actor, project_id, proposal_id)
    if proposal.status == 'committed':
        raise AgentError('proposal_committed', 'A committed proposal cannot be rejected')
    proposal.status = 'rejected'
    return envelope(proposal_view(proposal))


@router.post('/projects/{project_id}/restore-proposals', status_code=202)
async def restore(project_id: str, body: RestoreRequest, actor: AgentActor = Depends(get_agent_actor), db: AsyncSession = Depends(get_db)):
    return envelope(proposal_view(await restore_proposal(db, actor, project_id, body.snapshot_id, body.operation_id, body.base_version)))
