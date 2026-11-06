"""LLM cassette: a substitute chat model that records or replays every call.

The Python pipeline creates every chat model through
``evodesign.core.llm_factory.LLMFactory.create`` → ``init_chat_model``.
``install(session)`` replaces that ``init_chat_model`` with a factory that
returns :class:`CassetteChatModel`, so every agent (Router, Structure, Styling,
Layout, Unified, verifier critic, refiner) talks to the cassette instead of a
provider. Nothing in ``evodesign/`` is edited.

Each call becomes one cassette entry (``cassette.jsonl``, one JSON per line)::

    {"index": 0,                      # call order inside the run (0-based)
     "caller": "StructureAgent",      # evodesign class on the call stack
     "role": "generator",             # LLMFactory role the model was created for
     "model_params": {...},           # init_chat_model kwargs (api_key redacted)
     "request": {"messages": [...],   # see message_record()
                 "invocation": {...}},# bound tools, tool_choice, stop, ...
     "response": {"content": "...", "tool_calls": []}
                 | {"error": {"type": "ConnectionError", "message": "...", "partial": "..."}},
     "source": "synthesized" | "synthesized-malformed" | "synthesized-error" | "real"}

Image parts (``image_url`` data URLs) are recorded as ``{"__image__": {...}}``
with the sha256 of the decoded bytes, size, decoded RGBA hash and the PNG file
saved next to the cassette (``images/<sha256>.<ext>``). The comparison rule is
documented in PHASE2_PLAN.md (appendix) and implemented in
test/harness/cassette.ts.

Record mode asks a *responder* (tools/cassette_synth.py) for each response.
Replay mode compares each request with entry N (JSON path diff) and returns the
recorded response; a mismatch raises :class:`CassetteMismatch`, a
``BaseException`` so the agents' ``except Exception`` retry loops cannot
swallow it.
"""
from __future__ import annotations

import base64
import hashlib
import inspect
import io
import json
import pathlib
import threading
from typing import Any, Callable, Dict, List, Optional

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool

REDACTED = "<redacted>"
# init_chat_model kwargs that never reach a fixture (secrets / transport only).
_SECRET_PARAMS = {"api_key"}

_ERROR_TYPES = {
    "ConnectionError": ConnectionError,
    "TimeoutError": TimeoutError,
    "ValueError": ValueError,
}


class CassetteMismatch(BaseException):
    """Replay request differs from the recorded one (or the cassette ran out)."""


# ── request normalization ───────────────────────────────────────────────


def json_diff(expected: Any, actual: Any, path: str = "$", limit: int = 8, out: Optional[List[str]] = None) -> List[str]:
    """Exact structural diff with JSON paths (same rule as test/harness/cassette.ts)."""
    out = [] if out is None else out
    if len(out) >= limit:
        return out
    if isinstance(expected, dict) and isinstance(actual, dict):
        for key in expected:
            if key not in actual:
                out.append(f"{path}.{key}: missing (expected {_short(expected[key])})")
            else:
                json_diff(expected[key], actual[key], f"{path}.{key}", limit, out)
        for key in actual:
            if key not in expected:
                out.append(f"{path}.{key}: unexpected {_short(actual[key])}")
        return out
    if isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            out.append(f"{path}: length {len(expected)} != {len(actual)}")
        for index, (left, right) in enumerate(zip(expected, actual)):
            json_diff(left, right, f"{path}[{index}]", limit, out)
        return out
    if type(expected) is not type(actual) and not (
        isinstance(expected, (int, float)) and isinstance(actual, (int, float))
        and not isinstance(expected, bool) and not isinstance(actual, bool)
    ):
        out.append(f"{path}: expected {_short(expected)}, got {_short(actual)}")
    elif expected != actual:
        if isinstance(expected, str) and isinstance(actual, str):
            index = next((i for i, (a, b) in enumerate(zip(expected, actual)) if a != b), min(len(expected), len(actual)))
            out.append(
                f"{path}: strings differ at char {index}: expected {_short(expected[max(0, index - 20):index + 40])}, "
                f"got {_short(actual[max(0, index - 20):index + 40])}"
            )
        else:
            out.append(f"{path}: expected {_short(expected)}, got {_short(actual)}")
    return out


