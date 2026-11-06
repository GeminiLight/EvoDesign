// Ported from evodesign/config/model_loader.py — keep in sync.
// server-only
//
// Load model/provider configuration from ``configs/models.yaml`` and roles from settings.
//
//     const cfg = new ModelConfig();                  // loads configs/models.yaml + settings roles
//     const params = cfg.get_model_config('generator'); // → dict ready for LLMFactory.create()
//     const model = await LLMFactory.create_from_config(cfg, 'generator');
//
// Python's ``**overrides`` keyword arguments become a trailing object.

import { existsSync, readFileSync } from '../py/fs.ts';
import { dirname, join, resolve } from '../py/path.ts';
import { getPlatform } from '../py/platform.ts';
import { KeyError, ValueError } from '../py/errors.ts';
import { getEnv } from '../py/env.ts';
import { getLogger } from '../py/logging.ts';
import { pyRepr, pyStr, pyStrip } from '../py/str.ts';
import { truthy } from '../py/truthy.ts';
import { pySorted } from '../py/sort.ts';
import { yamlSafeLoad } from '../py/yaml.ts';
import { is_placeholder_secret, ensure_env_loaded } from '../utils/env_loader.ts';
import { AppSettings, FileNotFoundError } from './settings.ts';

const logger = getLogger('evodesign.config.model_loader');

export let _PROJECT_ROOT = getPlatform().repoRoot;
// ``importlib.resources.files("evodesign.config.defaults")`` — the installed package, not _PROJECT_ROOT.
const _PACKAGED_DEFAULTS_DIR = join(getPlatform().repoRoot, 'evodesign', 'config', 'defaults');

/** Test hook: Python tests monkeypatch ``_PROJECT_ROOT``. */
export function _set_project_root(path: string): void {
  _PROJECT_ROOT = path;
}

export function _default_models_path(): string {
  const repo_path = join(_PROJECT_ROOT, 'configs', 'models.yaml');
  if (existsSync(repo_path)) {
    return repo_path;
  }
  return join(_PACKAGED_DEFAULTS_DIR, 'models.yaml');
}

export const _DEFAULT_PATH = _default_models_path();

// YAML model keys that map directly to LLMFactory.create() params.
export const _MODEL_TO_FACTORY: Record<string, string> = {
  model_name: 'model',
  provider: 'model_provider',
  temperature: 'temperature',
  max_tokens: 'max_tokens',
  timeout: 'timeout',
  max_retries: 'max_retries',
  reasoning_effort: 'reasoning_effort',
  thinking: 'thinking',
};

// Optional model keys whose ``$ENV`` reference may stay unset without a warning.
export const _OPTIONAL_ENV_KEYS = new Set(['thinking']);

// YAML provider keys that map to LLMFactory.create() params.
export const _PROVIDER_TO_FACTORY: Record<string, string> = {
  base_url: 'base_url',
  api_key: 'api_key',
};

/** Load repository-root .env before resolving provider api_key entries. */
export function _ensure_project_env_loaded(): void {
  ensure_env_loaded();
}

const has = (obj: Record<string, unknown>, key: string): boolean => Object.prototype.hasOwnProperty.call(obj, key);
const get = (obj: Record<string, unknown>, key: string, defaultValue: unknown = null): unknown => (has(obj, key) ? obj[key] : defaultValue);

/** ``str(list)`` of strings, e.g. ``['a', 'b']``. */
const listRepr = (items: string[]): string => pyRepr(items);

/**
 * Resolve role → model → provider chains from ``models.yaml`` + ``settings.yaml``.
 *
 * Providers and models are defined in ``models.yaml``. Roles (which model
 * powers which pipeline stage) are defined in ``settings.yaml`` under ``roles``.
 */
export class ModelConfig {
  static _instance: ModelConfig | null = null;
  static _override_path: string | null = null;

  _path: string;
  _raw: Record<string, unknown>;
  _providers: Record<string, Record<string, unknown>>;
  _models: Record<string, Record<string, unknown>>;
  _roles: Record<string, string>;

  constructor(path: string = _DEFAULT_PATH) {
    _ensure_project_env_loaded();

    this._path = path;
    if (!existsSync(this._path)) {
      throw new FileNotFoundError(`Model config not found: ${this._path}`);
    }
    const loaded = yamlSafeLoad(readFileSync(this._path, 'utf-8'));
    this._raw = (truthy(loaded) ? loaded : {}) as Record<string, unknown>;

    this._providers = get(this._raw, 'providers', {}) as Record<string, Record<string, unknown>>;
    this._models = get(this._raw, 'models', {}) as Record<string, Record<string, unknown>>;
    // Roles live in settings.yaml, not models.yaml
    const settings = AppSettings.get_default();
    this._roles = settings.roles;
  }

  // ── singleton ────────────────────────────────────────────────────────

  /** Override the default path (call before ``get_default()``). */
  static init(path: string): void {
    ModelConfig._override_path = path;
    ModelConfig._instance = null; // force reload on next get_default()
  }

