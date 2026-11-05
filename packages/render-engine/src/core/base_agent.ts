// Ported from evodesign/core/base_agent.py — keep in sync.
// server-only (AsyncLocalStorage for the ContextVar budgets; LangChain.js)
//
// Translation notes
// -----------------
// * Python's synchronous ``invoke``/``invoke_with_history`` are ``async``;
//   the call order (and therefore the cassette order) is unchanged.
// * ``ContextVar`` → ``AsyncLocalStorage``; context managers
//   (``llm_run_budget``, ``_CallBudget.scope``) take the body as a callback.
// * ``time.monotonic``/``time.sleep`` go through ``_monotonic``/``_sleep``,
//   which tests may replace with ``_set_clock``.
// * ``create_agent(model, tools, system_prompt=str)`` → ``createAgent`` with
//   ``systemPrompt: new SystemMessage(str)`` (a plain string would become a
//   list of content parts and differ from Python's request).
// * Exception classification: Python ``isinstance`` checks against builtin,
//   httpx, openai and anthropic classes become checks of the error's class
//   names (prototype chain), ``status``/``status_code`` and Node socket error
//   codes; see ``_class_names``.

import { AsyncLocalStorage } from 'node:async_hooks';
import type { BaseChatModel } from '@langchain/core/language_models/chat_models';
import { AIMessage, HumanMessage, SystemMessage, type BaseMessage } from '@langchain/core/messages';
import { createAgent } from 'langchain';
import { RuntimeError } from '../py/errors.ts';
import { getEnv } from '../py/env.ts';
import { getLogger } from '../py/logging.ts';
import { pyFloatParse } from '../py/number.ts';
import { cpLen, cpSlice, pyStr, pyStrip } from '../py/str.ts';
import { isDict } from '../py/truthy.ts';
import { PyJSONDecodeError } from '../py/json_decoder.ts';
import { get_text_from_response, preprocess_response } from '../utils/llm_output.ts';

const logger = getLogger('evodesign.core.base_agent');

/** Custom exception for malformed LLM responses. */
export class LLMResponseError extends Error {
  constructor(message = '') {
    super(message);
    this.name = 'LLMResponseError';
  }
}

/**
 * An LLM call or workflow run exhausted its wall-clock or call budget.
 *
 * Deliberately not retryable: every retry layer must stop on it.
 */
export class LLMBudgetExceeded extends RuntimeError {
  constructor(message = '') {
    super(message);
    this.name = 'LLMBudgetExceeded';
  }
}

// ── exception classification ────────────────────────────────────────────

/** Class names along the prototype chain (``type(exc).__mro__`` names). */
export function _class_names(exc: unknown): string[] {
  const names: string[] = [];
  if (exc === null || typeof exc !== 'object') return names;
  let proto = Object.getPrototypeOf(exc);
  while (proto && proto !== Object.prototype) {
    const name = proto.constructor?.name;
    if (name) names.push(name);
    proto = Object.getPrototypeOf(proto);
  }
  const own = (exc as { name?: unknown }).name;
  if (typeof own === 'string' && !names.includes(own)) names.unshift(own);
  return names;
}

// Exceptions that are safe to retry — transient network / API issues.
// Builtin LLMResponseError/ConnectionError/TimeoutError/OSError (and OSError
// subclasses), openai/anthropic APITimeoutError and APIConnectionError.
export const _RETRYABLE_EXCEPTIONS = new Set([
  'LLMResponseError',
  'ConnectionError',
  'TimeoutError',
  'OSError',
  // OSError subclasses
  'BrokenPipeError', 'ConnectionAbortedError', 'ConnectionRefusedError', 'ConnectionResetError',
  'FileExistsError', 'FileNotFoundError', 'InterruptedError', 'IsADirectoryError', 'NotADirectoryError',
  'PermissionError', 'ProcessLookupError', 'BlockingIOError', 'ChildProcessError',
  // provider SDKs
  'APITimeoutError', 'APIConnectionError', 'APIConnectionTimeoutError',
]);
// Node socket errors are OSError in Python terms.
const _OS_ERROR_CODES = new Set(['ECONNRESET', 'ECONNREFUSED', 'ECONNABORTED', 'ETIMEDOUT', 'EPIPE', 'ENOTFOUND', 'EAI_AGAIN', 'EHOSTUNREACH', 'ENETUNREACH', 'UND_ERR_SOCKET', 'UND_ERR_CONNECT_TIMEOUT', 'UND_ERR_HEADERS_TIMEOUT', 'UND_ERR_BODY_TIMEOUT']);
// httpx.HTTPStatusError.
export const _HTTP_STATUS_ERROR_TYPES = new Set(['HTTPStatusError']);
// openai/anthropic APIStatusError and its subclasses (openai-python's list:
// APIStatusError, AuthenticationError, BadRequestError, ConflictError,
// InternalServerError, NotFoundError, OAuthError, PermissionDeniedError,
// RateLimitError, UnprocessableEntityError). openai-node has no APIStatusError
// class: these subclass APIError directly, and a status it does not map is a
// plain APIError carrying ``status`` -- see _is_retryable_exception.
export const _PROVIDER_STATUS_ERROR_TYPES = new Set([
  'APIStatusError', 'AuthenticationError', 'BadRequestError', 'ConflictError', 'InternalServerError',
  'NotFoundError', 'OAuthError', 'PermissionDeniedError', 'RateLimitError', 'UnprocessableEntityError',
]);
// openai/anthropic APIError (base of the status and connection errors).
export const _PROVIDER_API_ERROR_TYPES = new Set(['APIError', 'APIStatusError', 'APIConnectionError', 'APIConnectionTimeoutError', 'APITimeoutError', 'APIUserAbortError']);
export const _TRANSIENT_API_ERROR_MARKERS = [
  'temporarily unavailable',
  'service unavailable',
  'stream_timeout',
  'stream timeout',
  'server overloaded',
  'overloaded',
  'rate limit',
  'try again later',
];

