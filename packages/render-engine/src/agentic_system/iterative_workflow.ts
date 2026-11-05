// Ported from evodesign/agentic_system/iterative_workflow.py — keep in sync.
// server-only (file I/O, rendering, LangGraph.js)
//
// IterativeRefinerWorkflow — orchestrates verify → fix → render loop.
//
// This is the **iteration orchestrator**. It composes three independent stages:
//
//   1. **Verification** — ``verification_stage.checks.run_all_checks()``
//      returns findings; the orchestrator does not own check logic.
//   2. **Refinement** — deterministic fixers + LLM agent produce EditOps,
//      which are applied to the manifest.
//   3. **Rendering** — ``canvas_environment.render_png_result()`` re-draws
//      the PNG for the next iteration's VLM input while preserving failures.
//
// LangGraph nodes:
//
//   load_inputs        read manifest, structure, verifier report
//   run_iteration      verify → fix → apply → repair → re-render (loop body)
//   check_convergence  conditional edge: loop or finalize
//   finalize           write refined manifest + image + report
//
// Two invariants the loop body maintains, both of which used to be missing:
//
// * **Derived geometry is repaired after every edit batch.** Arrow polylines and
//   the elements-array paint order cannot be expressed as EditOps, so they are
//   recomputed in place once the batch has been applied. Otherwise every shape
//   the refiner moved left its arrows pointing at empty canvas.
// * **A round that makes things worse is rolled back.** Each round starts from a
//   deepcopy snapshot and is discarded if its post-fix findings score is worse
//   than what it started from, so the manifest at every round boundary is the
//   best result seen so far — not merely the last one attempted.
//
// TS notes: ``StateGraph(VerifierRefinerState)`` → ``PydanticStateGraph``
// (nodes receive the state re-validated into a ``VerifierRefinerState``).
// Everything that renders or calls the model is async; the call order is the
// Python one. Keyword-only parameters are positional in declaration order.

