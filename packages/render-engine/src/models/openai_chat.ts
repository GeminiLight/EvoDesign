// WP30: OpenAI-compatible chat model whose HTTP behaviour matches Python
// ``langchain_openai.ChatOpenAI`` as built by ``evodesign/core/llm_factory.py``.
//
// LangChain.js ``ChatOpenAI`` differs from langchain-openai (Python 1.x) on the
// wire and in its errors (PHASE2_REPORT.md #1/#2). This module closes the gaps
// in the model layer, so BaseAgent's retry classification (a line-by-line port
// of Python) sees the same exceptions Python's sees:
//
// Request body
//   * ``max_tokens`` → ``max_completion_tokens`` (langchain-openai renames it
//     for every Chat Completions model; LangChain.js only for o-series/gpt-5).
//   * no ``stream_options`` unless Python would send it (``stream_usage`` is
//     only defaulted on when neither ``base_url`` nor a custom client is set).
//   * ``reasoning_effort`` is always sent (LangChain.js drops it for model
//     names it does not recognise as reasoning models).
//   * ``extra_body`` is merged into the body (Python: openai ``extra_body``).
// Headers
//   * ``default_headers`` (``User-Agent: EvoDesign/diagnostic``) is applied
//     last, replacing LangChain.js' ``langchainjs-openai/...`` user agent.
//   * In a browser the SDK's ``x-stainless-*`` telemetry headers and the user
//     agent are dropped: browsers cannot set ``User-Agent`` and extra headers
//     trigger CORS preflight failures at many OpenAI-compatible providers.
//     These are the documented transport headers (see TRANSPORT_HEADERS).
// Errors (what Python raises)
//   * A request timeout is ``OpenAITimeoutError`` (an ``openai.APIError``), not
//     LangChain.js' plain ``Error{name:'TimeoutError'}``; Python's BaseAgent
//     therefore does not retry it.
//   * A stream without any chunk raises ``ValueError("No generations found in
//     stream.")`` (Python ``generate_from_stream``), which BaseAgent retries,
//     instead of LangChain.js' ``TypeError`` / "Received empty response".
//
// The module has no ``node:*`` imports: the same class runs in the browser.

import { ChatOpenAI } from '@langchain/openai';
import type { BaseMessage } from '@langchain/core/messages';
import type { ChatResult } from '@langchain/core/outputs';
import type { ChatGenerationChunk } from '@langchain/core/outputs';
import type { CallbackManagerForLLMRun } from '@langchain/core/callbacks/manager';
import { ValueError } from '../py/errors.ts';
import { pyJsonDumps } from '../py/json.ts';

type FetchLike = (input: string | URL | Request, init?: RequestInit) => Promise<Response>;

/**
 * Headers that are not part of the compared request (they describe the HTTP
 * client, not the request): Python's httpx/openai-python and the browser /
 * openai-node set them independently.
 */
export const TRANSPORT_HEADERS: readonly string[] = [
  'host', 'connection', 'content-length', 'accept-encoding', 'accept', 'user-agent',
  'x-stainless-*',
];

export function isTransportHeader(name: string): boolean {
  const lower = name.toLowerCase();
  return TRANSPORT_HEADERS.some((entry) => (entry.endsWith('*') ? lower.startsWith(entry.slice(0, -1)) : lower === entry));
}

// ── Python langchain-openai exception shapes ─────────────────────────────
// Class names follow langchain_openai.chat_models.base so the prototype chain
// gives BaseAgent the same ``isinstance`` answers as Python's MRO.

export class OpenAIError extends Error {
  constructor(message: string) {
    super(message);
    this.name = new.target.name;
  }
}
export class APIError extends OpenAIError {}
export class APIConnectionError extends APIError {}
export class APITimeoutError extends APIConnectionError {}
/** ``langchain_openai.chat_models.base.OpenAITimeoutError`` */
export class OpenAITimeoutError extends APITimeoutError {
  constructor(message = 'Request timed out.') {
    super(message);
  }
}

/**
 * @langchain/openai ``wrapOpenAIClientError`` replaces openai-node's
 * ``APIConnectionTimeoutError`` with a plain ``Error`` named ``TimeoutError``
 * (a real ``TimeoutError`` class, e.g. a cassette's, keeps its constructor).
 */
function isLangChainWrappedTimeout(error: unknown): boolean {
  return error instanceof Error && error.constructor === Error && error.name === 'TimeoutError';
}

function translateError(error: unknown): unknown {
  if (isLangChainWrappedTimeout(error)) {
    const translated = new OpenAITimeoutError((error as Error).message || 'Request timed out.');
    (translated as { cause?: unknown }).cause = error;
    return translated;
  }
  return error;
}

const EMPTY_STREAM = 'No generations found in stream.';

/**
 * ``ChatOpenAI`` with Python's error semantics (timeouts, empty streams).
 * Construct it through ``createOpenAIChatModel``.
 */
export class EvoChatOpenAI extends ChatOpenAI {
  static override lc_name(): string {
    return 'ChatOpenAI';
  }

  override async _generate(messages: BaseMessage[], options: this['ParsedCallOptions'], runManager?: CallbackManagerForLLMRun): Promise<ChatResult> {
    let result: ChatResult;
    try {
      result = await super._generate(messages, options, runManager);
    } catch (error) {
      throw translateError(error);
    }
    if (this.streaming && result.generations.length === 0) {
      throw new ValueError(EMPTY_STREAM);
    }
    return result;
  }

  override async *_streamResponseChunks(messages: BaseMessage[], options: this['ParsedCallOptions'], runManager?: CallbackManagerForLLMRun): AsyncGenerator<ChatGenerationChunk> {
    let any = false;
    try {
      for await (const chunk of super._streamResponseChunks(messages, options, runManager)) {
        any = true;
        yield chunk;
      }
    } catch (error) {
      throw translateError(error);
    }
    if (!any && !options.signal?.aborted) {
      throw new ValueError(EMPTY_STREAM);
    }
  }
}

