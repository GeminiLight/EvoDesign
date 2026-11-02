"""Regression tests for the review-hardening fixes (services and schemas)."""

import asyncio
import json
import threading
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import pytest_asyncio
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.exceptions import InvalidVerificationCodeException
from app.core.rate_limit import bind_rate_limit_identity, client_ip, rate_limit_key
from app.db.base import Base
from app.models import AgentConnection, AgentProposal, DnaRule, GuestGenerationUsage, Project, Snapshot
from app.schemas.auth import LoginRequest, RegisterRequest
from app.schemas.diagram_generate import (
    MAX_CURRENT_SCHEMA_BYTES,
    DiagramGenerateRequest,
    DiagramLocalEditRequest,
)
from app.services import agent_proposal_service, auth_service, design_learning_jobs
from app.services.agent_artifact_service import remove_project_previews
from app.services.agent_connection_service import (
    CLAIM_RETRY_SECONDS,
    TOKEN_TTL_SECONDS,
    AgentActor,
    approve_connection,
    authenticate_connection,
    claim_connection,
    create_connection,
)
from app.services.agent_contract import AgentError, ProposalRequest
from app.services.agent_proposal_service import create_proposal, reject_proposal, render_bounded, restore_proposal
from app.services.diagram_persistence_service import DiagramPersistenceInput, DiagramPersistenceService
from app.services.dna_rule_service import DnaRuleConflictError, DnaRuleService
from app.services.document_commit_service import CanvasEngineChangeError, commit_document
from app.services.document_service import digest, effective_constraints
from app.services.guest_quota_service import GuestQuotaExceededError, consume_guest_generation
from app.services.project_service import ProjectService
from app.schemas.dna import DnaRulesPayload


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine('sqlite+aiosqlite:///:memory:')
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    await engine.dispose()


def _request(peer, forwarded=None):
    headers = {'x-forwarded-for': forwarded} if forwarded else {}
    return SimpleNamespace(client=SimpleNamespace(host=peer), headers=headers, state=SimpleNamespace())


# --- Finding 3: real client IP and per-user keys --------------------------------------------

def test_client_ip_trusts_forwarded_for_only_from_trusted_proxies():
    assert client_ip(_request('127.0.0.1', '198.51.100.4'), '127.0.0.1') == '198.51.100.4'
    # Appending proxies (Vite xfwd) put the real peer last; a spoofed prefix is ignored.
    assert client_ip(_request('127.0.0.1', '6.6.6.6, 198.51.100.4'), '127.0.0.1') == '198.51.100.4'
    assert client_ip(_request('203.0.113.2', '198.51.100.4'), '127.0.0.1') == '203.0.113.2'
    assert client_ip(_request('10.1.2.3', '198.51.100.4, 10.0.0.9'), '10.0.0.0/8') == '198.51.100.4'
    assert client_ip(_request('127.0.0.1'), '127.0.0.1') == '127.0.0.1'


def test_rate_limit_key_prefers_bound_user_identity():
    first, second = _request('127.0.0.1', '198.51.100.4'), _request('127.0.0.1', '198.51.100.4')
    assert rate_limit_key(first) == rate_limit_key(second)
    bind_rate_limit_identity(first, 'alice')
    bind_rate_limit_identity(second, 'bob')
    assert rate_limit_key(first) == 'user:alice' and rate_limit_key(second) == 'user:bob'


# --- Finding 1: durable guest quota -----------------------------------------------------------

@pytest.mark.asyncio
async def test_guest_quota_counts_per_client_and_resets_next_utc_day(db):
    today = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)
    consume = lambda ip, clock=lambda: today: consume_guest_generation(  # noqa: E731
        db, client_ip=ip, limit=2, secret='secret', clock=clock)
    assert await consume('198.51.100.1') == 1
    assert await consume('198.51.100.1') == 2
    with pytest.raises(GuestQuotaExceededError) as error:
        await consume('198.51.100.1')
    assert 'Guests can run 2 diagram generations per day' in error.value.public_detail
    assert await consume('198.51.100.2') == 1
    tomorrow = lambda: today + timedelta(days=1)  # noqa: E731
    assert await consume('198.51.100.1', tomorrow) == 1
    days = set((await db.scalars(select(GuestGenerationUsage.day))).all())
    assert days == {'2026-11-03'}  # Earlier days are purged.


