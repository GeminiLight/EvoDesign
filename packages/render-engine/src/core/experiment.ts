// Ported from evodesign/core/experiment.py — keep in sync.
// server-only
//
// Experiment directory management.
//
//     experiments/{exp_id}/
//         outputs/
//             baseline/{algo}/{model}/{sample_id}/render.png
//             evodesign/{variant}/{model}/{sample_id}/rendered_diagram.png
//         scores/
//             baseline/{algo}/{model}/{sample_id}.json
//             evodesign/{variant}/{model}/{sample_id}.json
//
// Configuration priority (highest first):
//     1. Environment variable EVO_EXPERIMENT_ID
//     2. settings.yaml -> experiment.id ("exp" or empty → date)
//     3. Auto-generated date (YYYY-MM-DD)

import { existsSync, mkdirSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { ValueError } from '../py/errors.ts';
import { getEnv } from '../py/env.ts';
import { pyStr, pyStrip } from '../py/str.ts';
import { truthy } from '../py/truthy.ts';
import { safe_join_under, safe_path_segment } from '../utils/path_manager.ts';
import { AppSettings } from '../config/settings.ts';

export let _PROJECT_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..', '..', '..');

/** Test hook: Python tests monkeypatch ``experiment._PROJECT_ROOT``. */
export function _set_project_root(path: string): void {
  _PROJECT_ROOT = path;
}

const startsWithAny = (name: string, prefixes: string[]): boolean => prefixes.some((prefix) => name.startsWith(prefix));

/** Accept historical method IDs while writing the EvoDesign spelling. */
export function canonical_method_name(name: string): string {
  if (name === 'evodiagram' || startsWithAny(name, ['evodiagram_', 'evodiagram-', 'evodiagram/'])) {
    return 'evodesign' + name.slice('evodiagram'.length);
  }
  return name;
}

/** Map a canonical research method to its historical storage identifier. */
export function legacy_method_name(name: string): string {
  if (name === 'evodesign' || startsWithAny(name, ['evodesign_', 'evodesign-', 'evodesign/'])) {
    return 'evodiagram' + name.slice('evodesign'.length);
  }
  return name;
}

/** ``Path(path).parts`` for POSIX paths. */
function pathParts(path: string): string[] {
  const parts = path.split('/').filter((part) => part && part !== '.');
  return path.startsWith('/') ? ['/', ...parts] : parts;
}

function joinParts(parts: string[]): string {
  if (parts[0] === '/') return '/' + parts.slice(1).join('/');
  return parts.join('/') || '.';
}

/** Map only the experiment namespace/variant, preserving model/sample IDs. */
export function legacy_experiment_path(path: string): string {
  const parts = pathParts(path);
  for (let index = 0; index < parts.length - 4; index += 1) {
    if (parts[index] === 'experiments' && (parts[index + 2] === 'outputs' || parts[index + 2] === 'scores')) {
      if (parts[index + 3] === 'evodesign') {
        parts[index + 3] = 'evodiagram';
        parts[index + 4] = legacy_method_name(parts[index + 4]);
        return joinParts(parts);
      }
      break;
    }
  }
  return path;
}

/** Read canonical artifacts first, then historical paths; never move data. */
export function resolve_existing_artifact(path: string): string {
  if (existsSync(path)) {
    return path;
  }
  const legacy = legacy_experiment_path(path);
  return existsSync(legacy) ? legacy : path;
}

/** Return the repository root path. */
export function get_project_root(): string {
  return _PROJECT_ROOT;
}

/** Reject experiment ids that would escape or reshape ``experiments/``. */
export function _validated_experiment_id(value: string, source: string): string {
  try {
    return safe_path_segment(value, 'experiment id');
  } catch (exc) {
    if (exc instanceof ValueError) {
      throw new ValueError(`Invalid experiment id from ${source}: ${exc.message}`);
    }
    throw exc;
  }
}

/** ``datetime.now().strftime("%Y-%m-%d")`` (local time). */
function today(): string {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

/**
 * Resolve the current experiment ID.
 *
 * Priority: EVO_EXPERIMENT_ID env var; settings.yaml experiment.id (if set
 * and != 'exp'); auto-generated date string YYYY-MM-DD.
 */
export function get_experiment_id(): string {
  // 1. Environment variable
  const env_id = pyStrip(getEnv('EVO_EXPERIMENT_ID', ''));
  if (env_id) {
    return _validated_experiment_id(env_id, 'EVO_EXPERIMENT_ID');
  }

  // 2. Config file
  const config_id = _get_config_experiment_id();
  if (config_id && config_id.toLowerCase() !== 'exp') {
    return _validated_experiment_id(config_id, 'settings.yaml experiment.id');
  }

  // 3. Default date
  return today();
}

/** Read experiment.id from settings.yaml if available. */
export function _get_config_experiment_id(): string | null {
  try {
    const settings = AppSettings.get_default();
    const val = settings.get_raw('experiment.id', '');
    if (truthy(val) && pyStrip(pyStr(val))) {
      return pyStrip(pyStr(val));
    }
  } catch {
    // pass
  }
  return null;
}

/**
 * Return the experiment root directory. ``exp_id`` is joined safely so it can
 * never place the experiment tree outside ``<repo>/experiments``.
 */
export function get_experiment_root(exp_id: string | null = null): string {
  const eid = exp_id || get_experiment_id();
  return safe_join_under(join(_PROJECT_ROOT, 'experiments'), eid);
}

// ═══════════════════════════════════════════════════════════════════════
//  Output paths (algorithm-generated artifacts)
// ═══════════════════════════════════════════════════════════════════════

/** experiments/{exp}/outputs/baseline/{algo}/{model}/ */
export function get_baseline_output_dir(algo: string, model: string, exp_id: string | null = null): string {
  return join(get_experiment_root(exp_id), 'outputs', 'baseline', algo, model);
}

/** experiments/{exp}/outputs/evodesign/{variant}/{model}/ */
export function get_evodesign_output_dir(variant: string, model: string, exp_id: string | null = null): string {
  return join(get_experiment_root(exp_id), 'outputs', 'evodesign', canonical_method_name(variant), model);
}

// ═══════════════════════════════════════════════════════════════════════
//  Score paths (evaluation results)
// ═══════════════════════════════════════════════════════════════════════

/** experiments/{exp}/scores/baseline/{algo}/{model}/ */
export function get_baseline_score_dir(algo: string, model: string, exp_id: string | null = null): string {
  return join(get_experiment_root(exp_id), 'scores', 'baseline', algo, model);
}

/** experiments/{exp}/scores/evodesign/{variant}/{model}/ */
export function get_evodesign_score_dir(variant: string, model: string, exp_id: string | null = null): string {
  return join(get_experiment_root(exp_id), 'scores', 'evodesign', canonical_method_name(variant), model);
}

// ═══════════════════════════════════════════════════════════════════════
//  Convenience helpers
// ═══════════════════════════════════════════════════════════════════════

/** Create all experiment subdirectories and return them. */
export function ensure_experiment_dirs(exp_id: string | null = null): Record<string, string> {
  const root = get_experiment_root(exp_id);
  const dirs: Record<string, string> = {
    root,
    outputs_baseline: join(root, 'outputs', 'baseline'),
    outputs_evodesign: join(root, 'outputs', 'evodesign'),
    scores_baseline: join(root, 'scores', 'baseline'),
    scores_evodesign: join(root, 'scores', 'evodesign'),
  };
  for (const p of Object.values(dirs)) {
    mkdirSync(p, { recursive: true });
  }
  return dirs;
}

