from __future__ import annotations

import json
from typing import Any

import httpx


import openai
import pytest

from evodesign.core.base_agent import BaseAgent, _render_template
from evodesign.core.base_agent import _is_retryable_exception


class _DummyAgent(BaseAgent):
    def run(self, state: Any) -> Any:
        return state


class _FakeModel:
    def __init__(self, raw_output: str) -> None:
        self.raw_output = raw_output

    def invoke(self, messages):
        self.messages = messages
        return self.raw_output


def test_invoke_with_history_records_last_raw_output():
    model = _FakeModel('{"ok": true}')
    agent = object.__new__(_DummyAgent)
    agent._model = model
    agent._tools = []
    agent.exclude_think = True
    agent.jsonalize_output = True
    agent.json_retry_attempts = 1
    agent._last_raw_output = None

    result = agent.invoke_with_history([{"role": "user", "content": "Return JSON"}])

    assert result == {"ok": True}
    assert agent._last_raw_output == '{"ok": true}'


def test_render_template_does_not_expand_placeholders_inside_values():
    rendered = _render_template(
        "text={{text_content}}\nruntime={{runtime_directives}}",
        {
            "text_content": "literal {{runtime_directives}} marker",
            "runtime_directives": "KEEP_THIS_BOUNDARY",
        },
    )

    assert "text=literal {{runtime_directives}} marker" in rendered
    assert "runtime=KEEP_THIS_BOUNDARY" in rendered


def _http_status_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://api.example.test/v1/chat")
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError("status error", request=request, response=response)


def test_retry_predicate_retries_only_transient_http_statuses():
    assert _is_retryable_exception(_http_status_error(429)) is True
    assert _is_retryable_exception(_http_status_error(500)) is True
    assert _is_retryable_exception(_http_status_error(401)) is False
    assert _is_retryable_exception(_http_status_error(404)) is False


@pytest.mark.parametrize("code", ["exceeded_current_quota_error", "insufficient_quota", "billing_hard_limit_reached"])
def test_exhausted_provider_quota_is_not_a_transient_rate_limit(code):
    request = httpx.Request("POST", "https://api.example.test/v1/chat")
    body = {"error": {"type": code, "message": "Quota exhausted"}}
    response = httpx.Response(429, request=request, json=body)
    error = openai.RateLimitError("Quota exhausted", response=response, body=body)
    assert _is_retryable_exception(error) is False
    assert _is_retryable_exception(httpx.HTTPStatusError("Quota exhausted", request=request, response=response)) is False


def test_temporary_provider_rate_limit_still_retries():
    response = httpx.Response(429, request=httpx.Request("POST", "https://api.example.test"))
    error = openai.RateLimitError("Too many requests", response=response, body={"code": "rate_limit_exceeded"})
    assert _is_retryable_exception(error) is True


class _ScriptedModel:
    """Model returning a scripted sequence of raw outputs, recording prompts."""

    def __init__(self, outputs: list[str]) -> None:
        self._outputs = list(outputs)
        self.calls: list[Any] = []

    def invoke(self, messages):
        self.calls.append(messages)
        return self._outputs[min(len(self.calls) - 1, len(self._outputs) - 1)]


def _history_agent(model, *, attempts: int = 3, strict: bool = True) -> _DummyAgent:
    agent = object.__new__(_DummyAgent)
    agent._model = model
    agent._tools = []
    agent.exclude_think = True
    agent.jsonalize_output = True
    agent.strict_json_output = strict
    agent.json_retry_attempts = attempts
    agent._last_raw_output = None
    return agent


def test_invoke_with_history_feeds_parse_error_back_into_the_retry():
    model = _ScriptedModel(['```json\n{"ok": true}\n```', '{"ok": true}'])
    agent = _history_agent(model, attempts=3)

    assert agent.invoke_with_history([{"role": "user", "content": "Return JSON"}]) == {
        "ok": True
    }
    assert len(model.calls) == 2

    retry_messages = model.calls[1]
    assert len(retry_messages) == 3
    # The rejected output and the parse error are both handed back to the model.
    assert "```json" in retry_messages[1].content
    assert "could not be parsed as JSON" in retry_messages[2].content
    # Feedback is rebuilt from the original prompt, never stacked on itself.
    assert retry_messages[0].content == "Return JSON"