@pytest.mark.asyncio
async def test_zero_guest_limit_disables_guest_generation(db):
    with pytest.raises(GuestQuotaExceededError) as error:
        await consume_guest_generation(db, client_ip='198.51.100.1', limit=0, secret='s')
    assert 'disabled' in error.value.public_detail


# --- Finding 2 and 11: input caps --------------------------------------------------------------

def test_generation_inputs_are_capped():
    base = {'context': 'ok', 'canvas_library': 'excalidraw'}
    with pytest.raises(ValidationError):
        DiagramGenerateRequest(**{**base, 'context': 'x' * 100_001})
    with pytest.raises(ValidationError):
        DiagramGenerateRequest(**{**base, 'requirements': 'x' * 50_001})
    with pytest.raises(ValidationError):
        DiagramGenerateRequest(**{**base, 'locked_nodes': ['n'] * 2_001})
    with pytest.raises(ValidationError, match='current_schema is too large'):
        DiagramGenerateRequest(**{**base, 'current_schema': {'blob': 'x' * MAX_CURRENT_SCHEMA_BYTES}})
    edit = {'current_schema': {'elements': []}, 'selected_node_ids': ['a'], 'instruction': 'x',
            'canvas_library': 'excalidraw'}
    with pytest.raises(ValidationError):
        DiagramLocalEditRequest(**{**edit, 'instruction': 'x' * 10_001})
    with pytest.raises(ValidationError):
        DiagramLocalEditRequest(**{**edit, 'selected_node_ids': ['a'] * 2_001})
    with pytest.raises(ValidationError):
        DiagramLocalEditRequest(**{**edit, 'current_schema': {'blob': 'x' * MAX_CURRENT_SCHEMA_BYTES}})
    assert DiagramGenerateRequest(**{**base, 'current_schema': {'elements': []}}).current_schema == {'elements': []}


def test_password_policy_bounds():
    with pytest.raises(ValidationError):
        RegisterRequest(email='a@example.org', password='short', verification_code='')
    with pytest.raises(ValidationError):
        RegisterRequest(email='a@example.org', password='x' * 1025, verification_code='')
    with pytest.raises(ValidationError):
        LoginRequest(email='a@example.org', password='x' * 1025)
    assert RegisterRequest(email='a@example.org', password='x' * 8, verification_code='').password
    assert LoginRequest(email='a@example.org', password='old').password == 'old'


# --- Finding 10 and 9: signup verification and PBKDF2 off the loop ------------------------------

def test_settings_refuse_enabled_verification_without_code(monkeypatch):
    from app.config import Settings
    with pytest.raises(ValidationError, match='SIGNUP_VERIFICATION_CODE is required'):
        Settings(_env_file=None, jwt_secret='a-real-jwt-secret-value', session_secret='a-real-session-secret',
                 enable_signup_verification=True, signup_verification_code='  ')


@pytest.mark.asyncio
async def test_register_fails_closed_and_hashes_off_the_event_loop(db, monkeypatch):
    threads = []

    def fake_hash(password):
        threads.append(threading.current_thread())
        return 'hashed'

    monkeypatch.setattr(auth_service, 'hash_password', fake_hash)
    settings = SimpleNamespace(enable_signup_verification=True, signup_verification_code='')
    service = auth_service.AuthService(db, settings=settings)
    with pytest.raises(InvalidVerificationCodeException):
        await service.register('a@example.org', 'password1', verification_code='')
    service.settings = SimpleNamespace(enable_signup_verification=True, signup_verification_code='123456')
    with pytest.raises(InvalidVerificationCodeException):
        await service.register('a@example.org', 'password1', verification_code='12345')
    user = await service.register('a@example.org', 'password1', verification_code='123456')
    assert user.password_hash == 'hashed'
    assert threads and threads[0] is not threading.main_thread()


