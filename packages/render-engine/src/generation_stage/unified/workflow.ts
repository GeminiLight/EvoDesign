// Ported from evodesign/agentic_system/generation_stage/unified/workflow.py — keep in sync.
// server-only (LangGraph.js; writes the attempt report with node:fs)
//
// UnifiedGeneratorWorkflow — wires UnifiedGenerator into a single-node LangGraph.
//
// One generation call produces the Excalidraw scene; then we run a trimmed post-pass:
// a deterministic normalizer that mirrors the pipeline-mode converter's
// z-order + group-title-dedup guarantees (so the unified path doesn't silently
// regress the 2026-04 render-fidelity fixes), followed by the validator.
// The group fitter is still skipped here because the unified generator already
// derives group bounds itself. Contract failures return the current scene and
// diagnostic to generation for at most two repairs before failing closed.
//
// ``StateGraph(UnifiedWorkflowState)`` → ``PydanticStateGraph`` (common/base_workflow.ts):
// nodes and the conditional-edge path function receive the state re-validated
// into a ``UnifiedWorkflowState``, like Python LangGraph with a pydantic schema.
// ``set_entry_point(x)`` → ``addEdge(START, x)``.

import { mkdirSync, writeFileSync } from '../../py/fs.ts';
import { dirname } from '../../py/path.ts';
import type { BaseChatModel } from '@langchain/core/language_models/chat_models';
import { END, START } from '@langchain/langgraph';
import {
  audit_manifest,
  normalize_manifest,
  validate_manifest,
} from '../../canvas_environment/validation.ts';
import {
  compact_architecture_layout,
  normalize_architecture_style,
  rebuild_excalidraw_arrows,
} from '../../canvas_environment/scene.ts';
import { PydanticStateGraph, type WorkflowStateClass } from '../../common/base_workflow.ts';
import { RuntimeError, ValueError } from '../../py/errors.ts';
import { pyJsonDumps } from '../../py/json.ts';
import { getLogger } from '../../py/logging.ts';
import { pyStr } from '../../py/str.ts';
import { isDict, truthy } from '../../py/truthy.ts';
import { _deepcopy_with_py_floats, _with_py_floats } from '../layout/sequence_layout.ts';
import { UnifiedWorkflowState } from './state.ts';
import { UnifiedGenerator } from './generator.ts';
import { complete_native_elements, complete_native_semantics } from './native_defaults.ts';
import { validate_semantic_sidecar } from './sidecar.ts';

const logger = getLogger('evodesign.agentic_system.generation_stage.unified.workflow');
export const MAX_SCENE_ATTEMPTS = 3;

type Dict = Record<string, unknown>;

/** ``str(exc)`` */
function excStr(exc: unknown): string {
  return exc instanceof Error ? exc.message : pyStr(exc);
}

/** ``raise ErrorClass(message) from cause`` */
function withCause<E extends Error>(error: E, cause: unknown): E {
  (error as { cause?: unknown }).cause = cause;
  return error;
}

/**
 * Single-shot workflow: UnifiedGenerator -> normalizer -> validator.
 *
 * The normalizer is a belt for the pipeline-mode converter's suspenders:
 * group frames paint behind their children, duplicate bound+standalone
 * titles collapse to a single header, and fractional indices become
 * zero-padded so lexicographic order matches numeric order. All three
 * are enforced by the pipeline's ``InstantiationToExcalidrawConverter``
 * but were silently bypassed on the ``--mode oneshot`` path before
 * this node was added.
 */
export class UnifiedGeneratorWorkflow {
  agent: UnifiedGenerator;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  graph: any;

  constructor(
    model: BaseChatModel,
    full_domain_knowledge = true,
  ) {
    this.agent = new UnifiedGenerator(
      model,
      null,
      full_domain_knowledge,
    );
    this.graph = this._build_graph();
  }

  _build_graph() {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const workflow: any = new PydanticStateGraph(UnifiedWorkflowState as unknown as WorkflowStateClass);
    const _run_generation_cycle = (state: UnifiedWorkflowState) => this._run_generation_cycle(state);
    workflow.addNode('generate_validate', _run_generation_cycle);
    workflow.addEdge(START, 'generate_validate');
    workflow.addConditionalEdges(
      'generate_validate',
      (state: UnifiedWorkflowState) => (
        truthy(state.validation_error) && state.generation_attempts.length < MAX_SCENE_ATTEMPTS
      ) ? 'repair' : 'done',
      { repair: 'generate_validate', done: END },
    );
    return workflow.compile();
  }

  /** Return contract failures to generation, without retrying runtime failures. */
  async _run_generation_cycle(state: UnifiedWorkflowState): Promise<UnifiedWorkflowState> {
    let stage = 'generate';
    state.candidate_output = null;
    state.diagram_manifest = null;
    state.structure_instantiation = null;
    let failure: unknown = null;
    let failed = false;
    try {
      state = await this._run_agent(state);
      stage = 'normalize';
      state = this._run_normalizer(state);
      stage = 'validate';
      state = this._run_validator(state);
    } catch (exc) {
      if (!(exc instanceof ValueError || exc instanceof RuntimeError)) {
        throw exc;
      }
      if (exc instanceof RuntimeError && stage !== 'normalize') {
        throw exc;
      }
      if (state.candidate_output === null || state.candidate_output === undefined) {
        // Transport, prompt configuration, and JSON parsing failures
        // have their own policies; there is no scene to repair here.
        throw exc;
      }
      failed = true;
      failure = exc;
    }
    if (failed) {
      const exc = failure as Error;
      let detail = excStr(exc);
      const cause = (exc as { cause?: unknown }).cause;
      if (cause !== null && cause !== undefined) {
        detail += ` Cause: ${excStr(cause)}`;
      }
      state.validation_error = detail;
      state.generation_attempts.push({
        attempt: state.generation_attempts.length + 1,
        stage,
        error: detail,
        output: _deepcopy_with_py_floats(
          state.diagram_manifest !== null && state.diagram_manifest !== undefined
            ? state.diagram_manifest
            : state.candidate_output,
        ),
      });
      logger.warning('[UnifiedGeneratorWorkflow] Scene validation failed: %s', detail);
    } else {
      state.validation_error = null;
      state.generation_attempts.push({
        attempt: state.generation_attempts.length + 1,
        stage: 'complete',
        error: null,
      });
    }
    UnifiedGeneratorWorkflow._save_attempt_report(state);
    return state;
  }

