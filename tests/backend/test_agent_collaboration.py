import copy
import time

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models import Project, Snapshot
from app.services.agent_connection_service import (AgentActor, approve_connection, authenticate_connection,
    claim_connection, create_connection)
from app.services.agent_contract import AgentError, ProposalRequest
from app.services.agent_proposal_service import commit_proposal, create_proposal, restore_proposal
from app.services.document_service import effective_constraints
from app.services.schema_service import SchemaService


@pytest_asyncio.fixture
async def workspace():
    engine = create_async_engine('sqlite+aiosqlite:///:memory:')
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        project = Project(user_id='owner', latest_schema={'elements': []})
        db.add(project)
        await db.commit()
        yield db, project, AgentActor('owner')
    await engine.dispose()


async def candidate(db, project, actor, operation_id='edit-1'):
    constraints = await effective_constraints(db, project)
    proposal = await create_proposal(db, actor, project.project_id, ProposalRequest(
        operation_id=operation_id, base_version=project.version, constraints_hash=constraints['constraints_hash'],
        scope={'kind': 'project'}, operations=[{'op': 'add_node', 'id': operation_id, 'x': 0, 'y': 0,
                                               'width': 160, 'height': 80, 'text': 'Example'}]))
    return proposal


@pytest.mark.asyncio
async def test_commit_is_idempotent_and_autosave_cannot_rewrite_checkpoint(workspace):
    db, project, actor = workspace
    proposal = await candidate(db, project, actor)
    proposal.status = 'ready'
    proposal.report = {'render': 'passed'}
    await db.commit()
    await commit_proposal(db, actor, project.project_id, proposal.proposal_id)
    await db.commit()
    original = await db.get(Snapshot, proposal.committed_snapshot_id)
    frozen = copy.deepcopy(original.schema_blob)
    v = project.version
    await commit_proposal(db, actor, project.project_id, proposal.proposal_id)
    assert project.version == v
    _, working = await SchemaService(db).sync_schema('owner', project.project_id,
        {'elements': []}, base_snapshot_id=original.snapshot_id, version=v)
    await db.commit()
    assert working.snapshot_id != original.snapshot_id
    assert original.schema_blob == frozen and original.is_checkpoint
    assert project.current_snapshot_id == working.snapshot_id
    assert working.parent_id == original.snapshot_id


@pytest.mark.asyncio
async def test_two_candidates_cannot_overwrite_and_restore_is_new_version(workspace):
    db, project, actor = workspace
    first, second = await candidate(db, project, actor), await candidate(db, project, actor, 'edit-2')
    first.status = second.status = 'ready'
    await db.commit()
    await commit_proposal(db, actor, project.project_id, first.proposal_id)
    await db.commit()
    current = copy.deepcopy(project.latest_schema)
    with pytest.raises(AgentError) as error:
        await commit_proposal(db, actor, project.project_id, second.proposal_id)
    assert error.value.code == 'version_conflict'
    assert project.latest_schema == current
    before = await db.get(Snapshot, (await db.get(Snapshot, first.committed_snapshot_id)).parent_id)
    restored = await restore_proposal(db, actor, project.project_id, before.snapshot_id, 'undo-1', project.version)
    restored.status = 'ready'
    await db.commit()
    await commit_proposal(db, actor, project.project_id, restored.proposal_id)
    assert project.version == 3 and project.latest_schema == {'elements': []}


@pytest.mark.asyncio
async def test_operation_id_cannot_be_reused_for_different_edits(workspace):
    db, project, actor = workspace
    proposal = await candidate(db, project, actor)
    assert (await candidate(db, project, actor)).proposal_id == proposal.proposal_id
    with pytest.raises(AgentError) as error:
        await create_proposal(db, actor, project.project_id, ProposalRequest(
            operation_id='edit-1', base_version=1, constraints_hash=proposal.constraints_hash,
            scope={'kind': 'project'}, operations=[{'op': 'delete_node', 'id': 'x', 'cascade': True}]))
    assert error.value.code == 'operation_id_reused'


@pytest.mark.asyncio
async def test_pairing_single_use_project_scope_and_revocation(workspace):
    db, project, actor = workspace
    row, secret = await create_connection(db, 'test agent')
    assert (await claim_connection(db, row.connection_id, secret))['status'] == 'pending'
    await approve_connection(db, row.connection_id, 'owner', project.project_id, row.user_code, True)
    await db.commit()
    claimed = await claim_connection(db, row.connection_id, secret)
    await db.commit()
    scoped = await authenticate_connection(db, claimed['access_token'])
    assert row.token_hash != claimed['access_token'] and row.device_hash == ''
    with pytest.raises(AgentError):
        await claim_connection(db, row.connection_id, secret)
    with pytest.raises(AgentError):
        scoped.require_project('another-project')
    row.status = 'revoked'
    await db.commit()
    with pytest.raises(AgentError) as error:
        await authenticate_connection(db, claimed['access_token'])
    assert error.value.code == 'connection_expired'


@pytest.mark.asyncio
async def test_expired_and_unpreviewed_candidates_cannot_commit(workspace):
    db, project, actor = workspace
    proposal = await candidate(db, project, actor)
    with pytest.raises(AgentError) as error:
        await commit_proposal(db, actor, project.project_id, proposal.proposal_id)
    assert error.value.code == 'proposal_not_ready'
    proposal.expires_at = time.time() - 1
    with pytest.raises(AgentError) as error:
        await commit_proposal(db, actor, project.project_id, proposal.proposal_id)
    assert error.value.code == 'proposal_expired'
    assert project.version == 1


@pytest.mark.asyncio
async def test_long_generation_preserves_result_without_overwriting_newer_document(workspace):
    from app.services.diagram_persistence_service import DiagramPersistenceInput, DiagramPersistenceService
    from app.models import AgentProposal
    db, project, actor = workspace
    base = copy.deepcopy(project.latest_schema)
    await SchemaService(db).sync_schema('owner', project.project_id,
        {'elements': [{'id': 'human-edit'}]}, create_snapshot=True, version=1)
    await db.commit()
    saved = copy.deepcopy(project.latest_schema)
    result = await DiagramPersistenceService(db).persist_generation_result(DiagramPersistenceInput(
        user_id='owner', context='Example', requirements=None, project_id=project.project_id,
        canvas_library='excalidraw', workflow_result={'request_id': 'long-run', 'schema_blob': {'elements': [{'id': 'generated'}]}},
        base_version=1, base_schema=base))
    await db.commit()
    assert result.proposal_id and result.snapshot_id is None
    assert project.latest_schema == saved and project.version == 2
    candidate = await db.get(AgentProposal, result.proposal_id)
    assert candidate.base_schema == base and candidate.candidate_schema['elements'][0]['id'] == 'generated'
