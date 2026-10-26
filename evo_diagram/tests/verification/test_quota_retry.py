"""Exhausted usage windows must not consume the outer review retry budget."""
import httpx
import openai
import pytest

from evo_diagram.agentic_system.verification_stage.critic import critic_agent as critic
from evo_diagram.agentic_system.refinement_stage.agent import llm_agent as refiner


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