import { isF, markF, withPyFloats } from '../py/float_marks.ts';
import { copyFileSync, existsSync, mkdirSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { END, START } from '@langchain/langgraph';

import { objective_rank, needs_refinement } from './quality_policy.ts';

import { ANALYSIS_RENDER_SCALE, normalize_manifest, rebuild_excalidraw_arrows, render_png_result } from '../canvas_environment/index.ts';
import { normalize_canvas_library } from '../canvas_runtime.ts';
import { run_all_checks } from '../verification_stage/checks/aggregator.ts';
import { Finding, summarize_findings } from '../verification_stage/checks/finding.ts';

import { RefinerLLMAgent, build_manifest_summary } from '../refinement_stage/agent/llm_agent.ts';
import { apply_edits } from '../refinement_stage/fixers/apply_edits.ts';
import { reroute_bound_arrows } from '../refinement_stage/fixers/arrow_reroute.ts';
import {
  DeterministicFixerError,
  patch_schema_defaults,
  reorder_elements_by_index,
  run_all_deterministic_fixers,
} from '../refinement_stage/fixers/deterministic.ts';
import { build_refiner_report, write_refiner_report } from '../refinement_stage/reports/refiner_report.ts';
import {
  EditApplyOutcome,
  EditOp,
  IterationLog,
  PreparedIteration,
  SUPPORTED_REFINER_CANVAS_LIBRARIES,
  VerifierRefinerState,
  refiner_recursion_limit,
} from '../refinement_stage/state.ts';
import { icons_disabled, locked_scene_elements } from '../common/design_constraints.ts';
import { PydanticStateGraph, type WorkflowStateClass } from '../common/base_workflow.ts';
import { ModelConfig } from '../config/model_loader.ts';
import { _deepcopy_with_py_floats, _with_py_floats } from '../generation_stage/layout/sequence_layout.ts';

import { JSONDecodeError, KeyError, ValueError } from '../py/errors.ts';
import { sha256Hex, utf8Encode } from '../py/hash.ts';
import { PyJSONDecodeError, pyJsonLoadsExact } from '../py/json_decoder.ts';
import { pyJsonDumps } from '../py/json.ts';
import { getLogger } from '../py/logging.ts';
import { pyNe } from '../py/eq.ts';
import { pyGet } from '../py/dict.ts';
import { pyGt, pySorted } from '../py/sort.ts';
import { pyFormatFixed, pyRepr, pyStr } from '../py/str.ts';
import { isDict, isList, isStr, pyTypeName, truthy } from '../py/truthy.ts';

const logger = getLogger('evodesign.agentic_system.iterative_workflow');

type Dict = Record<string, any>;

// ---------------------------------------------------------------- local Python helpers

/** ``type(exc).__name__`` */
function _exc_type_name(exc: unknown): string {
  if (exc instanceof Error) {
    const name = exc.name || exc.constructor?.name || 'Exception';
    return name === 'PyTypeError' ? 'TypeError' : name;
  }
  return pyTypeName(exc);
}

/** ``str(exc)`` */
function _exc_str(exc: unknown): string {
  if (exc instanceof KeyError) return pyRepr(exc.message);
  if (exc instanceof Error) return exc.message;
  return pyStr(exc);
}

/** Node fs errors are Python ``OSError``s. */
function _is_os_error(error: unknown): boolean {
  return typeof (error as { code?: unknown })?.code === 'string';
}

/** ``str(Path(p))`` for POSIX paths (collapses duplicate and trailing slashes, drops ``.``). */
function _path_str(path: string): string {
  if (path === '') return '.';
  const lead = /^\/+/.exec(path)?.[0].length ?? 0;
  const anchor = lead === 0 ? '' : lead === 2 ? '//' : '/';
  const parts = path.slice(lead).split('/').filter((part) => part && part !== '.');
  if (!parts.length) return anchor || '.';
  return anchor + parts.join('/');
}

/** ``str(Path(p).parent)`` */
function _path_parent(path: string): string {
  const normalized = _path_str(path);
  if (normalized === '/' || normalized === '//' || normalized === '.') return normalized;
  const index = normalized.lastIndexOf('/');
  if (index < 0) return '.';
  if (index === 0) return '/';
  if (index === 1 && normalized.startsWith('//')) return '//';
  return normalized.slice(0, index);
}

/** ``str(Path(a) / b)`` */
function _path_join(a: string, b: string): string {
  const base = _path_str(a);
  if (base === '.') return _path_str(b);
  return _path_str(`${base}/${b}`);
}

/** ``Path(p).is_file()`` */
function _is_file(path: string): boolean {
  try {
    return statSync(path).isFile();
  } catch {
    return false;
  }
}

/** ``Path(p).exists()`` */
function _exists(path: string): boolean {
  try {
    return existsSync(path);
  } catch {
    return false;
  }
}

/** ``Path(p).unlink(missing_ok=True)`` */
function _unlink_missing_ok(path: string): void {
  try {
    rmSync(path);
  } catch (exc) {
    if ((exc as { code?: unknown })?.code === 'ENOENT') return;
    throw exc;
  }
}

/** ``(mapping or {}).get(key, default)`` */
function _get(mapping: unknown, key: string, defaultValue: unknown = null): unknown {
  return pyGet(truthy(mapping) ? mapping : {}, key, defaultValue);
}

// ---------------------------------------------------------------- fingerprints

export function _manifest_fingerprint(manifest: Dict): string {
  return sha256Hex(utf8Encode(pyJsonDumps(_with_py_floats(manifest), { sortKeys: true })));
}

/** Bind prepared work to these exact inputs, never a different request. */
export function _input_fingerprint(state: VerifierRefinerState): string {
  const chunks: Uint8Array[] = [utf8Encode(state.design_constraints)];
  for (const path of [state.manifest_path, state.image_path, state.structure_path, state.layout_path]) {
    chunks.push(utf8Encode(pyStr(path)));
    if (truthy(path)) {
      chunks.push(new Uint8Array(readFileSync(path as string)));
    }
  }
  const total = chunks.reduce((sum, chunk) => sum + chunk.length, 0);
  const buffer = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    buffer.set(chunk, offset);
    offset += chunk.length;
  }
  return sha256Hex(buffer);
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

export function _load_json(path: string | null): Dict | null {
  if (!truthy(path)) {
    return null;
  }
  const p = path!;
  if (!_exists(p)) {
    return null;
  }
  try {
    return pyJsonLoadsExact(readFileSync(p, 'utf-8')) as Dict;
  } catch (exc) {
    if (_is_os_error(exc) || exc instanceof PyJSONDecodeError || exc instanceof JSONDecodeError) {
      logger.warning(`Could not load JSON from ${path}: ${_exc_str(exc)}`);
      return null;
    }
    throw exc;
  }
}

export function _findings_to_dicts(findings: Finding[]): Dict[] {
  return findings.map((f) => f.to_dict());
}

export function _finding_element_ids(findings: Finding[]): Set<string> {
  const ids = new Set<string>();
  for (const finding of findings) {
    if (truthy(finding.element_id)) {
      ids.add(finding.element_id!);
    }
    const loc = truthy(finding.location) ? finding.location : {};
    if (!isDict(loc)) {
      continue;
    }
    for (const key of ['other_id', 'holder_id', 'element_id']) {
      const value = pyGet(loc, key);
      if (isStr(value) && value) {
        ids.add(value);
      }
    }
    const pairs = pyGet(loc, 'pairs');
    if (isList(pairs)) {
      for (const pair of pairs) {
        if (!isList(pair)) {
          continue;
        }
        for (const value of pair) {
          if (isStr(value) && value) {
            ids.add(value);
          }
        }
      }
    }
  }
  return ids;
}

export function _any_applied(outcomes: EditApplyOutcome[]): boolean {
  return outcomes.some((outcome) => outcome.applied);
}

export function _major_or_critical_count(findings: Finding[]): number {
  return findings.filter((f) => f.severity === 'critical' || f.severity === 'major').length;
}

// Weighted histogram used to compare two rounds. Convergence still keys off
// "no serious findings", but progress must be measured across ALL severities,
// otherwise a round that trades one MAJOR for six MINORs reads as an
// improvement — and a round that wrecks the layout and happens to end at zero
// serious findings reads as success.
export const _SEVERITY_WEIGHTS: Record<string, number> = { critical: 100.0, major: 10.0, minor: 1.0, info: 0.0 };

/** Lower is better. 0.0 means nothing above INFO remains. */
export function _findings_score(findings: Finding[]): number {
  let total = 0;
  for (const f of findings) {
    total += Object.prototype.hasOwnProperty.call(_SEVERITY_WEIGHTS, f.severity) ? _SEVERITY_WEIGHTS[f.severity] : 1.0;
  }
  return total;
}

/** Ids whose position or size actually changed in the given batches. */
export function _touched_geometry_ids(...outcome_batches: EditApplyOutcome[][]): Set<string> {
  const touched = new Set<string>();
  for (const outcomes of outcome_batches) {
    for (const outcome of outcomes) {
      if (!outcome.applied || outcome.edit === null) {
        continue;
      }
      if (['set_position', 'set_size', 'set_icon'].includes(outcome.edit.op)) {
        touched.add(outcome.edit.id);
      }
    }
  }
  return touched;
}

/**
 * Deterministic string fingerprint of a findings list.
 *
 * Used for stagnation detection: if two consecutive iterations produce the
 * same fingerprint, the fixes had no effect and we should stop.
 */
export function _fingerprint_findings(findings: Finding[]): string {
  const parts = pySorted(findings.map((f) => [f.category, f.element_id || '', f.message] as [string, string, string]));
  return parts.map(([c, e, m]) => `${c}:${e}:${m}`).join('|');
}

export function _normalize_refiner_canvas_library(canvas_library: string): string {
  const value = normalize_canvas_library(canvas_library);
  if (!(SUPPORTED_REFINER_CANVAS_LIBRARIES as readonly string[]).includes(value)) {
    throw new ValueError(
      'IterativeRefinerWorkflow currently supports Excalidraw manifests '
      + `only; got canvas_library=${pyRepr(canvas_library)}.`,
    );
  }
  return value;
}

export function _outcome_to_prompt_dict(outcome: EditApplyOutcome): Dict {
  return {
    applied: outcome.applied,
    edit: outcome.edit !== null ? outcome.edit.to_dict() : null,
    error: outcome.error,
  };
}

export function _iter_log_to_prompt_dict(log: IterationLog): Dict {
  return {
    iteration: log.iteration,
    deterministic_edits: log.deterministic_edits.map((o) => _outcome_to_prompt_dict(o)),
    llm_edits: log.llm_edits.map((o) => _outcome_to_prompt_dict(o)),
  };
}

export const LAYOUT_AUDIT_SKIP_NOTE = (
  'layout_audit — no layout_instantiation was provided, so the layout-stage '
  + 'checks (empty title / edge classifier) did NOT run. Pass '
  + '--layout to enable them.'
);

/**
 * Objective checks the refiner must not run this session.
 *
 * ``check_layout_audit`` returns a CRITICAL when layout is missing, which is
 * right for the verifier (a configured check silently returning [] is worse
 * than a loud failure) but fatal for the refiner: no fixer can ever produce a
 * layout_instantiation, so the serious-finding count never reaches zero,
 * ``converged`` stays False forever, and a fully repaired diagram is written
 * out as a mere candidate with exit code 1. ``--layout`` is documented as
 * optional, so the refiner skips the check and says so in the report instead
 * of failing on an input it never required.
 */
export function _objective_skip_categories(state: VerifierRefinerState): string[] {
  const skip: string[] = [...(truthy(state.skip_checks) ? state.skip_checks : [])];
  if (state.layout_instantiation === null && !skip.includes('layout_audit')) {
    skip.push('layout_audit');
  }
  return skip;
}

export function _run_objective_checks(state: VerifierRefinerState): Finding[] {
  const skip = _objective_skip_categories(state);
  return run_all_checks(
    state.manifest as Dict,
    state.structure,
    state.layout_instantiation,
    state.canvas_library,
    truthy(skip) ? skip : null,
  );
}

function _design_constraints(state: VerifierRefinerState): string {
  return (state.design_constraints || _get(state.initial_report, 'design_constraints', '')) as string;
}

export function _apply_edit_batch(
  state: VerifierRefinerState,
  edits: unknown[],
  log: IterationLog,
  target_attr: 'deterministic_edits' | 'llm_edits',
  log_prefix: string,
): EditApplyOutcome[] {
  const constraints = _design_constraints(state);
  const locked_before = locked_scene_elements(state.manifest as Dict, constraints);
  const snapshot = truthy(locked_before) ? _deepcopy_with_py_floats(state.manifest) : null;
  const [manifest, outcomes_like] = apply_edits(state.manifest as Dict, edits as never[], !icons_disabled(constraints));
  state.manifest = manifest;
  const outcomes = outcomes_like as unknown as EditApplyOutcome[];
  // extend, not assign: schema-rejected LLM proposals were already recorded
  // on this log before anything reached the dispatcher.
  log[target_attr].push(...outcomes);
  const applied_n = outcomes.filter((outcome) => outcome.applied).length;
  state.add_log(`${log_prefix} emitted=${edits.length} applied=${applied_n}`);
  const geometry_refreshed = _refresh_edited_geometry(state, outcomes, log);
  _repair_derived_geometry(
    state,
    log,
    _touched_geometry_ids(outcomes),
    geometry_refreshed,
  );
  if (snapshot !== null && pyNe(locked_scene_elements(state.manifest as Dict, constraints), locked_before)) {
    state.manifest = snapshot;
    for (const outcome of outcomes) {
      if (outcome.applied) {
        outcome.applied = false;
        outcome.error = 'Batch rejected: would change a user-locked element';
      }
    }
    log.notes.push('Preserved locked elements; rejected the entire conflicting edit batch');
  }
  return outcomes;
}

/** Refresh routes and label geometry after shape or typography edits. */
export function _refresh_edited_geometry(
  state: VerifierRefinerState,
  outcomes: EditApplyOutcome[],
  log: IterationLog,
): boolean {
  const manifest: Dict = truthy(state.manifest) ? state.manifest! : {};
  const metadata = truthy(pyGet(manifest, '_meta')) ? (pyGet(manifest, '_meta') as Dict) : {};
  if (!truthy(state.structure) || !truthy(pyGet(metadata, 'edge_data'))) {
    return false;
  }
  const elements = new Map<unknown, Dict>();
  for (const element of pyGet(manifest, 'elements', []) as Dict[]) {
    elements.set(pyGet(element, 'id'), element);
  }
  const elementGet = (id: unknown): Dict => (elements.has(id) ? elements.get(id)! : {});
  const changed_shapes = new Set<string>();
  for (const outcome of outcomes) {
    if (
      outcome.applied
      && ['set_position', 'set_size', 'set_icon'].includes(outcome.edit!.op)
      && ['rectangle', 'ellipse', 'diamond', 'image'].includes(pyGet(elementGet(outcome.edit!.id), 'type') as string)
    ) {
      changed_shapes.add(outcome.edit!.id);
    }
  }
  const changed_edge_labels = new Set<string>();
  for (const outcome of outcomes) {
    if (!(outcome.applied && outcome.edit!.op === 'set_style')) continue;
    const payload = outcome.edit!.payload as Dict;
    if (!('fontSize' in payload || 'fontFamily' in payload)) continue;
    if (pyGet(elementGet(outcome.edit!.id), 'type') !== 'text') continue;
    const element = elements.get(outcome.edit!.id)!;
    const meta = truthy(pyGet(element, 'meta')) ? (pyGet(element, 'meta') as Dict) : {};
    if (truthy(pyGet(meta, 'semantic_edge_id')) || pyGet(elementGet(pyGet(element, 'containerId')), 'type') === 'arrow') {
      changed_edge_labels.add(outcome.edit!.id);
    }
  }
  if (!changed_shapes.size && !changed_edge_labels.size) {
    return false;
  }

  // Excalidraw exports authored polylines as supplied; changing a shape's
  // bbox alone does not retarget or reroute them. Reuse the scene router,
  // which also preserves semantic IDs and authored connector styles.
  state.manifest = rebuild_excalidraw_arrows(manifest, state.structure!);
  normalize_manifest(state.manifest, state.canvas_library);
  const message = (
    `rebuilt connectors after edits to ${changed_shapes.size} shape(s) `
    + `and ${changed_edge_labels.size} edge label(s)`
  );
  log.notes.push(message);
  state.add_log(message);
  return true;
}

export async function _propose_llm_edits(
  state: VerifierRefinerState,
  llm_agent: RefinerLLMAgent,
  log: IterationLog,
  iteration: number,
  image_note: string | null = null,
): Promise<EditOp[]> {
  const critique_raw = _get(state.initial_report, 'subjective');
  const critique = truthy(critique_raw) ? (critique_raw as Dict) : null;
  const previous_attempts = state.iteration_logs.map((iter_log) => _iter_log_to_prompt_dict(iter_log));
  // This round's own deterministic edits are not in ``iteration_logs`` yet —
  // the log is only appended at convergence marking — so without this the
  // model is told nothing about the fixes that just moved the elements it is
  // looking at, and re-proposes them.
  previous_attempts.push(_iter_log_to_prompt_dict(log));

  // Re-verify after deterministic pass so LLM sees remaining issues.
  const findings_after_det = _run_objective_checks(state);

  let proposed_edits: EditOp[];
  try {
    proposed_edits = await llm_agent.propose_edits(
      state.current_image_path as string,
      _get(state.structure, 'chart_type') as string | null,
      _findings_to_dicts(findings_after_det),
      critique,
      build_manifest_summary(
        state.manifest as Dict,
        undefined,
        _finding_element_ids(findings_after_det),
      ),
      previous_attempts,
      iteration,
      state.max_iterations,
      image_note,
      _design_constraints(state),
    );
  } catch (exc) {
    logger.exception('LLM agent failed; degrading to deterministic-only this iteration');
    state.add_error(`iteration ${iteration} LLM failed: ${_exc_str(exc)}`);
    proposed_edits = [];
  }

  if (truthy(llm_agent.last_exhaustion_error ?? null)) {
    state.add_error(
      `iteration ${iteration} LLM exhausted retries: `
      + `${llm_agent.last_exhaustion_error}`,
    );
    log.notes.push(`LLM unavailable: ${llm_agent.last_exhaustion_error}`);
  }

  _record_rejected_llm_edits(state, llm_agent, log, iteration, proposed_edits.length);
  return proposed_edits;
}

/**
 * Log LLM proposals that never became EditOps.
 *
 * ``EditOp`` forbids extra keys, so a single drifted field name invalidates a
 * whole proposal. Dropping those with only a logger warning made "20 edits
 * proposed, 20 malformed" indistinguishable from "the model saw nothing to
 * fix" — the same ambiguity ``last_exhaustion_error`` was added to close for
 * the transport failure path.
 */
export function _record_rejected_llm_edits(
  state: VerifierRefinerState,
  llm_agent: RefinerLLMAgent,
  log: IterationLog,
  iteration: number,
  accepted: number,
): void {
  const rejected: Dict[] = [...(truthy(llm_agent.last_rejected_edits ?? null) ? llm_agent.last_rejected_edits : [])];
  if (!rejected.length) {
    return;
  }

  for (const item of rejected) {
    log.llm_edits.push(
      new EditApplyOutcome({
        edit: null,
        applied: false,
        error: pyGet(item, 'error') || 'schema: rejected',
        raw: pyGet(item, 'raw'),
      }),
    );
  }
  state.add_log(`  llm:           rejected=${rejected.length} (schema)`);
  log.notes.push(`${rejected.length} LLM proposal(s) rejected by EditOp schema validation`);
  if (accepted === 0) {
    state.add_error(
      `iteration ${iteration} LLM: all ${rejected.length} proposed edit(s) `
      + 'failed EditOp schema validation; no edit reached the manifest',
    );
  }
}

/**
 * Restore the two invariants no EditOp can express.
 *
 * 1. **Arrow polylines.** An Excalidraw arrow bakes its shape into absolute
 *    ``x``/``y``/``points``; moving or resizing a shape leaves the arrow
 *    behind while every id-level binding still looks perfect.
 * 2. **Elements-array order.** ``set_index`` carries only half of what
 *    ``repair_manifest_zorder`` does — the array itself must be re-sorted to
 *    match, or the manifest asserts two contradictory paint orders.
 */
export function _repair_derived_geometry(
  state: VerifierRefinerState,
  log: IterationLog,
  touched_ids: Set<string>,
  geometry_refreshed = false,
): void {
  if (!isDict(state.manifest)) {
    return;
  }

  if (state.canvas_library === 'excalidraw' && truthy(state.structure)
      && pyGet(state.structure, 'chart_type') === 'sequence_diagram') {
    const repaired = rebuild_excalidraw_arrows(state.manifest, state.structure!);
    const before = new Map<unknown, Dict>();
    for (const item of pyGet(state.manifest, 'elements', []) as Dict[]) before.set(item.id, item);
    for (const item of pyGet(repaired, 'elements', []) as Dict[]) {
      if (pyGet(item, 'type') === 'arrow' && pyNe(item, before.has(item.id) ? before.get(item.id) : null)) {
        log.rerouted_arrows.push({ arrow_id: item.id, reason: 'restored sequence chronology' });
      }
    }
    state.manifest = repaired;
    geometry_refreshed = true;
  }

  // The scene router already accounts for obstacles, shared ports and label
  // placement. Endpoint-only fallback routing would overwrite those routes.
  // Keep it for imported scenes without semantic structure/edge metadata.
  const rerouted = geometry_refreshed ? [] : reroute_bound_arrows(
    state.manifest!,
    state.canvas_library,
    touched_ids,
  );
  if (rerouted.length) {
    log.rerouted_arrows.push(...rerouted);
    state.add_log(`  arrows:        re-routed=${rerouted.length}`);
    const sample = rerouted.slice(0, 5).map((item) => pyStr(pyGet(item, 'arrow_id'))).join(', ');
    const more = rerouted.length <= 5 ? '' : ` (+${rerouted.length - 5} more)`;
    log.notes.push(
      `re-routed ${rerouted.length} arrow(s) onto their moved endpoints: `
      + `${sample}${more}`,
    );
  }

  if (reorder_elements_by_index(state.manifest!)) {
    state.add_log('  zorder:        elements array re-sorted to match index');
    log.notes.push(
      'elements array re-sorted so paint order matches the repaired '
      + 'fractional indices',
    );
  }
}

/**
 * Re-render the current manifest and point the VLM at the new PNG.
 *
 * ``stage`` names an intra-round render (currently ``"det"``, taken after the
 * deterministic pass and before the LLM call) and keeps it in its own file.
 * Only the end-of-round render, ``stage=None``, is recorded as the log's
 * canonical ``rerender_*`` result.
 *
 * Iteration PNGs are **analysis renders**: exported at scale 1 (one image
 * pixel = one manifest unit) with the post-export smart crop disabled, so
 * the VLM measures the same units the manifest summary quotes and the
 * framing no longer drifts with pixel-content detection between rounds.
 * The product render in ``_node_finalize`` deliberately keeps the default
 * magnified + cropped pipeline.
 */
export async function _rerender_iteration_image(
  state: VerifierRefinerState,
  log: IterationLog,
  iteration: number,
  stage: string | null = null,
): Promise<void> {
  const out_dir = _path_str(state.output_dir || _path_parent(state.manifest_path));
  if (state.skip_rerender_between_iterations) {
    if (stage === null) {
      log.notes.push('re-render skipped (--no-rerender)');
    }
    return;
  }

  const suffix = stage === null ? '' : `_${stage}`;
  const iter_image = _path_join(out_dir, `refined_iter_${iteration}${suffix}.png`);
  const render_result = await render_png_result(
    state.manifest as Dict,
    iter_image,
    state.canvas_library,
    undefined,
    undefined,
    ANALYSIS_RENDER_SCALE,
    false,
  );
  if (stage === null) {
    log.rerender_ok = render_result.ok;
  }
  if (render_result.ok) {
    const rendered_path = render_result.output_path || iter_image;
    if (stage === null) {
      log.rerender_path = rendered_path;
    }
    state.current_image_path = rendered_path;
    state.analysis_manifest_fingerprint = _manifest_fingerprint(state.manifest as Dict);
    state.add_log(`  re-rendered to ${iter_image}`);
  } else {
    log.rerender_error = render_result.error || null;
    const detail = render_result.error ? `: ${render_result.error}` : '';
    const message = (
      'intermediate re-render failed; stopping before next LLM iteration '
      + `to avoid stale image input${detail}`
    );
    log.notes.push(message);
    state.add_error(message);
    state.status = 'failed';
  }
}

export function _mark_convergence(
  state: VerifierRefinerState,
  log: IterationLog,
  findings_after_iter: Finding[],
  edits_applied: boolean,
  iteration: number,
): void {
  state.iteration_logs.push(log);
  state.current_iteration = iteration;

  const remaining_serious = _major_or_critical_count(findings_after_iter);
  const baseline = state.iteration_logs[0].findings_before;
  const current = summarize_findings(findings_after_iter);
  const has_regression = pyGt(objective_rank(current), objective_rank(baseline));
  let quality_resolved = !objective_rank(current).some((value) => truthy(value)) && !has_regression;
  const subjective_raw = _get(state.initial_report, 'subjective');
  const subjective = truthy(subjective_raw) ? (subjective_raw as Dict) : {};
  const visual_work_remains = needs_refinement({
    score: pyGet(subjective, 'overall_score'),
    constraint_violations: pyGet(subjective, 'constraint_violations', []),
  });
  if (!edits_applied && visual_work_remains) {
    quality_resolved = false;
  }
  const current_fp = _fingerprint_findings(findings_after_iter);
  const is_stagnant = (
    state.prev_findings_fingerprint !== null
    && current_fp === state.prev_findings_fingerprint
  );
  state.prev_findings_fingerprint = current_fp;

  if (is_stagnant) {
    state.termination_reason = 'stagnant';
    state.converged = quality_resolved;
    state.add_log(
      `  → stagnant (findings unchanged after round ${iteration}; `
      + `${remaining_serious} serious finding(s) remain)`,
    );
    log.notes.push('stagnation: findings identical to previous round');
  } else if (!edits_applied) {
    if (quality_resolved) {
      state.converged = true;
      state.termination_reason = 'no_edits_resolved';
      state.add_log('  → converged (no edits emitted, no serious findings or objective regression)');
    } else {
      state.converged = false;
      state.termination_reason = 'fixed_point_unresolved';
      state.add_log(
        `  → fixed point reached (${remaining_serious} serious finding(s), `
        + `objective regression=${has_regression ? 'True' : 'False'}, no applicable edits)`,
      );
      log.notes.push('stopped at fixed point with unresolved findings or objective regression');
    }
  } else if (quality_resolved) {
    state.converged = true;
    state.termination_reason = 'resolved';
    state.add_log('  → converged (no serious findings or objective regression remain)');
  } else if (has_regression) {
    state.add_log('  → continuing to repair objective regression from the initial scene');
  }
}

// ---------------------------------------------------------------------------
// Graph nodes
// ---------------------------------------------------------------------------

export function _node_load_inputs(state: VerifierRefinerState): VerifierRefinerState {
  state.add_log(`loading manifest from ${state.manifest_path}`);

  const manifest = _load_json(state.manifest_path);
  if (manifest === null) {
    state.add_error(`could not load manifest from ${state.manifest_path}`);
    state.status = 'failed';
    return state;
  }
  state.manifest = manifest;

  if (truthy(state.structure_path)) {
    state.structure = _load_json(state.structure_path);
    if (state.structure === null) {
      state.add_error(
        `could not load explicit structure_path from ${state.structure_path}; `
        + 'refiner cannot safely run structure-dependent fixes.',
      );
      state.status = 'failed';
      return state;
    }
  }

  if (truthy(state.layout_path)) {
    state.layout_instantiation = _load_json(state.layout_path);
    if (state.layout_instantiation === null) {
      state.add_error(
        `could not load explicit layout_path from ${state.layout_path}; `
        + 'refiner cannot safely run layout-dependent fixes.',
      );
      state.status = 'failed';
      return state;
    }
  }

  if (!truthy(state.verifier_report_path)) {
    const candidate = _path_join(_path_parent(state.manifest_path), 'verifier_report.json');
    if (_exists(candidate)) {
      state.verifier_report_path = candidate;
    }
  }

  state.initial_report = _load_json(state.verifier_report_path);
  if (state.initial_report === null) {
    state.add_log(
      'no pre-existing verifier_report found '
      + `(looked at ${pyStr(state.verifier_report_path)}); will compute fresh `
      + 'objective findings each iteration.',
    );
  }

  // Pre-processing: patch missing schema fields so all downstream code
  // sees well-formed elements. Runs once (not per-iteration).
  patch_schema_defaults(state.manifest);

  for (const skipped of _objective_skip_categories(state)) {
    let note: string;
    if (skipped === 'layout_audit') {
      note = LAYOUT_AUDIT_SKIP_NOTE;
    } else {
      note = `${skipped} — skipped by the refiner; this check did NOT run`;
    }
    if (!state.skipped_objective_checks.includes(note)) {
      state.skipped_objective_checks.push(note);
    }
    state.add_log(`objective check skipped: ${note}`);
  }

  state.current_image_path = state.image_path;
  state.status = 'loaded';
  return state;
}

/** Run deterministic work without a model call or a final quality decision. */
export async function _prepare_iteration(
  state: VerifierRefinerState,
  prepare_image: boolean,
): Promise<PreparedIteration | null> {
  const iteration = state.current_iteration + 1;
  state.add_log(`--- iteration ${iteration}/${state.max_iterations} ---`);

  // ── Phase 1: Verify ──────────────────────────────────────────────
  const findings_before = _run_objective_checks(state);
  state.latest_findings = findings_before;
  // Rollback point. Every op mutates ``state.manifest`` in place and a batch
  // is not transactional, so without a snapshot a round that half-applies a
  // bad plan leaves the damage in the artifact that eventually ships.
  const snapshot = isDict(state.manifest) ? _deepcopy_with_py_floats(state.manifest) : null;

  const log = new IterationLog({
    iteration,
    findings_before: summarize_findings(findings_before),
  });

  // ── Phase 2: Fix — deterministic ─────────────────────────────────
  let det_edits: unknown[];
  try {
    det_edits = run_all_deterministic_fixers(state.manifest as Dict, findings_before, state.structure);
  } catch (exc) {
    if (!(exc instanceof DeterministicFixerError)) throw exc;
    const message = _exc_str(exc);
    state.add_error(message);
    state.status = 'failed';
    log.notes.push(message);
    state.iteration_logs.push(log);
    state.current_iteration = iteration;
    return null;
  }

  _apply_edit_batch(state, det_edits, log, 'deterministic_edits', '  deterministic:');

  let image_note: string | null = null;
  // Serious defects commonly also produce a low critic score. Prepare their
  // corrected view speculatively so a necessary model call does not wait for
  // another render after the critic. Clean/minor-only drafts stay lazy.
  const prepare_visual = (_major_or_critical_count(findings_before) > 0
    || objective_rank(summarize_findings(_run_objective_checks(state))).some((value) => truthy(value)));
  if (prepare_image && prepare_visual) {
    image_note = await _refresh_image_for_llm(state, log, iteration);
    if (state.status === 'failed') {
      state.iteration_logs.push(log);
      state.current_iteration = iteration;
      return null;
    }
  }
  return new PreparedIteration({
    iteration, findings_before,
    snapshot, log, image_note,
  });
}

export async function _run_one_iteration(
  state: VerifierRefinerState,
  llm_agent: RefinerLLMAgent | null,
): Promise<VerifierRefinerState> {
  let prepared = state.prepared_iteration;
  state.prepared_iteration = null;
  if (prepared === null) {
    prepared = await _prepare_iteration(state, llm_agent !== null);
  }
  if (prepared === null) {
    return state;
  }
  const iteration = prepared.iteration;
  const findings_before = prepared.findings_before;
  const score_before = _findings_score(findings_before);
  const snapshot = prepared.snapshot;
  const log = prepared.log;
  const det_outcomes = log.deterministic_edits;

  // ── Phase 3: Fix — LLM ──────────────────────────────────────────
  let llm_outcomes: EditApplyOutcome[] = [];
  const subjective_raw = _get(state.initial_report, 'subjective');
  const subjective = truthy(subjective_raw) ? (subjective_raw as Dict) : {};
  const remaining = summarize_findings(_run_objective_checks(state));
  const model_needed = (!truthy(state.initial_report) || needs_refinement({
    findings: remaining,
    score: pyGet(subjective, 'overall_score'),
    constraint_violations: pyGet(subjective, 'constraint_violations', []),
  }));
  if (llm_agent !== null && model_needed) {
    if (!truthy(prepared.image_note)) {
      prepared.image_note = await _refresh_image_for_llm(state, log, iteration);
      if (state.status === 'failed') {
        state.iteration_logs.push(log);
        state.current_iteration = iteration;
        return state;
      }
    }
    const proposed_edits = await _propose_llm_edits(state, llm_agent, log, iteration, prepared.image_note);

    if (proposed_edits.length) {
      llm_outcomes = _apply_edit_batch(state, proposed_edits, log, 'llm_edits', '  llm:          ');
    } else {
      state.add_log('  llm:           emitted=0 (no proposals)');
    }
  }

  if (!model_needed) {
    log.notes.push('LLM skipped: deterministic fixes resolved the requested quality work');
  }

  // ── Phase 4: Verify (post-fix) ───────────────────────────────────
  let findings_after_iter = _run_objective_checks(state);
  let edits_applied = _any_applied(det_outcomes) || _any_applied(llm_outcomes) || log.rerouted_arrows.length > 0;

  // ── Phase 4b: Roll back a round that made things worse ───────────
  let score_after = _findings_score(findings_after_iter);
  if (snapshot !== null && pyGt(objective_rank(summarize_findings(findings_after_iter)), objective_rank(summarize_findings(findings_before)))) {
    state.manifest = snapshot;
    log.rolled_back = true;
    const message = (
      `round ${iteration} rolled back: objective severity regressed; diagnostic score `
      + `${pyFormatFixed(score_before, 0)} → ${pyFormatFixed(score_after, 0)} `
      + `(discarded: ${pyRepr(summarize_findings(findings_after_iter))})`
    );
    log.notes.push(message);
    state.add_log(`  → ${message}`);
    findings_after_iter = findings_before;
    score_after = score_before;
    // Nothing survived, so the round made no progress. Reporting otherwise
    // would let the loop keep spending iterations re-deriving the same
    // regression from the same input.
    edits_applied = false;
  }

  log.findings_after = summarize_findings(findings_after_iter);
  state.latest_findings = findings_after_iter;
  // _findings_score: sum() of float weights is a float, except sum([]) == 0 (int).
  // min(best, after) keeps ``best`` unless ``after`` is strictly smaller.
  const score_after_f = findings_after_iter.length > 0;
  const best_findings_score_f = state.best_findings_score === null || score_after < state.best_findings_score
    ? score_after_f
    : isF(state, 'best_findings_score');
  state.best_findings_score = (
    state.best_findings_score === null
      ? score_after
      : Math.min(state.best_findings_score, score_after)
  );
  markF(state, 'best_findings_score', best_findings_score_f);

  // Decide whether another analysis image will actually be consumed. A
  // converged round proceeds directly to the required product render.
  _mark_convergence(state, log, findings_after_iter, edits_applied, iteration);
  if (!state.converged) {
    await _rerender_iteration_image(state, log, iteration);
  } else if (state.skip_rerender_between_iterations) {
    log.notes.push('re-render skipped (--no-rerender)');
  } else {
    log.notes.push('terminal analysis render omitted; final product render follows');
  }

  return state;
}

/**
 * Re-render between the deterministic pass and the LLM call.
 *
 * Costs one extra headless render per iteration. The alternative — telling
 * the model in prose that the picture predates the listed edits — is cheaper
 * but leaves it reasoning about a diagram that no longer exists, which is
 * exactly the failure this exists to prevent. ``--no-rerender`` still buys
 * the cheap path, and then the prose note is all the model gets.
 */
export async function _refresh_image_for_llm(
  state: VerifierRefinerState,
  log: IterationLog,
  iteration: number,
): Promise<string> {
  if (state.skip_rerender_between_iterations) {
    return (
      "this PNG predates this iteration's deterministic edits (re-render "
      + 'disabled). It may also be the magnified, cropped product export '
      + 'rather than a 1:1 analysis render, so treat it as qualitative '
      + 'only: do not read pixel distances from it, treat the edits listed '
      + 'below as already applied, and trust the manifest summary over the '
      + 'picture where they disagree.'
    );
  }
  if (state.analysis_manifest_fingerprint === _manifest_fingerprint(state.manifest as Dict)
      && truthy(state.current_image_path) && _is_file(state.current_image_path!)) {
    log.notes.push('reused unchanged 1:1 analysis image');
  } else {
    await _rerender_iteration_image(state, log, iteration, 'det');
  }
  if (state.status === 'failed') {
    return '';
  }
  return (
    "rendered AFTER this iteration's deterministic edits as a 1:1 "
    + 'analysis render (one image pixel = one manifest unit, uncropped), '
    + 'so it matches the manifest summary below.'
  );
}

export async function _node_finalize(
  state: VerifierRefinerState,
  vlm_model_name = 'unknown',
): Promise<VerifierRefinerState> {
  const out_dir = _path_str(state.output_dir || _path_parent(state.manifest_path));
  mkdirSync(out_dir, { recursive: true });
  const failed_before_finalize = state.status === 'failed';

  if (failed_before_finalize) {
    state.add_log('skipping refined manifest/render because refiner failed before finalize');
  } else {
    // ``state.manifest`` is the last round that did not regress: a round
    // whose *objective severity rank* got worse was rolled back in
    // _run_one_iteration. It is not necessarily the best-scoring manifest
    // (diagnostic score and visual quality are not compared here), so the
    // outer workflow's final verification still decides promotion.
    const should_promote_refined = state.converged === true;
    const manifest_name = should_promote_refined ? 'refined_manifest.json' : 'candidate_manifest.json';
    const image_name = should_promote_refined ? 'refined_diagram.png' : 'candidate_diagram.png';
    const output_manifest_path = _path_join(out_dir, manifest_name);
    const output_image_path = _path_join(out_dir, image_name);

    const stale_paths = [
      _path_join(out_dir, 'refined_manifest.json'),
      _path_join(out_dir, 'refined_diagram.png'),
      _path_join(out_dir, 'candidate_manifest.json'),
      _path_join(out_dir, 'candidate_diagram.png'),
    ];
    for (const artifact_path of stale_paths) {
      try {
        _unlink_missing_ok(artifact_path);
      } catch (exc) {
        if (!_is_os_error(exc)) throw exc;
        state.add_error(`could not remove stale refiner artifact ${artifact_path}: ${_exc_str(exc)}`);
        state.status = 'failed';
      }
    }

    let final_image_ready = false;
    if (state.status !== 'failed') {
      if (should_promote_refined || state.skip_rerender_between_iterations) {
        // Product render: renderer-default scale + smart crop. The
        // analysis mode (scale 1, uncropped) is for VLM iteration
        // input only and must not leak into shipped artifacts.
        const render_result = await render_png_result(
          state.manifest as Dict,
          output_image_path,
          state.canvas_library,
        );
        if (render_result.ok) {
          final_image_ready = true;
        } else {
          const detail = render_result.error ? `: ${render_result.error}` : '';
          const label = should_promote_refined ? 'final' : 'candidate';
          state.add_error(`${label} render failed${detail}`);
          state.status = 'failed';
          try {
            _unlink_missing_ok(output_image_path);
          } catch (exc) {
            if (!_is_os_error(exc)) throw exc;
            logger.warning(`Could not remove failed refiner image: ${output_image_path}`);
          }
        }
      } else if (truthy(state.current_image_path) && _exists(state.current_image_path!)) {
        // Non-converged candidate: reuse the last re-rendered image.
        // That PNG is an analysis render (scale 1, uncropped); this is
        // acceptable because the candidate is a debug-only artifact —
        // the orchestrator keeps the original product render as the
        // final output whenever the refiner does not converge.
        try {
          copyFileSync(state.current_image_path!, output_image_path);
          final_image_ready = true;
          state.add_log(`copied non-converged candidate image to ${output_image_path}`);
        } catch (exc) {
          if (!_is_os_error(exc)) throw exc;
          state.add_error(`could not write candidate image: ${_exc_str(exc)}`);
        }
      }
    }

    if (state.status !== 'failed') {
      try {
        writeFileSync(
          output_manifest_path,
          pyJsonDumps(withPyFloats(state.manifest), { indent: 2, ensureAscii: false }),
          'utf-8',
        );
        if (should_promote_refined) {
          state.refined_manifest_path = output_manifest_path;
          state.add_log(`wrote refined manifest to ${output_manifest_path}`);
          if (final_image_ready) {
            state.refined_image_path = output_image_path;
            state.add_log(`final render → ${output_image_path}`);
          }
        } else {
          state.candidate_manifest_path = output_manifest_path;
          state.add_log(`wrote non-converged candidate manifest to ${output_manifest_path}`);
          if (final_image_ready) {
            state.candidate_image_path = output_image_path;
          }
        }
      } catch (exc) {
        state.add_error(`could not write refiner manifest: ${_exc_str(exc)}`);
        state.status = 'failed';
        if (final_image_ready) {
          try {
            _unlink_missing_ok(output_image_path);
          } catch (unlink_exc) {
            if (!_is_os_error(unlink_exc)) throw unlink_exc;
            logger.warning(`Could not remove refiner image after manifest write failure: ${output_image_path}`);
          }
        }
      }
    }
  }

  if (state.status !== 'failed') {
    const exhausted_iterations = (
      state.current_iteration >= state.max_iterations
      && !state.converged
    );
    if (state.termination_reason === null && exhausted_iterations) {
      state.termination_reason = 'max_iterations_exhausted';
    }
    state.status = truthy(state.errors) ? 'reported_degraded' : 'reported';
  }
  const report = build_refiner_report(state, vlm_model_name);
  const paths = write_refiner_report(
    report,
    out_dir,
    undefined,
    state.emit_markdown ? 'refiner_report.md' : null,
  );
  state.refiner_report_path = (pyGet(paths, 'json') as string | null) ?? null;
  if (state.status !== 'failed') {
    state.status = truthy(state.errors) ? 'reported_degraded' : 'reported';
  }
  return state;
}

// ---------------------------------------------------------------------------
// Workflow
// ---------------------------------------------------------------------------

/** ``except (KeyError, FileNotFoundError, ValueError)`` around the model lookup. */
function _is_model_config_error(error: unknown): boolean {
  return error instanceof KeyError
    || error instanceof ValueError
    || (error as Error)?.name === 'FileNotFoundError'
    || (error as { code?: unknown })?.code === 'ENOENT';
}

/**
 * Orchestrates verify → fix → render iteration loop.
 *
 * Verification, refinement, and rendering are independent stages — this
 * workflow composes them into an iteration loop with convergence checking.
 */
export class IterativeRefinerWorkflow {
  _llm_agent: RefinerLLMAgent | null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  graph: any;

  constructor(llm_agent: RefinerLLMAgent | null = null) {
    this._llm_agent = llm_agent;
    this.graph = this._build_graph();
  }

  /** ``RefinerLLMAgent()`` needs an await to create its model. */
  async _ensure_llm(): Promise<RefinerLLMAgent> {
    if (this._llm_agent === null) {
      this._llm_agent = await RefinerLLMAgent.create();
    }
    return this._llm_agent;
  }

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  _build_graph(): any {
    let vlm_model_name: unknown = 'unknown';
    try {
      const params = ModelConfig.get_default().get_model_config('refiner');
      vlm_model_name = pyGet(params, 'model', 'unknown');
    } catch (exc) {
      // Report metadata only; an unconfigured model must not break the graph.
      if (!_is_model_config_error(exc)) throw exc;
    }

    const graph = new PydanticStateGraph(VerifierRefinerState as unknown as WorkflowStateClass);

    const iteration_node = (state: VerifierRefinerState) => this._iteration_node(state);
    const finalize = (state: VerifierRefinerState) => _node_finalize(state, vlm_model_name as string);
    graph.addNode('load_inputs', _node_load_inputs);
    graph.addNode('run_iteration', iteration_node);
    graph.addNode('finalize', finalize);

    graph.addConditionalEdges(
      START,
      (s: VerifierRefinerState) => (s.prepared_iteration !== null ? 'run_iteration' : 'load_inputs'),
      { run_iteration: 'run_iteration', load_inputs: 'load_inputs' },
    );
    graph.addConditionalEdges(
      'load_inputs',
      (s: VerifierRefinerState) => (s.status === 'failed' ? 'finalize' : 'run_iteration'),
      { finalize: 'finalize', run_iteration: 'run_iteration' },
    );
    graph.addConditionalEdges(
      'run_iteration',
      (s: VerifierRefinerState) => this._after_iteration(s),
      { run_iteration: 'run_iteration', finalize: 'finalize' },
    );
    graph.addEdge('finalize', END);

    return graph.compile();
  }

  async _iteration_node(state: VerifierRefinerState): Promise<VerifierRefinerState> {
    try {
      return await _run_one_iteration(state, await this._ensure_llm());
    } catch (exc) {
      // A half-applied round must never ship: mark the run failed so
      // finalize skips the refined/candidate artifacts and the caller
      // keeps the already-verified render.
      logger.exception('Refiner iteration raised');
      state.add_error(`refiner iteration raised ${_exc_type_name(exc)}: ${_exc_str(exc)}`);
      state.status = 'failed';
      return state;
    }
  }

  _after_iteration(state: VerifierRefinerState): string {
    if (state.status === 'failed') {
      return 'finalize';
    }
    if (truthy(state.termination_reason)) {
      return 'finalize';
    }
    if (state.converged) {
      return 'finalize';
    }
    if (state.current_iteration >= state.max_iterations) {
      if (state.termination_reason === null) {
        state.termination_reason = 'max_iterations_exhausted';
      }
      return 'finalize';
    }
    return 'run_iteration';
  }

  /**
   * Prepare the first iteration while the initial critic is running.
   *
   * No edits leave this private state until run_prepared consumes the
   * completed critic report and the normal final quality gate accepts it.
   */
  async prepare(kwargs: Dict): Promise<VerifierRefinerState> {
    const initial = new VerifierRefinerState(kwargs);
    initial.prepared_input_fingerprint = _input_fingerprint(initial);
    const state = _node_load_inputs(initial);
    if (state.status !== 'failed') {
      state.prepared_iteration = await _prepare_iteration(state, true);
    }
    return state;
  }

  async run_prepared(state: VerifierRefinerState, verifier_report_path: string): Promise<VerifierRefinerState> {
    if (state.prepared_input_fingerprint !== _input_fingerprint(state)) {
      throw new ValueError('Refiner inputs changed after preparation');
    }
    if (state.status === 'failed' || state.prepared_iteration === null) {
      throw new ValueError('Refiner preparation did not produce a usable iteration');
    }
    state.verifier_report_path = verifier_report_path;
    state.initial_report = _load_json(verifier_report_path);
    if (state.initial_report === null) {
      throw new ValueError('Completed verifier report is unavailable');
    }
    const result = await this.graph.invoke(
      state, { recursionLimit: refiner_recursion_limit(state.max_iterations) },
    );
    return result instanceof VerifierRefinerState ? result : VerifierRefinerState.model_validate(result);
  }

  async run(
    manifest_path: string,
    image_path: string,
    verifier_report_path: string | null = null,
    design_constraints = '',
    structure_path: string | null = null,
    layout_path: string | null = null,
    output_dir: string | null = null,
    canvas_library = 'excalidraw',
    max_iterations = 3,
    skip_rerender_between_iterations = false,
    skip_checks: string[] | null = null,
    emit_markdown = false,
  ): Promise<VerifierRefinerState> {
    canvas_library = _normalize_refiner_canvas_library(canvas_library);
    const initial = new VerifierRefinerState({
      manifest_path,
      image_path,
      verifier_report_path,
      design_constraints,
      structure_path,
      layout_path,
      output_dir,
      canvas_library,
      max_iterations,
      skip_rerender_between_iterations,
      skip_checks: truthy(skip_checks) ? skip_checks : [],
      emit_markdown,
    });
    const result = await this.graph.invoke(
      initial, { recursionLimit: refiner_recursion_limit(initial.max_iterations) },
    );
    if (result instanceof VerifierRefinerState) {
      return result;
    }
    if (isDict(result)) {
      return VerifierRefinerState.model_validate(result);
    }
    return initial;
  }
}

export const __all__ = ['IterativeRefinerWorkflow'];
