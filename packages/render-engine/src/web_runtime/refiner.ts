// Ported from backend/app/services/workflow_runtime/refiner.py — keep in sync
// (PHASE3_PLAN.md WP29).

import { readFileSync } from '../py/fs.ts';
import { pyJsonLoadsExact } from '../py/json_decoder.ts';
import { getLogger } from '../py/logging.ts';
import { should_refine } from '../agentic_system/quality_policy.ts';
import { canvas_library_supports_refiner } from './canvas.ts';
import { isCancellation } from './cancel.ts';
import {
  _layout_instantiation_path,
  _refiner_output_dir,
  _structure_instantiation_path,
  _verifier_report_path,
} from './artifacts.ts';
import {
  REFINER_FAILURE_ARTIFACT,
  REFINER_FAILURE_EXECUTION,
  RefinerArtifactError,
  RefinerExecutionStatusError,
  _wrap_refiner_error,
} from './errors.ts';
import { getattr, type _StreamingArtifacts } from './stream_pipeline.ts';
import { monotonic } from './stage_execution.ts';

const logger = getLogger('app.services.workflow_runtime.refiner');

type Dict = Record<string, any>;

export class _RefinerRunResult {
  constructor(
    readonly fixes_applied: number,
    readonly refined_manifest: Dict | null,
    readonly refined_manifest_path: string | null,
    readonly refined_image_path: string | null,
    readonly converged: boolean,
    readonly termination_reason: string | null,
  ) {}
}

export class _RefinerPreparation {
  constructor(readonly workflow: any, readonly state: any, readonly duration_ms: number) {}
}

export function _count_surviving_fixes(iteration_logs: Iterable<any>): number {
  let total = 0;
  for (const log of iteration_logs) {
    if (getattr(log, 'rolled_back', false)) continue;
    let applied = 0;
    for (const outcome of [...log.deterministic_edits, ...log.llm_edits]) applied += Number(Boolean(outcome.applied));
    // A sequence can be repaired by rebuilding chronology alone. Report
    // those real changes even when no primitive EditOp was necessary;
    // avoid counting connectors again after a normal node edit.
    const derived = new Set<unknown>();
    for (const item of getattr(log, 'rerouted_arrows', []) as Dict[]) {
      const arrow_id = item?.arrow_id;
      if (arrow_id) derived.add(arrow_id);
    }
    total += applied || derived.size;
  }
  return total;
}

/** Overlap only deterministic work; the LLM still receives the full critic. */
export async function _prepare_iterative_refiner(
  { iterative_refiner_workflow_cls, request, save_dir, refiner_max_iterations, artifacts, design_constraints = '' }:
  {
    iterative_refiner_workflow_cls: new () => any; request: { canvas_library: string }; save_dir: string;
    refiner_max_iterations: number; artifacts: _StreamingArtifacts; design_constraints?: string;
  },
): Promise<_RefinerPreparation | null> {
  const started = monotonic();
  try {
    const refiner = new iterative_refiner_workflow_cls();
    const state = await refiner.prepare({
      manifest_path: artifacts.render_result.manifest_path,
      image_path: artifacts.render_result.png_path,
      structure_path: _structure_instantiation_path(save_dir),
      layout_path: _layout_instantiation_path(save_dir),
      output_dir: _refiner_output_dir(save_dir),
      canvas_library: request.canvas_library,
      max_iterations: refiner_max_iterations,
      emit_markdown: true,
      design_constraints,
    });
    if (getattr(state, 'status', null) === 'failed') return null;
    return new _RefinerPreparation(refiner, state, Math.trunc((monotonic() - started) * 1000));
  } catch (exc) {
    if (isCancellation(exc)) throw exc;
    logger.exception('Parallel refiner preparation unavailable; using serial refinement');
    return null;
  }
}

export function _is_refiner_canvas_supported(canvas_library: string): boolean {
  return canvas_library_supports_refiner(canvas_library);
}

/** Whether verifier failures make refinement unsafe to run. */
export function _has_blocking_verification_errors(verifier_state: unknown): boolean {
  const has_blocking_errors = getattr(verifier_state, 'has_blocking_errors', null);
  if (has_blocking_errors === true) return true;
  if (has_blocking_errors === false) return false;

  const blocking_errors = getattr(verifier_state, 'blocking_errors', null);
  if (Array.isArray(blocking_errors)) return blocking_errors.length > 0;
  if (typeof blocking_errors === 'string') return Boolean(blocking_errors);

  return getattr(verifier_state, 'has_errors', false) === true;
}

