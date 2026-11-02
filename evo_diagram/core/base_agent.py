import json
import os
import re
import threading
import time
from abc import ABC, abstractmethod
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterator, Optional
import logging

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel

from evo_diagram.utils.llm_output import preprocess_response, get_text_from_response

logger = logging.getLogger(__name__)


class LLMResponseError(Exception):
    """Custom exception for malformed LLM responses."""
    pass


class LLMBudgetExceeded(RuntimeError):
    """An LLM call or workflow run exhausted its wall-clock or call budget.

    Deliberately not retryable: every retry layer must stop on it.
    """


# Exceptions that are safe to retry — transient network / API issues.
# Programming errors (KeyError, AttributeError, …) should NOT be retried.
_RETRYABLE_EXCEPTIONS = (
    LLMResponseError,
    ConnectionError,
    TimeoutError,
    OSError,
)
_HTTP_STATUS_ERROR_TYPES: tuple[type[BaseException], ...] = ()
_PROVIDER_STATUS_ERROR_TYPES: tuple[type[BaseException], ...] = ()
_PROVIDER_API_ERROR_TYPES: tuple[type[BaseException], ...] = ()
_TRANSIENT_API_ERROR_MARKERS = (
    "temporarily unavailable",
    "service unavailable",
    "stream_timeout",
    "stream timeout",
    "server overloaded",
    "overloaded",
    "rate limit",
    "try again later",
)

try:
    import httpx
    _HTTP_STATUS_ERROR_TYPES = (httpx.HTTPStatusError,)
except ImportError:
    pass

try:
    import openai
    _RETRYABLE_EXCEPTIONS = (*_RETRYABLE_EXCEPTIONS, openai.APITimeoutError)
    api_connection_error = getattr(openai, "APIConnectionError", None)
    if api_connection_error is not None:
        _RETRYABLE_EXCEPTIONS = (*_RETRYABLE_EXCEPTIONS, api_connection_error)
    _PROVIDER_STATUS_ERROR_TYPES = (
        *_PROVIDER_STATUS_ERROR_TYPES,
        openai.APIStatusError,
    )
    _PROVIDER_API_ERROR_TYPES = (
        *_PROVIDER_API_ERROR_TYPES,
        openai.APIError,
    )
except ImportError:
    pass

try:
    import anthropic
    _RETRYABLE_EXCEPTIONS = (*_RETRYABLE_EXCEPTIONS, anthropic.APITimeoutError)
    api_connection_error = getattr(anthropic, "APIConnectionError", None)
    if api_connection_error is not None:
        _RETRYABLE_EXCEPTIONS = (*_RETRYABLE_EXCEPTIONS, api_connection_error)
    _PROVIDER_STATUS_ERROR_TYPES = (
        *_PROVIDER_STATUS_ERROR_TYPES,
        anthropic.APIStatusError,
    )
    _PROVIDER_API_ERROR_TYPES = (
        *_PROVIDER_API_ERROR_TYPES,
        anthropic.APIError,
    )
except ImportError:
    pass


def _is_transient_status_code(status_code: int) -> bool:
    return status_code in {408, 409, 429} or status_code >= 500


def _status_code_from_exception(exc: BaseException) -> Optional[int]:
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        return status_code
    response = getattr(exc, "response", None)
    response_status = getattr(response, "status_code", None)
    return response_status if isinstance(response_status, int) else None


def _is_stream_transport_error(exc: BaseException) -> bool:
    """Distinguish broken provider events from invalid model-authored JSON."""
    if isinstance(exc, json.JSONDecodeError):
        traceback = exc.__traceback__
        while traceback is not None:
            if traceback.tb_frame.f_globals.get("__name__") == "openai._streaming":
                return True
            traceback = traceback.tb_next
        return False
    if isinstance(exc, ValueError) and str(exc) == "No generations found in stream.":
        traceback = exc.__traceback__
        while traceback is not None:
            frame = traceback.tb_frame
            if (
                frame.f_globals.get("__name__") == "langchain_core.language_models.chat_models"
                and frame.f_code.co_name == "generate_from_stream"
            ):
                return True
            traceback = traceback.tb_next
        return False
    return isinstance(exc, _PROVIDER_API_ERROR_TYPES) and any(
        marker in str(exc).lower()
        for marker in ("stream_read_error", "stream_timeout", "stream timeout")
    )