  /** Return the shared instance, creating it on first access. */
  static get_default(): ModelConfig {
    if (ModelConfig._instance === null) {
      ModelConfig._instance = new ModelConfig(ModelConfig._override_path ?? _DEFAULT_PATH);
    }
    return ModelConfig._instance;
  }

  // ── public API ──────────────────────────────────────────────────────

  /**
   * Resolve *role* to a flat dict ready for ``LLMFactory.create()``.
   *
   * Resolution chain (highest to lowest precedence):
   * 1. ``overrides`` — CLI flags (e.g. ``temperature=0.7``)
   * 2. ``settings.yaml`` roles → ``models.yaml`` models → providers
   */
  get_model_config(role: string, overrides: Record<string, unknown> = {}): Record<string, unknown> {
    if (!has(this._roles, role)) {
      throw new KeyError(
        `Role ${pyRepr(role)} not found in settings.yaml (roles section). `
        + `Available roles: ${listRepr(Object.keys(this._roles))}`,
      );
    }

    // ── resolve YAML chain first (role → model → provider) ──
    const yaml_model_name = this._roles[role];
    const model_cfg = this._get_model(yaml_model_name);
    const provider_name = get(model_cfg, 'provider') as string | null;
    const provider_cfg = truthy(provider_name) ? this._get_provider(provider_name) : {};

    return this._resolve_model_config(model_cfg, provider_name, provider_cfg, overrides);
  }

  /** Resolve a concrete model alias from ``models.yaml``. */
  get_named_model_config(model_alias: string, overrides: Record<string, unknown> = {}): Record<string, unknown> {
    const model_cfg = this._get_model(model_alias);
    const provider_name = get(model_cfg, 'provider') as string | null;
    const provider_cfg = truthy(provider_name) ? this._get_provider(provider_name) : {};
    return this._resolve_model_config(model_cfg, provider_name, provider_cfg, overrides);
  }

  /** Return whether ``model_alias`` is a declared ``models.yaml`` key. */
  has_model(model_alias: string): boolean {
    return has(this._models, model_alias);
  }

  /** Return ``{role_name: model_name}`` mapping. */
  list_roles(): Record<string, string> {
    return { ...this._roles };
  }

  /** Return available model names. */
  list_models(): string[] {
    return Object.keys(this._models);
  }

  /** Return available provider names. */
  list_providers(): string[] {
    return Object.keys(this._providers);
  }

  /**
   * Return declared capabilities for the model assigned to ``role``.
   * Models default to ``{"text"}`` when the field is omitted.
   */
  get_model_capabilities(role: string): Set<string> {
    if (!has(this._roles, role)) {
      throw new KeyError(
        `Role ${pyRepr(role)} not found in settings.yaml (roles section). `
        + `Available roles: ${listRepr(Object.keys(this._roles))}`,
      );
    }
    const model_alias = this._roles[role];
    const model_cfg = this._get_model(model_alias);
    const raw = get(model_cfg, 'capabilities', ['text']);
    let values: unknown[];
    if (typeof raw === 'string') {
      values = [raw];
    } else if (Array.isArray(raw)) {
      values = raw;
    } else {
      throw new ValueError(`Model ${pyRepr(model_alias)} capabilities must be a string or list.`);
    }
    const capabilities = new Set(
      values.filter((value) => pyStrip(pyStr(value))).map((value) => pyStrip(pyStr(value)).toLowerCase()),
    );
    return capabilities.size ? capabilities : new Set(['text']);
  }

  /** Fail fast when ``role`` lacks any required model capability. */
  require_model_capabilities(role: string, required: Set<string>): void {
    const capabilities = this.get_model_capabilities(role);
    const missing = new Set([...required].map((capability) => capability.toLowerCase()).filter((capability) => !capabilities.has(capability)));
    if (missing.size) {
      const model_alias = has(this._roles, role) ? this._roles[role] : '<unknown>';
      throw new ValueError(
        `Model role ${pyRepr(role)} uses ${pyRepr(model_alias)}, which lacks required `
        + `capabilities: ${listRepr(pySorted(missing))}. Declared capabilities: `
        + `${listRepr(pySorted(capabilities))}.`,
      );
    }
  }

  get path(): string {
    return this._path;
  }

  // ── internals ───────────────────────────────────────────────────────

  _get_model(name: string): Record<string, unknown> {
    if (!has(this._models, name)) {
      throw new KeyError(
        `Model ${pyRepr(name)} not found in ${this._path}. `
        + `Available models: ${listRepr(Object.keys(this._models))}`,
      );
    }
    return { ...this._models[name] };
  }

  _get_provider(name: string | null): Record<string, unknown> {
    if (!truthy(name)) {
      return {};
    }
    if (!has(this._providers, name!)) {
      throw new KeyError(
        `Provider ${pyRepr(name)} not found in ${this._path}. `
        + `Available providers: ${listRepr(Object.keys(this._providers))}`,
      );
    }
    return { ...this._providers[name!] };
  }

