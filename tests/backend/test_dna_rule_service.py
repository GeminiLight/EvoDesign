from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.exceptions import ProjectNotFoundException
from app.db.base import Base
from app.models import DnaRule, OAuthCode, Project, Snapshot, Subscription, User  # noqa: F401
from app.schemas.dna import DnaRuleSchema, DnaRulesPayload
from app.services.dna_rule_service import DnaRuleService, rows_to_payload


async def _create_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine, session_factory()


def _rule(**overrides) -> DnaRuleSchema:
    data = {
        "rule_id": "rule-1",
        "cabin_id": "structure",
        "title": "Layered flow",
        "preview": "Group related nodes into tiers.",
        "source": "manual",
        "enabled": True,
        "pinned": False,
        "usage_count": 0,
        "updated_at": "2026-01-01T00:00:00",
    }
    data.update(overrides)
    return DnaRuleSchema(**data)


def test_rows_to_payload_groups_known_cabins_and_ignores_unknown_rows():
    rows = [
        DnaRule(
            rule_id="structure-1",
            user_id="user-1",
            project_id=None,
            cabin_id="structure",
            title="Structure rule",
            preview="Use tiers.",
            source="manual",
            enabled=True,
            pinned=False,
            usage_count=1,
            updated_at=datetime(2026, 1, 1),
        ),
        DnaRule(
            rule_id="style-1",
            user_id="user-1",
            project_id=None,
            cabin_id="style",
            title="Style rule",
            preview="Use soft colors.",
            source="ai",
            enabled=False,
            pinned=True,
            usage_count=2,
            updated_at=datetime(2026, 1, 2),
        ),
        DnaRule(
            rule_id="unknown-1",
            user_id="user-1",
            project_id=None,
            cabin_id="unknown",
            title="Unknown rule",
            preview="Ignore me.",
            source="ai",
            enabled=True,
            pinned=False,
            usage_count=0,
            updated_at=datetime(2026, 1, 3),
        ),
    ]

    payload = rows_to_payload(rows, project_id=None)

    assert [rule.rule_id for rule in payload.structure] == ["structure-1"]
    assert [rule.rule_id for rule in payload.style] == ["style-1"]
    assert payload.layout == []


@pytest.mark.asyncio
async def test_get_rules_returns_only_user_scope_and_buckets_by_cabin():
    engine, session = await _create_session()
    try:
        session.add_all(
            [
                DnaRule(
                    rule_id="global-structure",
                    user_id="user-1",
                    project_id=None,
                    cabin_id="structure",
                    title="Global",
                    preview="Global rule",
                    source="manual",
                    enabled=True,
                    pinned=False,
                    usage_count=0,
                    created_at=datetime(2026, 1, 1),
                    updated_at=datetime(2026, 1, 1),
                ),
                DnaRule(
                    rule_id="project-style",
                    user_id="user-1",
                    project_id="project-1",
                    cabin_id="style",
                    title="Project",
                    preview="Project rule",
                    source="ai",
                    enabled=True,
                    pinned=True,
                    usage_count=3,
                    created_at=datetime(2026, 1, 2),
                    updated_at=datetime(2026, 1, 2),
                ),
                DnaRule(
                    rule_id="other-user",
                    user_id="user-2",
                    project_id="project-1",
                    cabin_id="layout",
                    title="Other",
                    preview="Other rule",
                    source="ai",
                    enabled=True,
                    pinned=False,
                    usage_count=0,
                    created_at=datetime(2026, 1, 3),
                    updated_at=datetime(2026, 1, 3),
                ),
            ]
        )
        await session.flush()

        payload = await DnaRuleService(session).get_rules(
            user_id="user-1",
            project_id="project-1",
        )

        assert payload.project_id == "project-1"
        assert payload.structure == []
        assert [rule.rule_id for rule in payload.style] == ["project-style"]
        assert payload.layout == []
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_replace_rules_replaces_only_requested_scope_and_generates_missing_ids():
    engine, session = await _create_session()
    try:
        session.add_all(
            [
                DnaRule(
                    rule_id="old-global",
                    user_id="user-1",
                    project_id=None,
                    cabin_id="structure",
                    title="Old global",
                    preview="Remove this.",
                    source="manual",
                    enabled=True,
                    pinned=False,
                    usage_count=0,
                    created_at=datetime(2026, 1, 1),
                    updated_at=datetime(2026, 1, 1),
                ),
                DnaRule(
                    rule_id="project-kept",
                    user_id="user-1",
                    project_id="project-1",
                    cabin_id="style",
                    title="Project kept",
                    preview="Different scope.",
                    source="ai",
                    enabled=True,
                    pinned=False,
                    usage_count=0,
                    created_at=datetime(2026, 1, 2),
                    updated_at=datetime(2026, 1, 2),
                ),
            ]
        )
        await session.flush()

        service = DnaRuleService(
            session,
            id_factory=lambda: "generated-rule",
            clock=lambda: datetime(2026, 2, 1, 12, 0, 0),
        )
        payload = await service.replace_rules(
            user_id="user-1",
            payload=DnaRulesPayload(
                project_id=None,
                structure=[
                    _rule(
                        rule_id="",
                        title="New structure",
                        preview="Use swimlanes.",
                    )
                ],
                layout=[
                    _rule(
                        rule_id="layout-existing",
                        cabin_id="layout",
                        title="New layout",
                        preview="Balance whitespace.",
                        usage_count=4,
                    )
                ],
            ),
        )

        result = await session.execute(select(DnaRule).order_by(DnaRule.rule_id))
        rows = result.scalars().all()

        assert [rule.rule_id for rule in payload.structure] == ["generated-rule"]
        assert [rule.rule_id for rule in payload.layout] == ["layout-existing"]
        assert [row.rule_id for row in rows] == [
            "generated-rule",
            "layout-existing",
            "project-kept",
        ]
        assert rows[0].created_at == datetime(2026, 2, 1, 12, 0, 0)
    finally:
        await session.close()
        await engine.dispose()