def _is_provider_quota_exhausted(exc: BaseException) -> bool:
    """A billing/window quota cannot recover within our short retry budget.

    Match structured provider codes, not arbitrary message text: ordinary 429
    throttling and unknown provider errors retain the existing retry policy.
    """
    if _status_code_from_exception(exc) != 429:
        return False
    body = getattr(exc, "body", None)
    if not isinstance(body, dict):
        response = getattr(exc, "response", None)
        try:
            body = response.json() if response is not None else None
        except (ValueError, RuntimeError):
            body = None
    if not isinstance(body, dict):
        return False
    error = body.get("error", body)
    if not isinstance(error, dict):
        return False
    exhausted_codes = {"exceeded_current_quota_error", "insufficient_quota", "billing_hard_limit_reached"}
    return any(isinstance(error.get(key), str) and error[key].lower() in exhausted_codes
               for key in ("code", "type"))


def _is_permanent_http_error(exc: BaseException) -> bool:
    """True for provider HTTP errors that outer retries cannot fix."""
    if _is_provider_quota_exhausted(exc):
        return True
    status_code = _status_code_from_exception(exc)
    if status_code is not None:
        return not _is_transient_status_code(status_code)

    cls_name = type(exc).__name__
    return cls_name in {
        "AuthenticationError",
        "BadRequestError",
        "NotFoundError",
        "PermissionDeniedError",
        "UnprocessableEntityError",
    }


def _is_retryable_exception(exc: BaseException) -> bool:
    """Retry only transient transport/provider failures."""
    if isinstance(exc, LLMBudgetExceeded):
        return False
    if _is_provider_quota_exhausted(exc):
        return False
    if _is_stream_transport_error(exc):
        return True
    if isinstance(exc, _HTTP_STATUS_ERROR_TYPES + _PROVIDER_STATUS_ERROR_TYPES):
        status_code = _status_code_from_exception(exc)
        return status_code is not None and _is_transient_status_code(status_code)
    if isinstance(exc, _PROVIDER_API_ERROR_TYPES):
        message = str(exc).lower()
        return any(marker in message for marker in _TRANSIENT_API_ERROR_MARKERS)
    return isinstance(exc, _RETRYABLE_EXCEPTIONS)


# ── Retry budget ────────────────────────────────────────────────────────
#
# BaseAgent owns the only transport-level retry layer: ``LLMFactory`` builds
# provider clients with ``max_retries=0`` by default so SDK retries never
# multiply with these. A logical call (``invoke`` / ``invoke_with_history``,
# including its JSON-repair turns) shares one retry allowance and one
# wall-clock deadline. A deadline is checked before every request and every
# backoff sleep; an in-flight request is bounded by the client ``timeout``.

DEFAULT_TRANSPORT_ATTEMPTS = 5
DEFAULT_CALL_DEADLINE_SECONDS = 1800.0
CALL_DEADLINE_ENV = "EVO_LLM_CALL_DEADLINE_SECONDS"
_BACKOFF_MIN_SECONDS = 4.0
_BACKOFF_MAX_SECONDS = 30.0


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def _backoff_seconds(retry_index: int) -> float:
    """Exponential backoff: 4s, 4s, 8s, 16s, 30s (cap)."""
    return min(_BACKOFF_MAX_SECONDS, max(_BACKOFF_MIN_SECONDS, 2.0 * (2 ** retry_index)))


def resolve_call_deadline_seconds(value: Any = None) -> Optional[float]:
    """Return the per-call deadline; ``<= 0`` disables it.

    Precedence: explicit *value*, then ``EVO_LLM_CALL_DEADLINE_SECONDS``, then
    ``DEFAULT_CALL_DEADLINE_SECONDS``.
    """
    if value is None:
        raw = os.environ.get(CALL_DEADLINE_ENV, "").strip()
        if raw:
            try:
                value = float(raw)
            except ValueError:
                logger.warning("Ignoring invalid %s=%r", CALL_DEADLINE_ENV, raw)
                value = None
    if value is None:
        value = DEFAULT_CALL_DEADLINE_SECONDS
    value = float(value)
    return value if value > 0 else None