def test_invoke_with_history_last_attempt_falls_back_to_lenient_parsing():
    """A deterministic fenced response must not burn every attempt for nothing."""
    model = _ScriptedModel(['```json\n{"ok": true}\n```'])
    agent = _history_agent(model, attempts=2)

    assert agent.invoke_with_history([{"role": "user", "content": "Return JSON"}]) == {
        "ok": True
    }
    assert len(model.calls) == 2


def test_invoke_with_history_still_raises_on_unparsable_output():
    model = _ScriptedModel(["not json at all"])
    agent = _history_agent(model, attempts=2)

    with pytest.raises(json.JSONDecodeError):
        agent.invoke_with_history([{"role": "user", "content": "Return JSON"}])
    assert len(model.calls) == 2


def test_invoke_retries_with_repair_turn_and_lenient_final_attempt(monkeypatch):
    agent = object.__new__(_DummyAgent)
    agent._task_prompt = "Return JSON"
    agent.exclude_think = True
    agent.jsonalize_output = True
    agent.strict_json_output = True
    agent.json_retry_attempts = 2
    agent._last_raw_output = None

    prompts: list[dict] = []

    def fake_invoke_with_retry(prompt):
        prompts.append(prompt)
        return '```json\n{"ok": true}\n```'

    agent._invoke_with_retry = fake_invoke_with_retry

    assert agent.invoke({}) == {"ok": True}
    assert len(prompts) == 2

    retry_messages = prompts[1]["messages"]
    assert [msg["role"] for msg in retry_messages] == ["user", "assistant", "user"]
    assert "could not be parsed as JSON" in retry_messages[2]["content"]
    # The original prompt object is left untouched for the next rebuild.
    assert len(prompts[0]["messages"]) == 1


def test_invoke_with_history_empty_output_echo_is_never_an_empty_message():
    """kimi k3 can return empty visible content (reasoning burns the budget).

    The repair turn must not echo that as an empty assistant message: kimi
    rejects the next request with a 400 ("assistant must not be empty"),
    which killed the whole retry loop during the first real smoke run.
    """
    model = _ScriptedModel(["", '{"ok": true}'])
    agent = _history_agent(model, attempts=3)

    assert agent.invoke_with_history([{"role": "user", "content": "Return JSON"}]) == {
        "ok": True
    }
    assert len(model.calls) == 2

    echoed = model.calls[1][1]
    assert echoed.content.strip(), "empty assistant echo would 400 on kimi"
    assert "empty response" in echoed.content.lower()


def test_retry_predicate_distinguishes_malformed_stream_events_from_model_json():
    import json
    from openai._streaming import ServerSentEvent

    with pytest.raises(json.JSONDecodeError) as stream_error:
        ServerSentEvent(data='{"delta":"broken\ncontent"}').json()
    assert _is_retryable_exception(stream_error.value) is True

    with pytest.raises(json.JSONDecodeError) as content_error:
        json.loads('{"elements": [')
    assert _is_retryable_exception(content_error.value) is False


def test_retry_predicate_accepts_transient_stream_api_errors_without_status():
    request = httpx.Request("POST", "https://api.example.test/v1/chat")

    assert _is_retryable_exception(
        openai.APIError("Upstream service temporarily unavailable", request=request, body=None)
    ) is True
    assert _is_retryable_exception(
        openai.APIError("stream_timeout", request=request, body=None)
    ) is True
    assert _is_retryable_exception(
        openai.APIError("stream_read_error", request=request, body=None)
    ) is True
    assert _is_retryable_exception(
        openai.APIError("Invalid response payload", request=request, body=None)
    ) is False


def test_empty_provider_stream_retries_without_swallowing_application_value_errors():
    from langchain_core.language_models.chat_models import generate_from_stream

    with pytest.raises(ValueError, match="No generations found") as stream_error:
        generate_from_stream(iter([]))
    assert _is_retryable_exception(stream_error.value) is True
    assert _is_retryable_exception(ValueError("No generations found in stream.")) is False


