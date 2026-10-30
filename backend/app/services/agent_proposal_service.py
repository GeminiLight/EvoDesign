"""Prepare immutable candidates, render them and commit with a version fence."""

import asyncio
import copy
from pathlib import Path
import time
from uuid import uuid4

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.models.agent import AgentConnection, AgentProposal
from app.models.snapshot import Snapshot
from app.models.project import Project
from app.services.agent_connection_service import AgentActor
from app.services.agent_contract import AgentError, ProposalRequest
from app.services.document_commit_service import commit_document, VersionConflictError
from app.services.document_service import digest, effective_constraints, owned_project

_render_slots = asyncio.Semaphore(4)


async def _render_guarded(schema: dict, output: Path, started: asyncio.Event) -> dict:
    async with _render_slots:
        started.set()
        return await asyncio.to_thread(render_candidate, schema, output)


def _consume_render_result(task: asyncio.Task) -> None:
    if not task.cancelled():
        task.exception()  # A timed-out HTTP caller can leave a bounded render running.


def artifact_root() -> Path:
    # Outside the checkout's public frontend tree; never served without auth.
    return Path(__file__).resolve().parents[3] / 'data' / 'agent-previews'


async def get_proposal(db: AsyncSession, actor: AgentActor, project_id: str, proposal_id: str) -> AgentProposal:
    actor.require_project(project_id)
    await owned_project(db, actor.user_id, project_id)
    proposal = (await db.execute(select(AgentProposal).where(
        AgentProposal.project_id == project_id, AgentProposal.proposal_id == proposal_id,
        AgentProposal.user_id == actor.user_id,
    ).execution_options(populate_existing=True))).scalar_one_or_none()
    if proposal is None:
        raise AgentError('proposal_missing', 'Proposal not found', 404)
    return proposal


async def create_proposal(db: AsyncSession, actor: AgentActor, project_id: str, body: ProposalRequest) -> AgentProposal:
    actor.require_project(project_id)
    project = await owned_project(db, actor.user_id, project_id)
    if project.canvas_engine != 'excalidraw':
        raise AgentError('unsupported_canvas', 'Agent editing currently supports Excalidraw', 422)
    request_hash = digest(body.model_dump())
    old = (await db.execute(select(AgentProposal).where(AgentProposal.project_id == project_id,
                            AgentProposal.operation_id == body.operation_id))).scalar_one_or_none()
    if old:
        if old.request_hash != request_hash or old.connection_id != (actor.connection.connection_id if actor.connection else None):
            raise AgentError('operation_id_reused', 'Operation ID already used with another request')
        return old
    if body.base_version != project.version:
        raise AgentError('version_conflict', 'Read the current document before editing', current_version=project.version)
    constraints = await effective_constraints(db, project)
    if body.constraints_hash != constraints['constraints_hash']:
        raise AgentError('constraints_changed', 'Design constraints changed; read the current context')
    locked = list(constraints['locked_ids'])
    if body.context_version is not None:
        conn = actor.connection
        context = conn.context_json if conn else None
        if not context or conn.context_version != body.context_version or context['version'] != project.version or context['expires_at'] <= time.time():
            raise AgentError('context_stale', 'Shared selection expired; publish it again')
        if body.scope.kind != 'elements' or set(body.scope.element_ids) - set(context['selected_ids']):
            raise AgentError('scope_violation', 'Operations must stay within the shared selection', 422)
        locked.extend(context['locked_ids'])
    if body.scope.kind == 'elements' and not body.scope.element_ids:
        raise AgentError('scope_violation', 'An empty selection is not a whole-project edit', 422)
    from evo_diagram.canvas_environment import apply_operations, EditError
    try:
        candidate, changed = apply_operations(project.latest_schema or {'elements': []}, body.operations,
            scope=body.scope.element_ids if body.scope.kind == 'elements' else None, locked=locked)
    except EditError as exc:
        raise AgentError(exc.code, str(exc), 422) from exc
    proposal = AgentProposal(project_id=project_id, user_id=actor.user_id,
        connection_id=actor.connection.connection_id if actor.connection else None,
        operation_id=body.operation_id, request_hash=request_hash, base_version=project.version,
        base_schema=copy.deepcopy(project.latest_schema or {}), constraints_hash=constraints['constraints_hash'],
        candidate_schema=candidate, changed_ids=changed, expires_at=time.time()+7*86400)
    try:
        async with db.begin_nested():
            db.add(proposal)
            await db.flush()
    except IntegrityError:
        existing = (await db.execute(select(AgentProposal).where(AgentProposal.project_id == project_id,
                                     AgentProposal.operation_id == body.operation_id))).scalar_one_or_none()
        if existing and existing.request_hash == request_hash and existing.connection_id == proposal.connection_id:
            return existing
        raise AgentError('operation_id_reused', 'Operation ID already used with another request') from None
    return proposal


