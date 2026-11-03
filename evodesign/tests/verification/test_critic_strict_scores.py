"""A critique without scores is a critic failure, never an implicit 0."""
import httpx
import openai
import pytest

from evodesign.agentic_system.verification_stage.critic import critic_agent as critic


def _dim(score=7):
    return {"score": score, "strengths": [], "weaknesses": [], "suggestions": []}


def _payload(**overrides):
    data = {"structure": _dim(), "styling": _dim(), "layout": _dim(), "overall_score": 7, "summary": "ok"}
    data.update(overrides)
    return {k: v for k, v in data.items() if v is not None}


def test_complete_critique_is_accepted():
    critique = critic._coerce_critique(_payload(), raw=None)
    assert critique.overall_score == 7.0
    assert critique.layout.score == 7.0


@pytest.mark.parametrize("overrides", [
    {"overall_score": None},
    {"overall_score": "high"},
    {"overall_score": float("nan")},
    {"layout": None},
    {"styling": {"strengths": ["nice"]}},
    {"structure": {"score": None}},
])
def test_incomplete_critique_is_rejected(overrides):
    with pytest.raises(critic.IncompleteCritiqueError):
        critic._coerce_critique(_payload(**overrides), raw=None)


def test_bare_dict_does_not_become_a_zero_score(monkeypatch):
    class Response:
        content = '{"summary": "looks fine"}'

    class Model:
        calls = 0

        def invoke(self, _messages):
            Model.calls += 1
            return Response()

    monkeypatch.setattr(critic.time, "sleep", lambda _s: None)
    agent = critic.VerifierCriticAgent(model=Model(), max_retries=2)
    monkeypatch.setattr(agent, "_build_messages", lambda *args: [])
    with pytest.raises(critic.IncompleteCritiqueError):
        agent.critique("unused.png")
    assert Model.calls == 2


@pytest.mark.parametrize("status", [400, 401, 403])
def test_critic_does_not_retry_permanent_http_errors(monkeypatch, status):
    sleeps = []
    monkeypatch.setattr(critic.time, "sleep", sleeps.append)
    response = httpx.Response(status, request=httpx.Request("POST", "https://api.example.test"))
    error = openai.APIStatusError("client error", response=response, body=None)

    class Model:
        calls = 0

        def invoke(self, _messages):
            Model.calls += 1
            raise error

    agent = critic.VerifierCriticAgent(model=Model(), max_retries=3)
    monkeypatch.setattr(agent, "_build_messages", lambda *args: [])
    with pytest.raises(openai.APIStatusError):
        agent.critique("unused.png")
    assert Model.calls == 1
    assert sleeps == []