  /** Flatten a model/provider pair into ``LLMFactory.create`` kwargs. */
  _resolve_model_config(
    model_cfg: Record<string, unknown>,
    provider_name: string | null,
    provider_cfg: Record<string, unknown>,
    overrides: Record<string, unknown> = {},
  ): Record<string, unknown> {
    const result: Record<string, unknown> = {};

    // Provider-level keys (base_url, api_key)
    for (const [yaml_key, factory_key] of Object.entries(_PROVIDER_TO_FACTORY)) {
      if (yaml_key === 'api_key') {
        continue; // handled separately below
      }
      const val = get(provider_cfg, yaml_key);
      if (val !== null) {
        result[factory_key] = ModelConfig._resolve_value(val);
      }
    }

    // api_key must be declared by the provider config.
    result.api_key = this._resolve_api_key(provider_cfg, provider_name);

    // Model-level keys (model_name→model, temperature, timeout, etc.)
    for (const [yaml_key, factory_key] of Object.entries(_MODEL_TO_FACTORY)) {
      if (yaml_key === 'provider') {
        continue; // handled specially via protocol
      }
      let val = get(model_cfg, yaml_key);
      if (val !== null) {
        if (_OPTIONAL_ENV_KEYS.has(yaml_key)) {
          const env_var = ModelConfig._env_var_reference(val);
          val = env_var ? getEnv(env_var) : val;
          if (val === null || !pyStrip(pyStr(val))) {
            continue;
          }
        }
        const resolved = has(overrides, factory_key)
          ? overrides[factory_key]
          : (yaml_key === 'model_name' ? ModelConfig._resolve_value(val) : val);
        if (yaml_key === 'model_name' && (typeof resolved !== 'string' || !pyStrip(resolved))) {
          throw new ValueError('Model name is empty; set LLM_MODEL_NAME (or the model_name environment reference in models.yaml).');
        }
        result[factory_key] = resolved;
      }
    }

    // Resolve model_provider: use the provider's `provider` field (the
    // langchain protocol) if available, otherwise fall back to the provider name.
    const langchain_provider = get(provider_cfg, 'provider');
    if (truthy(langchain_provider)) {
      result.model_provider = langchain_provider;
    } else if (truthy(provider_name)) {
      result.model_provider = provider_name;
    }

    // Overrides (CLI flags, etc.) take highest precedence
    Object.assign(result, overrides);

    // Remove incidental None values so LLMFactory defaults kick in. Keep
    // api_key explicit.
    return Object.fromEntries(Object.entries(result).filter(([k, v]) => v !== null || k === 'api_key'));
  }

  /**
   * Resolve a YAML value that may reference an environment variable
   * (``env:VAR``, ``$VAR``, ``${VAR}``); returns ``null`` if the env var is not set.
   */
  static _resolve_value(raw: unknown): unknown {
    if (typeof raw !== 'string') {
      return raw;
    }

    let env_var: string | null = null;
    if (raw.startsWith('env:')) {
      env_var = pyStrip(raw.slice(4));
    } else if (raw.startsWith('${') && raw.endsWith('}')) {
      env_var = pyStrip(raw.slice(2, -1));
    } else if (raw.startsWith('$')) {
      env_var = pyStrip(raw.slice(1));
    }

    if (env_var !== null) {
      const val = getEnv(env_var);
      if (val === null) {
        logger.warning('models.yaml references env var %s which is not set', env_var);
      }
      return val;
    }
    return raw;
  }

  /** Return the env var name a YAML api_key entry points at, if any. */
  static _env_var_reference(raw: unknown): string | null {
    if (typeof raw !== 'string') {
      return null;
    }
    if (raw.startsWith('env:')) {
      return pyStrip(raw.slice(4)) || null;
    }
    if (raw.startsWith('${') && raw.endsWith('}')) {
      return pyStrip(raw.slice(2, -1)) || null;
    }
    if (raw.startsWith('$')) {
      return pyStrip(raw.slice(1)) || null;
    }
    return null;
  }

  /** Describe where a provider api_key came from, without leaking secrets. */
  _describe_api_key_source(raw: unknown): string {
    const env_var = ModelConfig._env_var_reference(raw);
    if (env_var) {
      return `environment variable ${env_var} (referenced from ${this._path} as ${pyRepr(raw)})`;
    }
    return `an inline api_key literal in ${this._path}`;
  }

  /** Resolve api_key with env-var support. */
  _resolve_api_key(provider_cfg: Record<string, unknown>, provider_name: string | null = null): string | null {
    const raw = get(provider_cfg, 'api_key');
    if (raw !== null) {
      const val = ModelConfig._resolve_value(raw);
      if (val !== null) {
        if (typeof val === 'string' && !pyStrip(val)) {
          return null;
        }
        if (is_placeholder_secret(val)) {
          const provider_label = provider_name || '<unnamed>';
          throw new ValueError(
            `Provider ${pyRepr(provider_label)} api_key resolves to an example `
            + `placeholder. Source: ${this._describe_api_key_source(raw)}. `
            + 'Set a real API key there. If this already is your real key, '
            + 'it matched the placeholder heuristic in '
            + 'evodesign/utils/env_loader.py (values starting with '
            + "'your_'/'your-'/'change-me' or ending with '_here'/'-here'); "
            + 're-issue or rename the key so it no longer matches.',
          );
        }
        return val as string;
      }
    }
    return null;
  }
}

export const __all__ = ['ModelConfig'];
