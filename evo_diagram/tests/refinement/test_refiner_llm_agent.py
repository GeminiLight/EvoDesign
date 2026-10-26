from __future__ import annotations

from types import SimpleNamespace

import evo_diagram.agentic_system.refinement_stage.agent.llm_agent as llm_agent_module
from evo_diagram.agentic_system.refinement_stage.agent.llm_agent import (
    RefinerLLMAgent,
    _is_permanent_http_error,
)


class _ProviderError(Exception):
    def __init__(self, status_code: int):
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


class RateLimitError(Exception):
    pass


class AuthenticationError(Exception):
    pass


def test_refiner_retry_policy_keeps_transient_provider_statuses_retryable():
    assert _is_permanent_http_error(_ProviderError(408)) is False
    assert _is_permanent_http_error(_ProviderError(409)) is False
    assert _is_permanent_http_error(_ProviderError(429)) is False
    assert _is_permanent_http_error(_ProviderError(500)) is False
    assert _is_permanent_http_error(_ProviderError(504)) is False


def test_refiner_retry_policy_stops_on_permanent_provider_statuses():
    assert _is_permanent_http_error(_ProviderError(400)) is True
    assert _is_permanent_http_error(_ProviderError(401)) is True
    assert _is_permanent_http_error(_ProviderError(403)) is True
    assert _is_permanent_http_error(_ProviderError(404)) is True


def test_refiner_retry_policy_uses_class_name_fallback_carefully():
    assert _is_permanent_http_error(RateLimitError("slow down")) is False
    assert _is_permanent_http_error(AuthenticationError("bad key")) is True


class _FakeModel:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def invoke(self, _messages):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _patch_refiner_side_effects(monkeypatch):
    sleeps = []
    monkeypatch.setattr(
        llm_agent_module,
        "image_to_data_url",
        lambda _path: "data:image/png;base64,FAKE",
    )
    monkeypatch.setattr(llm_agent_module.time, "sleep", sleeps.append)
    return sleeps


def _valid_edit_response():
    return SimpleNamespace(
        content=(
            '[{"op":"set_text","id":"n1",'
            '"payload":{"text":"OK"},"rationale":"fix label"}]'
        )
    )


def test_refiner_llm_retries_transient_provider_errors(monkeypatch):
    sleeps = _patch_refiner_side_effects(monkeypatch)
    model = _FakeModel(
        [
            _ProviderError(429),
            _ProviderError(500),
            _valid_edit_response(),
        ]
    )
    agent = RefinerLLMAgent(model=model, max_retries=3, retry_delay_seconds=0.25)

    edits = agent.propose_edits(
        image_path="fake.png",
        chart_type="flowchart",
        remaining_findings=[],
        critique=None,
        manifest_summary=[],
    )

    assert model.calls == 3
    assert sleeps == [0.25, 0.5]
    assert len(edits) == 1
    assert edits[0].op == "set_text"
    assert agent.last_exhaustion_error is None


def test_refiner_llm_stops_immediately_on_permanent_provider_error(monkeypatch):
    sleeps = _patch_refiner_side_effects(monkeypatch)
    model = _FakeModel([_ProviderError(401), _valid_edit_response()])
    agent = RefinerLLMAgent(model=model, max_retries=3, retry_delay_seconds=0.25)

    edits = agent.propose_edits(
        image_path="fake.png",
        chart_type="flowchart",
        remaining_findings=[],
        critique=None,
        manifest_summary=[],
    )

    assert edits == []
    assert model.calls == 1
    assert sleeps == []
    assert agent.last_exhaustion_error is not None
    assert "HTTP 401" in agent.last_exhaustion_error


def test_refiner_llm_surfaces_transient_retry_exhaustion(monkeypatch):
    sleeps = _patch_refiner_side_effects(monkeypatch)
    model = _FakeModel(
        [
            _ProviderError(503),
            _ProviderError(503),
            _ProviderError(503),
        ]
    )
    agent = RefinerLLMAgent(model=model, max_retries=3, retry_delay_seconds=0.25)

    edits = agent.propose_edits(
        image_path="fake.png",
        chart_type="flowchart",
        remaining_findings=[],
        critique=None,
        manifest_summary=[],
    )

    assert edits == []
    assert model.calls == 3
    assert sleeps == [0.25, 0.5]
    assert agent.last_exhaustion_error is not None
    assert "HTTP 503" in agent.last_exhaustion_error


def test_coerce_to_edits_reports_schema_rejections_instead_of_dropping_them():
    """One drifted field name invalidates a whole item (EditOp forbids extras).

    Returning a bare list made "20 malformed proposals" indistinguishable from
    "the model had nothing to propose".
    """
    from evo_diagram.agentic_system.refinement_stage.agent.llm_agent import (
        _coerce_to_edits,
    )

    edits, rejections = _coerce_to_edits(
        [
            {"op": "set_position", "id": "n1", "payload": {"x": 1, "y": 2}},
            # ``reason`` instead of ``rationale`` — the exact drift EditOp forbids.
            {"op": "set_position", "id": "n2", "payload": {"x": 3, "y": 4}, "reason": "x"},
            {"op": "teleport", "id": "n3"},
            "not-an-object",
        ]
    )

    assert [e.id for e in edits] == ["n1"]
    assert len(rejections) == 3
    assert all(item["error"].startswith("schema:") for item in rejections)
    assert rejections[0]["raw"]["id"] == "n2"


def test_propose_edits_exposes_rejections_on_the_agent(monkeypatch):
    from evo_diagram.agentic_system.refinement_stage.agent import llm_agent as module

    _patch_refiner_side_effects(monkeypatch)
    model = _FakeModel(
        [
            SimpleNamespace(
                content='[{"op": "set_position", "id": "n1", "payload": {"x": 1, "y": 2}, "reason": "typo"}]'
            )
        ]
    )
    agent = module.RefinerLLMAgent(model=model, max_retries=1, retry_delay_seconds=0)

    edits = agent.propose_edits(
        image_path="image.png",
        chart_type=None,
        remaining_findings=[],
        critique=None,
        manifest_summary=[],
    )

    assert edits == []
    assert len(agent.last_rejected_edits) == 1
    assert agent.last_rejected_edits[0]["error"].startswith("schema:")
