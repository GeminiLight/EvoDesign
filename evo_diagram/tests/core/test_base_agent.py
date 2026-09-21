from __future__ import annotations

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
