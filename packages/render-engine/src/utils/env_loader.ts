// Ported from evodesign/utils/env_loader.py — keep in sync.
// server-only
//
// Centralized environment variable loader for the EvoDesign project.
//
// This module loads the repository-root `.env` once at import time.
//
// All other modules should use ``ensure_env_loaded`` instead of reading
// `.env` themselves. ``os.environ`` reads go through ``py/env.ts getEnv``;
// writes go to ``process.env`` (and to the getEnv override table when one
// shadows the variable). python-dotenv is replaced by ``_parse_dotenv``
// below (the subset of python-dotenv's grammar that `.env.example` uses).

import { existsSync, readFileSync, statSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { getEnv, setEnv } from '../py/env.ts';
import { pyStrip } from '../py/str.ts';

export let _loaded = false;

export const _STEPFUN_MODEL_NAME = 'step-3.7-flash';
export const _STEPFUN_BASE_URL = 'https://api.stepfun.com/v1';
export const _PLACEHOLDER_SECRET_VALUES = new Set([
  'your_api_key_here',
  'your_stepfun_api_key_here',
  'your_backend_llm_api_key_here',
  'your_jwt_secret_here',
  'your_session_secret_here',
  'your-jwt-secret-here',
  'your-session-secret-here',
  'change-me-for-local-dev',
  'changeme',
]);

// evodesign root: parent of utils/ (this file lives in
// packages/render-engine/src/utils/, the Python one in evodesign/utils/).
const _REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..', '..', '..');
const _EVO_ROOT = join(_REPO_ROOT, 'evodesign');

/**
 * Return the single supported .env file.
 *
 * Only the repository-root .env is supported. Existing process env vars still
 * have the highest priority.
 */
export function _find_env_files(): string[] {
  const candidates = [join(_REPO_ROOT, '.env')];
  return candidates.filter((p) => existsSync(p) && statSync(p).isFile());
}

/** Return whether a configured secret/key is an example placeholder. */
export function is_placeholder_secret(value: unknown): boolean {
  if (typeof value !== 'string') {
    return false;
  }
  const normalized = pyStrip(value).toLowerCase();
  if (!normalized) {
    return false;
  }
  const normalized_slug = normalized.split('-').join('_');
  if (_PLACEHOLDER_SECRET_VALUES.has(normalized) || _PLACEHOLDER_SECRET_VALUES.has(normalized_slug)) {
    return true;
  }
  return (
    normalized.startsWith('your_')
    || normalized.startsWith('your-')
    || normalized.startsWith('change-me')
    || normalized.endsWith('_here')
    || normalized.endsWith('-here')
  );
}

/** ``os.environ[name] = value`` */
export function _set_environ(name: string, value: string): void {
  const proc = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process;
  if (proc?.env) proc.env[name] = value;
  if (getEnv(name) !== value) setEnv(name, value);
}

/**
 * Load .env files if not already loaded. Safe to call multiple times.
 *
 * Loads only the repo-root .env. Like ``load_dotenv(override=False)``,
 * explicit process environment values win.
 */
export function ensure_env_loaded(): void {
  if (_loaded) {
    _apply_stepfun_legacy_llm_defaults();
    return;
  }

  const env_files = _find_env_files();
  if (env_files.length) {
    for (const env_file of env_files) {
      load_dotenv(env_file);
    }
  }
  _apply_stepfun_legacy_llm_defaults();
  _loaded = true;
}

export const _LEGACY_LLM_ENV_NAMES = [
  'LLM_MODEL_PROVIDER',
  'LLM_MODEL_NAME',
  'LLM_ENDPOINT_URL',
  'LLM_API_KEY',
] as const;

/**
 * Map the canonical StepFun key to legacy LLM_* settings.
 *
 * The mapping applies only when none of the LLM_* variables is set.
 */
export function _apply_stepfun_legacy_llm_defaults(): void {
  const stepfun_api_key = getEnv('STEPFUN_API_KEY');
  if (!stepfun_api_key) {
    return;
  }
  if (is_placeholder_secret(stepfun_api_key)) {
    return;
  }

  // All-or-nothing: filling only the unset names would mix configurations,
  // e.g. send the StepFun key to a user-configured LLM_ENDPOINT_URL.
  if (_LEGACY_LLM_ENV_NAMES.some((name) => getEnv(name))) {
    return;
  }

  _set_environ('LLM_MODEL_PROVIDER', 'openai');
  _set_environ('LLM_MODEL_NAME', _STEPFUN_MODEL_NAME);
  _set_environ('LLM_ENDPOINT_URL', _STEPFUN_BASE_URL);
  _set_environ('LLM_API_KEY', stepfun_api_key);
}

// ── python-dotenv replacement ─────────────────────────────────────────────

/** ``dotenv.load_dotenv(path, override=False)`` */
export function load_dotenv(path: string, override = false): boolean {
  const values = _parse_dotenv(readFileSync(path, 'utf-8'));
  for (const [key, value] of values) {
    if (getEnv(key) !== null && !override) continue;
    if (value !== null) _set_environ(key, value);
  }
  return values.size > 0;
}

const DOUBLE_QUOTE_ESCAPES: Record<string, string> = {
  '\\': '\\', "'": "'", '"': '"', a: '\x07', b: '\b', f: '\f', n: '\n', r: '\r', t: '\t', v: '\v',
};

/**
 * python-dotenv ``dotenv_values`` (interpolate=True): ``[export] KEY=value``
 * lines, single quotes (literal), double quotes (escapes + ``${VAR}``),
 * unquoted values (inline `` #`` comments stripped, ``${VAR}`` expanded),
 * ``KEY`` without ``=`` → None. Variables expand from the process environment
 * first (override=False), then from earlier lines of the file.
 */
export function _parse_dotenv(text: string): Map<string, string | null> {
  const result = new Map<string, string | null>();
  const source = text.replace(/^﻿/, '');
  let pos = 0;
  const expand = (value: string): string => value.replace(/\$\{([^}:]+)(?::-([^}]*))?\}/g, (_m, name: string, fallback: string | undefined) => {
    const fromEnv = getEnv(name);
    if (fromEnv !== null) return fromEnv;
    const fromFile = result.get(name);
    if (fromFile !== undefined && fromFile !== null) return fromFile;
    return fallback ?? '';
  });
  while (pos < source.length) {
    const lineEnd = source.indexOf('\n', pos);
    const rawLine = source.slice(pos, lineEnd < 0 ? source.length : lineEnd);
    const match = /^\s*(?:export\s+)?([A-Za-z_][\w.-]*|'[^']*'|"[^"]*")\s*(=)?\s*/.exec(rawLine);
    if (!match || /^\s*#/.test(rawLine)) {
      pos = lineEnd < 0 ? source.length : lineEnd + 1;
      continue;
    }
    let key = match[1];
    if (key.startsWith("'") || key.startsWith('"')) key = key.slice(1, -1);
    if (!match[2]) {
      result.set(key, null);
      pos = lineEnd < 0 ? source.length : lineEnd + 1;
      continue;
    }
    const valueStart = pos + match[0].length;
    const quote = source[valueStart];
    if (quote === "'" || quote === '"') {
      // Quoted values may span lines.
      let i = valueStart + 1;
      let value = '';
      while (i < source.length && source[i] !== quote) {
        if (quote === '"' && source[i] === '\\' && i + 1 < source.length && source[i + 1] in DOUBLE_QUOTE_ESCAPES) {
          value += DOUBLE_QUOTE_ESCAPES[source[i + 1]];
          i += 2;
          continue;
        }
        if (quote === "'" && source[i] === '\\' && (source[i + 1] === "'" || source[i + 1] === '\\')) {
          value += source[i + 1];
          i += 2;
          continue;
        }
        value += source[i];
        i += 1;
      }
      result.set(key, quote === '"' ? expand(value) : value);
      const after = source.indexOf('\n', i);
      pos = after < 0 ? source.length : after + 1;
      continue;
    }
    let value = rawLine.slice(match[0].length);
    const comment = /\s+#.*$/.exec(value);
    if (comment) value = value.slice(0, comment.index);
    result.set(key, expand(value.replace(/\s+$/, '')));
    pos = lineEnd < 0 ? source.length : lineEnd + 1;
  }
  return result;
}

export { _EVO_ROOT, _REPO_ROOT };

// Auto-load on import
ensure_env_loaded();