# ── Retry budget: one transport layer, shared across repair turns ─────────

import evodesign.core.base_agent as base_agent_module
from evodesign.core.base_agent import LLMBudgetExceeded, llm_run_budget


class _FlakyModel:
    """Raises the scripted exceptions in order, then returns *final*."""

    def __init__(self, errors: list[BaseException], final: Any = '{"ok": true}') -> None:
        self.errors = list(errors)
        self.final = final
        self.calls = 0

    def invoke(self, messages):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return self.final


@pytest.fixture
def no_sleep(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr(base_agent_module, "_sleep", sleeps.append)
    return sleeps


def test_transient_errors_are_retried_once_per_call_not_per_layer(no_sleep):
    model = _FlakyModel([TimeoutError("t")] * 10)
    agent = _history_agent(model, attempts=5)
    agent.transport_attempts = 3

    with pytest.raises(TimeoutError):
        agent.invoke_with_history([{"role": "user", "content": "x"}])

    # 3 transport attempts in total — not 3 × JSON attempts × outer retries.
    assert model.calls == 3
    assert len(no_sleep) == 2


def test_json_repair_turns_share_the_transport_retry_allowance(no_sleep):
    outputs = iter(["not json", "still not json", '{"ok": true}'])

    class Model:
        calls = 0

        def invoke(self, messages):
            Model.calls += 1
            if Model.calls == 2:
                raise TimeoutError("blip")
            return next(outputs)

    agent = _history_agent(Model(), attempts=5)
    agent.transport_attempts = 2
    # attempt 1: non-JSON; attempt 2: timeout (uses the only retry) then
    # non-JSON; attempt 3: valid.
    assert agent.invoke_with_history([{"role": "user", "content": "x"}]) == {"ok": True}
    assert len(no_sleep) == 1


def test_permanent_http_errors_are_not_retried(no_sleep):
    model = _FlakyModel([_http_status_error(401)])
    agent = _history_agent(model)

    with pytest.raises(httpx.HTTPStatusError):
        agent.invoke_with_history([{"role": "user", "content": "x"}])
    assert model.calls == 1
    assert no_sleep == []


def test_call_deadline_fails_fast_instead_of_sleeping_past_it(no_sleep):
    model = _FlakyModel([TimeoutError("t")] * 10)
    agent = _history_agent(model)
    agent.call_deadline_seconds = 1  # shorter than the first 4s backoff

    with pytest.raises(LLMBudgetExceeded, match="deadline"):
        agent.invoke_with_history([{"role": "user", "content": "x"}])
    assert model.calls == 1
    assert no_sleep == []


def test_call_deadline_env_override(monkeypatch):
    monkeypatch.setenv(base_agent_module.CALL_DEADLINE_ENV, "42")
    assert base_agent_module.resolve_call_deadline_seconds() == 42.0
    monkeypatch.setenv(base_agent_module.CALL_DEADLINE_ENV, "0")
    assert base_agent_module.resolve_call_deadline_seconds() is None
    assert base_agent_module.resolve_call_deadline_seconds(5) == 5.0


def test_run_budget_caps_requests_across_calls(no_sleep):
    model = _FlakyModel([])
    agent = _history_agent(model)

    with llm_run_budget(max_calls=2):
        agent.invoke_with_history([{"role": "user", "content": "x"}])
        agent.invoke_with_history([{"role": "user", "content": "x"}])
        with pytest.raises(LLMBudgetExceeded, match="2 request"):
            agent.invoke_with_history([{"role": "user", "content": "x"}])
    assert model.calls == 2
    # Outside the context there is no cap.
    agent.invoke_with_history([{"role": "user", "content": "x"}])


def test_run_budget_reaches_self_consistency_worker_threads():
    from evodesign.agentic_system.common.self_consistency import sample_and_vote

    def invoke_fn(_input):
        base_agent_module.charge_llm_run_budget()
        return {"instantiation": {"k": 1}}

    with llm_run_budget(max_calls=2) as budget:
        sample_and_vote(
            invoke_fn, {}, n_samples=3, vote_key="k",
            unwrap_fn=lambda raw: ({}, raw["instantiation"]),
        )
    assert budget.calls == 2
