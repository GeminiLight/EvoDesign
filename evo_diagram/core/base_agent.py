import json
import re
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
import logging

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

from evo_diagram.utils.llm_output import preprocess_response, get_text_from_response

logger = logging.getLogger(__name__)


class LLMResponseError(Exception):
    """Custom exception for malformed LLM responses."""
    pass


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


def _is_retryable_exception(exc: BaseException) -> bool:
    """Retry only transient transport/provider failures."""
    if isinstance(exc, _HTTP_STATUS_ERROR_TYPES + _PROVIDER_STATUS_ERROR_TYPES):
        status_code = _status_code_from_exception(exc)
        return status_code is not None and _is_transient_status_code(status_code)
    return isinstance(exc, _RETRYABLE_EXCEPTIONS)


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

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=2, min=4, max=30),
        retry=retry_if_exception(_is_retryable_exception),
        reraise=True
    )
    def _invoke_with_retry(self, input_prompt: dict) -> Any:
        """Internal method to invoke agent with retry logic.

        Only retries on transient failures (network timeouts, API errors,
        malformed responses).  Programming errors propagate immediately.
        """
        try:
            result = self._agent.invoke(input_prompt)
            if result is None:
                raise LLMResponseError("LLM returned None response")
            if isinstance(result, dict) and "error" in result:
                raise LLMResponseError(f"LLM returned error: {result['error']}")
            return result
        except TypeError as e:
            # "NoneType object is not iterable" — API returned malformed response
            error_msg = str(e)
            if "NoneType" in error_msg and "not iterable" in error_msg:
                logger.warning(f"API returned malformed response (choices=None), retrying... Error: {e}")
                raise LLMResponseError(f"API returned malformed response: {e}") from e
            raise
        except _RETRYABLE_EXCEPTIONS:
            raise
        except Exception as e:
            logger.warning(f"LLM invocation failed (non-retryable): {type(e).__name__}: {e}")
            raise

    def invoke(self, input_dict: dict) -> Any:
        """Invoke the agent with the given input text."""
        input_prompt = self._build_prompt(input_dict)
        parse_attempts = self.json_retry_attempts if self.jsonalize_output else 1
        last_error: Optional[json.JSONDecodeError] = None

        for attempt in range(1, parse_attempts + 1):
            raw_output = self._invoke_with_retry(input_prompt)
            self._last_raw_output = raw_output
            try:
                return preprocess_response(
                    raw_output,
                    only_text=True,
                    exclude_think=self.exclude_think,
                    json_output=self.jsonalize_output,
                    strict_json_output=getattr(self, "strict_json_output", False),
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
                if attempt == parse_attempts:
                    raise

        # Defensive fallback; loop should already return or raise.
        if last_error is not None:
            raise last_error
        raise LLMResponseError("Unexpected invoke state: no output and no parse error.")

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=2, min=4, max=30),
        retry=retry_if_exception(_is_retryable_exception),
        reraise=True,
    )
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

        Args:
            messages: List of dicts with ``role`` and ``content`` keys.
                Roles: ``system``, ``user``, ``assistant``.
            tools: Optional tool list; falls back to ``self._tools``.

        Returns:
            Preprocessed model output (same format as ``invoke``).
        """
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

        for attempt in range(1, parse_attempts + 1):
            try:
                raw_output = model.invoke(lc_messages)
                self._last_raw_output = raw_output
                if raw_output is None:
                    raise LLMResponseError("LLM returned None response")
            except TypeError as e:
                if "NoneType" in str(e) and "not iterable" in str(e):
                    raise LLMResponseError(f"Malformed response: {e}") from e
                raise

            try:
                return preprocess_response(
                    raw_output,
                    only_text=True,
                    exclude_think=self.exclude_think,
                    json_output=self.jsonalize_output,
                    strict_json_output=getattr(self, "strict_json_output", False),
                )
            except json.JSONDecodeError as e:
                last_error = e
                logger.warning(
                    "Non-JSON output (attempt %s/%s): %s",
                    attempt, parse_attempts, self._preview_response(raw_output),
                )
                if attempt == parse_attempts:
                    raise

        if last_error is not None:
            raise last_error
        raise LLMResponseError("Unexpected invoke_with_history state.")

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
