// Ported from evodesign/config/settings.py — keep in sync.
// server-only
//
// Load application settings from ``configs/settings.yaml`` with env-var overrides.
//
//     const settings = AppSettings.get_default();
//     const db_path = settings.design_memory_vector_db_path;
//
// Singleton: ``AppSettings.get_default()`` returns (or creates) the shared
// instance. ``AppSettings.init(path)`` overrides the default path (e.g. from
// a CLI ``--settings`` flag) before first access.
//
// Each YAML value can be overridden by its corresponding env var
// (``_ENV_OVERRIDES``). If the env var is set, it takes precedence.

import { existsSync, homedir, readFileSync, realpathSync } from '../py/fs.ts';
import { dirname, isAbsolute, join, resolve } from '../py/path.ts';
import { getPlatform } from '../py/platform.ts';
import { ValueError } from '../py/errors.ts';
import { getEnv } from '../py/env.ts';
import { getLogger } from '../py/logging.ts';
import { pyRepr, pyStr, pyStrip } from '../py/str.ts';
import { isDict, truthy } from '../py/truthy.ts';
import { yamlSafeLoad } from '../py/yaml.ts';

const logger = getLogger('evodesign.config.settings');

// Path(__file__).resolve().parents[2] — the repository root.
export let _PROJECT_ROOT = getPlatform().repoRoot;
// ``importlib.resources.files("evodesign.config.defaults")`` — the installed package, not _PROJECT_ROOT.
const _PACKAGED_DEFAULTS_DIR = join(getPlatform().repoRoot, 'evodesign', 'config', 'defaults');

/** Test hook: Python tests monkeypatch ``_PROJECT_ROOT``. */
export function _set_project_root(path: string): void {
  _PROJECT_ROOT = path;
}

export class FileNotFoundError extends Error {
  override name = 'FileNotFoundError';
}

export function _default_settings_path(): string {
  const repo_path = join(_PROJECT_ROOT, 'configs', 'settings.yaml');
  if (existsSync(repo_path)) {
    return repo_path;
  }
  return join(_PACKAGED_DEFAULTS_DIR, 'settings.yaml');
}

export const _DEFAULT_PATH = _default_settings_path();

// YAML dotted-path → env var name. When the env var is set, it overrides the YAML value.
export const _ENV_OVERRIDES: Record<string, string> = {
  'experiment.id': 'EVO_EXPERIMENT_ID',
  'services.render_url': 'RENDER_SERVICE_URL',
  'services.tool_service_url': 'TOOL_SERVICE_URL',
  'canvas.library': 'CANVAS_LIBRARY',
  'design_memory.vector_db_path': 'DESIGN_MEMORY_VECTOR_DB_PATH',
  'design_memory.embedding_model': 'DESIGN_MEMORY_EMBEDDING_MODEL',
  'user_preference.memory_path': 'USER_PREFERENCE_MEMORY_PATH',
  'user_preference.embedding_model': 'USER_PREFERENCE_EMBEDDING_MODEL',
  'generation.mode': 'GENERATION_MODE',
  'generation.enable_refiner': 'ENABLE_REFINER',
  'generation.use_icons': 'USE_ICONS',
  'generation.structure_self_consistency_n': 'STRUCTURE_SELF_CONSISTENCY_N',
  'generation.full_domain_knowledge': 'FULL_DOMAIN_KNOWLEDGE',
  'render.fix_zorder': 'EVODESIGN_RENDER_FIX_ZORDER',
  'render.icon_base_url': 'ICON_BASE_URL',
};

export const VALID_GENERATION_MODES = ['multiagent', 'oneshot'] as const;
export const MAX_STRUCTURE_SELF_CONSISTENCY_N = 9;

/**
 * Normalize the configured generation mode.
 *
 * Only the current public mode names are accepted. Legacy aliases such as
 * ``pipeline`` and ``unified`` are intentionally rejected.
 */