const isA = (exc: unknown, types: Set<string>): boolean => _class_names(exc).some((name) => types.has(name));

function _is_os_error(exc: unknown): boolean {
  const code = (exc as { code?: unknown })?.code;
  const causeCode = ((exc as { cause?: { code?: unknown } })?.cause)?.code;
  return (typeof code === 'string' && _OS_ERROR_CODES.has(code)) || (typeof causeCode === 'string' && _OS_ERROR_CODES.has(causeCode));
}

/** Python ``str(exc)``. */
function excStr(exc: unknown): string {
  if (exc instanceof Error) return exc.message;
  return pyStr(exc);
}

export function _is_transient_status_code(status_code: number): boolean {
  return [408, 409, 429].includes(status_code) || status_code >= 500;
}

const isInt = (value: unknown): value is number => typeof value === 'number' && Number.isInteger(value);

export function _status_code_from_exception(exc: unknown): number | null {
  const record = (exc ?? {}) as Record<string, unknown>;
  for (const key of ['status_code', 'status']) {
    if (isInt(record[key])) return record[key] as number;
  }
  const response = record.response as Record<string, unknown> | undefined;
  for (const key of ['status_code', 'status']) {
    const value = response?.[key];
    if (isInt(value)) return value;
  }
  return null;
}

/** Distinguish broken provider events from invalid model-authored JSON. */
export function _is_stream_transport_error(exc: unknown): boolean {
  if (exc instanceof SyntaxError || exc instanceof PyJSONDecodeError) {
    // json.JSONDecodeError raised while decoding the provider's SSE stream.
    const stack = (exc as Error).stack ?? '';
    return /node_modules[\\/](openai|@anthropic-ai)[\\/].*(stream|Stream)/.test(stack);
  }
  if (exc instanceof Error && _class_names(exc).includes('ValueError') && /^No generations found in stream\.?$/.test(exc.message)) {
    return true;
  }
  if (exc instanceof Error && exc.message === 'No generations found in stream.') {
    return true;
  }
  return isA(exc, _PROVIDER_API_ERROR_TYPES) && ['stream_read_error', 'stream_timeout', 'stream timeout'].some(
    (marker) => excStr(exc).toLowerCase().includes(marker),
  );
}

/**
 * A billing/window quota cannot recover within our short retry budget.
 * Match structured provider codes, not arbitrary message text.
 */
export function _is_provider_quota_exhausted(exc: unknown): boolean {
  if (_status_code_from_exception(exc) !== 429) {
    return false;
  }
  const record = (exc ?? {}) as Record<string, unknown>;
  let body: unknown = record.body;
  if (!isDict(body)) {
    // openai-node keeps the response body's ``error`` object on ``exc.error``.
    body = isDict(record.error) ? { error: record.error } : null;
  }
  if (!isDict(body)) {
    return false;
  }
  const error = Object.prototype.hasOwnProperty.call(body, 'error') ? body.error : body;
  if (!isDict(error)) {
    return false;
  }
  const exhausted_codes = new Set(['exceeded_current_quota_error', 'insufficient_quota', 'billing_hard_limit_reached']);
  return ['code', 'type'].some((key) => typeof error[key] === 'string' && exhausted_codes.has((error[key] as string).toLowerCase()));
}