async def _seed_project(session, *, project_id: str, user_id: str) -> None:
    session.add(User(user_id=user_id, email=f"{user_id}@example.com"))
    session.add(Project(project_id=project_id, user_id=user_id))
    await session.flush()


@pytest.mark.asyncio
async def test_replace_rules_rejects_a_project_owned_by_another_user():
    engine, session = await _create_session()
    try:
        await _seed_project(session, project_id="project-1", user_id="owner")

        service = DnaRuleService(session)

        with pytest.raises(ProjectNotFoundException):
            await service.replace_rules(
                user_id="attacker",
                payload=DnaRulesPayload(
                    project_id="project-1",
                    structure=[_rule()],
                ),
            )

        result = await session.execute(select(DnaRule))
        assert result.scalars().all() == []
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_replace_rules_accepts_a_project_owned_by_the_user():
    engine, session = await _create_session()
    try:
        await _seed_project(session, project_id="project-1", user_id="user-1")

        payload = await DnaRuleService(session).replace_rules(
            user_id="user-1",
            payload=DnaRulesPayload(
                project_id="project-1",
                structure=[_rule(rule_id="rule-1")],
            ),
        )

        assert [rule.rule_id for rule in payload.structure] == ["rule-1"]
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_replace_rules_regenerates_rule_ids_repeated_within_one_payload():
    engine, session = await _create_session()
    try:
        service = DnaRuleService(session, id_factory=lambda: "server-generated")
        payload = await service.replace_rules(
            user_id="user-1",
            payload=DnaRulesPayload(
                project_id=None,
                structure=[_rule(rule_id="duplicate")],
                layout=[_rule(rule_id="duplicate", cabin_id="layout")],
            ),
        )

        rule_ids = [rule.rule_id for rule in payload.structure + payload.layout]
        assert sorted(rule_ids) == ["duplicate", "server-generated"]
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_project_copy_of_global_dna_has_independent_identity_and_keeps_global_rules():
    engine, session = await _create_session()
    try:
        await _seed_project(session, project_id='project-1', user_id='user-1')
        service = DnaRuleService(session)
        await service.replace_rules(user_id='user-1', payload=DnaRulesPayload(
            structure=[_rule(rule_id='global-rule')]))
        copied = await service.replace_rules(user_id='user-1', payload=DnaRulesPayload(
            project_id='project-1', structure=[_rule(rule_id='global-rule')]))
        assert copied.structure[0].rule_id != 'global-rule'
        assert (await service.get_rules(user_id='user-1', project_id=None)).structure[0].rule_id == 'global-rule'
        copied_id = copied.structure[0].rule_id
        edited = await service.replace_rules(user_id='user-1', payload=DnaRulesPayload(
            project_id='project-1', structure=[_rule(rule_id=copied_id, title='Edited project rule')]))
        assert edited.structure[0].rule_id == copied_id
        await service.replace_rules(user_id='user-1', payload=DnaRulesPayload(project_id='project-1'))
        assert (await service.get_rules(user_id='user-1', project_id=None)).structure[0].title == 'Layered flow'
    finally:
        await session.close()
        await engine.dispose()