@pytest.mark.asyncio
async def test_login_verifies_password_off_the_event_loop(db, monkeypatch):
    threads = []

    def fake_verify(password, hashed):
        threads.append(threading.current_thread())
        return True

    monkeypatch.setattr(auth_service, 'hash_password', lambda password: 'hashed')
    monkeypatch.setattr(auth_service, 'verify_password', fake_verify)
    service = auth_service.AuthService(db, settings=SimpleNamespace(enable_signup_verification=False))
    await service.register('b@example.org', 'password1')
    await service.login('b@example.org', 'password1')
    assert threads[0] is not threading.main_thread()


# --- Finding 6 and 9: engine guard and a single thumbnail -------------------------------------

@pytest.mark.asyncio
async def test_commit_document_rejects_engine_change_on_nonempty_project(db):
    project = Project(user_id='u', canvas_engine='excalidraw', latest_schema={'elements': [{'id': 'a'}]})
    empty = Project(user_id='u', canvas_engine='excalidraw',
                    latest_schema={'elements': [{'id': 'gone', 'isDeleted': True}]})
    db.add_all([project, empty])
    await db.flush()
    with pytest.raises(CanvasEngineChangeError):
        await commit_document(db, project, {'shapes': []}, expected_version=1, source='HUMAN',
                              canvas_library='tldraw')
    assert project.canvas_engine == 'excalidraw' and project.version == 1
    await commit_document(db, empty, {'shapes': []}, expected_version=1, source='HUMAN', canvas_library='tldraw')
    assert empty.canvas_engine == 'tldraw'


@pytest.mark.asyncio
async def test_generation_persistence_renders_one_thumbnail(db):
    calls = []

    def thumbnail(schema, canvas):
        calls.append(canvas)
        return 'thumb'

    result = await DiagramPersistenceService(db, thumbnail_generator=thumbnail).persist_generation_result(
        DiagramPersistenceInput(user_id='u', context='A', requirements=None, project_id=None,
                                canvas_library='excalidraw', workflow_result={'schema_blob': {'elements': []}}))
    assert result.thumbnail_url == 'thumb' and calls == ['excalidraw']


# --- Finding 7: render cleanup and preview removal on project delete --------------------------

@pytest.mark.asyncio
async def test_render_bounded_removes_late_and_partial_outputs(tmp_path, monkeypatch):
    def slow_render(schema, output):
        time.sleep(0.2)
        output.write_bytes(b'png')
        return {}

    monkeypatch.setattr(agent_proposal_service, 'render_candidate', slow_render)
    late = tmp_path / 'late.png'
    with pytest.raises(asyncio.TimeoutError):
        await render_bounded({}, late, timeout=0.01)
    await asyncio.sleep(0.4)
    assert not late.exists()

    def failing_render(schema, output):
        output.write_bytes(b'partial')
        raise RuntimeError('renderer crashed')

    monkeypatch.setattr(agent_proposal_service, 'render_candidate', failing_render)
    partial = tmp_path / 'partial.png'
    with pytest.raises(RuntimeError):
        await render_bounded({}, partial)
    assert not partial.exists()


@pytest.mark.asyncio
async def test_deleting_a_project_removes_its_preview_directories(db, tmp_path, monkeypatch):
    monkeypatch.setattr(agent_proposal_service, 'artifact_root', lambda: tmp_path)
    project = Project(user_id='u', latest_schema={'elements': []})
    db.add(project)
    await db.flush()
    proposal = AgentProposal(project_id=project.project_id, user_id='u', operation_id='op', request_hash='h',
                             base_version=1, base_schema={}, candidate_schema={}, constraints_hash='c',
                             expires_at=time.time() + 60)
    db.add(proposal)
    await db.flush()
    formal = tmp_path / 'formal' / project.project_id
    candidate = tmp_path / proposal.proposal_id
    unrelated = tmp_path / '00000000-0000-4000-8000-000000000000'
    for directory in (formal, candidate, unrelated):
        directory.mkdir(parents=True)
        (directory / 'x.png').write_bytes(b'png')
    await ProjectService(db).delete_project('u', project.project_id)
    assert not formal.exists() and not candidate.exists() and unrelated.exists()
    assert remove_project_previews(tmp_path, '../escape', ['..']) == 0