def render_candidate(schema: dict, output: Path) -> dict:
    from evo_diagram.canvas_environment import audit_manifest, render_png_result, validate_manifest
    validation = validate_manifest(schema, 'excalidraw')
    if not validation.get('is_valid'):
        raise AgentError('invalid_scene', 'Candidate failed structure validation', 422)
    audit = audit_manifest(schema, canvas_library='excalidraw')
    rendered = render_png_result(schema, str(output), canvas_library='excalidraw')
    if not rendered.ok or not output.is_file():
        raise AgentError('render_failed', 'Preview renderer is unavailable or rejected the scene', 503)
    return {'structure': 'passed', 'render': 'passed', 'visual_review': 'unverified',
            'warnings': audit.warnings, 'issues': [vars(issue) for issue in audit.issues]}


async def prepare_preview(db: AsyncSession, proposal: AgentProposal) -> AgentProposal:
    if proposal.status not in {'queued', 'checking'}:
        return proposal
    now = time.time()
    if proposal.expires_at <= now:
        proposal.status = 'expired'
        await db.flush()
        return proposal
    if proposal.attempts >= 2 and proposal.lease_until < now:
        proposal.status = 'failed'
        proposal.report = {'code': 'preview_interrupted', 'message': 'Preview interrupted twice; prepare a new candidate'}
        await db.flush()
        return proposal
    # Serialize only the short per-project admission check, not rendering.
    await db.execute(update(Project).where(Project.project_id == proposal.project_id).values(
        version=Project.version, updated_at=Project.updated_at).execution_options(synchronize_session=False))
    active = await db.scalar(select(func.count()).select_from(AgentProposal).where(
        AgentProposal.project_id == proposal.project_id, AgentProposal.status == 'checking',
        AgentProposal.lease_until >= now))
    if active >= 2:
        return proposal
    lease = str(uuid4())
    result = await db.execute(update(AgentProposal).where(
        AgentProposal.proposal_id == proposal.proposal_id,
        or_(AgentProposal.status == 'queued', (AgentProposal.status == 'checking') & (AgentProposal.lease_until < now)),
        AgentProposal.attempts < 2,
    ).values(status='checking', lease_id=lease, lease_until=now+60, attempts=AgentProposal.attempts+1)
        .execution_options(synchronize_session=False))
    if result.rowcount != 1:
        return proposal
    schema = copy.deepcopy(proposal.candidate_schema)
    proposal_id = proposal.proposal_id
    await db.commit()  # Release the write lock before the expensive renderer call.
    directory = artifact_root() / proposal_id
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    output = directory / (lease + '.png')
    started = asyncio.Event()
    task = asyncio.create_task(_render_guarded(schema, output, started))
    task.add_done_callback(_consume_render_result)
    try:
        report = await asyncio.wait_for(asyncio.shield(task), timeout=45)
        status = 'ready'
    except (AgentError, ValueError, OSError, RuntimeError, asyncio.TimeoutError) as exc:
        report = {'code': 'render_failed', 'message': 'Preview failed; the saved document is unchanged',
                  'failure_type': type(exc).__name__, 'visual_review': 'unverified'}
        status = 'failed'
        if not started.is_set():
            task.cancel()
    await db.execute(update(AgentProposal).where(AgentProposal.proposal_id == proposal_id,
        AgentProposal.lease_id == lease, AgentProposal.status == 'checking').values(
            status=status, report=report, preview_path=str(output) if status == 'ready' else None,
        ).execution_options(synchronize_session=False))
    await db.refresh(proposal)
    return proposal