@dataclass
class LLMRunBudget:
    """Optional cap on LLM requests and wall-clock time for one workflow run."""

    max_calls: Optional[int] = None
    deadline_seconds: Optional[float] = None
    started_at: float = field(default_factory=time.monotonic)
    calls: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def remaining_seconds(self) -> Optional[float]:
        if self.deadline_seconds is None:
            return None
        return self.deadline_seconds - (time.monotonic() - self.started_at)

    def check(self) -> None:
        remaining = self.remaining_seconds()
        if remaining is not None and remaining <= 0:
            raise LLMBudgetExceeded(
                f"LLM run deadline of {self.deadline_seconds:.0f}s exceeded "
                f"after {self.calls} request(s)"
            )
        if self.max_calls is not None and self.calls >= self.max_calls:
            raise LLMBudgetExceeded(
                f"LLM run budget of {self.max_calls} request(s) exhausted"
            )

    def charge(self) -> None:
        with self._lock:
            self.check()
            self.calls += 1


_RUN_BUDGET: ContextVar[Optional[LLMRunBudget]] = ContextVar("evo_llm_run_budget", default=None)


@contextmanager
def llm_run_budget(
    *, max_calls: Optional[int] = None, deadline_seconds: Optional[float] = None,
) -> Iterator[LLMRunBudget]:
    """Cap every BaseAgent request made inside this context (and threads that
    copy it, see ``common/self_consistency.py``)."""
    budget = LLMRunBudget(
        max_calls=max_calls if max_calls and max_calls > 0 else None,
        deadline_seconds=deadline_seconds if deadline_seconds and deadline_seconds > 0 else None,
    )
    token = _RUN_BUDGET.set(budget)
    try:
        yield budget
    finally:
        _RUN_BUDGET.reset(token)


RUN_MAX_CALLS_ENV = "EVO_LLM_RUN_MAX_CALLS"
RUN_DEADLINE_ENV = "EVO_LLM_RUN_DEADLINE_SECONDS"


def _env_number(name: str) -> Optional[float]:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        logger.warning("Ignoring invalid %s=%r", name, raw)
        return None
    return value if value > 0 else None


@contextmanager
def llm_run_budget_from_env() -> Iterator[LLMRunBudget]:
    """``llm_run_budget`` configured by ``EVO_LLM_RUN_MAX_CALLS`` and
    ``EVO_LLM_RUN_DEADLINE_SECONDS`` (both unset → unlimited, the default)."""
    max_calls = _env_number(RUN_MAX_CALLS_ENV)
    with llm_run_budget(
        max_calls=int(max_calls) if max_calls is not None else None,
        deadline_seconds=_env_number(RUN_DEADLINE_ENV),
    ) as budget:
        yield budget


def charge_llm_run_budget() -> None:
    """Count one provider request against the active run budget, if any.

    For callers that invoke a chat model directly instead of via BaseAgent.
    Raises ``LLMBudgetExceeded`` once the run budget is spent.
    """
    budget = _RUN_BUDGET.get()
    if budget is not None:
        budget.charge()


@dataclass
class _CallBudget:
    deadline_seconds: Optional[float]
    retries_left: int
    started_at: float = field(default_factory=time.monotonic)
    retries_used: int = 0

    @classmethod
    def start(cls, agent: "BaseAgent") -> "_CallBudget":
        attempts = max(1, int(getattr(agent, "transport_attempts", DEFAULT_TRANSPORT_ATTEMPTS)))
        return cls(
            deadline_seconds=resolve_call_deadline_seconds(
                getattr(agent, "call_deadline_seconds", None)
            ),
            retries_left=attempts - 1,
        )

    @classmethod
    @contextmanager
    def scope(cls, agent: "BaseAgent") -> Iterator["_CallBudget"]:
        budget = cls.start(agent)
        token = _CALL_BUDGET.set(budget)
        try:
            yield budget
        finally:
            _CALL_BUDGET.reset(token)

    def elapsed_seconds(self) -> float:
        return time.monotonic() - self.started_at

    def remaining_seconds(self) -> Optional[float]:
        candidates = []
        if self.deadline_seconds is not None:
            candidates.append(self.deadline_seconds - self.elapsed_seconds())
        run_budget = _RUN_BUDGET.get()
        if run_budget is not None:
            run_remaining = run_budget.remaining_seconds()
            if run_remaining is not None:
                candidates.append(run_remaining)
        return min(candidates) if candidates else None

    def check(self, *, charge: bool = False) -> None:
        """Fail fast once either deadline is spent; *charge* counts a request."""
        if self.deadline_seconds is not None and self.elapsed_seconds() >= self.deadline_seconds:
            raise LLMBudgetExceeded(
                f"LLM call deadline of {self.deadline_seconds:.0f}s exceeded "
                f"(set {CALL_DEADLINE_ENV} or call_deadline_seconds to change it)"
            )
        run_budget = _RUN_BUDGET.get()
        if run_budget is not None:
            if charge:
                run_budget.charge()
            else:
                run_budget.check()