export function normalize_generation_mode(raw: unknown): string {
  const value = pyStrip(pyStr(raw)).toLowerCase();
  if ((VALID_GENERATION_MODES as readonly string[]).includes(value)) {
    return value;
  }
  throw new ValueError(`Unknown generation mode: ${pyRepr(raw)}. Use 'multiagent' or 'oneshot'.`);
}

/** ``Path(p).resolve()`` (strict=False): absolute, symlinks of the existing prefix resolved. */
export function _path_resolve(path: string): string {
  const absolute = resolve(path);
  let existing = absolute;
  const rest: string[] = [];
  while (!existsSync(existing)) {
    const parent = dirname(existing);
    if (parent === existing) return absolute;
    rest.unshift(existing.slice(parent.length).replace(/^[\\/]/, ''));
    existing = parent;
  }
  return join(realpathSync(existing), ...rest);
}

/** ``str(PurePosixPath(p))``: collapse ``//`` and ``/./``, drop a trailing ``/`` (``..`` is kept). */
export function _pure_path_str(path: string): string {
  const absolute = path.startsWith('/');
  const parts = path.split('/').filter((part) => part && part !== '.');
  const joined = parts.join('/');
  if (absolute) return `/${joined}`;
  return joined || '.';
}

/** ``int(raw)`` with Python's acceptance rules for str/float/bool/int. */
function pyIntConvert(raw: unknown): number {
  if (typeof raw === 'boolean') return raw ? 1 : 0;
  if (typeof raw === 'number') {
    if (!Number.isFinite(raw)) throw new ValueError(`cannot convert float ${raw} to integer`);
    return Math.trunc(raw);
  }
  if (typeof raw === 'string') {
    const text = pyStrip(raw).replace(/_/g, (m, offset: number, s: string) => (/\d/.test(s[offset - 1] ?? '') && /\d/.test(s[offset + 1] ?? '') ? '' : m));
    if (/^[-+]?\d+$/.test(text)) return Number(text);
    throw new ValueError(`invalid literal for int() with base 10: ${pyRepr(raw)}`);
  }
  throw new TypeError(`int() argument must be a string, a bytes-like object or a real number, not '${raw === null ? 'NoneType' : typeof raw}'`);
}

/** ``float(raw)`` */
function pyFloatConvert(raw: unknown): number {
  if (typeof raw === 'number') return raw;
  if (typeof raw === 'boolean') return raw ? 1 : 0;
  if (typeof raw === 'string') {
    const text = pyStrip(raw).replace(/_/g, '');
    if (/^[-+]?(?:\d+\.?\d*(?:[eE][-+]?\d+)?|\.\d+(?:[eE][-+]?\d+)?|inf(?:inity)?|nan)$/i.test(text)) {
      const lower = text.toLowerCase();
      if (lower.endsWith('inf') || lower.endsWith('infinity')) return lower.startsWith('-') ? -Infinity : Infinity;
      if (lower.endsWith('nan')) return NaN;
      return Number(text);
    }
    throw new ValueError(`could not convert string to float: ${pyRepr(raw)}`);
  }
  throw new TypeError(`float() argument must be a string or a real number, not '${raw === null ? 'NoneType' : typeof raw}'`);
}

/** Resolve application settings from ``settings.yaml`` + env vars. */
export class AppSettings {
  static _instance: AppSettings | null = null;
  static _override_path: string | null = null;

  _path: string;
  _raw: Record<string, unknown>;

  constructor(path: string = _DEFAULT_PATH) {
    this._path = path;
    if (!existsSync(this._path)) {
      throw new FileNotFoundError(`Settings file not found: ${this._path}`);
    }
    this._path = _path_resolve(this._path);
    const loaded = yamlSafeLoad(readFileSync(this._path, 'utf-8'));
    this._raw = (truthy(loaded) ? loaded : {}) as Record<string, unknown>;
  }

  // ── singleton ────────────────────────────────────────────────────────

