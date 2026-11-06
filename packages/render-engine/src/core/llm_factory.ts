// Ported from evodesign/core/llm_factory.py — keep in sync.
// server-only
//
// ``init_chat_model(**config_kwargs)`` → ``init_chat_model(config_kwargs)``
// below: it maps the Python keyword names onto LangChain.js ``initChatModel``
// fields, or — when a factory was installed with ``set_chat_model_factory`` —
// hands the *Python-named* kwargs to that factory instead. This is the TS
// counterpart of the place where tools/llm_cassette.py substitutes the
// cassette model (it replaces ``llm_factory.init_chat_model``), so the replay
// model receives exactly the parameters Python recorded. The factory also
// receives the role of the enclosing ``LLMFactory.create_for_role`` call
// (null otherwise), like the Python harness records it.
//
// Python keyword arguments map to positional parameters in declaration order
// with ``**kwargs`` as a trailing object. ``LLMFactory.create_kw(params)`` is
// the ``LLMFactory.create(**params)`` call form used with config dicts.
// Model creation is async (``initChatModel`` is async in LangChain.js).

import type { BaseChatModel } from '@langchain/core/language_models/chat_models';
import { initChatModel } from 'langchain';
import { ValueError } from '../py/errors.ts';
import { getLogger } from '../py/logging.ts';
import { pyRepr, pyStr, pyStrip } from '../py/str.ts';
import { isDict, truthy } from '../py/truthy.ts';
import { ModelConfig } from '../config/model_loader.ts';
import { createOpenAIChatModel } from '../models/openai_chat.ts';

const logger = getLogger('evodesign.core.llm_factory');

/** Replacement for ``init_chat_model``: Python-named kwargs + LLMFactory role. */
export type ChatModelFactory = (params: Record<string, unknown>, role: string | null) => BaseChatModel | Promise<BaseChatModel>;

let _chat_model_factory: ChatModelFactory | null = null;
let _ROLE: string | null = null;

/**
 * Install (or with ``null`` remove) the factory that replaces
 * ``init_chat_model`` for every model LLMFactory creates (tests: the cassette
 * replay model; ``runRecordedPipeline``'s ``chatModelFactory``).
 */
export function set_chat_model_factory(factory: ChatModelFactory | null): void {
  _chat_model_factory = factory;
}

export function get_chat_model_factory(): ChatModelFactory | null {
  return _chat_model_factory;
}

const OPENAI_COMPATIBLE = new Set(['openai', 'azure_openai', 'deepseek', 'xai', 'groq', 'fireworks', 'together']);

/** snake_case → camelCase for pass-through kwargs (``top_p`` → ``topP``). */
function camel(name: string): string {
  return name.replace(/_([a-z0-9])/g, (_m, ch: string) => ch.toUpperCase());
}

/**
 * Python ``init_chat_model`` kwargs → LangChain.js ``initChatModel(model, fields)``.
 * Seconds become milliseconds (``timeout``); ``base_url``/``default_headers``
 * go into the OpenAI client ``configuration``; ``extra_body`` becomes
 * ``modelKwargs`` (merged into the request body, like langchain-openai);
 * ``reasoning_effort`` becomes ``reasoning: {effort}``.
 */
export function _init_chat_model_fields(config_kwargs: Record<string, unknown>): { model: string; fields: Record<string, unknown> } {
  const fields: Record<string, unknown> = {};
  const configuration: Record<string, unknown> = {};
  const provider = typeof config_kwargs.model_provider === 'string' ? config_kwargs.model_provider.toLowerCase() : null;
  for (const [key, value] of Object.entries(config_kwargs)) {
    if (value === undefined) continue;
    switch (key) {
      case 'model':
        break;
      case 'model_provider':
        fields.modelProvider = value;
        break;
      case 'timeout':
        if (value !== null) fields.timeout = Number(value) * 1000;
        break;
      case 'base_url':
        if (provider === 'anthropic') fields.anthropicApiUrl = value;
        else configuration.baseURL = value;
        break;
      case 'default_headers':
        if (provider === 'anthropic') fields.clientOptions = { ...(fields.clientOptions as object), defaultHeaders: value };
        else configuration.defaultHeaders = value;
        break;
      case 'extra_body':
        fields.modelKwargs = { ...(fields.modelKwargs as object), ...(value as object) };
        break;
      case 'reasoning_effort':
        if (provider && OPENAI_COMPATIBLE.has(provider)) fields.reasoning = { effort: value };
        else fields.reasoningEffort = value;
        break;
      case 'use_responses_api':
        fields.useResponsesApi = value;
        break;
      default:
        fields[camel(key)] = value;
    }
  }
  if (Object.keys(configuration).length) fields.configuration = configuration;
  return { model: pyStr(config_kwargs.model), fields };
}