export function _should_run_refiner(
  { workflow, verifier_state, canvas_library }: { workflow: unknown; verifier_state: unknown; severity_cls?: unknown; canvas_library: string },
): boolean {
  if (!_is_refiner_canvas_supported(canvas_library)) return false;
  if (_has_blocking_verification_errors(verifier_state)) return false;
  if (getattr(workflow, 'always_refine', false)) return true;
  return should_refine(verifier_state);
}

/** ``json.load`` failures (OSError / JSONDecodeError) are the only ones wrapped. */
function isLoadError(exc: unknown): boolean {
  const code = (exc as { code?: unknown })?.code;
  return (typeof code === 'string' && /^E[A-Z]+$/.test(code)) || (exc instanceof Error && /JSONDecodeError/.test(exc.constructor.name));
}

export function _load_refined_manifest(refiner_state: unknown): Dict | null {
  const refined_manifest_path = getattr(refiner_state, 'refined_manifest_path', null);
  const refined_image_path = getattr(refiner_state, 'refined_image_path', null);

  if (refined_manifest_path && refined_image_path) {
    try {
      return pyJsonLoadsExact(readFileSync(refined_manifest_path, 'utf-8')) as Dict;
    } catch (exc) {
      if (!isLoadError(exc)) throw exc;
      throw _wrap_refiner_error({ phase: REFINER_FAILURE_ARTIFACT, reason: 'Refiner artifact load failed', exc });
    }
  }
  if (refined_manifest_path) {
    throw new RefinerArtifactError({ phase: REFINER_FAILURE_ARTIFACT, reason: 'Refiner produced a refined manifest without an image' });
  }
  if (refined_image_path) {
    throw new RefinerArtifactError({ phase: REFINER_FAILURE_ARTIFACT, reason: 'Refiner produced a refined image without a manifest' });
  }
  return null;
}

export async function _run_iterative_refiner(
  {
    iterative_refiner_workflow_cls, request, save_dir, verification_dir, refiner_max_iterations, artifacts,
    preparation = null, design_constraints = '',
  }: {
    iterative_refiner_workflow_cls: new () => any; request: { canvas_library: string }; save_dir: string;
    verification_dir: string; refiner_max_iterations: number; artifacts: _StreamingArtifacts;
    preparation?: _RefinerPreparation | null; design_constraints?: string;
  },
): Promise<_RefinerRunResult> {
  let refiner_state: any;
  let fixes_applied: number;
  try {
    if (preparation !== null) {
      refiner_state = await preparation.workflow.run_prepared(preparation.state, _verifier_report_path(verification_dir));
    } else {
      const refiner = new iterative_refiner_workflow_cls();
      // refiner.run(manifest_path=…, image_path=…, structure_path=…, layout_path=…,
      //   verifier_report_path=…, output_dir=…, canvas_library=…, max_iterations=…,
      //   emit_markdown=True, design_constraints=…)
      refiner_state = await refiner.run(
        artifacts.render_result.manifest_path,
        artifacts.render_result.png_path,
        _verifier_report_path(verification_dir),
        design_constraints,
        _structure_instantiation_path(save_dir),
        _layout_instantiation_path(save_dir),
        _refiner_output_dir(save_dir),
        request.canvas_library,
        refiner_max_iterations,
        false,
        null,
        true,
      );
    }
    // Iteration logs record every proposal, including deterministic skips
    // and LLM items rejected by EditOp schema validation. Count surviving
    // applied outcomes or standalone derived repairs, never proposals.
    fixes_applied = _count_surviving_fixes(getattr(refiner_state, 'iteration_logs', []));
  } catch (exc) {
    if (isCancellation(exc)) throw exc;
    throw _wrap_refiner_error({ phase: REFINER_FAILURE_EXECUTION, reason: 'Refiner execution failed', exc });
  }

  if (getattr(refiner_state, 'status', null) === 'failed') {
    throw new RefinerExecutionStatusError({ phase: REFINER_FAILURE_EXECUTION, reason: 'Refiner returned failed status' });
  }

  const converged = getattr(refiner_state, 'converged', null) === true;
  const termination_reason = getattr(refiner_state, 'termination_reason', null);
  const reason = termination_reason !== null ? String(termination_reason) : null;
  if (!converged) {
    return new _RefinerRunResult(fixes_applied, null, null, null, false, reason);
  }

  const refined_manifest = _load_refined_manifest(refiner_state);
  const refined_manifest_path = getattr(refiner_state, 'refined_manifest_path', null);
  const refined_image_path = getattr(refiner_state, 'refined_image_path', null);
  return new _RefinerRunResult(
    fixes_applied,
    refined_manifest,
    refined_manifest !== null ? String(refined_manifest_path) : null,
    refined_manifest !== null ? String(refined_image_path) : null,
    true,
    reason,
  );
}