  /** Override the default path (call before ``get_default()``). */
  static init(path: string): void {
    AppSettings._override_path = path;
    AppSettings._instance = null; // force reload on next get_default()
  }

  /** Return the shared instance, creating it on first access. */
  static get_default(): AppSettings {
    if (AppSettings._instance === null) {
      AppSettings._instance = new AppSettings(AppSettings._override_path ?? _DEFAULT_PATH);
    }
    return AppSettings._instance;
  }

  // ── raw access ──────────────────────────────────────────────────────

  /**
   * Access a value by ``section.key`` dotted path.
   *
   * Env var override is applied if present. An env var that is set but empty
   * is treated as "not configured" and falls back to the YAML value.
   */
  get_raw(dotted_key: string, defaultValue: unknown = null): unknown {
    const env_var = _ENV_OVERRIDES[dotted_key];
    if (env_var) {
      const env_val = getEnv(env_var);
      if (env_val !== null) {
        if (pyStrip(env_val)) {
          return env_val;
        }
        logger.warning(
          'Environment variable %s is set but empty; ignoring it and using the %s value from %s. Remove the line or give it a value to override the config.',
          env_var,
          dotted_key,
          this._path,
        );
      }
    }

    const dot = dotted_key.indexOf('.');
    const section = dot < 0 ? dotted_key : dotted_key.slice(0, dot);
    const key = dot < 0 ? '' : dotted_key.slice(dot + 1);
    const section_data = Object.prototype.hasOwnProperty.call(this._raw, section) ? this._raw[section] : {};
    if (isDict(section_data)) {
      return Object.prototype.hasOwnProperty.call(section_data, key) ? section_data[key] : defaultValue;
    }
    return defaultValue;
  }

  // ── typed accessors ─────────────────────────────────────────────────

  /** Experiment identifier. Falls back to date if 'exp' or empty. */
  get experiment_id(): string {
    return pyStr(this.get_raw('experiment.id', 'exp'));
  }

  /** URL of the TLDraw/Excalidraw PNG render service. */
  get render_service_url(): string {
    return pyStr(this.get_raw('services.render_url', 'http://localhost:3000'));
  }

  /** Base URL of the tool services (dagre layout, icons, etc.). */
  get tool_service_url(): string {
    return pyStr(this.get_raw('services.tool_service_url', 'http://localhost:3000'));
  }

  /** Canvas library: 'excalidraw' or 'tldraw'. */
  get canvas_library(): string {
    return pyStr(this.get_raw('canvas.library', 'excalidraw'));
  }

  get design_memory_vector_db_path(): string {
    return this._resolve_path_setting('design_memory.vector_db_path', '../data/knowledge');
  }

  get design_memory_embedding_model(): string {
    return pyStr(this.get_raw('design_memory.embedding_model', 'Qwen/Qwen3-Embedding-0.6B'));
  }

  get user_preference_memory_path(): string {
    return this._resolve_path_setting('user_preference.memory_path', '../data/user_preferences');
  }

  get user_preference_embedding_model(): string {
    return pyStr(this.get_raw('user_preference.embedding_model', 'Qwen/Qwen3-Embedding-0.6B'));
  }

  /** Generation strategy: 'multiagent' or 'oneshot'. */
  get generation_mode(): string {
    const raw = this.get_raw('generation.mode', 'multiagent');
    try {
      return normalize_generation_mode(raw);
    } catch (exc) {
      if (exc instanceof ValueError) {
        throw new ValueError(`Unknown generation.mode: ${pyRepr(raw)}. Use 'multiagent' or 'oneshot'.`);
      }
      throw exc;
    }
  }

  get generation_enable_refiner(): boolean {
    return this._bool_setting('generation.enable_refiner', true);
  }

  get generation_use_icons(): boolean {
    return this._bool_setting('generation.use_icons', false);
  }