async def commit_proposal(db: AsyncSession, actor: AgentActor, project_id: str, proposal_id: str) -> AgentProposal:
    from evo_diagram.canvas_environment import EditError
    actor.require_project(project_id)
    if actor.connection:
        fence = await db.execute(update(AgentConnection).where(
            AgentConnection.connection_id == actor.connection.connection_id,
            AgentConnection.status == 'active', AgentConnection.expires_at > time.time(),
            AgentConnection.can_commit.is_(True),
        ).values(status='active').execution_options(synchronize_session=False))
        if fence.rowcount != 1:
            raise AgentError('commit_forbidden', 'Connection cannot commit or has been revoked', 403)
    proposal = await get_proposal(db, actor, project_id, proposal_id)
    if proposal.status == 'committed':
        return proposal
    if proposal.expires_at <= time.time():
        raise AgentError('proposal_expired', 'Proposal expired; prepare a new candidate')
    if proposal.status != 'ready':
        raise AgentError('proposal_not_ready', 'A successful preview is required before commit')
    project = await owned_project(db, actor.user_id, project_id)
    if project.version != proposal.base_version:
        raise AgentError('version_conflict', 'Document changed; read it and remake this candidate',
                         current_version=project.version, proposal_id=proposal_id)
    constraints = await effective_constraints(db, project)
    if constraints['constraints_hash'] != proposal.constraints_hash:
        raise AgentError('constraints_changed', 'Design constraints changed; remake the candidate')
    try:
        snapshot = await commit_document(db, project, proposal.candidate_schema,
            expected_version=proposal.base_version, source=proposal.author_kind, checkpoint=True,
            metrics={'agent': proposal.report})
    except VersionConflictError as exc:
        await db.rollback()
        completed = await get_proposal(db, actor, project_id, proposal_id)
        if completed.status == 'committed':
            return completed
        raise AgentError('version_conflict', 'Document changed during commit', proposal_id=proposal_id) from exc
    except EditError as exc:
        raise AgentError(exc.code, str(exc), 422) from exc
    proposal.status = 'committed'
    proposal.committed_version = project.version
    proposal.committed_snapshot_id = snapshot.snapshot_id
    await db.flush()
    return proposal


async def restore_proposal(db: AsyncSession, actor: AgentActor, project_id: str,
                           snapshot_id: str, operation_id: str, base_version: int) -> AgentProposal:
    actor.require_project(project_id)
    project = await owned_project(db, actor.user_id, project_id)
    old = (await db.execute(select(AgentProposal).where(AgentProposal.project_id == project_id,
                            AgentProposal.operation_id == operation_id))).scalar_one_or_none()
    request_hash = digest({'restore': snapshot_id, 'base_version': base_version})
    if old:
        if old.request_hash != request_hash or old.connection_id != (actor.connection.connection_id if actor.connection else None):
            raise AgentError('operation_id_reused', 'Operation ID already used')
        return old
    snapshot = await db.get(Snapshot, snapshot_id)
    if snapshot is None or snapshot.project_id != project_id or not snapshot.is_checkpoint:
        raise AgentError('checkpoint_missing', 'Choose a checkpoint from this project', 404)
    if project.canvas_engine != 'excalidraw':
        raise AgentError('unsupported_canvas', 'Agent restore supports Excalidraw', 422)
    if project.version != base_version:
        raise AgentError('version_conflict', 'Read current document before restoring', current_version=project.version)
    constraints = await effective_constraints(db, project)
    old_elements = {e['id']: e for e in (project.latest_schema or {}).get('elements', [])}
    new_elements = {e['id']: e for e in snapshot.schema_blob.get('elements', [])}
    from evo_diagram.canvas_environment import assert_preserves_locks, EditError
    try:
        assert_preserves_locks(project.latest_schema or {}, snapshot.schema_blob)
    except EditError as exc:
        raise AgentError(exc.code, str(exc), 422) from exc
    proposal = AgentProposal(project_id=project_id, user_id=actor.user_id,
        connection_id=actor.connection.connection_id if actor.connection else None,
        operation_id=operation_id, request_hash=request_hash, base_version=base_version,
        base_schema=copy.deepcopy(project.latest_schema or {}), candidate_schema=copy.deepcopy(snapshot.schema_blob),
        constraints_hash=constraints['constraints_hash'], expires_at=time.time()+7*86400,
        changed_ids=sorted(eid for eid in set(old_elements) | set(new_elements)
                           if old_elements.get(eid) != new_elements.get(eid)))
    db.add(proposal)
    await db.flush()
    return proposal