def _short(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= 120 else text[:117] + "..."


class ImageStore:
    """Decodes data-URL image parts into references and saves the bytes."""

    def __init__(self, directory: Optional[pathlib.Path]) -> None:
        self.directory = directory

    def reference(self, url: str) -> Any:
        if not isinstance(url, str) or not url.startswith("data:") or ";base64," not in url:
            return url
        header, payload = url.split(",", 1)
        mime = header[len("data:"):].split(";", 1)[0]
        raw = base64.b64decode(payload)
        digest = hashlib.sha256(raw).hexdigest()
        ref: Dict[str, Any] = {"mime": mime, "sha256": digest, "bytes": len(raw)}
        try:
            from PIL import Image

            with Image.open(io.BytesIO(raw)) as image:
                ref["width"], ref["height"] = image.size
                ref["rgba_sha256"] = hashlib.sha256(image.convert("RGBA").tobytes()).hexdigest()
        except Exception:  # noqa: BLE001 - non-image payloads keep the byte hash only
            pass
        ext = {"image/png": "png", "image/jpeg": "jpg", "image/svg+xml": "svg"}.get(mime, "bin")
        ref["file"] = f"images/{digest}.{ext}"
        if self.directory is not None:
            target = self.directory / ref["file"]
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)
        return {"__image__": ref}


def content_record(content: Any, images: ImageStore) -> Any:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "image_url":
                image_url = part.get("image_url")
                if isinstance(image_url, dict):
                    image_url = {**image_url, "url": images.reference(image_url.get("url"))}
                else:
                    image_url = images.reference(image_url)
                parts.append({**part, "image_url": image_url})
            else:
                parts.append(part)
        return parts
    return content


def message_record(message: BaseMessage, images: ImageStore) -> Dict[str, Any]:
    """Role + content parts verbatim; tool-call fields only when present."""
    record: Dict[str, Any] = {"type": message.type, "content": content_record(message.content, images)}
    tool_calls = getattr(message, "tool_calls", None)
    if tool_calls:
        record["tool_calls"] = [{"name": c.get("name"), "args": c.get("args"), "id": c.get("id")} for c in tool_calls]
    if message.type == "tool":
        record["tool_call_id"] = getattr(message, "tool_call_id", None)
    if getattr(message, "name", None):
        record["name"] = message.name
    return record


def sanitize_params(params: Dict[str, Any]) -> Dict[str, Any]:
    clean = {}
    for key, value in params.items():
        if key in _SECRET_PARAMS:
            clean[key] = REDACTED
        elif callable(value):
            clean[key] = f"<callable {getattr(value, '__name__', type(value).__name__)}>"
        else:
            clean[key] = json.loads(json.dumps(value, default=str))
    return clean


def invocation_record(stop: Optional[List[str]], kwargs: Dict[str, Any]) -> Dict[str, Any]:
    record: Dict[str, Any] = {}
    if stop is not None:
        record["stop"] = list(stop)
    for key in sorted(kwargs):
        if key == "tools" and isinstance(kwargs[key], list) and not kwargs[key]:
            continue  # an empty tool list is not sent to the provider
        record[key] = json.loads(json.dumps(kwargs[key], default=str))
    return record


# ── caller attribution ─────────────────────────────────────────────────


def find_caller() -> str:
    """Name of the nearest evodesign object on the stack (agent class)."""
    frame = inspect.currentframe()
    try:
        while frame is not None:
            candidate = frame.f_locals.get("self")
            if candidate is not None:
                module = type(candidate).__module__ or ""
                if module.startswith("evodesign") and not isinstance(candidate, CassetteChatModel):
                    return type(candidate).__name__
            frame = frame.f_back
    finally:
        del frame
    return "<unknown>"


# ── session ─────────────────────────────────────────────────────────────


Responder = Callable[[Dict[str, Any]], Dict[str, Any]]