/**
 * ``langchain.chat_models.init_chat_model(**config_kwargs)`` (the substitution point).
 * ``model_provider`` openai builds ``models/openai_chat.EvoChatOpenAI`` (WP30:
 * HTTP-level parity with langchain-openai; ``http_client`` may be a fetch
 * function); other providers go through LangChain.js ``initChatModel``.
 */
export async function init_chat_model(config_kwargs: Record<string, unknown>): Promise<BaseChatModel> {
  if (_chat_model_factory) {
    return _chat_model_factory({ ...config_kwargs }, _ROLE);
  }
  if (typeof config_kwargs.model_provider === 'string' && config_kwargs.model_provider.toLowerCase() === 'openai') {
    // WP30: request body, headers and errors aligned with langchain-openai.
    return createOpenAIChatModel(config_kwargs) as unknown as BaseChatModel;
  }
  const { model, fields } = _init_chat_model_fields(config_kwargs);
  return (await initChatModel(model, fields)) as unknown as BaseChatModel;
}

const has = (obj: Record<string, unknown>, key: string): boolean => Object.prototype.hasOwnProperty.call(obj, key);

/** ``dict.pop(key, None)`` */
function pop(obj: Record<string, unknown>, key: string): unknown {
  if (!has(obj, key)) return null;
  const value = obj[key];
  delete obj[key];
  return value;
}

