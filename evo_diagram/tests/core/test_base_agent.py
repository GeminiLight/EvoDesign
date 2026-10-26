from __future__ import annotations

import json
from typing import Any

import httpx


import openai
import pytest

from evo_diagram.core.base_agent import BaseAgent, _render_template
from evo_diagram.core.base_agent import _is_retryable_exception


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