class CassetteSession:
    """One run's cassette: records (responder) or replays (entries)."""

    def __init__(
        self,
        directory: Optional[pathlib.Path],
        *,
        mode: str,
        responder: Optional[Responder] = None,
        entries: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        if mode not in {"record", "replay"}:
            raise ValueError(mode)
        self.mode = mode
        self.directory = directory
        self.responder = responder
        self.recorded = list(entries or [])
        self.entries: List[Dict[str, Any]] = []
        self.mismatch: Optional[Dict[str, Any]] = None
        self.images = ImageStore(directory)
        self._lock = threading.Lock()

    @classmethod
    def load(cls, directory: pathlib.Path) -> "CassetteSession":
        lines = (directory / "cassette.jsonl").read_text(encoding="utf-8").splitlines()
        return cls(None, mode="replay", entries=[json.loads(line) for line in lines if line.strip()])

    def call(self, *, caller: str, role: Optional[str], params: Dict[str, Any], request: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            index = len(self.entries)
            entry: Dict[str, Any] = {
                "index": index, "caller": caller, "role": role,
                "model_params": params, "request": request,
            }
            if self.mode == "replay":
                if index >= len(self.recorded):
                    self.mismatch = {"call": index, "diffs": [f"call {index}: cassette has only {len(self.recorded)} entries"]}
                    raise CassetteMismatch(self.mismatch["diffs"][0])
                expected = self.recorded[index]
                diffs = json_diff(
                    {k: expected.get(k) for k in ("caller", "role", "model_params", "request")},
                    {k: entry[k] for k in ("caller", "role", "model_params", "request")},
                )
                if diffs:
                    self.mismatch = {"call": index, "diffs": diffs}
                    raise CassetteMismatch(f"LLM call {index} differs from cassette: " + "; ".join(diffs))
                entry["response"] = expected["response"]
                entry["source"] = expected.get("source")
                if "note" in expected:
                    entry["note"] = expected["note"]
            else:
                assert self.responder is not None
                answer = self.responder(entry)
                entry["response"] = answer["response"]
                entry["source"] = answer.get("source", "synthesized")
                if answer.get("note"):
                    entry["note"] = answer["note"]
            self.entries.append(entry)
            return entry

    def write(self, directory: pathlib.Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        with open(directory / "cassette.jsonl", "w", encoding="utf-8") as handle:
            for entry in self.entries:
                handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=False) + "\n")


_SESSION: Optional[CassetteSession] = None
_ROLE = threading.local()


def active_session() -> CassetteSession:
    if _SESSION is None:
        raise RuntimeError("no cassette session installed")
    return _SESSION


# ── the substitute model ────────────────────────────────────────────────


class CassetteChatModel(BaseChatModel):
    """BaseChatModel that answers from the active cassette session."""

    role: Optional[str] = None
    params: Dict[str, Any] = {}

    @property
    def _llm_type(self) -> str:
        return "evodesign-cassette"

    @property
    def _identifying_params(self) -> Dict[str, Any]:
        return {"role": self.role, **self.params}

    def bind_tools(self, tools: Any, *, tool_choice: Any = None, **kwargs: Any):  # type: ignore[override]
        formatted = [convert_to_openai_tool(tool) for tool in tools]
        if tool_choice is not None:
            kwargs["tool_choice"] = tool_choice
        return self.bind(tools=formatted, **kwargs)

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        session = active_session()
        request = {
            "messages": [message_record(message, session.images) for message in messages],
            "invocation": invocation_record(stop, kwargs),
        }
        entry = session.call(caller=find_caller(), role=self.role, params=self.params, request=request)
        response = entry["response"]
        if "error" in response:
            error = response["error"]
            partial = error.get("partial") or ""
            if partial and run_manager is not None:
                run_manager.on_llm_new_token(partial)
            raise _ERROR_TYPES[error["type"]](error.get("message", ""))
        tool_calls = [
            {"name": call["name"], "args": call.get("args") or {}, "id": call.get("id"), "type": "tool_call"}
            for call in response.get("tool_calls") or []
        ]
        message = AIMessage(content=response.get("content", ""), tool_calls=tool_calls, id=f"cassette-{entry['index']}")
        return ChatResult(generations=[ChatGeneration(message=message)])


def _fake_init_chat_model(**config_kwargs: Any) -> CassetteChatModel:
    role = getattr(_ROLE, "value", None)
    return CassetteChatModel(role=role, params=sanitize_params(config_kwargs))


def install(session: CassetteSession) -> None:
    """Route every LLMFactory model through the cassette (process-wide)."""
    global _SESSION
    _SESSION = session
    import evodesign.core.llm_factory as llm_factory

    if getattr(llm_factory, "_cassette_installed", False):
        return
    llm_factory.init_chat_model = _fake_init_chat_model
    factory = llm_factory.LLMFactory
    original_for_role = factory.create_for_role.__func__

    def create_for_role(cls, role: str, **overrides: Any):
        previous = getattr(_ROLE, "value", None)
        _ROLE.value = role
        try:
            return original_for_role(cls, role, **overrides)
        finally:
            _ROLE.value = previous

    factory.create_for_role = classmethod(create_for_role)
    llm_factory._cassette_installed = True