# --- Finding 8 and 12: reject permissions and concurrent operation IDs ------------------------

async def _proposal(db, project, actor, operation_id):
    constraints = await effective_constraints(db, project)
    return await create_proposal(db, actor, project.project_id, ProposalRequest(
        operation_id=operation_id, base_version=project.version, constraints_hash=constraints['constraints_hash'],
        scope={'kind': 'project'}, operations=[{'op': 'add_node', 'id': operation_id, 'x': 0, 'y': 0,
                                               'width': 160, 'height': 80, 'text': 'Example'}]))


@pytest.mark.asyncio
async def test_preview_only_connections_can_only_withdraw_their_own_proposals(db):
    project = Project(user_id='owner', latest_schema={'elements': []})
    db.add(project)
    await db.flush()
    kwargs = dict(user_id='owner', project_id=project.project_id, status='active', user_code='X',
                  device_hash='', expires_at=time.time() + 600)
    viewer = AgentConnection(name='viewer', can_commit=False, **kwargs)
    editor = AgentConnection(name='editor', can_commit=True, **kwargs)
    db.add_all([viewer, editor])
    await db.flush()
    owner_proposal = await _proposal(db, project, AgentActor('owner'), 'by-owner')
    own_proposal = await _proposal(db, project, AgentActor('owner', viewer), 'by-viewer')

    with pytest.raises(AgentError) as error:
        await reject_proposal(db, AgentActor('owner', viewer), project.project_id, owner_proposal.proposal_id)
    assert error.value.code == 'reject_forbidden' and error.value.status_code == 403
    assert (await reject_proposal(db, AgentActor('owner', viewer), project.project_id,
                                  own_proposal.proposal_id)).status == 'rejected'
    assert (await reject_proposal(db, AgentActor('owner', editor), project.project_id,
                                  owner_proposal.proposal_id)).status == 'rejected'


@pytest.mark.asyncio
async def test_restore_race_on_operation_id_returns_the_winner(db):
    project = Project(user_id='owner', latest_schema={'elements': []})
    db.add(project)
    await db.flush()
    checkpoint = Snapshot(project_id=project.project_id, schema_blob={'elements': []}, is_checkpoint=True,
                          edit_source='HUMAN')
    db.add(checkpoint)
    await db.flush()
    constraints = await effective_constraints(db, project)
    original_get = db.get

    async def racing_get(model, ident, **kwargs):
        # A concurrent retry inserts the same operation after our duplicate check.
        if model is Snapshot and not getattr(racing_get, 'raced', False):
            racing_get.raced = True
            db.add(AgentProposal(project_id=project.project_id, user_id='owner', operation_id='undo',
                                 request_hash=digest({'restore': checkpoint.snapshot_id, 'base_version': 1}),
                                 base_version=1, base_schema={}, candidate_schema={},
                                 constraints_hash=constraints['constraints_hash'], expires_at=time.time() + 60))
            await db.flush()
        return await original_get(model, ident, **kwargs)

    db.get = racing_get
    winner = await restore_proposal(db, AgentActor('owner'), project.project_id, checkpoint.snapshot_id, 'undo', 1)
    rows = (await db.scalars(select(AgentProposal).where(AgentProposal.operation_id == 'undo'))).all()
    assert len(rows) == 1 and winner.proposal_id == rows[0].proposal_id


