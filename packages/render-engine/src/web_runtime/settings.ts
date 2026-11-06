// The subset of backend ``app.config.Settings`` the generation stream reads
// (PHASE3_PLAN.md WP29). In the browser there is no .env: the caller passes
// the values; defaults equal the backend's, except that design memory is off
// (design memory and learning are not part of the browser runtime; with them
// off the stream behaves exactly like the backend with memory disabled).

export interface WebSettings {
  llm_model_name: string | null;
  llm_model_provider: string;
  llm_api_key: string | null;
  llm_endpoint_url: string | null;
  llm_temperature: number;
  llm_max_tokens: number;
  llm_reasoning_effort: 'low' | 'medium' | 'high' | null;
  llm_thinking: 'enabled' | 'disabled' | null;
  canvas_library: string;
  results_dir: string;
  auto_refine_enabled: boolean;
  auto_refine_max_iterations: number;
  design_memory_enabled: boolean;
  design_memory_path: string;
  design_memory_seed_path: string;
  design_memory_model: string;
  design_memory_top_k: number;
  design_memory_learning: boolean;
  retain_generation_artifacts: boolean;
}

export const WEB_SETTINGS_DEFAULTS: Readonly<WebSettings> = Object.freeze({
  llm_model_name: null,
  llm_model_provider: 'openai',
  llm_api_key: null,
  llm_endpoint_url: null,
  llm_temperature: 0.0,
  llm_max_tokens: 16384,
  llm_reasoning_effort: null,
  llm_thinking: null,
  canvas_library: 'excalidraw',
  results_dir: 'results',
  auto_refine_enabled: true,
  auto_refine_max_iterations: 2,
  // backend default: True (memory is not ported; see the module comment)
  design_memory_enabled: false,
  design_memory_path: 'data/web-design-memory',
  design_memory_seed_path: 'evodesign/design_memory/seeds/web_strategies.json',
  design_memory_model: 'Qwen/Qwen3-Embedding-0.6B',
  design_memory_top_k: 2,
  // backend default: True (only for signed-in users, which the browser runtime has none of)
  design_memory_learning: false,
  retain_generation_artifacts: false,
});

/** Merge caller settings over the defaults; unknown keys (e.g. a redacted api key marker) are kept. */
export function resolveWebSettings(overrides: Partial<WebSettings> & Record<string, unknown> = {}): WebSettings {
  const settings = { ...WEB_SETTINGS_DEFAULTS } as WebSettings & Record<string, unknown>;
  for (const [key, value] of Object.entries(overrides)) {
    if (value !== undefined) settings[key] = value;
  }
  const iterations = settings.auto_refine_max_iterations;
  if (!Number.isInteger(iterations) || iterations < 1 || iterations > 3) {
    throw new RangeError(`auto_refine_max_iterations must be an integer in [1, 3], got ${String(iterations)}`);
  }
  const topK = settings.design_memory_top_k;
  if (!Number.isInteger(topK) || topK < 1 || topK > 5) {
    throw new RangeError(`design_memory_top_k must be an integer in [1, 5], got ${String(topK)}`);
  }
  return settings;
}