  static _save_attempt_report(state: UnifiedWorkflowState): void {
    if (!state.validation_report_path) {
      return;
    }
    const path = state.validation_report_path;
    mkdirSync(dirname(path), { recursive: true });
    const status = !state.validation_error ? 'complete' : (
      state.generation_attempts.length >= MAX_SCENE_ATTEMPTS ? 'failed' : 'repairing'
    );
    writeFileSync(path, pyJsonDumps(_with_py_floats({
      status,
      max_attempts: MAX_SCENE_ATTEMPTS,
      attempts: state.generation_attempts,
    }), { ensureAscii: false, indent: 2 }), 'utf-8');
  }

  _run_agent(state: UnifiedWorkflowState): Promise<UnifiedWorkflowState> {
    return this.agent.run(state);
  }

  /**
   * Enforce layer-based z-order + title dedup on the LLM-emitted scene.
   *
   * Normalization is part of the one-shot contract: if it fails, the scene is
   * not safe to pass to render because z-order and title semantics may be
   * wrong while still passing schema validation.
   */
  _run_normalizer(state: UnifiedWorkflowState): UnifiedWorkflowState {
    const manifest = state.diagram_manifest;
    if (!isDict(manifest)) {
      return state;
    }
    try {
      complete_native_elements(manifest);
      complete_native_semantics(manifest);
      normalize_manifest(manifest, 'excalidraw');
      logger.info(
        '[UnifiedGeneratorWorkflow/normalizer] z-order + title dedup applied (%d elements)',
        ((manifest.elements as unknown[] | null) || []).length,
      );
    } catch (exc) {
      throw withCause(new RuntimeError(
        'UnifiedGeneratorWorkflow normalizer failed; refusing to render '
        + 'an unnormalized one-shot manifest.',
      ), exc);
    }
    try {
      state.structure_instantiation = validate_semantic_sidecar(manifest);
    } catch (exc) {
      if (exc instanceof ValueError) {
        throw withCause(new ValueError(
          'UnifiedGeneratorWorkflow normalizer produced an invalid '
          + `semantic sidecar: ${exc.message}`,
        ), exc);
      }
      throw exc;
    }
    // Keep one-shot output visually consistent with the pipeline renderer.
    // The unified generator emits native Excalidraw, so this is a small
    // deterministic polish pass rather than a second layout strategy.
    let polished: Dict = compact_architecture_layout(
      manifest,
      state.structure_instantiation as Dict,
    );
    if (polished !== manifest) {
      polished = rebuild_excalidraw_arrows(
        polished,
        state.structure_instantiation as Dict,
      );
    }
    state.diagram_manifest = normalize_architecture_style(
      polished,
      state.structure_instantiation as Dict,
    );
    if (state.diagram_manifest !== manifest) {
      try {
        normalize_manifest(
          state.diagram_manifest,
          'excalidraw',
        );
        state.structure_instantiation = validate_semantic_sidecar(
          state.diagram_manifest,
        );
      } catch (exc) {
        throw withCause(new RuntimeError(
          'UnifiedGeneratorWorkflow post-layout normalization failed; '
          + 'refusing to render stale arrow geometry.',
        ), exc);
      }
    }
    return state;
  }

  _run_validator(state: UnifiedWorkflowState): UnifiedWorkflowState {
    const manifest = (truthy(state.diagram_manifest) ? state.diagram_manifest : {}) as Dict;
    // Validator mutates nothing; schema errors must stop one-shot output
    // before it reaches the renderer, especially when the caller disables
    // the downstream verifier.
    const report = validate_manifest(manifest, 'excalidraw');
    const is_valid = Object.prototype.hasOwnProperty.call(report, 'is_valid') ? report.is_valid : true;
    if (!truthy(is_valid)) {
      const errors = (truthy(report.errors) ? report.errors : []) as unknown[];
      for (const err of errors) {
        logger.error('[UnifiedGeneratorWorkflow] validator: %s', err);
      }
      const message = errors.map((err) => pyStr(err)).join('; ') || 'unknown schema error';
      throw new ValueError(`UnifiedGeneratorWorkflow schema validation failed: ${message}`);
    }
    const audit_report = audit_manifest(
      manifest,
      state.structure_instantiation,
      'excalidraw',
    );
    state.audit_warnings = [...audit_report.warnings];
    return state;
  }

  async run(state: UnifiedWorkflowState): Promise<UnifiedWorkflowState> {
    logger.info('Starting unified generator workflow (single-shot)...');
    const result = await this.graph.invoke(state);
    const final = (
      isDict(result) ? new UnifiedWorkflowState(result) : result
    ) as UnifiedWorkflowState;
    if (final.validation_error) {
      throw new ValueError(
        `Unified scene remains invalid after ${final.generation_attempts.length} `
        + `attempts: ${final.validation_error}`,
      );
    }
    logger.info('Unified generator workflow finished.');
    return final;
  }
}
