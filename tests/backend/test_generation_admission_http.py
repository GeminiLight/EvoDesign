"""Guest daily quota, real-client-IP keying, connection release and OAuth binding over HTTP."""

import time
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.v1.endpoints.diagram import get_local_edit_service, get_workflow_generate_service
from app.application import create_app
from app.config import get_settings
from app.core.rate_limit import limiter
from app.core.security import create_access_token
from app.db.base import Base
from app.db.session import get_db
from app.models import GuestGenerationUsage, OAuthCode, User
from app.services.local_edit_service import LocalEditResult
from app.services.oauth_session_service import OAUTH_EXCHANGE_COOKIE_NAME, OAuthSessionService

GUEST = {'Authorization': 'Bearer guest-token-for-tests'}
GENERATE = {'context': 'A flows to B', 'canvas_library': 'excalidraw'}


class _FakeWorkflow:
    """Records whether the request session still held a transaction during the 'LLM' run."""

    def __init__(self, sessions):
        self.sessions = sessions
        self.in_transaction = []

    def _record(self):
        self.in_transaction.append(any(db.in_transaction() for db in self.sessions))

    async def generate_without_render(self, **_kwargs):
        self._record()
        return {'request_id': 'req_test', 'schema_blob': {'elements': []}, 'summary': 'ok'}

    async def generate_without_render_streaming(self, **_kwargs):
        self._record()
        yield 'event: stage_start\ndata: {"stage": "structure"}\n\n'


class _FakeLocalEdit:
    async def edit_local(self, **_kwargs):
        return LocalEditResult(modified_nodes={}, operation_type='update', summary='ok')


@pytest_asyncio.fixture
async def api():
    engine = create_async_engine('sqlite+aiosqlite:///:memory:')
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        db.add(User(user_id='owner', email='quota@example.org', auth_provider='email'))
        await db.commit()
    settings = SimpleNamespace(
        app_name='Admission test', app_version='test', debug=False, cors_origins_list=[],
        jwt_secret='test-admission-jwt-secret', jwt_algorithm='HS256', jwt_expires_in=3600,
        session_secret='test-admission-session-secret', frontend_url='http://localhost:5175',
        guest_token='guest-token-for-tests', guest_daily_generation_limit=3,
        google_callback_url='http://localhost:3010/api/v1/auth/google/callback',
        github_callback_url='http://localhost:3010/api/v1/auth/github/callback',
    )
    app = create_app(settings=settings, configure_logs=False, load_env=False)
    sessions = []

    async def session():
        async with factory() as db:
            sessions.append(db)
            try:
                yield db
                await db.commit()
            except Exception:
                await db.rollback()
                raise

    workflow = _FakeWorkflow(sessions)
    app.dependency_overrides[get_db] = session
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_workflow_generate_service] = lambda: workflow
    app.dependency_overrides[get_local_edit_service] = lambda: _FakeLocalEdit()
    owner = {'Authorization': 'Bearer ' + create_access_token({'user_id': 'owner'}, settings=settings)}
    limiter.reset()
    # ASGITransport reports the peer as 127.0.0.1, i.e. the trusted Vite proxy.
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://test') as client:
        yield SimpleNamespace(client=client, owner=owner, factory=factory, workflow=workflow, settings=settings)
    limiter.reset()
    await engine.dispose()


def _from(ip: str) -> dict:
    return {**GUEST, 'X-Forwarded-For': ip}


@pytest.mark.asyncio
async def test_guest_quota_is_shared_across_generation_endpoints_and_returns_429(api):
    client = api.client
    edit = {'current_schema': {'elements': [{'id': 'a'}]}, 'selected_node_ids': ['a'], 'instruction': 'Bigger',
            'canvas_library': 'excalidraw'}
    assert (await client.post('/api/v1/diagram/generate', headers=_from('198.51.100.7'), json=GENERATE)).status_code == 201
    stream = await client.post('/api/v1/diagram/generate/stream', headers=_from('198.51.100.7'), json=GENERATE)
    assert stream.status_code == 200
    assert (await client.post('/api/v1/diagram/edit-local', headers=_from('198.51.100.7'), json=edit)).status_code == 200

    blocked = await client.post('/api/v1/diagram/generate', headers=_from('198.51.100.7'), json=GENERATE)
    assert blocked.status_code == 429
    assert blocked.json()['detail'] == (
        'Guests can run 3 diagram generations per day. Sign in to keep generating, or try again tomorrow (UTC).'
    )
    assert (await client.post('/api/v1/diagram/edit-local', headers=_from('198.51.100.7'), json=edit)).status_code == 429
    # Another real client behind the same proxy keeps its own allowance.
    assert (await client.post('/api/v1/diagram/generate', headers=_from('198.51.100.8'), json=GENERATE)).status_code == 201
    # Signed-in users are not subject to the guest quota.
    assert (await client.post('/api/v1/diagram/generate', headers={**api.owner, 'X-Forwarded-For': '198.51.100.7'},
                              json=GENERATE)).status_code == 201

    async with api.factory() as db:
        rows = (await db.execute(select(GuestGenerationUsage))).scalars().all()
    # Raw IPs never reach the database.
    assert all('198.51.100' not in row.client_hash for row in rows)
    assert sorted(row.count for row in rows) == [1, 3]