/** True for provider HTTP errors that outer retries cannot fix. */
export function _is_permanent_http_error(exc: unknown): boolean {
  if (_is_provider_quota_exhausted(exc)) {
    return true;
  }
  const status_code = _status_code_from_exception(exc);
  if (status_code !== null) {
    return !_is_transient_status_code(status_code);
  }

  const cls_name = _class_names(exc)[0] ?? '';
  return [
    'AuthenticationError',
    'BadRequestError',
    'NotFoundError',
    'PermissionDeniedError',
    'UnprocessableEntityError',
  ].includes(cls_name);
}

/** Retry only transient transport/provider failures. */
export function _is_retryable_exception(exc: unknown): boolean {
  if (exc instanceof LLMBudgetExceeded) {
    return false;
  }
  if (_is_provider_quota_exhausted(exc)) {
    return false;
  }
  if (_is_stream_transport_error(exc)) {
    return true;
  }
  // isinstance(exc, _HTTP_STATUS_ERROR_TYPES + _PROVIDER_STATUS_ERROR_TYPES); the
  // last clause is openai-node's plain APIError for an unmapped status, which
  // openai-python raises as APIStatusError.
  if (
    isA(exc, _HTTP_STATUS_ERROR_TYPES) ||
    isA(exc, _PROVIDER_STATUS_ERROR_TYPES) ||
    (isA(exc, _PROVIDER_API_ERROR_TYPES) && _status_code_from_exception(exc) !== null)
  ) {
    const status_code = _status_code_from_exception(exc);
    return status_code !== null && _is_transient_status_code(status_code);
  }
  if (isA(exc, _PROVIDER_API_ERROR_TYPES)) {
    const message = excStr(exc).toLowerCase();
    return _TRANSIENT_API_ERROR_MARKERS.some((marker) => message.includes(marker));
  }
  return exc instanceof LLMResponseError || isA(exc, _RETRYABLE_EXCEPTIONS) || _is_os_error(exc);
}

// ── Retry budget ────────────────────────────────────────────────────────
//
// BaseAgent owns the only transport-level retry layer: ``LLMFactory`` builds
// provider clients with ``max_retries=0`` by default so SDK retries never
// multiply with these. A logical call (``invoke`` / ``invoke_with_history``,
// including its JSON-repair turns) shares one retry allowance and one
// wall-clock deadline. A deadline is checked before every request and every
// backoff sleep; an in-flight request is bounded by the client ``timeout``.

export const DEFAULT_TRANSPORT_ATTEMPTS = 5;
export const DEFAULT_CALL_DEADLINE_SECONDS = 1800.0;
export const CALL_DEADLINE_ENV = 'EVO_LLM_CALL_DEADLINE_SECONDS';
export const _BACKOFF_MIN_SECONDS = 4.0;
export const _BACKOFF_MAX_SECONDS = 30.0;

let _clock = {
  monotonic: (): number => performance.now() / 1000,
  sleep: (seconds: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, seconds * 1000)),
};

/** Replace ``time.monotonic`` / ``time.sleep`` (tests). Pass ``null`` to restore. */
export function _set_clock(clock: Partial<typeof _clock> | null): void {
  _clock = {
    monotonic: clock?.monotonic ?? (() => performance.now() / 1000),
    sleep: clock?.sleep ?? ((seconds) => new Promise((resolve) => setTimeout(resolve, seconds * 1000))),
  };
}

function _monotonic(): number {
  return _clock.monotonic();
}

export async function _sleep(seconds: number): Promise<void> {
  await _clock.sleep(seconds);
}

/** Exponential backoff: 4s, 4s, 8s, 16s, 30s (cap). */
export function _backoff_seconds(retry_index: number): number {
  return Math.min(_BACKOFF_MAX_SECONDS, Math.max(_BACKOFF_MIN_SECONDS, 2.0 * (2 ** retry_index)));
}

/** ``f"{x:.0f}"`` */
function fmt0(x: number): string {
  // Python rounds half to even in format(); toFixed rounds half away from zero.
  const rounded = Math.round(x);
  const value = Math.abs(x % 1) === 0.5 && rounded % 2 !== 0 ? rounded - 1 : rounded;
  return String(value === 0 ? 0 : value);
}

/**
 * Return the per-call deadline; ``<= 0`` disables it.
 *
 * Precedence: explicit *value*, then ``EVO_LLM_CALL_DEADLINE_SECONDS``, then
 * ``DEFAULT_CALL_DEADLINE_SECONDS``.
 */