/** ``urllib.parse.urlparse(url).hostname`` */
function hostname(url: string): string | null {
  try {
    const host = new URL(url).hostname;
    return host.startsWith('[') && host.endsWith(']') ? host.slice(1, -1) : host;
  } catch {
    const match = /^[a-zA-Z][a-zA-Z0-9+.-]*:\/\/(?:[^@/]*@)?(\[[^\]]*\]|[^:/?#]*)/.exec(url);
    if (!match) return null;
    const host = match[1].replace(/^\[|\]$/g, '');
    return host || null;
  }
}

export class LLMFactory {
  static _is_local_openai_endpoint(base_url: string | null): boolean {
    if (!base_url) {
      return false;
    }
    const host = (hostname(base_url) || '').toLowerCase();
    return ['localhost', '127.0.0.1', '::1', '0.0.0.0'].includes(host);
  }

  /** Normalize OpenAI-compatible endpoints and opt into Responses API when requested. */
  static _normalize_openai_base_url(
    base_url: string | null,
    model_provider: string | null,
    kwargs: Record<string, unknown>,
  ): string | null {
    if (!base_url || typeof model_provider !== 'string') {
      return base_url;
    }

    if (model_provider.toLowerCase() !== 'openai') {
      return base_url;
    }

    const normalized = base_url.replace(/\/+$/, '');

    if (normalized.endsWith('/chat/completions')) {
      // Caller pinned chat/completions — make sure langchain's agent path
      // doesn't silently switch to Responses API for reasoning models.
      if (!has(kwargs, 'use_responses_api')) kwargs.use_responses_api = false;
      return normalized.slice(0, normalized.lastIndexOf('/chat/completions'));
    }

    if (normalized.endsWith('/responses')) {
      if (!has(kwargs, 'use_responses_api')) kwargs.use_responses_api = true;
      return normalized.slice(0, normalized.lastIndexOf('/responses'));
    }

    // Generic /v1 endpoint — force the classic chat/completions path unless
    // the caller explicitly opted in.
    if (!has(kwargs, 'use_responses_api')) kwargs.use_responses_api = false;
    return normalized;
  }

  /**
   * Initialize LLM client with model parameters.
   *
   * ``max_retries`` defaults to 0: ``BaseAgent`` owns the single transport
   * retry layer and the per-call deadline. ``thinking`` (in ``kwargs``):
   * optional ``"enabled"``/``"disabled"`` sent as the ``thinking`` request
   * field. Other ``kwargs`` are passed to ``init_chat_model``.
   */
  static async create(
    model: string | null = null,
    model_provider: string | null = null,
    temperature: number | null = 0,
    base_url: string | null = null,
    api_key: string | null = null,
    timeout: number | null = 1200, // Default 20 minutes timeout for slow reasoning models
    max_retries: number = 0,
    max_tokens: number | null = null,
    kwargs: Record<string, unknown> = {},
  ): Promise<BaseChatModel> {
    kwargs = { ...kwargs };
    const thinking = pop(kwargs, 'thinking');
    if (thinking !== null && thinking !== undefined && pyStrip(pyStr(thinking))) {
      const mode = pyStrip(pyStr(thinking)).toLowerCase();
      if (mode !== 'enabled' && mode !== 'disabled') {
        throw new ValueError(`thinking must be 'enabled' or 'disabled', got ${pyRepr(thinking)}.`);
      }
      // GLM, DeepSeek and other OpenAI-compatible APIs read this body field.
      const extra_body: Record<string, unknown> = { ...((truthy(kwargs.extra_body) ? kwargs.extra_body : {}) as Record<string, unknown>) };
      extra_body.thinking = { type: mode };
      kwargs.extra_body = extra_body;
    }

    if (model === null || model === undefined || !pyStrip(pyStr(model))) {
      throw new ValueError(
        'LLMFactory.create requires a model name. Configure model_name '
        + 'for the role in models.yaml or pass model=... explicitly.',
      );
    }

    // NVIDIA endpoints are OpenAI-compatible; just remap the provider.
    let provider_key = typeof model_provider === 'string' ? model_provider.toLowerCase() : null;

    if (provider_key === 'nvidia') {
      model_provider = 'openai';
      provider_key = 'openai';
      base_url = base_url || 'https://integrate.api.nvidia.com/v1';
      if (!has(kwargs, 'streaming')) kwargs.streaming = true;
    }

    base_url = LLMFactory._normalize_openai_base_url(base_url, model_provider, kwargs);

    // Enable streaming by default to avoid Cloudflare/proxy 524 gateway
    // timeouts that occur when the server holds a connection silently.
    if (!has(kwargs, 'streaming')) kwargs.streaming = true;

    // Identify the application: some gateways reject the SDK's default User-Agent.
    if (provider_key === 'openai') {
      if (!has(kwargs, 'default_headers')) kwargs.default_headers = { 'User-Agent': 'EvoDesign/diagnostic' };
    }

    const config_kwargs: Record<string, unknown> = {
      model,
      model_provider,
      temperature,
      timeout,
      max_retries,
      ...kwargs,
    };

    if (base_url !== null && base_url !== undefined) {
      config_kwargs.base_url = base_url;
    }

    if (api_key !== null && api_key !== undefined && pyStrip(pyStr(api_key))) {
      config_kwargs.api_key = api_key;
    } else if (base_url !== null && base_url !== undefined && provider_key === 'openai') {
      if (LLMFactory._is_local_openai_endpoint(base_url)) {
        config_kwargs.api_key = 'dummy-key-for-local-openai-endpoint';
      } else {
        throw new ValueError(
          'Missing api_key for remote OpenAI-compatible endpoint '
          + `${pyRepr(base_url)}. Configure provider api_key in models.yaml `
          + 'or set the referenced API key environment variable.',
        );
      }
    }

    if (max_tokens !== null && max_tokens !== undefined) {
      config_kwargs.max_tokens = max_tokens;
    }

    // Initialize the model
    logger.debug(`Initializing LLM: model=${model}, provider=${model_provider}, timeout=${timeout}`);
    return init_chat_model(config_kwargs);
  }

  /** ``LLMFactory.create(**params)`` */
  static create_kw(params: Record<string, unknown>): Promise<BaseChatModel> {
    const rest = { ...params };
    const take = (name: string): unknown => {
      if (!has(rest, name)) return undefined;
      const value = rest[name];
      delete rest[name];
      return value;
    };
    return LLMFactory.create(
      take('model') as string | null | undefined,
      take('model_provider') as string | null | undefined,
      take('temperature') as number | null | undefined,
      take('base_url') as string | null | undefined,
      take('api_key') as string | null | undefined,
      take('timeout') as number | null | undefined,
      take('max_retries') as number | undefined,
      take('max_tokens') as number | null | undefined,
      rest,
    );
  }

  /** Initialize LLM client from a config dict (``model``/``model_provider`` or legacy ``model_name``/``provider``). */
  static from_config(config: unknown): Promise<BaseChatModel> {
    // Normalize the incoming config into a plain dict so .pop is safe.
    if (!isDict(config)) {
      throw new ValueError('Unsupported config type for LLMFactory.from_config');
    }
    const llm_config: Record<string, unknown> = { ...config };

    // Accept both key styles; pop both so a leftover alias is never
    // forwarded as a duplicate keyword argument.
    const model = pop(llm_config, 'model');
    const legacy_model = pop(llm_config, 'model_name');
    const model_provider = pop(llm_config, 'model_provider');
    const legacy_model_provider = pop(llm_config, 'provider');

    const base_url = pop(llm_config, 'base_url');
    const api_key = pop(llm_config, 'api_key');
    return LLMFactory.create_kw({
      model: model !== null ? model : legacy_model,
      model_provider: model_provider !== null ? model_provider : legacy_model_provider,
      base_url,
      api_key,
      ...llm_config,
    });
  }

  /**
   * Create a model for *role* using the default ``ModelConfig``. This is the
   * recommended entry point.
   */
  static async create_for_role(role: string, overrides: Record<string, unknown> = {}): Promise<BaseChatModel> {
    const config = ModelConfig.get_default();
    const params = config.get_model_config(role, overrides);
    // The role is read synchronously by init_chat_model, before create()'s
    // first await, so it is restored before any other code can run.
    const previous = _ROLE;
    _ROLE = role;
    let pending: Promise<BaseChatModel>;
    try {
      pending = LLMFactory.create_kw(params);
    } finally {
      _ROLE = previous;
    }
    return pending;
  }

  /** Create a model by resolving *role* through an explicit ``ModelConfig``. */
  static create_from_config(config: ModelConfig, role = 'generator', overrides: Record<string, unknown> = {}): Promise<BaseChatModel> {
    const params = config.get_model_config(role, overrides);
    return LLMFactory.create_kw(params);
  }

  /** Create LLM from the ``default`` role. */
  static create_default(
    provider_config: ModelConfig | null = null,
    temperature = 0,
    kwargs: Record<string, unknown> = {},
  ): Promise<BaseChatModel> {
    const config = provider_config || ModelConfig.get_default();
    const params = config.get_model_config('default', { temperature, ...kwargs });
    logger.info('Creating default LLM: model=%s', params.model ?? null);
    return LLMFactory.create_kw(params);
  }

  /** Fast-tier LLM for per-element fill tasks (the ``"fast"`` role). */
  static create_fast(
    provider_config: ModelConfig | null = null,
    temperature = 0,
    kwargs: Record<string, unknown> = {},
  ): Promise<BaseChatModel> {
    const config = provider_config || ModelConfig.get_default();
    const params = config.get_model_config('fast', { temperature, ...kwargs });
    logger.info('Creating fast-tier LLM: model=%s', params.model ?? null);
    return LLMFactory.create_kw(params);
  }
}
