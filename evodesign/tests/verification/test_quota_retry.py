"""Exhausted usage windows must not consume the outer review retry budget."""
import httpx
import openai
import pytest

from evodesign.agentic_system.verification_stage.critic import critic_agent as critic
from evodesign.agentic_system.refinement_stage.agent import llm_agent as refiner


class QuotaModel:
    def __init__(self, code):
        self.calls = 0
        response = httpx.Response(429, request=httpx.Request("POST", "https://api.example.test"))
        self.error = openai.RateLimitError("quota", response=response, body={"type": code})

    def invoke(self, _messages):
        self.calls += 1
        raise self.error


@pytest.mark.parametrize("code,expected_calls", [("exceeded_current_quota_error", 1), ("rate_limit_exceeded", 3)])
def test_critic_distinguishes_quota_from_temporary_throttling(monkeypatch, code, expected_calls):
    sleeps = []
    monkeypatch.setattr(critic.time, "sleep", sleeps.append)
    model = QuotaModel(code)
    agent = critic.VerifierCriticAgent(model=model, max_retries=3)
    monkeypatch.setattr(agent, "_build_messages", lambda *args: [])
    with pytest.raises(openai.RateLimitError):
        agent.critique("unused.png")
    assert model.calls == expected_calls
    assert len(sleeps) == expected_calls - 1


def test_refiner_stops_on_quota_without_claiming_success(monkeypatch):
    sleeps = []
    monkeypatch.setattr(refiner.time, "sleep", sleeps.append)
    monkeypatch.setattr(refiner, "image_to_data_url", lambda *_: "data:image/png;base64,AA==")
    model = QuotaModel("exceeded_current_quota_error")
    agent = refiner.RefinerLLMAgent(model=model, max_retries=3)
    assert agent.propose_edits(image_path="unused.png", chart_type="flowchart",
                              remaining_findings=[], critique=None, manifest_summary=[]) == []
    assert model.calls == 1
    assert not sleeps
    assert agent.last_exhaustion_error is not None


class ScriptedModel:
    """Returns the scripted contents in order, raising any exception entries."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def invoke(self, _messages):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return type("Response", (), {"content": outcome})()


_DIM = '{"score": 7, "strengths": [], "weaknesses": [], "suggestions": []}'
_CRITIQUE = f'{{"structure": {_DIM}, "styling": {_DIM}, "layout": {_DIM}, "overall_score": 7, "summary": "ok"}}'


def test_critic_resamples_format_errors_without_backoff(monkeypatch):
    sleeps = []
    monkeypatch.setattr(critic.time, "sleep", sleeps.append)
    model = ScriptedModel(["not json", '{"overall_score": 7}', _CRITIQUE])
    agent = critic.VerifierCriticAgent(model=model, max_retries=3, retry_delay_seconds=5)
    monkeypatch.setattr(agent, "_build_messages", lambda *args: [])
    assert agent.critique("unused.png").overall_score == 7.0
    assert model.calls == 3 and sleeps == []


def test_critic_still_backs_off_on_transient_transport_errors(monkeypatch):
    sleeps = []
    monkeypatch.setattr(critic.time, "sleep", sleeps.append)
    response = httpx.Response(503, request=httpx.Request("POST", "https://api.example.test"))
    model = ScriptedModel([openai.InternalServerError("busy", response=response, body=None), _CRITIQUE])
    agent = critic.VerifierCriticAgent(model=model, max_retries=3, retry_delay_seconds=5)
    monkeypatch.setattr(agent, "_build_messages", lambda *args: [])
    agent.critique("unused.png")
    assert sleeps == [5]


def test_refiner_resamples_format_errors_without_backoff(monkeypatch):
    sleeps = []
    monkeypatch.setattr(refiner.time, "sleep", sleeps.append)
    monkeypatch.setattr(refiner, "image_to_data_url", lambda _path: "data:image/png;base64,FAKE")
    edit = '[{"op":"set_text","id":"n1","payload":{"text":"OK"},"rationale":"fix"}]'
    model = ScriptedModel(["prose only", '{"op": "set_text"}', edit])
    agent = refiner.RefinerLLMAgent(model=model, max_retries=3, retry_delay_seconds=5)
    edits = agent.propose_edits(image_path="fake.png", chart_type="flowchart", remaining_findings=[],
                                critique=None, manifest_summary=[])
    assert len(edits) == 1 and model.calls == 3 and sleeps == []