export function resolve_call_deadline_seconds(value: unknown = null): number | null {
  if (value === null || value === undefined) {
    const raw = pyStrip(getEnv(CALL_DEADLINE_ENV, ''));
    value = null;
    if (raw) {
      try {
        value = pyFloatParse(raw);
      } catch {
        logger.warning('Ignoring invalid %s=%r', CALL_DEADLINE_ENV, raw);
        value = null;
      }
    }
  }
  if (value === null) {
    value = DEFAULT_CALL_DEADLINE_SECONDS;
  }
  const number = pyFloatParse(value as number | string | boolean);
  return number > 0 ? number : null;
}

/** Optional cap on LLM requests and wall-clock time for one workflow run. */
export class LLMRunBudget {
  max_calls: number | null;
  deadline_seconds: number | null;
  started_at: number;
  calls: number;

  constructor(max_calls: number | null = null, deadline_seconds: number | null = null, started_at: number | null = null, calls = 0) {
    this.max_calls = max_calls;
    this.deadline_seconds = deadline_seconds;
    this.started_at = started_at ?? _monotonic();
    this.calls = calls;
  }

  remaining_seconds(): number | null {
    if (this.deadline_seconds === null) {
      return null;
    }
    return this.deadline_seconds - (_monotonic() - this.started_at);
  }

  check(): void {
    const remaining = this.remaining_seconds();
    if (remaining !== null && remaining <= 0) {
      throw new LLMBudgetExceeded(
        `LLM run deadline of ${fmt0(this.deadline_seconds!)}s exceeded `
        + `after ${this.calls} request(s)`,
      );
    }
    if (this.max_calls !== null && this.calls >= this.max_calls) {
      throw new LLMBudgetExceeded(`LLM run budget of ${this.max_calls} request(s) exhausted`);
    }
  }

  charge(): void {
    // Python holds a threading.Lock here; JS runs this synchronously.
    this.check();
    this.calls += 1;
  }
}

export const _RUN_BUDGET = new AsyncLocalStorage<LLMRunBudget | null>();

/**
 * Cap every BaseAgent request made inside ``body`` (and the concurrent
 * samples it starts, see ``common/self_consistency.ts``).
 */
export async function llm_run_budget<T>(
  max_calls: number | null,
  deadline_seconds: number | null,
  body: (budget: LLMRunBudget) => Promise<T> | T,
): Promise<T> {
  const budget = new LLMRunBudget(
    max_calls && max_calls > 0 ? max_calls : null,
    deadline_seconds && deadline_seconds > 0 ? deadline_seconds : null,
  );
  return _RUN_BUDGET.run(budget, () => body(budget));
}

export const RUN_MAX_CALLS_ENV = 'EVO_LLM_RUN_MAX_CALLS';
export const RUN_DEADLINE_ENV = 'EVO_LLM_RUN_DEADLINE_SECONDS';

export function _env_number(name: string): number | null {
  const raw = pyStrip(getEnv(name, ''));
  if (!raw) {
    return null;
  }
  let value: number;
  try {
    value = pyFloatParse(raw);
  } catch {
    logger.warning('Ignoring invalid %s=%r', name, raw);
    return null;
  }
  return value > 0 ? value : null;
}

/**
 * ``llm_run_budget`` configured by ``EVO_LLM_RUN_MAX_CALLS`` and
 * ``EVO_LLM_RUN_DEADLINE_SECONDS`` (both unset → unlimited, the default).
 */
export function llm_run_budget_from_env<T>(body: (budget: LLMRunBudget) => Promise<T> | T): Promise<T> {
  const max_calls = _env_number(RUN_MAX_CALLS_ENV);
  return llm_run_budget(
    max_calls !== null ? Math.trunc(max_calls) : null,
    _env_number(RUN_DEADLINE_ENV),
    body,
  );
}

/**
 * Count one provider request against the active run budget, if any.
 * For callers that invoke a chat model directly instead of via BaseAgent.
 */
export function charge_llm_run_budget(): void {
  const budget = _RUN_BUDGET.getStore() ?? null;
  if (budget !== null) {
    budget.charge();
  }
}

/** ``getattr(agent, name, default)`` */
function getattr(obj: unknown, name: string, defaultValue: unknown): unknown {
  const value = obj === null || obj === undefined ? undefined : (obj as Record<string, unknown>)[name];
  return value === undefined ? defaultValue : value;
}

export class _CallBudget {
  deadline_seconds: number | null;
  retries_left: number;
  started_at: number;
  retries_used: number;

  constructor(deadline_seconds: number | null, retries_left: number, started_at: number | null = null, retries_used = 0) {
    this.deadline_seconds = deadline_seconds;
    this.retries_left = retries_left;
    this.started_at = started_at ?? _monotonic();
    this.retries_used = retries_used;
  }

