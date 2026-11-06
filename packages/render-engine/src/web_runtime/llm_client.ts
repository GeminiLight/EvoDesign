// Ported from backend/app/services/llm_client.py — keep in sync (PHASE3_PLAN.md
// WP29). Chat-model construction from the backend settings.
//
// The model is created through the engine's ``LLMFactory.create`` so every
// model goes through ``init_chat_model`` and therefore through the injected
// ``chatModelFactory`` (browser: the user's / shared model, parity: cassette).

import type { BaseChatModel } from '@langchain/core/language_models/chat_models';
import { RuntimeError } from '../py/errors.ts';
import { LLMFactory } from '../core/llm_factory.ts';
import type { WebSettings } from './settings.ts';

const _DEFAULT_EXPLICIT_MODEL = 'gpt-4.1-mini';

/** Raised when the LLM settings are incomplete or invalid. */
export class BackendLLMConfigurationError extends RuntimeError {}

/** Resolved chat-model configuration. */
export class BackendLLMConfig {
  constructor(
    readonly model: string,
    readonly model_provider: string,
    readonly api_key: string,
    readonly base_url: string | null,
    readonly temperature: number,
    readonly max_tokens: number,
    readonly reasoning_effort: string | null = null,
    readonly thinking: string | null = null,
  ) {}

  as_factory_kwargs(): Record<string, unknown> {
    const kwargs: Record<string, unknown> = {
      model: this.model,
      model_provider: this.model_provider,
      api_key: this.api_key,
      temperature: this.temperature,
      max_tokens: this.max_tokens,
    };
    if (this.base_url) kwargs.base_url = this.base_url;
    if (this.reasoning_effort) kwargs.reasoning_effort = this.reasoning_effort;
    if (this.thinking) kwargs.thinking = this.thinking;
    return kwargs;
  }
}

function _first_nonempty(...values: (string | null | undefined)[]): string | null {
  for (const value of values) if (value) return value;
  return null;
}

export function resolve_backend_llm_config(
  settings: WebSettings,
  temperature: number | null = null,
  max_tokens: number | null = null,
): BackendLLMConfig {
  const resolved_temperature = temperature === null ? settings.llm_temperature : temperature;
  const resolved_max_tokens = max_tokens === null ? settings.llm_max_tokens : max_tokens;
  if (settings.llm_api_key) {
    return new BackendLLMConfig(
      _first_nonempty(settings.llm_model_name, _DEFAULT_EXPLICIT_MODEL) || _DEFAULT_EXPLICIT_MODEL,
      settings.llm_model_provider || 'openai',
      settings.llm_api_key,
      settings.llm_endpoint_url,
      resolved_temperature,
      resolved_max_tokens,
      settings.llm_reasoning_effort ?? null,
      settings.llm_thinking ?? null,
    );
  }
  throw new BackendLLMConfigurationError(
    'LLM API key is missing. Configure LLM_API_KEY for backend diagram generation.',
  );
}

/** Create the chat model from the resolved settings (``LLMFactory.create(**kwargs)``). */
export async function create_backend_llm(settings: WebSettings): Promise<BaseChatModel> {
  const config = resolve_backend_llm_config(settings);
  return LLMFactory.create_kw(config.as_factory_kwargs());
}