_CALL_BUDGET: ContextVar[Optional[_CallBudget]] = ContextVar("evo_llm_call_budget", default=None)


valid_agent_arg_list = [
    "middleware",
    "response_format",
    "state_schema",
    "context_schema",
    "checkpointer",
    "store",
    "interrupt_before",
    "interrupt_after",
    "debug",
    "name",
    "cache"
]

_TEMPLATE_VAR_RE = re.compile(r"{{\s*([A-Za-z_][A-Za-z0-9_]*)\s*}}")


def _render_template(template: str, variables: Dict[str, Any]) -> str:
    """Replace ``{{key}}`` placeholders in *template* with values from *variables*.

    Replacement is single-pass: inserted values are not scanned for additional
    ``{{...}}`` placeholders. This keeps untrusted source text from expanding
    prompt-control placeholders such as ``{{runtime_directives}}``.
    """
    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in variables:
            return match.group(0)
        return str(variables[key])

    return _TEMPLATE_VAR_RE.sub(replace, template)


class BaseAgent(ABC):

    # Class-level defaults so partially constructed agents (tests use
    # ``object.__new__``) still get the standard retry budget.
    transport_attempts: int = DEFAULT_TRANSPORT_ATTEMPTS
    call_deadline_seconds: Optional[float] = None  # None → env/default

    def __init__(
            self,
            model: BaseChatModel,
            system_prompt: Optional[str] = None,
            task_prompt: Optional[str] = None,
            tools: Optional[list[Any]] = None,
            **kwargs
        ) -> None:
        """Initialize a base agent with JSON output and validation."""
        self._model = model
        self._system_prompt = system_prompt
        self._task_prompt = task_prompt
        self._tools = tools or []
        self._agent = create_agent(
            model=model,
            tools=self._tools,
            system_prompt=system_prompt,
            **{k: v for k, v in kwargs.items() if k in valid_agent_arg_list}
        )
        self.exclude_think = kwargs.get("exclude_think", True)
        self.jsonalize_output = kwargs.get("jsonalize_output", True)
        self.strict_json_output = kwargs.get("strict_json_output", False)
        # LLMs can occasionally return non-JSON text even when prompted for JSON.
        # Retry a few times before failing the whole workflow.
        self.json_retry_attempts = max(1, int(kwargs.get("json_retry_attempts", 5)))
        # Transport retries and the wall-clock deadline are shared by all
        # requests of one logical call, including the JSON-repair turns above.
        self.transport_attempts = max(
            1, int(kwargs.get("transport_attempts", DEFAULT_TRANSPORT_ATTEMPTS))
        )
        self.call_deadline_seconds = kwargs.get("call_deadline_seconds")
        # Last raw LLM response (before JSON parsing) — useful for debugging.
        self._last_raw_output: Optional[Any] = None

    def _build_prompt(self, variables: Dict[str, Any]) -> Dict[str, Any]:
        """Build chat messages for model call."""
        if "img_url" in variables:
            img_url = variables.get("img_url")
            task_prompt = _render_template(self._task_prompt, variables)
            prompt = {
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": task_prompt},
                            {"type": "image_url", "image_url": {"url": img_url}},
                        ],
                    }
                ]
            }
        else:
            task_prompt = _render_template(self._task_prompt, variables)
            prompt = {
                "messages": [
                    {"role": "user", "content": task_prompt}
                ]
            }
        return prompt

    def _call_model_once(self, call: Callable[[], Any]) -> Any:
        """Run one provider request and normalize malformed responses."""
        try:
            result = call()
        except TypeError as e:
            # "NoneType object is not iterable" — API returned malformed response
            error_msg = str(e)
            if "NoneType" in error_msg and "not iterable" in error_msg:
                logger.warning("API returned malformed response (choices=None): %s", e)
                raise LLMResponseError(f"API returned malformed response: {e}") from e
            raise
        if result is None:
            raise LLMResponseError("LLM returned None response")
        if isinstance(result, dict) and "error" in result:
            raise LLMResponseError(f"LLM returned error: {result['error']}")
        return result

    def _transport_call(self, call: Callable[[], Any]) -> Any:
        """The single transport-level retry layer for this agent.

        Transient failures (timeouts, connection errors, 408/409/429/5xx,
        broken stream events, malformed responses) are retried with
        exponential backoff. Permanent failures (auth, bad request, exhausted
        quota) and programming errors propagate immediately. The retry count
        is shared across every request made for one logical ``invoke`` /
        ``invoke_with_history`` call, so JSON-repair turns cannot multiply
        transport retries, and no attempt starts after the call deadline.
        """
        budget = _CALL_BUDGET.get() or _CallBudget.start(self)
        while True:
            budget.check(charge=True)
            try:
                return self._call_model_once(call)
            except Exception as exc:
                if not _is_retryable_exception(exc):
                    if not isinstance(exc, LLMBudgetExceeded):
                        logger.warning(
                            "LLM invocation failed (non-retryable): %s: %s",
                            type(exc).__name__, exc,
                        )
                    raise
                if budget.retries_left <= 0:
                    raise
                delay = _backoff_seconds(budget.retries_used)
                remaining = budget.remaining_seconds()
                if remaining is not None and remaining <= delay:
                    raise LLMBudgetExceeded(
                        f"LLM call deadline reached after {budget.elapsed_seconds():.0f}s "
                        f"while retrying {type(exc).__name__}: {exc}"
                    ) from exc
                budget.retries_left -= 1
                budget.retries_used += 1
                logger.warning(
                    "LLM invocation failed (transient; retry %s/%s in %.0fs): %s: %s",
                    budget.retries_used, budget.retries_used + budget.retries_left,
                    delay, type(exc).__name__, exc,
                )
                _sleep(delay)

    def _invoke_with_retry(self, input_prompt: dict) -> Any:
        """Invoke the agent through the shared transport retry layer."""
        return self._transport_call(lambda: self._agent.invoke(input_prompt))

    def invoke(self, input_dict: dict) -> Any:
        """Invoke the agent with the given input text."""
        with _CallBudget.scope(self):
            return self._invoke_parsed(input_dict)

    def _invoke_parsed(self, input_dict: dict) -> Any:
        input_prompt = self._build_prompt(input_dict)
        parse_attempts = self.json_retry_attempts if self.jsonalize_output else 1
        last_error: Optional[json.JSONDecodeError] = None
        strict = getattr(self, "strict_json_output", False)
        attempt_prompt = input_prompt
        budget = _CALL_BUDGET.get()

        for attempt in range(1, parse_attempts + 1):
            is_last_attempt = attempt == parse_attempts
            if budget is not None:
                budget.check()
            raw_output = self._invoke_with_retry(attempt_prompt)
            self._last_raw_output = raw_output
            try:
                return preprocess_response(
                    raw_output,
                    only_text=True,
                    exclude_think=self.exclude_think,
                    json_output=self.jsonalize_output,
                    # Last attempt gives up on the "response is exactly one JSON
                    # value" contract so a fenced or embedded payload is still
                    # recovered instead of burning the whole run.
                    strict_json_output=strict and not is_last_attempt,
                )
            except json.JSONDecodeError as e:
                last_error = e
                preview = self._preview_response(raw_output)
                logger.warning(
                    "LLM returned non-JSON output (attempt %s/%s), retrying. Error: %s | Preview: %s",
                    attempt,
                    parse_attempts,
                    e,
                    preview,
                )
                if is_last_attempt:
                    raise
                # Feed the parse failure back so the next sample is a correction
                # instead of an identical re-sample at the same temperature.
                attempt_prompt = {
                    **input_prompt,
                    "messages": [
                        *input_prompt.get("messages", []),
                        {
                            "role": "assistant",
                            "content": self._invalid_output_echo(raw_output),
                        },
                        {
                            "role": "user",
                            "content": self._json_repair_instruction(e),
                        },
                    ],
                }

        # Defensive fallback; loop should already return or raise.
        if last_error is not None:
            raise last_error
        raise LLMResponseError("Unexpected invoke state: no output and no parse error.")

    def invoke_with_history(
        self,
        messages: list,
        tools: Optional[list] = None,
    ) -> Any:
        """Invoke the LLM with a pre-built messages list (conversation mode).

        Unlike ``invoke``, this method calls the model directly (bypassing the
        LangGraph agent) so the caller has full control over the message list —
        including the system message.  This is used by the pipeline conversation
        mode where a single system message is shared across multiple turns.

        Transport retries and the call deadline are shared with the JSON-repair
        loop (see ``_transport_call``); the parse loop itself is not retried.

        Args:
            messages: List of dicts with ``role`` and ``content`` keys.
                Roles: ``system``, ``user``, ``assistant``.
            tools: Optional tool list; falls back to ``self._tools``.

        Returns:
            Preprocessed model output (same format as ``invoke``).
        """
        with _CallBudget.scope(self):
            return self._invoke_with_history_parsed(messages, tools)

    def _invoke_with_history_parsed(self, messages: list, tools: Optional[list]) -> Any:
        from langchain_core.messages import (
            SystemMessage, HumanMessage, AIMessage,
        )

        lc_messages = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                lc_messages.append(SystemMessage(content=content))
            elif role == "assistant":
                lc_messages.append(AIMessage(content=content))
            else:
                lc_messages.append(HumanMessage(content=content))

        effective_tools = tools if tools is not None else self._tools
        model = self._model
        if effective_tools:
            model = model.bind_tools(effective_tools)

        parse_attempts = self.json_retry_attempts if self.jsonalize_output else 1
        last_error: Optional[json.JSONDecodeError] = None
        strict = getattr(self, "strict_json_output", False)
        attempt_messages = lc_messages

        for attempt in range(1, parse_attempts + 1):
            is_last_attempt = attempt == parse_attempts
            request = attempt_messages
            raw_output = self._transport_call(lambda: model.invoke(request))
            self._last_raw_output = raw_output

            try:
                return preprocess_response(
                    raw_output,
                    only_text=True,
                    exclude_think=self.exclude_think,
                    json_output=self.jsonalize_output,
                    # See ``invoke``: the final attempt parses leniently.
                    strict_json_output=strict and not is_last_attempt,
                )
            except json.JSONDecodeError as e:
                last_error = e
                logger.warning(
                    "Non-JSON output (attempt %s/%s): %s",
                    attempt, parse_attempts, self._preview_response(raw_output),
                )
                if is_last_attempt:
                    raise
                attempt_messages = [
                    *lc_messages,
                    AIMessage(content=self._invalid_output_echo(raw_output)),
                    HumanMessage(content=self._json_repair_instruction(e)),
                ]

        if last_error is not None:
            raise last_error
        raise LLMResponseError("Unexpected invoke_with_history state.")

    @staticmethod
    def _json_repair_instruction(error: json.JSONDecodeError) -> str:
        """Correction turn appended after a failed JSON parse."""
        return (
            "Your previous response could not be parsed as JSON: "
            f"{error.msg} (line {error.lineno}, column {error.colno}). "
            "Resend the same result as a corrected, complete JSON value. "
            "Output raw JSON only: no ```json fences, no prose before or after, "
            "no trailing commas, and no comments. Escape any quotes, backslashes "
            "and newlines inside string values."
        )

    @classmethod
    def _invalid_output_echo(cls, raw_output: Any, max_len: int = 2000) -> str:
        """Return the rejected model output so the repair turn has context."""
        try:
            text = get_text_from_response(raw_output)
        except Exception:  # noqa: BLE001 - debugging aid must never raise
            text = str(raw_output)
        if not text.strip():
            # Reasoning models (e.g. kimi k3) can burn the whole token budget
            # on hidden thinking and return empty visible content. Echoing an
            # empty assistant turn makes OpenAI-compatible endpoints reject the
            # next request outright ("assistant must not be empty"), which
            # would mask the real failure and kill the retry loop.
            return "(empty response — no visible content was returned)"
        if len(text) > max_len:
            return text[:max_len] + "\n...(truncated)"
        return text

    @staticmethod
    def _preview_response(raw_output: Any, max_len: int = 400) -> str:
        """Return a single-line preview of raw model output for debugging."""
        try:
            text = get_text_from_response(raw_output)
        except Exception:
            text = str(raw_output)

        text = text.replace("\n", "\\n").strip()
        if len(text) > max_len:
            return text[:max_len] + "...(truncated)"
        return text

    def run_safe(self, state: Any) -> Any:
        """Run the agent safely, catching exceptions and updating state."""
        try:
            return self.run(state)
        except Exception as e:
            error_msg = f"{self.__class__.__name__} failed: {str(e)}"
            if hasattr(state, "errors") and isinstance(state.errors, list):
                state.errors.append(error_msg)
            if hasattr(state, "status"):
                state.status = "failed"
            return state

    @abstractmethod
    def run(self, state: Any) -> Any:
        """Execute the agent logic.  Subclasses must implement this."""
        ...
