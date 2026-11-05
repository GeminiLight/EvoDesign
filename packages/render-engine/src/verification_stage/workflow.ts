// Ported from evodesign/agentic_system/verification_stage/workflow.py — keep in sync.
// server-only (file I/O, LangGraph.js)
//
// VerifierWorkflow — LangGraph orchestrator for objective + subjective verify.
//
// Four nodes:
//     load_inputs           load manifest / structure / layout JSON from disk
//     run_objective_checks  pure computation, no LLM
//     run_subjective_critic single VLM call (skipped when state.skip_critic)
//     build_report          merge → write verifier_report.json (+.md optional)
//
// Each node only mutates ``state`` and never raises out of the graph: failures
// go into ``state.errors`` so partial results still get written. This matches
// the render/validation boundary's "always emit something" philosophy.
//
// ``StateGraph(VerifierState)`` → ``PydanticStateGraph`` (common/base_workflow.ts):
// a LangGraph.js StateGraph whose nodes and path functions receive the state
// re-validated into a ``VerifierState`` instance, like Python LangGraph with a
// pydantic schema. ``_node_run_subjective_critic`` and ``run`` are async.

import { existsSync, readFileSync } from 'node:fs';
import { END, START } from '@langchain/langgraph';
import { validate_png_file } from '../canvas_environment/index.ts';
import { run_all_checks } from './checks/aggregator.ts';
import { summarize_findings } from './checks/finding.ts';
import { build_report, write_report } from './reports/report_builder.ts';
import { VerifierState } from './state.ts';
import { constraint_prompt } from '../common/design_constraints.ts';
import { PydanticStateGraph, type WorkflowStateClass } from '../common/base_workflow.ts';
import { ModelConfig } from '../config/model_loader.ts';
import { JSONDecodeError, KeyError, RuntimeError, ValueError } from '../py/errors.ts';
import { PyJSONDecodeError, pyJsonLoadsExact } from '../py/json_decoder.ts';
import { getLogger } from '../py/logging.ts';
import { pyGet } from '../py/dict.ts';
import { pyFormatFixed, pyRepr, pyStr } from '../py/str.ts';
import { isDict, truthy } from '../py/truthy.ts';

const logger = getLogger('evodesign.agentic_system.verification_stage.workflow');

type Dict = Record<string, any>;

// ---------------------------------------------------------------- pathlib helpers

/** ``Path(p).parts`` for POSIX paths. */
function _path_parts(path: string): string[] {
  const parts: string[] = [];
  let rest = path;
  if (rest.startsWith('/')) {
    // POSIX keeps exactly two leading slashes, collapses three or more.
    const lead = /^\/+/.exec(rest)![0].length;
    parts.push(lead === 2 ? '//' : '/');
    rest = rest.slice(lead);
  }
  for (const part of rest.split('/')) {
    if (part && part !== '.') parts.push(part);
  }
  return parts;
}

/** ``str(Path(*parts))`` */
function _join_parts(parts: string[]): string {
  if (!parts.length) return '.';
  const [first, ...rest] = parts;
  if (first === '/' || first === '//') return first + rest.join('/');
  return parts.join('/');
}

/** ``str(Path(p).parent)`` */
function _path_parent(path: string): string {
  const parts = _path_parts(path);
  const anchored = parts.length > 0 && (parts[0] === '/' || parts[0] === '//');
  if (parts.length <= (anchored ? 1 : 0)) return _join_parts(parts);
  return _join_parts(parts.slice(0, -1));
}

/** ``Path(p).exists()`` */
function _exists(path: string): boolean {
  try {
    return existsSync(path);
  } catch {
    return false;
  }
}

/** Node fs errors are Python ``OSError``s. */
function _is_os_error(error: unknown): boolean {
  return typeof (error as { code?: unknown })?.code === 'string';
}

/** ``str(exc)`` */
function _exc_str(error: unknown): string {
  if (error instanceof KeyError) return pyRepr(error.message);
  if (error instanceof Error) return error.message;
  return pyStr(error);
}

// ---------------------------------------------------------------- helpers

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

/**
 * If structure_path is .../1_structure/structure_instantiation.json, look
 * for the sibling .../3_layout/layout_instantiation.json.
 */