export interface OpenAIModelOptions {
  /** Replaces the SDK's fetch (Python: ``http_client``). */
  fetch?: FetchLike;
  /** Browser transport: drop ``x-stainless-*`` and ``User-Agent``. */
  browser?: boolean;
}

/** ``{**a, **b}`` for plain objects. */
const merge = (a: unknown, b: unknown): Record<string, unknown> => ({ ...(a as object), ...(b as object) });

/**
 * Python ``init_chat_model(**config_kwargs)`` for an OpenAI-compatible
 * provider → ``EvoChatOpenAI`` constructor fields. ``timeout`` is seconds.
 */
export function openaiFieldsFromKwargs(config_kwargs: Record<string, unknown>): {
  fields: Record<string, unknown>;
  defaultHeaders: Record<string, string> | null;
  fetch: FetchLike | null;
} {
  const fields: Record<string, unknown> = {};
  const configuration: Record<string, unknown> = {};
  let modelKwargs: Record<string, unknown> = {};
  let defaultHeaders: Record<string, string> | null = null;
  let fetchImpl: FetchLike | null = null;
  let maxTokens: unknown;
  let hasStreamUsage = false;
  for (const [key, value] of Object.entries(config_kwargs)) {
    if (value === undefined) continue;
    switch (key) {
      case 'model':
        fields.model = value;
        break;
      case 'model_provider':
        break;
      case 'temperature':
        if (value !== null) fields.temperature = value;
        break;
      case 'timeout':
        if (value !== null) fields.timeout = Number(value) * 1000;
        break;
      case 'max_retries':
        if (value !== null) fields.maxRetries = value;
        break;
      case 'streaming':
        fields.streaming = value;
        break;
      case 'stream_usage':
        hasStreamUsage = true;
        if (value !== null) fields.streamUsage = value;
        break;
      case 'base_url':
        if (value !== null) configuration.baseURL = value;
        break;
      case 'api_key':
        if (value !== null) fields.apiKey = value;
        break;
      case 'default_headers':
        if (value !== null) {
          defaultHeaders = { ...(value as Record<string, string>) };
          configuration.defaultHeaders = value;
        }
        break;
      case 'http_client':
        fetchImpl = value as FetchLike;
        break;
      case 'max_tokens':
        maxTokens = value;
        break;
      case 'extra_body':
      case 'model_kwargs':
        if (value !== null) modelKwargs = merge(modelKwargs, value);
        break;
      case 'reasoning_effort':
        if (value !== null) modelKwargs.reasoning_effort = value;
        break;
      case 'use_responses_api':
        fields.useResponsesApi = value;
        break;
      default:
        fields[key.replace(/_([a-z0-9])/g, (_m, ch: string) => ch.toUpperCase())] = value;
    }
  }
  if (maxTokens !== undefined && maxTokens !== null) {
    if (fields.useResponsesApi === true || /^(o\d|gpt-5)/.test(String(fields.model))) fields.maxTokens = maxTokens;
    else modelKwargs = { max_completion_tokens: maxTokens, ...modelKwargs };
  }
  // langchain-openai: stream_usage defaults on only for the default OpenAI
  // endpoint with the default client.
  if (!hasStreamUsage) {
    fields.streamUsage = configuration.baseURL === undefined && fetchImpl === null;
  }
  if (Object.keys(modelKwargs).length) fields.modelKwargs = modelKwargs;
  if (Object.keys(configuration).length) fields.configuration = configuration;
  return { fields, defaultHeaders, fetch: fetchImpl };
}

/** Wrap *base* so headers match Python (or the browser transport policy). */
export function transportFetch(base: FetchLike, defaultHeaders: Record<string, string> | null, browser: boolean): FetchLike {
  return async (input, init) => {
    const headers = new Headers(init?.headers ?? (input instanceof Request ? input.headers : undefined));
    if (browser) {
      for (const name of [...headers.keys()]) {
        if (name.startsWith('x-stainless-') || name === 'user-agent') headers.delete(name);
      }
    } else if (defaultHeaders) {
      for (const [name, value] of Object.entries(defaultHeaders)) headers.set(name, value);
    }
    let body = init?.body;
    if (typeof body === 'string') {
      const payload = JSON.parse(body);
      // Python sends null content on assistant tool calls with no text.
      for (const message of payload.messages ?? []) {
        if (message.role === 'assistant' && message.tool_calls?.length && message.content === '') message.content = null;
        for (const call of message.tool_calls ?? []) {
          if (call.type === 'function' && typeof call.function?.arguments === 'string') {
            try { call.function.arguments = pyJsonDumps(JSON.parse(call.function.arguments)); } catch { /* Keep malformed provider arguments for the model to repair. */ }
          }
        }
      }
      body = JSON.stringify(payload);
    }
    return base(input, { ...init, headers, body });
  };
}

/** ``init_chat_model(**config_kwargs)`` for ``model_provider`` openai (and its aliases). */
export function createOpenAIChatModel(config_kwargs: Record<string, unknown>, options: OpenAIModelOptions = {}): EvoChatOpenAI {
  const { fields, defaultHeaders, fetch: kwFetch } = openaiFieldsFromKwargs(config_kwargs);
  const base = options.fetch ?? kwFetch ?? ((input, init) => globalThis.fetch(input, init));
  const configuration = { ...(fields.configuration as object | undefined), fetch: transportFetch(base, defaultHeaders, options.browser === true) };
  return new EvoChatOpenAI({ ...fields, configuration } as ConstructorParameters<typeof ChatOpenAI>[0]);
}