@pytest.mark.asyncio
async def test_rejected_bodies_do_not_consume_guest_quota(api):
    for _ in range(5):
        invalid = await api.client.post('/api/v1/diagram/generate', headers=_from('203.0.113.9'),
                                        json={'context': 'x' * 100_001, 'canvas_library': 'excalidraw'})
        assert invalid.status_code == 422
    async with api.factory() as db:
        assert await db.scalar(select(func.count()).select_from(GuestGenerationUsage)) == 0
    assert (await api.client.post('/api/v1/diagram/generate', headers=_from('203.0.113.9'),
                                  json=GENERATE)).status_code == 201


@pytest.mark.asyncio
async def test_spoofed_forwarded_header_from_untrusted_peer_is_ignored(api):
    """A direct client cannot mint fresh quotas by rotating X-Forwarded-For."""
    transport = httpx.ASGITransport(api.client._transport.app, client=('192.0.2.50', 4000))
    async with httpx.AsyncClient(transport=transport, base_url='http://test') as direct:
        for index in range(3):
            response = await direct.post('/api/v1/diagram/generate', headers=_from(f'10.0.0.{index}'), json=GENERATE)
            assert response.status_code == 201
        blocked = await direct.post('/api/v1/diagram/generate', headers=_from('10.0.0.99'), json=GENERATE)
    assert blocked.status_code == 429


@pytest.mark.asyncio
async def test_generation_runs_without_holding_the_request_transaction(api):
    assert (await api.client.post('/api/v1/diagram/generate', headers=api.owner, json=GENERATE)).status_code == 201
    assert (await api.client.post('/api/v1/diagram/generate/stream', headers=api.owner, json=GENERATE)).status_code == 200
    assert (await api.client.post('/api/v1/diagram/generate', headers=GUEST, json=GENERATE)).status_code == 201
    assert api.workflow.in_transaction == [False, False, False]


@pytest.mark.asyncio
async def test_oauth_exchange_requires_the_browser_binding_cookie(api):
    token = create_access_token({'user_id': 'owner'}, settings=api.settings)
    async with api.factory() as db:
        db.add(OAuthCode(code='exchange-code', token=token, expires_at=time.time() + 60))
        await db.commit()

    # Login CSRF: the code is valid, but this browser never completed the callback.
    forged = await api.client.post('/api/v1/auth/exchange', json={'code': 'exchange-code'})
    assert forged.status_code == 400
    wrong = await api.client.post('/api/v1/auth/exchange', json={'code': 'exchange-code'},
                                  headers={'Cookie': f'{OAUTH_EXCHANGE_COOKIE_NAME}=not-the-binding'})
    assert wrong.status_code == 400
    async with api.factory() as db:
        assert await db.get(OAuthCode, 'exchange-code') is not None  # Not burned by the forged attempt.

    binding = OAuthSessionService(settings=api.settings).exchange_binding('exchange-code')
    accepted = await api.client.post('/api/v1/auth/exchange', json={'code': 'exchange-code'},
                                     headers={'Cookie': f'{OAUTH_EXCHANGE_COOKIE_NAME}={binding}'})
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()['user']['user_id'] == 'owner'
    cleared = accepted.headers['set-cookie']
    assert cleared.startswith(f'{OAUTH_EXCHANGE_COOKIE_NAME}=') and 'Max-Age=0' in cleared


@pytest.mark.asyncio
async def test_password_policy_returns_422_instead_of_500(api):
    short = await api.client.post('/api/v1/auth/register', json={
        'email': 'short@example.org', 'password': 'seven77', 'verification_code': ''})
    assert short.status_code == 422
    huge = await api.client.post('/api/v1/auth/login', json={'email': 'quota@example.org', 'password': 'x' * 5000})
    assert huge.status_code == 422


@pytest.mark.asyncio
async def test_invalid_local_edit_is_rejected_before_spending_guest_quota(api):
    client = api.client
    missing = {'current_schema': {'elements': []}, 'selected_node_ids': ['ghost'], 'instruction': 'Bigger',
               'canvas_library': 'excalidraw'}
    for _ in range(5):
        response = await client.post('/api/v1/diagram/edit-local', headers=_from('198.51.100.9'), json=missing)
        assert response.status_code == 400
        assert response.json()['detail'] == 'Selected nodes were not found'
    # The full allowance (3 in this fixture) is still available afterwards.
    for _ in range(3):
        assert (await client.post('/api/v1/diagram/generate', headers=_from('198.51.100.9'),
                                  json=GENERATE)).status_code == 201