  get structure_self_consistency_n(): number {
    const raw = this.get_raw('generation.structure_self_consistency_n', 1);
    let value: number;
    try {
      value = pyIntConvert(raw);
    } catch {
      throw new ValueError(
        'Invalid integer setting generation.structure_self_consistency_n: '
        + `${pyRepr(raw)}. Use an integer >= 1.`,
      );
    }
    if (value < 1) {
      throw new ValueError(
        'Invalid integer setting generation.structure_self_consistency_n: '
        + `${pyRepr(raw)}. Use an integer >= 1.`,
      );
    }
    if (value > MAX_STRUCTURE_SELF_CONSISTENCY_N) {
      throw new ValueError(
        'Invalid integer setting generation.structure_self_consistency_n: '
        + `${pyRepr(raw)}. Use an integer between 1 and `
        + `${MAX_STRUCTURE_SELF_CONSISTENCY_N}.`,
      );
    }
    return value;
  }

  get full_domain_knowledge(): boolean {
    return this._bool_setting('generation.full_domain_knowledge', true);
  }

  get render_fix_zorder(): boolean {
    return this._bool_setting('render.fix_zorder', true);
  }

  get icon_base_url(): string {
    const defaultValue = 'http://localhost:3000/icons/material-design-icons/{color}/{icon}.svg';
    return pyStr(this.get_raw('render.icon_base_url', defaultValue));
  }

  // ── retriever weights ─────────────────────────────────────────────

  get retriever_utility_weight(): number {
    return pyFloatConvert(this.get_raw('retriever.utility_weight', 0.25));
  }

  get retriever_diversity_weight(): number {
    return pyFloatConvert(this.get_raw('retriever.diversity_weight', 0.20));
  }

  get retriever_exploration_weight(): number {
    return pyFloatConvert(this.get_raw('retriever.exploration_weight', 0.10));
  }

  /** Model role used by evaluation scoring. */
  get evaluation_role(): string {
    return pyStr(this.get_raw('evaluation.role', 'eval'));
  }

  /** Default metric list for evaluation runs. */
  get evaluation_default_metrics(): string[] {
    const raw = this.get_raw('evaluation.default_metrics', []);
    if (Array.isArray(raw)) {
      return raw.map((item) => pyStr(item));
    }
    if (typeof raw === 'string') {
      return raw.split(',').map((item) => pyStrip(item)).filter((item) => item);
    }
    return [];
  }

  /** Role → model name mapping from ``settings.yaml``. */
  get roles(): Record<string, string> {
    const roles = Object.prototype.hasOwnProperty.call(this._raw, 'roles') ? this._raw.roles : {};
    return { ...(roles as Record<string, string>) };
  }

  get path(): string {
    return this._path;
  }

  /** Resolve filesystem path settings relative to the settings file. */
  _resolve_path_setting(dotted_key: string, defaultValue: string): string {
    let raw_path = pyStr(this.get_raw(dotted_key, defaultValue));
    // Path.expanduser()
    if (raw_path === '~' || raw_path.startsWith('~/')) raw_path = homedir() + raw_path.slice(1);
    if (isAbsolute(raw_path)) {
      return _pure_path_str(raw_path);
    }
    return _path_resolve(join(dirname(this._path), raw_path));
  }

  _bool_setting(dotted_key: string, defaultValue: boolean): boolean {
    const raw = this.get_raw(dotted_key, defaultValue);
    if (typeof raw === 'boolean') {
      return raw;
    }
    const val = pyStrip(pyStr(raw)).toLowerCase();
    if (['1', 'true', 'yes', 'on'].includes(val)) {
      return true;
    }
    if (['0', 'false', 'no', 'off'].includes(val)) {
      return false;
    }
    throw new ValueError(
      `Invalid boolean setting ${dotted_key}: ${pyRepr(raw)}. `
      + 'Use true/false, yes/no, on/off, or 1/0.',
    );
  }
}

export const __all__ = ['AppSettings', 'VALID_GENERATION_MODES', 'normalize_generation_mode'];