@pytest.mark.asyncio
async def test_dna_rule_replacement_conflict_maps_to_conflict_error(db, monkeypatch):
    service = DnaRuleService(db)
    duplicate = [DnaRule(rule_id='same', user_id='u', project_id=None, cabin_id='style', title='t', preview='p',
                         source='manual', enabled=True, pinned=False, usage_count=0) for _ in range(2)]
    monkeypatch.setattr(service, '_build_rows', lambda **_kwargs: duplicate)
    with pytest.raises(DnaRuleConflictError) as error:
        await service.replace_rules(user_id='u', payload=DnaRulesPayload(project_id=None))
    assert 'reload' in error.value.public_detail


# --- Finding 9: learning job writes off the loop -------------------------------------------------

@pytest.mark.asyncio
async def test_learning_enqueue_writes_files_off_the_event_loop(tmp_path, monkeypatch):
    threads = []
    original = design_learning_jobs._write

    def recording_write(path, value):
        threads.append(threading.current_thread())
        original(path, value)

    monkeypatch.setattr(design_learning_jobs, '_write', recording_write)
    report = tmp_path / 'report.json'
    report.write_text(json.dumps({'iterations': []}))
    await design_learning_jobs.enqueue_learning(
        memory_path=str(tmp_path / 'memory'), embedding_model='test', report_path=str(report),
        request_id='req_thread', diagram_type='flowchart', before={'score': 6}, after={'score': 8},
        model=object(), retriever=object(), learner=lambda **_kwargs: {'status': 'saved', 'saved_count': 0})
    await design_learning_jobs.wait_for_learning()
    assert threads and all(thread is not threading.main_thread() for thread in threads)


def test_workflow_memory_path_uses_the_shared_private_path_helper():
    from app.services.workflow_generate_service import WorkflowGenerateService
    settings = SimpleNamespace(design_memory_path='/memory', auto_refine_enabled=False, auto_refine_max_iterations=1,
                               design_memory_enabled=True, design_memory_seed_path='/seed', design_memory_model='m',
                               design_memory_top_k=1, design_memory_learning=True, retain_generation_artifacts=False)
    service = WorkflowGenerateService(settings=settings, engine_adapter=object())
    request = service._build_run_request(context='c', requirements=None, locked_nodes=[], current_schema=None,
                                         canvas_library='excalidraw', request_id='r', user_tier=None, user_id='alice')
    assert request.design_memory_path == str(design_learning_jobs.private_memory_path('/memory', 'alice'))


# --- Finding 14: retryable CLI claim -------------------------------------------------------------

@pytest.mark.asyncio
async def test_lost_claim_response_can_be_reclaimed_briefly_by_the_same_device(db, monkeypatch):
    project = Project(user_id='owner', latest_schema={'elements': []})
    db.add(project)
    await db.flush()
    row, secret = await create_connection(db, 'cli')
    await approve_connection(db, row.connection_id, 'owner', project.project_id, row.user_code, False)
    first = await claim_connection(db, row.connection_id, secret)  # Response "lost".
    with pytest.raises(AgentError):
        await claim_connection(db, row.connection_id, 'another-device-secret')
    second = await claim_connection(db, row.connection_id, secret)
    assert second['access_token'] != first['access_token'] and second['expires_at'] == first['expires_at']
    with pytest.raises(AgentError):
        await authenticate_connection(db, first['access_token'])  # Rotated away.
    await authenticate_connection(db, second['access_token'])
    with pytest.raises(AgentError):  # First use closes the window.
        await claim_connection(db, row.connection_id, secret)

    other, other_secret = await create_connection(db, 'cli-2')
    await approve_connection(db, other.connection_id, 'owner', project.project_id, other.user_code, False)
    await claim_connection(db, other.connection_id, other_secret)
    real_time = time.time
    monkeypatch.setattr('app.services.agent_connection_service.time.time',
                        lambda: real_time() + CLAIM_RETRY_SECONDS + 1)
    with pytest.raises(AgentError) as error:
        await claim_connection(db, other.connection_id, other_secret)
    assert error.value.code == 'pairing_expired'
    assert TOKEN_TTL_SECONDS == 86400