export function _resolve_layout_path(structure_path: string | null): string | null {
  if (!truthy(structure_path)) {
    return null;
  }
  const parts = _path_parts(structure_path!);
  if (!parts.includes('1_structure')) {
    return null;
  }
  const replaced = parts.map((part) => (part === '1_structure' ? '3_layout' : part));
  // .with_name("layout_instantiation.json"); the name is the last part (never
  // the anchor here: "1_structure" is a real component).
  const layout_parts = [...replaced.slice(0, -1), 'layout_instantiation.json'];
  const layout_p = _join_parts(layout_parts);
  if (_exists(layout_p)) {
    return layout_p;
  }
  return null;
}

// ---------------------------------------------------------------- nodes

export function _node_load_inputs(state: VerifierState): VerifierState {
  state.add_log(`loading inputs: manifest=${state.manifest_path}`);

  const manifest = _load_json(state.manifest_path);
  if (manifest === null) {
    state.add_error(`Could not load manifest from ${state.manifest_path}`);
    state.status = 'failed';
    return state;
  }
  state.manifest = manifest;

  if (truthy(state.structure_path)) {
    state.structure = _load_json(state.structure_path);
    if (state.structure === null) {
      state.add_error(
        `Could not load explicit structure_path from ${state.structure_path}; `
        + 'structure-dependent verification checks were skipped.',
      );
    }
  }

  const explicit_layout_path = state.layout_path;
  const layout_path = truthy(explicit_layout_path) ? explicit_layout_path : _resolve_layout_path(state.structure_path);
  if (truthy(layout_path)) {
    state.layout_instantiation = _load_json(layout_path);
    if (truthy(state.layout_instantiation)) {
      state.add_log(`loaded layout_instantiation from ${layout_path}`);
    } else if (truthy(explicit_layout_path)) {
      state.add_error(
        `Could not load explicit layout_path from ${layout_path}; `
        + 'layout-dependent verification checks cannot run.',
      );
    } else {
      state.add_log(`layout_path ${layout_path} could not be loaded`);
    }
  }

  const image_p = state.image_path;
  try {
    validate_png_file(image_p, 'verifier input');
    state.add_log(`loaded PNG image from ${state.image_path}`);
  } catch (exc) {
    if (!(exc instanceof RuntimeError)) throw exc;
    state.add_error(_exc_str(exc));
    state.status = 'failed';
    return state;
  }

  state.status = 'loaded';
  return state;
}

export function _node_run_objective_checks(state: VerifierState): VerifierState {
  if (state.manifest === null) {
    return state;
  }
  try {
    const findings = run_all_checks(
      state.manifest,
      state.structure,
      state.layout_instantiation,
      state.canvas_library,
      state.skip_checks,
    );
    state.objective_findings = findings;
    state.objective_summary = summarize_findings(findings);
    state.add_log(`objective: ${findings.length} findings (${pyRepr(state.objective_summary)})`);
    state.status = 'checked';
  } catch (exc) {
    logger.exception('objective checks failed');
    state.add_error(`objective checks failed: ${_exc_str(exc)}`);
    state.status = 'failed';
  }
  return state;
}

export async function _node_run_subjective_critic(state: VerifierState): Promise<VerifierState> {
  if (state.skip_critic) {
    state.add_log('subjective critic skipped (--no-critic)');
    return state;
  }

  const image_p = state.image_path;
  if (!_exists(image_p)) {
    state.add_error(`cannot critique — image missing at ${state.image_path}`);
    return state;
  }

  try {
    const { VerifierCriticAgent, review_image_edge_limit } = await import('./critic/critic_agent.ts');

    let chart_type: string | null = null;
    if (isDict(state.structure)) {
      chart_type = pyGet(state.structure, 'chart_type') as string | null;
    }

    const agent = await VerifierCriticAgent.create(
      null,
      undefined,
      undefined,
      review_image_edge_limit(state.image_path, state.manifest),
    );
    const critique = await agent.critique(
      state.image_path,
      chart_type,
      (state.source_text || '') + constraint_prompt(state.design_constraints),
      truthy(state.objective_summary) ? { ...state.objective_summary } : null,
    );
    state.critique = critique;
    state.status = 'critiqued';
    state.add_log(
      `subjective critic ok: structure=${pyFormatFixed(critique.structure.score, 1)}, `
      + `styling=${pyFormatFixed(critique.styling.score, 1)}, `
      + `layout=${pyFormatFixed(critique.layout.score, 1)}, overall=${pyFormatFixed(critique.overall_score, 1)}`,
    );
  } catch (exc) {
    logger.exception('subjective critic failed');
    state.add_error(`subjective critic failed: ${_exc_str(exc)}`, false);
  }
  return state;
}

