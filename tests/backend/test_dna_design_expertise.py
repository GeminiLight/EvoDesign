"""DNA rule injection into the diagram generation path.

Covers the three layers of the wiring:
- ``dna_design_expertise`` formatting/loading (caps, truncation, guests,
  database failure degradation),
- ``WorkflowEngineAdapter`` handing the text to the engine's
  ``design_expertise`` construction points (streaming and sync),
- ``WorkflowGenerateService`` threading loaded DNA into ``WorkflowRunRequest``.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models import DnaRule, OAuthCode, Project, Snapshot, Subscription, User  # noqa: F401
from app.schemas.dna import DnaRuleSchema, DnaRulesPayload
from app.services.dna_design_expertise import (
    DNA_SECTION_FOOTER,
    DNA_SECTION_HEADER,
    MAX_DNA_PREVIEW_CHARS,
    MAX_INJECTED_DNA_RULES,
    format_dna_design_expertise,
    load_dna_design_expertise,
)
from app.services.workflow_engine_adapter import (
    StreamingEngineDependencies,
    WorkflowEngineAdapter,
    WorkflowRunRequest,
)
from app.services.workflow_generate_service import WorkflowGenerateService


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


def _row(**overrides) -> DnaRule:
    data = {
        "rule_id": "row-1",
        "user_id": "user-1",
        "project_id": None,
        "cabin_id": "structure",
        "title": "Layered flow",
        "preview": "Group related nodes into tiers.",
        "source": "manual",
        "enabled": True,
        "pinned": False,
        "usage_count": 0,
        "created_at": datetime(2026, 1, 1),
        "updated_at": datetime(2026, 1, 1),
    }
    data.update(overrides)
    return DnaRule(**data)


async def _memory_session_factory(rows):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add_all(rows)
        await session.commit()
    return engine, factory


# ---------------------------------------------------------------------------
# format_dna_design_expertise
# ---------------------------------------------------------------------------


def test_format_renders_enabled_rules_in_cabin_order_with_section_fences():
    payload = DnaRulesPayload(
        structure=[_rule(rule_id="s1", title="Layered flow", preview="Use tiers.")],
        style=[
            _rule(rule_id="x1", title="Disabled rule", preview="Never shown.", enabled=False),
            _rule(rule_id="t1", title="Muted palette", preview="Prefer muted colors."),
        ],
        layout=[_rule(rule_id="l1", title="Grid anchors", preview="Snap blocks to a grid.")],
        project_id=None,
    )

    assert format_dna_design_expertise(payload) == "\n".join(
        [
            DNA_SECTION_HEADER,
            "- Layered flow: Use tiers.",
            "- Muted palette: Prefer muted colors.",
            "- Grid anchors: Snap blocks to a grid.",
            DNA_SECTION_FOOTER,
        ]
    )
    assert "Disabled rule" not in format_dna_design_expertise(payload)


def test_format_returns_empty_string_when_nothing_is_injectable():
    assert format_dna_design_expertise(DnaRulesPayload()) == ""
    assert (
        format_dna_design_expertise(
            DnaRulesPayload(structure=[_rule(enabled=False)])
        )
        == ""
    )


def test_format_caps_injected_rules_at_the_prompt_budget():
    rules = [
        _rule(rule_id=f"r{i}", title=f"Rule {i:02d}", preview=f"preview {i}")
        for i in range(MAX_INJECTED_DNA_RULES + 5)
    ]

    text = format_dna_design_expertise(DnaRulesPayload(structure=rules))

    body = text.splitlines()[1:-1]
    assert len(body) == MAX_INJECTED_DNA_RULES
    assert body[0] == "- Rule 00: preview 0"
    assert body[-1] == f"- Rule {MAX_INJECTED_DNA_RULES - 1:02d}: preview {MAX_INJECTED_DNA_RULES - 1}"
    assert f"Rule {MAX_INJECTED_DNA_RULES:02d}" not in text


def test_format_truncates_long_previews():
    long_preview = "x" * (MAX_DNA_PREVIEW_CHARS + 50)

    text = format_dna_design_expertise(
        DnaRulesPayload(structure=[_rule(title="Verbose", preview=long_preview)])
    )

    assert text.splitlines()[1] == f"- Verbose: {'x' * MAX_DNA_PREVIEW_CHARS}"


def test_format_collapses_rule_text_to_single_line_bullets():
    text = format_dna_design_expertise(
        DnaRulesPayload(
            structure=[_rule(title="Multi\nline\ttitle", preview="spaced\n\npreview")]
        )
    )

    assert text.splitlines()[1] == "- Multi line title: spaced preview"
    assert len(text.splitlines()) == 3


# ---------------------------------------------------------------------------
# load_dna_design_expertise
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_skips_guests_without_touching_the_database():
    def exploding_factory():
        raise AssertionError("guest DNA lookup must not open a database session")

    assert (
        await load_dna_design_expertise(
            user_id=None,
            project_id="project-1",
            session_factory=exploding_factory,
        )
        == ""
    )


@pytest.mark.asyncio
async def test_load_reads_enabled_global_rules_from_the_database():
    engine, factory = await _memory_session_factory(
        [
            _row(rule_id="r1", created_at=datetime(2026, 1, 1)),
            _row(
                rule_id="r2",
                cabin_id="style",
                title="Muted palette",
                preview="Prefer muted colors.",
                created_at=datetime(2026, 1, 2),
            ),
            _row(rule_id="r3", title="Disabled", preview="Hidden.", enabled=False),
            _row(rule_id="r4", user_id="other-user", title="Foreign", preview="Not mine."),
        ]
    )
    try:
        text = await load_dna_design_expertise(
            user_id="user-1",
            session_factory=factory,
        )
    finally:
        await engine.dispose()

    assert text == "\n".join(
        [
            DNA_SECTION_HEADER,
            "- Layered flow: Group related nodes into tiers.",
            "- Muted palette: Prefer muted colors.",
            DNA_SECTION_FOOTER,
        ]
    )


@pytest.mark.asyncio
async def test_load_scopes_to_the_requested_project():
    engine, factory = await _memory_session_factory(
        [
            _row(rule_id="global-1", title="Global rule", preview="global."),
            _row(
                rule_id="project-1-rule",
                project_id="project-1",
                title="Project rule",
                preview="project.",
            ),
            _row(
                rule_id="project-2-rule",
                project_id="project-2",
                title="Other project rule",
                preview="other.",
            ),
        ]
    )
    try:
        text = await load_dna_design_expertise(
            user_id="user-1",
            project_id="project-1",
            session_factory=factory,
        )
    finally:
        await engine.dispose()

    assert "- Project rule: project." in text
    assert "Global rule" not in text
    assert "Other project rule" not in text


@pytest.mark.asyncio
async def test_load_degrades_to_empty_string_on_database_failure():
    def broken_factory():
        raise RuntimeError("database unavailable")

    assert (
        await load_dna_design_expertise(
            user_id="user-1",
            session_factory=broken_factory,
        )
        == ""
    )


# ---------------------------------------------------------------------------
# WorkflowEngineAdapter injection points
# ---------------------------------------------------------------------------


def _dna_request(design_expertise: str) -> WorkflowRunRequest:
    return WorkflowRunRequest(
        context="A to B",
        requirements=None,
        locked_nodes=[],
        current_schema=None,
        canvas_library="excalidraw",
        user_tier=None,
        request_id="req_dna",
        design_expertise=design_expertise,
    )


def test_sync_adapter_passes_dna_text_to_workflow_run(tmp_path):
    run_seen = []

    class FakeWorkflow:
        def __init__(self, **kwargs):
            pass

        def run(self, **kwargs):
            run_seen.append(kwargs)
            return SimpleNamespace(
                diagram_manifest={"elements": []},
                refined_diagram_manifest=None,
                structure_instantiation={},
                styling_instantiation={},
                layout_instantiation={},
            )

    adapter = WorkflowEngineAdapter(
        results_dir=str(tmp_path),
        workflow_cls_loader=lambda: FakeWorkflow,
    )

    adapter.run_without_render_sync(
        model="fake-model",
        request=_dna_request("=== USER DESIGN DNA ===\n- Rule: preview\n=== END USER DESIGN DNA ==="),
    )

    assert run_seen[0]["design_expertise"] == (
        "=== USER DESIGN DNA ===\n- Rule: preview\n=== END USER DESIGN DNA ==="
    )


class _DesignExpertiseSentinel(Exception):
    """Stops the fake streaming pipeline right after the expertise is built."""


@pytest.mark.asyncio
async def test_streaming_adapter_builds_design_expertise_from_dna_text(tmp_path):
    seen = {}

    class FakeWorkflow:
        def __init__(self, **kwargs):
            pass

        def build_design_expertise(self, design_expertise, diagram_type, content_area, **queries):
            seen["build_args"] = (design_expertise, diagram_type, content_area)
            seen["queries"] = queries
            return f"FULL[{design_expertise}]"

        def begin_generation_run(
            self,
            text_content,
            user_query,
            *,
            design_expertise="",
            runtime_directives="",
            **kwargs,
        ):
            seen["run"] = SimpleNamespace(effective_diagram_type="flowchart", design_expertise=design_expertise)
            return seen["run"]

        def run_generation_stage(self, run_state, stage_name, *, save_dir=None):
            raise _DesignExpertiseSentinel

    def unused_dependency():
        raise AssertionError("streaming must stop before verification/refiner/render")

    adapter = WorkflowEngineAdapter(
        results_dir=str(tmp_path),
        streaming_dependency_loader=lambda: StreamingEngineDependencies(
            workflow_cls=FakeWorkflow,
            verifier_workflow_cls=unused_dependency,
            iterative_refiner_workflow_cls=unused_dependency,
            severity_cls=unused_dependency,
            render_manifest=unused_dependency,
        ),
    )

    async for _chunk in adapter.stream_without_render(
        model="fake-model",
        request=_dna_request("DNA-TEXT"),
    ):
        pass

    # The DNA text is the caller-explicit first slot of build_design_expertise,
    # and its assembled result is what the generation run receives.
    assert seen["build_args"] == ("DNA-TEXT", "flowchart", None)
    assert seen["queries"]["retrieval_query"] == _dna_request("DNA-TEXT").context
    assert seen["queries"]["user_query"]
    assert seen["run"].design_expertise == "FULL[DNA-TEXT]"


# ---------------------------------------------------------------------------
# WorkflowGenerateService wiring
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_without_render_loads_dna_for_user_and_project(monkeypatch):
    captured = {}

    class FakeEngineAdapter:
        def run_without_render_sync(self, *, model, request):
            captured["request"] = request
            return {"schema_blob": {"elements": []}}

    async def fake_loader(*, user_id, project_id=None, **kwargs):
        captured["dna_args"] = (user_id, project_id)
        return "DNA-TEXT"

    monkeypatch.setattr(
        "app.services.workflow_generate_service.load_dna_design_expertise",
        fake_loader,
    )
    service = WorkflowGenerateService(engine_adapter=FakeEngineAdapter())
    monkeypatch.setattr(service, "_create_llm", lambda: "fake-model")

    await service.generate_without_render(
        context="A to B",
        requirements=None,
        locked_nodes=[],
        current_schema=None,
        canvas_library="excalidraw",
        user_tier=None,
        user_id="user-1",
        project_id="project-1",
    )

    assert captured["dna_args"] == ("user-1", "project-1")
    assert captured["request"].design_expertise == "DNA-TEXT"


@pytest.mark.asyncio
async def test_generate_without_render_streaming_loads_dna_for_user_and_project(
    monkeypatch,
):
    captured = {}

    class FakeEngineAdapter:
        async def stream_without_render(self, *, model, request):
            captured["request"] = request
            yield 'event: result\ndata: {"schema_blob": {}}\n\n'

    async def fake_loader(*, user_id, project_id=None, **kwargs):
        captured["dna_args"] = (user_id, project_id)
        return "DNA-TEXT"

    monkeypatch.setattr(
        "app.services.workflow_generate_service.load_dna_design_expertise",
        fake_loader,
    )
    service = WorkflowGenerateService(engine_adapter=FakeEngineAdapter())
    monkeypatch.setattr(service, "_create_llm", lambda: "fake-model")

    async for _chunk in service.generate_without_render_streaming(
        context="A to B",
        requirements=None,
        locked_nodes=[],
        current_schema=None,
        canvas_library="excalidraw",
        user_tier=None,
        user_id="user-1",
        project_id="project-1",
    ):
        pass

    assert captured["dna_args"] == ("user-1", "project-1")
    assert captured["request"].design_expertise == "DNA-TEXT"


@pytest.mark.asyncio
async def test_generate_without_render_defaults_to_empty_dna_for_guests(monkeypatch):
    captured = {}

    class FakeEngineAdapter:
        def run_without_render_sync(self, *, model, request):
            captured["request"] = request
            return {"schema_blob": {"elements": []}}

    async def fake_loader(*, user_id, project_id=None, **kwargs):
        captured["dna_args"] = (user_id, project_id)
        return await load_dna_design_expertise(
            user_id=user_id,
            project_id=project_id,
            session_factory=lambda: pytest.fail("guests must not open sessions"),
        )

    monkeypatch.setattr(
        "app.services.workflow_generate_service.load_dna_design_expertise",
        fake_loader,
    )
    service = WorkflowGenerateService(engine_adapter=FakeEngineAdapter())
    monkeypatch.setattr(service, "_create_llm", lambda: "fake-model")

    await service.generate_without_render(
        context="A to B",
        requirements=None,
        locked_nodes=[],
        current_schema=None,
        canvas_library="excalidraw",
    )

    assert captured["dna_args"] == (None, None)
    assert captured["request"].design_expertise == ""