  static start(agent: unknown): _CallBudget {
    const attempts = Math.max(1, Math.trunc(Number(getattr(agent, 'transport_attempts', DEFAULT_TRANSPORT_ATTEMPTS))));
    return new _CallBudget(
      resolve_call_deadline_seconds(getattr(agent, 'call_deadline_seconds', null)),
      attempts - 1,
    );
  }

  /** ``with _CallBudget.scope(agent) as budget:`` */
  static scope<T>(agent: unknown, body: (budget: _CallBudget) => Promise<T>): Promise<T> {
    const budget = _CallBudget.start(agent);
    return _CALL_BUDGET.run(budget, () => body(budget));
  }

  elapsed_seconds(): number {
    return _monotonic() - this.started_at;
  }

  remaining_seconds(): number | null {
    const candidates: number[] = [];
    if (this.deadline_seconds !== null) {
      candidates.push(this.deadline_seconds - this.elapsed_seconds());
    }
    const run_budget = _RUN_BUDGET.getStore() ?? null;
    if (run_budget !== null) {
      const run_remaining = run_budget.remaining_seconds();
      if (run_remaining !== null) {
        candidates.push(run_remaining);
      }
    }
    return candidates.length ? Math.min(...candidates) : null;
  }

  /** Fail fast once either deadline is spent; *charge* counts a request. */
  check(charge = false): void {
    if (this.deadline_seconds !== null && this.elapsed_seconds() >= this.deadline_seconds) {
      throw new LLMBudgetExceeded(
        `LLM call deadline of ${fmt0(this.deadline_seconds)}s exceeded `
        + `(set ${CALL_DEADLINE_ENV} or call_deadline_seconds to change it)`,
      );
    }
    const run_budget = _RUN_BUDGET.getStore() ?? null;
    if (run_budget !== null) {
      if (charge) {
        run_budget.charge();
      } else {
        run_budget.check();
      }
    }
  }
}

export const _CALL_BUDGET = new AsyncLocalStorage<_CallBudget | null>();

// Unbound method forms (``_CallBudget.check(self, ...)``) for the parity harness.
export function _CallBudget_check(self: _CallBudget, charge = false): null {
  self.check(charge);
  return null;
}
export function _CallBudget_elapsed_seconds(self: _CallBudget): number {
  return self.elapsed_seconds();
}
export function _CallBudget_remaining_seconds(self: _CallBudget): number | null {
  return self.remaining_seconds();
}

export const valid_agent_arg_list = [
  'middleware',
  'response_format',
  'state_schema',
  'context_schema',
  'checkpointer',
  'store',
  'interrupt_before',
  'interrupt_after',
  'debug',
  'name',
  'cache',
];

// create_agent keyword → createAgent option.
const _CREATE_AGENT_OPTION: Record<string, string> = {
  middleware: 'middleware',
  response_format: 'responseFormat',
  state_schema: 'stateSchema',
  context_schema: 'contextSchema',
  checkpointer: 'checkpointer',
  store: 'store',
  interrupt_before: 'interruptBefore',
  interrupt_after: 'interruptAfter',
  debug: 'debug',
  name: 'name',
  cache: 'cache',
};

// ``\s`` of Python's ``re`` (str patterns).
const _PY_S = '[\\t\\n\\v\\f\\r\\x1c-\\x1f \\x85\\u00a0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000]';
export const _TEMPLATE_VAR_RE = new RegExp(`{{${_PY_S}*([A-Za-z_][A-Za-z0-9_]*)${_PY_S}*}}`, 'g');

/**
 * Replace ``{{key}}`` placeholders in *template* with values from *variables*.
 *
 * Replacement is single-pass: inserted values are not scanned for additional
 * ``{{...}}`` placeholders.
 */
export function _render_template(template: string, variables: Record<string, unknown>): string {
  return template.replace(_TEMPLATE_VAR_RE, (match: string, key: string) => {
    if (!Object.prototype.hasOwnProperty.call(variables, key)) {
      return match;
    }
    return pyStr(variables[key]);
  });
}

export type ChatMessageDict = { role?: string; content?: unknown };
export type PromptDict = { messages: ChatMessageDict[]; [key: string]: unknown };

export abstract class BaseAgent {
  // Class-level defaults so partially constructed agents still get the
  // standard retry budget (Python tests use ``object.__new__``).
  transport_attempts: number = DEFAULT_TRANSPORT_ATTEMPTS;
  call_deadline_seconds: number | null = null; // None → env/default

