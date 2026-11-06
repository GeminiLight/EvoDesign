// Ported from backend/app/services/workflow_runtime/artifacts.py — keep in
// sync (PHASE3_PLAN.md WP29). File-system access goes through the active
// RuntimeFS (``py/fs.ts``), so the browser runs on a MemoryFS.

import { mkdirSync, rmSync, writeFileSync } from '../py/fs.ts';
import { dirname, join } from '../py/path.ts';
import { pyJsonDumps } from '../py/json.ts';
import { withPyFloats } from '../py/float_marks.ts';

export const STRUCTURE_STAGE_DIR = '1_structure';
export const STYLING_STAGE_DIR = '2_styling';
export const LAYOUT_STAGE_DIR = '3_layout';
export const RENDER_STAGE_DIR = '4_render';
export const VERIFICATION_STAGE_DIR = '6_verification';
export const REFINER_STAGE_DIR = '7_refiner';
export const FINAL_VERIFICATION_STAGE_DIR = '8_final_verification';

/** ``value.model_dump()`` for pydantic-like models, the value itself otherwise. */
export function _to_plain(value: unknown): any {
  if (value === null || value === undefined) return null;
  const dump = (value as { model_dump?: unknown }).model_dump;
  if (typeof dump === 'function') return (dump as () => unknown).call(value);
  return value;
}

/** A per-request workdir for streaming artifacts. */
export function _request_scoped_stream_dir(results_dir: string, request_id: string): string {
  let safe_request_id = String(request_id).replace(/[^A-Za-z0-9_.-]+/g, '_').replace(/^[._]+|[._]+$/g, '');
  if (!safe_request_id) safe_request_id = 'request';
  return join(results_dir, 'stream_runs', safe_request_id);
}

/** ``shutil.rmtree(save_dir, ignore_errors=True)`` */
export function _cleanup_stream_dir(save_dir: string): void {
  try {
    rmSync(save_dir, { recursive: true, force: true });
  } catch {
    // ignore_errors=True
  }
}

export function _save_json(filepath: string, data: unknown): void {
  mkdirSync(dirname(filepath), { recursive: true });
  writeFileSync(filepath, pyJsonDumps(withPyFloats(_to_plain(data) || {}), { indent: 2, ensureAscii: false }), 'utf-8');
}

export function _run_stage_dir(save_dir: string, stage_dir: string): string {
  return join(save_dir, stage_dir);
}

export function _stage_artifact_path(save_dir: string, stage_dir: string, artifact_name: string): string {
  return join(_run_stage_dir(save_dir, stage_dir), `${artifact_name}.json`);
}

export function _structure_instantiation_path(save_dir: string): string {
  return _stage_artifact_path(save_dir, STRUCTURE_STAGE_DIR, 'structure_instantiation');
}

export function _layout_instantiation_path(save_dir: string): string {
  return _stage_artifact_path(save_dir, LAYOUT_STAGE_DIR, 'layout_instantiation');
}

export function _render_output_dir(save_dir: string): string {
  return _run_stage_dir(save_dir, RENDER_STAGE_DIR);
}

export function _verification_output_dir(save_dir: string): string {
  return _run_stage_dir(save_dir, VERIFICATION_STAGE_DIR);
}

export function _final_verification_output_dir(save_dir: string): string {
  return _run_stage_dir(save_dir, FINAL_VERIFICATION_STAGE_DIR);
}

export function _verifier_report_path(verification_dir: string): string {
  return join(verification_dir, 'verifier_report.json');
}

export function _refiner_output_dir(save_dir: string): string {
  return _run_stage_dir(save_dir, REFINER_STAGE_DIR);
}

export function _save_stage_artifact(save_dir: string, stage_dir: string, artifact_name: string, data: unknown): void {
  if (data === null || data === undefined) return;
  _save_json(_stage_artifact_path(save_dir, stage_dir, artifact_name), data);
}