/** ``except (KeyError, FileNotFoundError, ValueError)`` around the model lookup. */
function _is_model_config_error(error: unknown): boolean {
  return error instanceof KeyError
    || error instanceof ValueError
    || (error as Error)?.name === 'FileNotFoundError'
    || (error as { code?: unknown })?.code === 'ENOENT';
}

export function _node_build_report(state: VerifierState): VerifierState {
  const out_dir = state.output_dir || _path_parent(state.manifest_path);

  let vlm_model: unknown = 'unknown';
  try {
    const params = ModelConfig.get_default().get_model_config('verifier');
    vlm_model = pyGet(params, 'model', 'unknown');
  } catch (exc) {
    // Report metadata only; an unconfigured model must not fail the report.
    if (!_is_model_config_error(exc)) throw exc;
  }

  let final_status: string;
  if (state.has_blocking_errors) {
    final_status = 'reported_with_errors';
  } else if (state.has_blocking_findings) {
    final_status = 'reported_with_findings';
  } else if (state.has_nonblocking_errors) {
    final_status = 'reported_with_warnings';
  } else {
    final_status = 'reported';
  }
  state.status = final_status;
  const report = build_report(state, vlm_model as string | null);
  state.report = report;

  try {
    const paths = _report_writer.write_report(
      report,
      out_dir,
      'verifier_report.json',
      state.emit_markdown ? 'verifier_report.md' : null,
    );
    state.report_path = pyGet(paths, 'json') as string | null;
    state.add_log(`report written to ${state.report_path}`);
  } catch (exc) {
    logger.exception('failed to write verifier report');
    state.add_error(`failed to write report: ${_exc_str(exc)}`, false);
    state.status = 'reported_with_warnings';
    state.report = build_report(state, vlm_model as string | null);
  }

  return state;
}

/**
 * Module-level binding of ``write_report`` (Python looks the name up in this
 * module's globals at call time, which tests monkeypatch). TS module imports
 * are read-only, so the call goes through this object.
 */
export const _report_writer = { write_report };

// ---------------------------------------------------------------- workflow

/** Compile-once / invoke-many wrapper around the 4-node verifier graph. */
export class VerifierWorkflow {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  graph: any;

  constructor() {
    this.graph = this._build_graph();
  }

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  _build_graph(): any {
    const graph = new PydanticStateGraph(VerifierState as unknown as WorkflowStateClass);

    graph.addNode('load_inputs', _node_load_inputs);
    graph.addNode('run_objective_checks', _node_run_objective_checks);
    graph.addNode('run_subjective_critic', _node_run_subjective_critic);
    graph.addNode('build_report', _node_build_report);

    graph.addEdge(START, 'load_inputs');
    graph.addConditionalEdges(
      'load_inputs',
      (s: VerifierState) => (s.status === 'failed' ? 'build_report' : 'run_objective_checks'),
      { build_report: 'build_report', run_objective_checks: 'run_objective_checks' },
    );
    graph.addConditionalEdges(
      'run_objective_checks',
      (s: VerifierState) => (s.status === 'failed' ? 'build_report' : 'run_subjective_critic'),
      { build_report: 'build_report', run_subjective_critic: 'run_subjective_critic' },
    );
    graph.addEdge('run_subjective_critic', 'build_report');
    graph.addEdge('build_report', END);

    return graph.compile();
  }

  /** Run the full workflow end-to-end. Returns the final state. */
  async run(
    manifest_path: string,
    image_path: string,
    canvas_library = 'excalidraw',
    structure_path: string | null = null,
    layout_path: string | null = null,
    source_text: string | null = null,
    design_constraints = '',
    output_dir: string | null = null,
    skip_critic = false,
    skip_checks: string[] | null = null,
    emit_markdown = false,
  ): Promise<VerifierState> {
    const initial = new VerifierState({
      manifest_path,
      image_path,
      canvas_library,
      structure_path,
      layout_path,
      source_text,
      design_constraints,
      output_dir,
      skip_critic,
      skip_checks: truthy(skip_checks) ? skip_checks : [],
      emit_markdown,
    });
    // LangGraph's invoke returns a plain dict (the state schema), so we
    // rebuild the pydantic model for typed access at call sites.
    const result = await this.graph.invoke(initial);
    if (result instanceof VerifierState) {
      return result;
    }
    if (isDict(result)) {
      return VerifierState.model_validate(result);
    }
    // Should never happen; defensively return the original.
    return initial;
  }
}

export const __all__ = ['VerifierWorkflow'];
