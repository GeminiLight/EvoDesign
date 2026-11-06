"""WP30: record the HTTP requests Python ``langchain_openai`` sends (ground truth).

For every case in ``test/models/http_cases.json`` this builds the model with
the production ``LLMFactory.create(**factory)`` and performs the case's call.
An ``httpx.MockTransport`` (passed as ``http_client``, which only replaces the
transport) captures method, URL, headers and JSON body; no network traffic.
Retry scenarios (``test/models/retry_cases.json``) run the production
``BaseAgent._transport_call`` against scripted provider failures and record
the request count, the outcome and the exception classification.

Usage (repo root):
    PYTHONPATH=. .venv/bin/python packages/render-engine/tools/wp30/record_http.py [out.json]
Default output: packages/render-engine/test/models/http_parity_py.json
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

for _k in list(os.environ):
    if _k.startswith(("OPENAI", "LLM_", "ANTHROPIC", "NVIDIA", "EVO_LLM")):
        del os.environ[_k]

import httpx  # noqa: E402
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage  # noqa: E402

from evodesign.core import base_agent as ba  # noqa: E402
from evodesign.core.llm_factory import LLMFactory  # noqa: E402

HERE = Path(__file__).resolve().parent
PKG = HERE.parent.parent
IMG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
TOOL = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Get the weather for a city",
        "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
    },
}

SSE_OK = (
    b'data: {"id":"x","object":"chat.completion.chunk","created":1,"model":"m","choices":[{"index":0,"delta":{"role":"assistant","content":"ok"},"finish_reason":null}]}\n\n'
    b'data: {"id":"x","object":"chat.completion.chunk","created":1,"model":"m","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\n'
    b"data: [DONE]\n\n"
)
JSON_OK = {"id": "x", "object": "chat.completion", "created": 1, "model": "m",
           "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}]}


def _ok_response(body: dict) -> httpx.Response:
    if body.get("stream"):
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=SSE_OK)
    return httpx.Response(200, json=JSON_OK)


def messages_for(call: str):
    if call in ("vision",):
        return [SystemMessage(content="sys 中文"), HumanMessage(content=[
            {"type": "text", "text": "hi"}, {"type": "image_url", "image_url": {"url": IMG, "detail": "high"}}])]
    if call in ("text", "json_mode"):
        return [SystemMessage(content="Return JSON only."), HumanMessage(content="只要 JSON：{\"a\": 1}")]
    if call == "history":
        return [SystemMessage(content="sys"), HumanMessage(content="first"), AIMessage(content='{"a": 1'),
                HumanMessage(content="Your previous response could not be parsed as JSON.")]
    if call in ("tools", "tool_choice_named"):
        return [HumanMessage(content="Weather in Paris?")]
    if call == "tool_roundtrip":
        return [HumanMessage(content="Weather in Paris?"),
                AIMessage(content="", tool_calls=[{"id": "call_1", "name": "get_weather", "args": {"city": "Paris"}}]),
                ToolMessage(content="sunny", tool_call_id="call_1"),
                HumanMessage(content="thanks")]
    raise ValueError(call)


def perform(model, call: str):
    if call in ("vision", "text", "history"):
        return model.invoke(messages_for(call))
    if call == "tools" or call == "tool_roundtrip":
        return model.bind_tools([TOOL]).invoke(messages_for(call))
    if call == "tool_choice_named":
        return model.bind_tools([TOOL], tool_choice="get_weather").invoke(messages_for(call))
    if call == "json_mode":
        return model.bind(response_format={"type": "json_object"}).invoke(messages_for(call))
    if call == "agent":
        from langchain.agents import create_agent
        agent = create_agent(model=model, tools=[], system_prompt="sys 中文")
        return agent.invoke({"messages": [{"role": "user", "content": [
            {"type": "text", "text": "hi"}, {"type": "image_url", "image_url": {"url": IMG}}]}]})
    raise ValueError(call)


def record_requests(cases):
    out = []
    for case in cases:
        captured = []

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content or b"{}")
            captured.append({
                "method": request.method,
                "url": str(request.url),
                "headers": {k.lower(): v for k, v in request.headers.items()},
                "body": body,
            })
            return _ok_response(body)

        factory = dict(case["factory"])
        model = LLMFactory.create(http_client=httpx.Client(transport=httpx.MockTransport(handler)), **factory)
        perform(model, case["call"])
        out.append({"tag": case["tag"], "requests": captured})
    return out


# ── retry scenarios ─────────────────────────────────────────────────────

def _error(status: int, payload: dict) -> httpx.Response:
    return httpx.Response(status, json=payload)


def scripted(scenario: str, body: dict) -> httpx.Response:
    """One provider response for *scenario* (raise = transport-level failure)."""
    stream = bool(body.get("stream"))
    if scenario == "ok":
        return _ok_response(body)
    if scenario == "s429q":
        return _error(429, {"error": {"message": "You exceeded your current quota", "type": "insufficient_quota", "code": "insufficient_quota"}})
    if scenario == "s429":
        return _error(429, {"error": {"message": "Rate limit reached", "type": "requests", "code": "rate_limit_exceeded"}})
    if scenario == "s503":
        return _error(503, {"error": {"message": "Service unavailable", "type": "server_error"}})
    if scenario == "s500":
        return _error(500, {"error": {"message": "overloaded"}})
    if scenario == "s502_html":
        return httpx.Response(502, headers={"content-type": "text/html"}, content=b"<html>bad gateway</html>")
    if scenario == "s408":
        return _error(408, {"error": {"message": "request timeout"}})
    if scenario == "s409":
        return _error(409, {"error": {"message": "conflict"}})
    if scenario == "s401":
        return _error(401, {"error": {"message": "bad key", "type": "invalid_request_error", "code": "invalid_api_key"}})
    if scenario == "s403":
        return _error(403, {"error": {"message": "forbidden"}})
    if scenario == "s400":
        return _error(400, {"error": {"message": "bad request", "type": "invalid_request_error"}})
    if scenario == "s404":
        return _error(404, {"error": {"message": "no model", "type": "invalid_request_error"}})
    if scenario == "s422":
        return _error(422, {"error": {"message": "unprocessable"}})
    if scenario == "timeout":
        raise httpx.ReadTimeout("timed out", request=None)
    if scenario == "connect":
        raise httpx.ConnectError("[Errno 61] Connection refused", request=None)
    if scenario == "empty_stream":
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=b"data: [DONE]\n\n")
    if scenario == "bad_sse":
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=(
            b'data: {"id":"x","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"content":"hi"}}]}\n\n'
            b"data: {not json\n\n"))
    if scenario == "error_in_stream":
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=(
            b'data: {"error":{"message":"stream_read_error: upstream closed","type":"server_error"}}\n\n'))
    if scenario == "null_choices":
        if stream:
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=(
                b'data: {"id":"x","object":"chat.completion.chunk","created":1,"model":"m","choices":null}\n\ndata: [DONE]\n\n'))
        return httpx.Response(200, json={"id": "x", "object": "chat.completion", "created": 1, "model": "m", "choices": None})
    raise ValueError(scenario)


class _Agent(ba.BaseAgent):
    def run(self, state):  # pragma: no cover - abstract stub
        raise NotImplementedError


def record_retries(cases):
    out = []
    original_sleep = ba._sleep
    sleeps: list = []
    ba._sleep = lambda seconds: sleeps.append(seconds)
    try:
        for case in cases:
            sleeps.clear()
            sequence = list(case["sequence"])
            requests = []

            def handler(request: httpx.Request) -> httpx.Response:
                body = json.loads(request.content or b"{}")
                index = len(requests)
                requests.append(index)
                scenario = sequence[min(index, len(sequence) - 1)]
                return scripted(scenario, body)

            model = LLMFactory.create(
                http_client=httpx.Client(transport=httpx.MockTransport(handler)),
                model="m", model_provider="openai", api_key="k-test", base_url="https://llm.example.test/v1",
                **case.get("factory", {}),
            )
            agent = object.__new__(_Agent)
            agent.transport_attempts = case.get("transport_attempts", ba.DEFAULT_TRANSPORT_ATTEMPTS)
            agent.call_deadline_seconds = None
            record = {"tag": case["tag"]}
            try:
                result = agent._transport_call(lambda: model.invoke("hi"))
                record["outcome"] = {"ok": True, "content": result.content}
            except BaseException as exc:  # noqa: BLE001
                record["outcome"] = {
                    "ok": False,
                    "type": type(exc).__name__,
                    "retryable": ba._is_retryable_exception(exc),
                    "permanent": ba._is_permanent_http_error(exc),
                    "quota": ba._is_provider_quota_exhausted(exc),
                    "status": ba._status_code_from_exception(exc),
                }
            record["requests"] = len(requests)
            record["sleeps"] = list(sleeps)
            out.append(record)
    finally:
        ba._sleep = original_sleep
    return out


def main():
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else PKG / "test" / "models" / "http_parity_py.json"
    cases = json.loads((PKG / "test" / "models" / "http_cases.json").read_text())
    retry_cases = json.loads((PKG / "test" / "models" / "retry_cases.json").read_text())
    import langchain_openai, openai, langchain_core  # noqa: E401
    from importlib.metadata import version
    data = {
        "versions": {"langchain-openai": version("langchain-openai"), "openai": openai.__version__,
                     "langchain-core": langchain_core.__version__, "langchain": version("langchain")},
        "requests": record_requests(cases),
        "retries": record_retries(retry_cases),
    }
    target.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n")
    print(f"wrote {target}: {len(data['requests'])} request cases, {len(data['retries'])} retry cases")


if __name__ == "__main__":
    main()