  _model: BaseChatModel;
  _system_prompt: string | null;
  _task_prompt: string | null;
  _tools: unknown[];
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  _agent: any;
  exclude_think: boolean;
  jsonalize_output: boolean;
  strict_json_output: boolean;
  json_retry_attempts: number;
  /** Last raw LLM response (before JSON parsing) — useful for debugging. */
  _last_raw_output: unknown = null;

  /** Initialize a base agent with JSON output and validation. */
  constructor(
    model: BaseChatModel,
    system_prompt: string | null = null,
    task_prompt: string | null = null,
    tools: unknown[] | null = null,
    kwargs: Record<string, unknown> = {},
  ) {
    this._model = model;
    this._system_prompt = system_prompt;
    this._task_prompt = task_prompt;
    this._tools = tools && tools.length ? tools : [];
    const options: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(kwargs)) {
      if (valid_agent_arg_list.includes(key)) options[_CREATE_AGENT_OPTION[key]] = value;
    }
    this._agent = createAgent({
      model,
      tools: this._tools,
      ...(system_prompt !== null && system_prompt !== undefined ? { systemPrompt: new SystemMessage(system_prompt) } : {}),
      ...options,
    } as unknown as Parameters<typeof createAgent>[0]);
    const kw = (key: string, defaultValue: unknown) => (Object.prototype.hasOwnProperty.call(kwargs, key) ? kwargs[key] : defaultValue);
    this.exclude_think = kw('exclude_think', true) as boolean;
    this.jsonalize_output = kw('jsonalize_output', true) as boolean;
    this.strict_json_output = kw('strict_json_output', false) as boolean;
    // LLMs can occasionally return non-JSON text even when prompted for JSON.
    // Retry a few times before failing the whole workflow.
    this.json_retry_attempts = Math.max(1, Math.trunc(Number(kw('json_retry_attempts', 5))));
    // Transport retries and the wall-clock deadline are shared by all
    // requests of one logical call, including the JSON-repair turns above.
    this.transport_attempts = Math.max(1, Math.trunc(Number(kw('transport_attempts', DEFAULT_TRANSPORT_ATTEMPTS))));
    this.call_deadline_seconds = kw('call_deadline_seconds', null) as number | null;
    this._last_raw_output = null;
  }

  /** Build chat messages for model call. */
  _build_prompt(variables: Record<string, unknown>): PromptDict {
    let prompt: PromptDict;
    if ('img_url' in variables) {
      const img_url = Object.prototype.hasOwnProperty.call(variables, 'img_url') ? variables.img_url : null;
      const task_prompt = _render_template(this._task_prompt as string, variables);
      prompt = {
        messages: [
          {
            role: 'user',
            content: [
              { type: 'text', text: task_prompt },
              { type: 'image_url', image_url: { url: img_url } },
            ],
          },
        ],
      };
    } else {
      const task_prompt = _render_template(this._task_prompt as string, variables);
      prompt = {
        messages: [
          { role: 'user', content: task_prompt },
        ],
      };
    }
    return prompt;
  }

  /** Run one provider request and normalize malformed responses. */
  async _call_model_once(call: () => unknown): Promise<unknown> {
    let result: unknown;
    try {
      result = await call();
    } catch (e) {
      // "NoneType object is not iterable" — API returned malformed response
      // (JS: "... is not iterable" on null/undefined).
      if (e instanceof TypeError) {
        const error_msg = e.message;
        if ((error_msg.includes('NoneType') || /\b(null|undefined)\b/.test(error_msg)) && error_msg.includes('not iterable')) {
          logger.warning('API returned malformed response (choices=None): %s', e);
          throw new LLMResponseError(`API returned malformed response: ${error_msg}`);
        }
      }
      throw e;
    }
    if (result === null || result === undefined) {
      throw new LLMResponseError('LLM returned None response');
    }
    if (isDict(result) && 'error' in result) {
      throw new LLMResponseError(`LLM returned error: ${pyStr(result.error)}`);
    }
    return result;
  }

  /**
   * The single transport-level retry layer for this agent.
   *
   * Transient failures (timeouts, connection errors, 408/409/429/5xx, broken
   * stream events, malformed responses) are retried with exponential
   * backoff. Permanent failures and programming errors propagate
   * immediately. The retry count is shared across every request made for one
   * logical ``invoke`` / ``invoke_with_history`` call, and no attempt starts
   * after the call deadline.
   */
  async _transport_call(call: () => unknown): Promise<unknown> {
    const budget = _CALL_BUDGET.getStore() ?? _CallBudget.start(this);
    while (true) {
      budget.check(true);
      try {
        return await this._call_model_once(call);
      } catch (exc) {
        if (!_is_retryable_exception(exc)) {
          if (!(exc instanceof LLMBudgetExceeded)) {
            logger.warning('LLM invocation failed (non-retryable): %s: %s', _class_names(exc)[0] ?? typeof exc, excStr(exc));
          }
          throw exc;
        }
        if (budget.retries_left <= 0) {
          throw exc;
        }
        const delay = _backoff_seconds(budget.retries_used);
        const remaining = budget.remaining_seconds();
        if (remaining !== null && remaining <= delay) {
          const error = new LLMBudgetExceeded(
            `LLM call deadline reached after ${fmt0(budget.elapsed_seconds())}s `
            + `while retrying ${_class_names(exc)[0] ?? 'Error'}: ${excStr(exc)}`,
          );
          (error as { cause?: unknown }).cause = exc;
          throw error;
        }
        budget.retries_left -= 1;
        budget.retries_used += 1;
        logger.warning(
          'LLM invocation failed (transient; retry %s/%s in %.0fs): %s: %s',
          budget.retries_used, budget.retries_used + budget.retries_left,
          delay, _class_names(exc)[0] ?? 'Error', excStr(exc),
        );
        await _sleep(delay);
      }
    }
  }

  /** Invoke the agent through the shared transport retry layer. */
  _invoke_with_retry(input_prompt: PromptDict): Promise<unknown> {
    return this._transport_call(() => this._agent.invoke(input_prompt));
  }

  /** Invoke the agent with the given input variables. */
  invoke(input_dict: Record<string, unknown>): Promise<unknown> {
    return _CallBudget.scope(this, () => this._invoke_parsed(input_dict));
  }

  async _invoke_parsed(input_dict: Record<string, unknown>): Promise<unknown> {
    const input_prompt = this._build_prompt(input_dict);
    const parse_attempts = this.jsonalize_output ? this.json_retry_attempts : 1;
    let last_error: PyJSONDecodeError | null = null;
    const strict = Boolean(getattr(this, 'strict_json_output', false));
    let attempt_prompt = input_prompt;
    const budget = _CALL_BUDGET.getStore() ?? null;

    for (let attempt = 1; attempt <= parse_attempts; attempt += 1) {
      const is_last_attempt = attempt === parse_attempts;
      if (budget !== null) {
        budget.check();
      }
      const raw_output = await this._invoke_with_retry(attempt_prompt);
      this._last_raw_output = raw_output;
      try {
        return preprocess_response(
          raw_output,
          true,
          this.exclude_think,
          this.jsonalize_output,
          // Last attempt gives up on the "response is exactly one JSON
          // value" contract so a fenced or embedded payload is still
          // recovered instead of burning the whole run.
          strict && !is_last_attempt,
        );
      } catch (e) {
        if (!(e instanceof PyJSONDecodeError)) throw e;
        last_error = e;
        const preview = BaseAgent._preview_response(raw_output);
        logger.warning(
          'LLM returned non-JSON output (attempt %s/%s), retrying. Error: %s | Preview: %s',
          attempt,
          parse_attempts,
          e.message,
          preview,
        );
        if (is_last_attempt) {
          throw e;
        }
        // Feed the parse failure back so the next sample is a correction
        // instead of an identical re-sample at the same temperature.
        attempt_prompt = {
          ...input_prompt,
          messages: [
            ...(input_prompt.messages ?? []),
            {
              role: 'assistant',
              content: (this.constructor as typeof BaseAgent)._invalid_output_echo(raw_output),
            },
            {
              role: 'user',
              content: BaseAgent._json_repair_instruction(e),
            },
          ],
        };
      }
    }

    // Defensive fallback; loop should already return or raise.
    if (last_error !== null) {
      throw last_error;
    }
    throw new LLMResponseError('Unexpected invoke state: no output and no parse error.');
  }

  /**
   * Invoke the LLM with a pre-built messages list (conversation mode).
   *
   * Unlike ``invoke``, this calls the model directly (bypassing the agent
   * graph) so the caller has full control over the message list — including
   * the system message. Transport retries and the call deadline are shared
   * with the JSON-repair loop.
   *
   * @param messages List of dicts with ``role`` (``system``/``user``/``assistant``) and ``content``.
   * @param tools Optional tool list; falls back to ``this._tools``.
   */
  invoke_with_history(messages: ChatMessageDict[], tools: unknown[] | null = null): Promise<unknown> {
    return _CallBudget.scope(this, () => this._invoke_with_history_parsed(messages, tools));
  }

  async _invoke_with_history_parsed(messages: ChatMessageDict[], tools: unknown[] | null): Promise<unknown> {
    const lc_messages: BaseMessage[] = [];
    for (const msg of messages) {
      const role = Object.prototype.hasOwnProperty.call(msg, 'role') ? msg.role : 'user';
      const content = (Object.prototype.hasOwnProperty.call(msg, 'content') ? msg.content : '') as string;
      if (role === 'system') {
        lc_messages.push(new SystemMessage({ content }));
      } else if (role === 'assistant') {
        lc_messages.push(new AIMessage({ content }));
      } else {
        lc_messages.push(new HumanMessage({ content }));
      }
    }

    const effective_tools = tools !== null && tools !== undefined ? tools : this._tools;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let model: any = this._model;
    if (effective_tools && effective_tools.length) {
      model = model.bindTools(effective_tools);
    }

    const parse_attempts = this.jsonalize_output ? this.json_retry_attempts : 1;
    let last_error: PyJSONDecodeError | null = null;
    const strict = Boolean(getattr(this, 'strict_json_output', false));
    let attempt_messages = lc_messages;

    for (let attempt = 1; attempt <= parse_attempts; attempt += 1) {
      const is_last_attempt = attempt === parse_attempts;
      const request = attempt_messages;
      const raw_output = await this._transport_call(() => model.invoke(request));
      this._last_raw_output = raw_output;

      try {
        return preprocess_response(
          raw_output,
          true,
          this.exclude_think,
          this.jsonalize_output,
          // See ``invoke``: the final attempt parses leniently.
          strict && !is_last_attempt,
        );
      } catch (e) {
        if (!(e instanceof PyJSONDecodeError)) throw e;
        last_error = e;
        logger.warning(
          'Non-JSON output (attempt %s/%s): %s',
          attempt, parse_attempts, BaseAgent._preview_response(raw_output),
        );
        if (is_last_attempt) {
          throw e;
        }
        attempt_messages = [
          ...lc_messages,
          new AIMessage({ content: (this.constructor as typeof BaseAgent)._invalid_output_echo(raw_output) }),
          new HumanMessage({ content: BaseAgent._json_repair_instruction(e) }),
        ];
      }
    }

    if (last_error !== null) {
      throw last_error;
    }
    throw new LLMResponseError('Unexpected invoke_with_history state.');
  }

  /** Correction turn appended after a failed JSON parse. */
  static _json_repair_instruction(error: PyJSONDecodeError): string {
    return (
      'Your previous response could not be parsed as JSON: '
      + `${error.msg} (line ${error.lineno}, column ${error.colno}). `
      + 'Resend the same result as a corrected, complete JSON value. '
      + 'Output raw JSON only: no ```json fences, no prose before or after, '
      + 'no trailing commas, and no comments. Escape any quotes, backslashes '
      + 'and newlines inside string values.'
    );
  }

  /** Return the rejected model output so the repair turn has context. */
  static _invalid_output_echo(raw_output: unknown, max_len = 2000): string {
    let text: string;
    try {
      text = get_text_from_response(raw_output);
    } catch {
      // debugging aid must never raise
      text = pyStr(raw_output);
    }
    if (!pyStrip(text)) {
      // Reasoning models can burn the whole token budget on hidden thinking
      // and return empty visible content. Echoing an empty assistant turn
      // makes OpenAI-compatible endpoints reject the next request outright.
      return '(empty response — no visible content was returned)';
    }
    if (cpLen(text) > max_len) {
      return cpSlice(text, 0, max_len) + '\n...(truncated)';
    }
    return text;
  }

  /** Return a single-line preview of raw model output for debugging. */
  static _preview_response(raw_output: unknown, max_len = 400): string {
    let text: string;
    try {
      text = get_text_from_response(raw_output);
    } catch {
      text = pyStr(raw_output);
    }

    text = pyStrip(text.split('\n').join('\\n'));
    if (cpLen(text) > max_len) {
      return cpSlice(text, 0, max_len) + '...(truncated)';
    }
    return text;
  }

  /** Run the agent safely, catching exceptions and updating state. */
  async run_safe(state: unknown): Promise<unknown> {
    try {
      return await this.run(state);
    } catch (e) {
      const error_msg = `${this.constructor.name} failed: ${excStr(e)}`;
      const record = state as Record<string, unknown> | null;
      if (record && typeof record === 'object' && 'errors' in record && Array.isArray(record.errors)) {
        record.errors.push(error_msg);
      }
      if (record && typeof record === 'object' && 'status' in record) {
        record.status = 'failed';
      }
      return state;
    }
  }

  /** Execute the agent logic. Subclasses must implement this. */
  abstract run(state: unknown): unknown;
}

