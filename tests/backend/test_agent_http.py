"""Real routes, credentials and transactions; rendering is exercised separately."""

import copy
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.application import create_app
from app.api.v1.endpoints.diagram import get_workflow_generate_service
from app.config import get_settings
from app.core.security import create_access_token
from app.db.base import Base
from app.db.session import get_db
from app.models import AgentProposal, Project, User


@pytest_asyncio.fixture
async def api():
    engine = create_async_engine('sqlite+aiosqlite:///:memory:')
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        user = User(user_id='owner', email='agent-test@example.org', auth_provider='email')
        project = Project(user_id='owner', latest_schema={'elements': []})
        other = Project(user_id='another-owner', latest_schema={'elements': []})
        db.add_all([user, project, other])
        await db.commit()
        project_id, other_id = project.project_id, other.project_id
    settings = SimpleNamespace(app_name='Agent HTTP test', app_version='test', debug=False, cors_origins_list=[],
        jwt_secret='test-agent-http-secret', jwt_algorithm='HS256', jwt_expires_in=3600,
        frontend_url='http://localhost:5175', guest_token=None)
    app = create_app(settings=settings, configure_logs=False, load_env=False)

    async def session():
        async with factory() as db:
            try:
                yield db
                await db.commit()
            except Exception:
                await db.rollback()
                raise

    app.dependency_overrides[get_db] = session
    app.dependency_overrides[get_settings] = lambda: settings
    # These tests reject invalid generation input before the workflow executes.
    app.dependency_overrides[get_workflow_generate_service] = lambda: object()
    token = create_access_token({'user_id': 'owner'}, settings=settings)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://test') as client:
        yield client, {'Authorization': 'Bearer ' + token}, project_id, other_id, factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_real_pairing_scopes_permissions_and_cannot_access_account_endpoints(api):
    client, owner, project_id, other_id, factory = api
    start = await client.post('/api/v1/agent/connections', json={'name': 'Terminal'})
    assert start.status_code == 201
    pairing = start.json()['data']
    cid = pairing['connection_id']
    approved = await client.post(f'/api/v1/agent/connections/{cid}/approve', headers=owner,
        json={'user_code': pairing['user_code'], 'project_id': project_id, 'can_commit': False})
    assert approved.status_code == 200
    claimed = await client.post(f'/api/v1/agent/connections/{cid}/claim', json={'device_secret': pairing['device_secret']})
    agent = {'Authorization': 'Bearer ' + claimed.json()['data']['access_token']}
    document = (await client.get(f'/api/v1/projects/{project_id}/document', headers=agent)).json()['data']
    assert document['version'] == 1
    assert (await client.get(f'/api/v1/projects/{other_id}/document', headers=agent)).status_code == 403
    assert (await client.get('/api/v1/auth/me', headers=agent)).status_code == 401
    assert (await client.get('/api/v1/projects', headers=agent)).status_code == 401
    proposal = await client.post(f'/api/v1/projects/{project_id}/agent-proposals', headers=agent, json={
        'operation_id': 'http-operation', 'base_version': 1,
        'constraints_hash': document['constraints']['constraints_hash'], 'scope': {'kind': 'project'},
        'operations': [{'op': 'add_node', 'id': 'a', 'x': 0, 'y': 0, 'width': 100, 'height': 80}]})
    assert proposal.status_code == 202, proposal.text
    pid = proposal.json()['data']['proposal_id']
    async with factory() as db:
        row = await db.get(AgentProposal, pid)
        row.status = 'ready'
        await db.commit()
    assert (await client.post(f'/api/v1/projects/{project_id}/agent-proposals/{pid}/commit', headers=agent)).status_code == 403
    # The owner may accept the candidate even when the connection is preview-only.
    accepted = await client.post(f'/api/v1/projects/{project_id}/agent-proposals/{pid}/commit', headers=owner)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()['data']['committed_version'] == 2
    assert (await client.delete(f'/api/v1/agent/connections/{cid}', headers=owner)).status_code == 200
    assert (await client.get(f'/api/v1/projects/{project_id}/document', headers=agent)).status_code == 401


@pytest.mark.asyncio
async def test_missing_versions_rejected_before_formal_document_write(api):
    client, owner, project_id, _, factory = api
    saved = await client.patch('/api/v1/schema/sync', headers=owner, json={
        'project_id': project_id, 'schema_patch': {'elements': []}, 'create_snapshot': True})
    assert saved.status_code == 422
    generated = await client.post('/api/v1/diagram/generate', headers=owner,
        json={'project_id': project_id, 'context': 'Example', 'canvas_library': 'excalidraw'})
    assert generated.status_code == 422
    async with factory() as db:
        project = await db.get(Project, project_id)
        assert project.version == 1 and project.latest_schema == {'elements': []}
