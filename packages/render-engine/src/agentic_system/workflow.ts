// Ported from evodesign/agentic_system/workflow.py — keep in sync.
// server-only (file I/O, temp dirs, rendering)
//
// Text2Diagram Orchestrator — 5-phase pipeline.
//
// Phase 1: Generate  — Structure → Styling → Layout
// Phase 2: Render    — manifest JSON + PNG via canvas_environment
// Phase 3: Verify    — objective checks + optional VLM critic
// Phase 4: Refine    — deterministic + LLM fix loop (optional)
// Phase 5: Finalize  — save outputs, report
//
// TS notes:
// * Keyword-only parameters are positional in declaration order (MIGRATION_PLAN §2).
// * Everything that calls a model, renders or runs a LangGraph graph is async;
//   the call order is the Python one.
// * ``user_memory`` / ``design_memory`` are not ported (PHASE2_PLAN §1). Their
//   entry points are injectable through ``user_memory_hooks`` and
//   ``design_memory_hooks``. With nothing injected the workflow behaves like
//   Python with those packages unavailable (ImportError paths): user memory is
//   disabled with a warning, design memory degrades with a recorded error.
//   With the features off (the default for recorded runs) neither is touched.

import { copyFileSync, existsSync, mkdirSync, readFileSync, rmSync, statSync, tmpdir, writeFileSync } from '../py/fs.ts';
import { dirname, isAbsolute, join, relative, resolve } from '../py/path.ts';
import { withPyFloats } from '../py/float_marks.ts';
import type { BaseChatModel } from '@langchain/core/language_models/chat_models';

import { require_generation_capability, require_refiner_capability } from '../canvas_environment/capabilities.ts';
import { AgenticSystemConfig } from './config.ts';
import { RenderResult, render_manifest, render_png_result } from '../canvas_environment/index.ts';
import { normalize_canvas_library } from '../canvas_runtime.ts';
import { normalize_generation_mode } from '../config/settings.ts';
import { require_icon_assets_available } from '../common/icon_assets.ts';
import { LayoutValidationError, validate_layout_instantiation } from '../common/layout_contract.ts';
import { create_generator, type GeneratorWorkflow } from '../generation_stage/workflow.ts';
import { StructureValidationError, validate_structure_instantiation } from '../generation_stage/structure/schemas.ts';
import { StylingValidationError, validate_styling_instantiation } from '../generation_stage/styling/schemas.ts';
import { VerifierWorkflow } from '../verification_stage/workflow.ts';
import { IterativeRefinerWorkflow } from './iterative_workflow.ts';
import { VerifierRefinerState } from '../refinement_stage/state.ts';
import { build_design_constraints } from '../common/design_constraints.ts';
import { quality_status, quality_summary, refinement_rejection, should_refine } from './quality_policy.ts';
import { llm_run_budget_from_env } from '../core/base_agent.ts';

import { ensure_env_loaded } from '../utils/env_loader.ts';
import { EXPERIMENTS_DIR } from '../utils/path_manager.ts';

import { field, BaseModel, type FieldSpec } from '../py/pydantic.ts';
import { KeyError, RuntimeError, ValueError } from '../py/errors.ts';
import { PyJSONDecodeError, pyJsonLoadsExact } from '../py/json_decoder.ts';
import { pyJsonDumps } from '../py/json.ts';
import { getLogger } from '../py/logging.ts';
import { pyGet, pyPop } from '../py/dict.ts';
import { pyRepr, pyStr, pyStrip } from '../py/str.ts';
import { isBool, isDict, isInt, isList, isStr, pyOr, pyTypeName, truthy } from '../py/truthy.ts';

ensure_env_loaded();

const logger = getLogger('evodesign.agentic_system.workflow');

type Dict = Record<string, any>;

/** ``_DEFAULT_SAVE_DIR = object()`` */
export const _DEFAULT_SAVE_DIR: unique symbol = Symbol('_DEFAULT_SAVE_DIR');
export const DEFAULT_WORKFLOW_SAVE_DIR = EXPERIMENTS_DIR;

// Markers that fence the retrieved design-memory block inside the assembled
// ``design_expertise`` string. The block has to stay one identifiable segment:
// ``WorkflowState.design_memory_retrieved_items`` is the provenance record for
// exactly this text, and interleaving it with caller-supplied expertise or user
// preferences would make that record unverifiable.
export const DESIGN_MEMORY_SECTION_HEADER = '=== RETRIEVED DESIGN KNOWLEDGE ===';
export const DESIGN_MEMORY_SECTION_FOOTER = '=== END RETRIEVED DESIGN KNOWLEDGE ===';

export const DEFAULT_DESIGN_MEMORY_TOP_K = 5;
export const DEFAULT_DESIGN_MEMORY_SCORE_THRESHOLD = 0.0;

// ---------------------------------------------------------------------------
// Injectable out-of-scope subsystems (user_memory / design_memory)
// ---------------------------------------------------------------------------

/** ``DiagramDesignRetriever``-shaped object returned by ``load_shared_retriever``. */
export interface DesignMemoryRetriever {
  retrieve_design_expertise(
    query: string,
    options: { diagram_type: string; content_area: string; retrieval_query: string; top_k: number; score_threshold: number },
  ): Promise<[string | null, Dict[] | null]> | [string | null, Dict[] | null];
}

/** ``evodesign.design_memory.shared_retriever`` entry points (not ported). */
export const design_memory_hooks: {
  load_shared_retriever: ((vector_db_path: string | null, embedding_model_name: string | null) => [DesignMemoryRetriever | null, string | null]) | null;
  reset_shared_retriever_cache: (() => void) | null;
} = {
  load_shared_retriever: null,
  reset_shared_retriever_cache: null,
};

/** ``evodesign.user_memory.main.UserPreferenceMemorySystem``-shaped object. */
export interface UserPreferenceMemorySystemLike {
  retrieve_preferences(options: {
    query: string; agent_category: string; diagram_type: string | null; content_area: string | null; min_confidence: number; top_k: number;
  }): Promise<unknown[]> | unknown[];
  format_preferences_for_prompt(prefs: unknown[], max_length: number): Promise<string> | string;
  learn_from_edit?(options: Dict): Promise<Dict> | Dict;
}

/** ``evodesign.user_memory.main`` (not ported): inject a constructor to enable user memory. */
export const user_memory_hooks: {
  UserPreferenceMemorySystem: ((options: { user_id: string; memory_db_path: string | null }) => UserPreferenceMemorySystemLike) | null;
} = {
  UserPreferenceMemorySystem: null,
};

/** Message of the ``ImportError`` the TS port stands in for. */
export const _USER_MEMORY_IMPORT_ERROR = "No module named 'evodesign.user_memory' (not ported to TypeScript)";
export const _DESIGN_MEMORY_IMPORT_ERROR = "No module named 'evodesign.design_memory' (not ported to TypeScript)";

/** Drop the shared design-memory retrievers (tests, or after a rebuild). */
export function reset_design_memory_cache(): void {
  const reset = design_memory_hooks.reset_shared_retriever_cache;
  if (reset === null) {
    return;
  }
  reset();
}

/**
 * Backward-compatible alias of ``design_memory.shared_retriever.load_shared_retriever``.
 *
 * Kept under this private name because ``backend/app/services`` imports it.
 */
export function _load_design_memory_retriever(
  vector_db_path: string | null,
  embedding_model_name: string | null,
): [DesignMemoryRetriever | null, string | null] {
  const load = design_memory_hooks.load_shared_retriever;
  if (load === null) {
    return [null, `design memory dependencies unavailable: ${_DESIGN_MEMORY_IMPORT_ERROR}`];
  }
  return load(vector_db_path, embedding_model_name);
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** ``str(exc)`` */
function _exc_str(exc: unknown): string {
  if (exc instanceof KeyError) return pyRepr(exc.message);
  if (exc instanceof Error) return exc.message;
  return pyStr(exc);
}

/** ``getattr(obj, name, default)`` */
function getattr(obj: unknown, name: string, defaultValue: unknown = null): unknown {
  if (obj === null || obj === undefined) return defaultValue;
  const value = (obj as Dict)[name];
  return value === undefined ? defaultValue : value;
}

/**
 * Recover ``locked_nodes`` from a runtime-directives string (legacy path).
 *
 * Accepts the backend format (a header line followed by a JSON object) and
 * bare JSON. Unparsable directives are logged instead of silently dropping
 * the user's locks.
 */
export function _locked_nodes_from_runtime_directives(runtime_directives: string): string[] {
  const text = pyStrip(runtime_directives || '');
  if (!text) {
    return [];
  }
  const candidates = [text];
  if (text.includes('\n')) {
    candidates.push(pyStrip(text.slice(text.indexOf('\n') + 1)));
  }
  for (const candidate of candidates) {
    let data: unknown;
    try {
      data = pyJsonLoadsExact(candidate);
    } catch (exc) {
      if (exc instanceof ValueError || exc instanceof PyJSONDecodeError) continue;
      throw exc;
    }
    if (!isDict(data)) {
      continue;
    }
    const nodes = pyGet(data, 'locked_nodes', []);
    if (isList(nodes)) {
      return nodes.map((node) => pyStr(node));
    }
    logger.warning(
      `runtime_directives.locked_nodes is not a list (${pyTypeName(nodes)}); no nodes locked`,
    );
    return [];
  }
  logger.warning(
    'Could not parse runtime_directives as JSON; locked nodes (if any) '
    + 'are not enforced. Pass locked_nodes= explicitly instead.',
  );
  return [];
}

/** Save JSON data to file, creating parent dirs as needed. */
export function _save_json(filepath: string, data: unknown): void {
  mkdirSync(dirname(filepath), { recursive: true });
  writeFileSync(filepath, pyJsonDumps(withPyFloats(data), { indent: 2, ensureAscii: false }), 'utf-8');
  logger.info(`Saved: ${filepath}`);
}

export function _optional_str(value: unknown): string | null {
  return value !== null && value !== undefined ? pyStr(value) : null;
}

export function _optional_bool(value: unknown): boolean | null {
  return isBool(value) ? value : null;
}

export function _optional_int(value: unknown): number | null {
  return isInt(value) ? (value as number) : null;
}

export function _refinement_regression_reason(initial: unknown, candidate: unknown): string | null {
  return refinement_rejection(initial, candidate);
}

export function _optional_string_list(value: unknown): string[] | null {
  if (value === null || value === undefined) {
    return null;
  }
  if (isList(value)) {
    return value.map((item) => pyStr(item));
  }
  if (isStr(value)) {
    return [value];
  }
  return null;
}

export function _optional_int_dict(value: unknown): Record<string, number> | null {
  if (!isDict(value)) {
    return null;
  }
  const result: Record<string, number> = {};
  for (const [key, item] of Object.entries(value)) {
    if (isBool(item)) {
      continue;
    }
    // JS numbers cannot tell ``1`` from ``1.0``; both paths give ``int(item)``.
    if (typeof item === 'number' && Number.isInteger(item)) {
      result[pyStr(key)] = item;
    }
  }
  return result;
}

/** Normalize design-memory provenance records for the public state. */
export function _optional_retrieved_items(value: unknown): Record<string, string>[] | null {
  if (!isList(value)) {
    return null;
  }
  const items: Record<string, string>[] = value
    .filter((entry) => isDict(entry))
    .map((entry) => Object.fromEntries(Object.entries(entry as Dict).map(([key, item]) => [pyStr(key), pyStr(item)])));
  return items.length ? items : null;
}

export function _has_error_values(value: unknown): boolean {
  if (value === null || value === undefined) {
    return false;
  }
  if (isStr(value)) {
    return Boolean(value);
  }
  if (isList(value)) {
    return value.length > 0;
  }
  return false;
}

/** Return whether verifier failures make refinement unsafe to run. */
export function _has_blocking_verification_errors(verifier_state: unknown): boolean {
  if (verifier_state === null || verifier_state === undefined) {
    return false;
  }

  const has_blocking_errors = getattr(verifier_state, 'has_blocking_errors', null);
  if (has_blocking_errors === true) {
    return true;
  }
  if (has_blocking_errors === false) {
    return false;
  }

  const blocking_errors = getattr(verifier_state, 'blocking_errors', null);
  if (isList(blocking_errors)) {
    return blocking_errors.length > 0;
  }
  if (isStr(blocking_errors)) {
    return Boolean(blocking_errors);
  }

  return getattr(verifier_state, 'has_errors', false) === true;
}

export function _finding_summary(finding: unknown): Dict {
  if (finding !== null && typeof (finding as { model_dump?: unknown }).model_dump === 'function') {
    return (finding as BaseModel).model_dump();
  }
  if (isDict(finding)) {
    return { ...finding };
  }
  return { message: pyStr(finding) };
}

export function _refiner_findings_summary(refiner_state: unknown): Dict[] | null {
  if (refiner_state === null || refiner_state === undefined) {
    return null;
  }
  const latest_findings = getattr(refiner_state, 'latest_findings', null);
  if (!isList(latest_findings)) {
    return null;
  }
  return latest_findings.map((finding) => _finding_summary(finding));
}

/** ``Model.model_construct(**values)``: no validation, defaults for missing fields. */
function _model_construct<T extends BaseModel>(cls: { prototype: T; model_fields: Record<string, FieldSpec> }, values: Dict): T {
  const instance = Object.create(cls.prototype) as T;
  for (const [name, spec] of Object.entries(cls.model_fields)) {
    let value: unknown;
    if (Object.prototype.hasOwnProperty.call(values, name)) value = values[name];
    else if (spec.default_factory) value = spec.default_factory();
    else if ('default' in spec) value = spec.default;
    else continue;
    Object.defineProperty(instance, name, { value, writable: true, enumerable: true, configurable: true });
  }
  return instance;
}

// ---------------------------------------------------------------------------
// Orchestrator state
// ---------------------------------------------------------------------------

/** ``Optional[List[str]]`` (strict str items, like pydantic v2). */
function _optional_str_list_field(value: unknown): unknown {
  if (value === null) return null;
  if (!isList(value)) throw new ValueError('Input should be a valid list');
  for (const item of value) if (!isStr(item)) throw new ValueError('Input should be a valid string');
  return [...value];
}

/** ``Optional[Dict[str, int]]`` */
function _optional_str_int_dict_field(value: unknown): unknown {
  if (value === null) return null;
  if (!isDict(value)) throw new ValueError('Input should be a valid dictionary');
  const out: Record<string, number> = {};
  for (const [key, item] of Object.entries(value)) {
    if (typeof item === 'boolean') out[key] = item ? 1 : 0;
    else if (typeof item === 'number' && Number.isInteger(item)) out[key] = item;
    else throw new ValueError('Input should be a valid integer');
  }
  return out;
}

/** ``Optional[List[Dict[...]]]`` */
function _optional_list_of_dict_field(value: unknown): unknown {
  if (value === null) return null;
  if (!isList(value)) throw new ValueError('Input should be a valid list');
  return value.map((item) => {
    if (!isDict(item)) throw new ValueError('Input should be a valid dictionary');
    return { ...item };
  });
}

/** ``Optional[Dict[str, str]]`` */
function _optional_str_dict_field(value: unknown): unknown {
  if (value === null) return null;
  if (!isDict(value)) throw new ValueError('Input should be a valid dictionary');
  for (const item of Object.values(value)) if (!isStr(item)) throw new ValueError('Input should be a valid string');
  return { ...value };
}

/** Top-level state for the full Text2Diagram pipeline. */
export class WorkflowState extends BaseModel {
  static override pythonName = 'evodesign.agentic_system.workflow.WorkflowState';
  static override model_fields: Record<string, FieldSpec> = {
    text_content: field({ type: 'str', required: true }),
    user_query: field({ type: 'str', required: true }),

    // Generation outputs
    structure_instantiation: field({ type: 'optional_dict', default: null }),
    structure_specification: field({ type: 'optional_dict', default: null }),
    styling_instantiation: field({ type: 'optional_dict', default: null }),
    styling_specification: field({ type: 'optional_dict', default: null }),
    layout_instantiation: field({ type: 'optional_dict', default: null }),
    layout_specification: field({ type: 'optional_dict', default: null }),

    // Render outputs
    diagram_manifest: field({ type: 'optional_dict', default: null }),
    manifest_path: field({ type: 'optional_str', default: null }),
    png_path: field({ type: 'optional_str', default: null }),

    // Refinement outputs
    refined_diagram_manifest: field({ type: 'optional_dict', default: null }),
    refined_manifest_path: field({ type: 'optional_str', default: null }),
    refined_png_path: field({ type: 'optional_str', default: null }),
    refiner_status: field({ type: 'optional_str', default: null }),
    refiner_converged: field({ type: 'optional_bool', default: null }),
    refiner_degraded: field({ type: 'bool', default: false }),
    refiner_errors: field({ before: _optional_str_list_field, default: null }),
    refiner_termination_reason: field({ type: 'optional_str', default: null }),
    refiner_latest_findings_summary: field({ before: _optional_list_of_dict_field, default: null }),
    refiner_candidate_manifest_path: field({ type: 'optional_str', default: null }),
    refiner_candidate_png_path: field({ type: 'optional_str', default: null }),

    // Final artifacts selected for downstream consumers.
    final_diagram_manifest: field({ type: 'optional_dict', default: null }),
    final_manifest_path: field({ type: 'optional_str', default: null }),
    final_png_path: field({ type: 'optional_str', default: null }),
    verification_report_path: field({ type: 'optional_str', default: null }),
    verification_status: field({ type: 'optional_str', default: null }),
    verification_quality_passed: field({ type: 'optional_bool', default: null }),
    quality_status: field({ type: 'str', default: 'unverified' }),
    verification_cli_exit_code: field({ type: 'optional_int', default: null }),
    verification_objective_summary: field({ before: _optional_str_int_dict_field, default: null }),
    verification_errors: field({ before: _optional_str_list_field, default: null }),
    refiner_report_path: field({ type: 'optional_str', default: null }),
    user_memory_enabled: field({ type: 'bool', default: false }),
    user_memory_degraded: field({ type: 'bool', default: false }),
    user_memory_errors: field({ before: _optional_str_list_field, default: null }),
    // Design memory observability. ``design_memory_enabled`` says design
    // knowledge was actually available for injection, ``design_memory_degraded``
    // says it was requested but could not be used (missing store, missing
    // dependency, failed consistency check, failed retrieval), and
    // ``design_memory_retrieved_items`` records which entries reached the prompt.
    design_memory_enabled: field({ type: 'bool', default: false }),
    design_memory_degraded: field({ type: 'bool', default: false }),
    design_memory_errors: field({ before: _optional_str_list_field, default: null }),
    design_memory_retrieved_items: field({ before: (v) => (v === null ? null : (_optional_list_of_dict_field(v) as Dict[]).map((d) => _optional_str_dict_field(d))), default: null }),
    artifact_paths: field({ before: _optional_str_dict_field, default: null }),
  };

  declare text_content: string;
  declare user_query: string;
  declare structure_instantiation: Dict | null;
  declare structure_specification: Dict | null;
  declare styling_instantiation: Dict | null;
  declare styling_specification: Dict | null;
  declare layout_instantiation: Dict | null;
  declare layout_specification: Dict | null;
  declare diagram_manifest: Dict | null;
  declare manifest_path: string | null;
  declare png_path: string | null;
  declare refined_diagram_manifest: Dict | null;
  declare refined_manifest_path: string | null;
  declare refined_png_path: string | null;
  declare refiner_status: string | null;
  declare refiner_converged: boolean | null;
  declare refiner_degraded: boolean;
  declare refiner_errors: string[] | null;
  declare refiner_termination_reason: string | null;
  declare refiner_latest_findings_summary: Dict[] | null;
  declare refiner_candidate_manifest_path: string | null;
  declare refiner_candidate_png_path: string | null;
  declare final_diagram_manifest: Dict | null;
  declare final_manifest_path: string | null;
  declare final_png_path: string | null;
  declare verification_report_path: string | null;
  declare verification_status: string | null;
  declare verification_quality_passed: boolean | null;
  declare quality_status: string;
  declare verification_cli_exit_code: number | null;
  declare verification_objective_summary: Record<string, number> | null;
  declare verification_errors: string[] | null;
  declare refiner_report_path: string | null;
  declare user_memory_enabled: boolean;
  declare user_memory_degraded: boolean;
  declare user_memory_errors: string[] | null;
  declare design_memory_enabled: boolean;
  declare design_memory_degraded: boolean;
  declare design_memory_errors: string[] | null;
  declare design_memory_retrieved_items: Record<string, string>[] | null;
  declare artifact_paths: Record<string, string> | null;
}

/** ``tempfile.TemporaryDirectory(prefix=...)`` */
export class _TemporaryDirectory {
  name: string;

  constructor(prefix = 'tmp') {
    // Python's ``_RandomNameSequence``: 8 characters of [a-z0-9_].
    const characters = 'abcdefghijklmnopqrstuvwxyz0123456789_';
    for (;;) {
      let suffix = '';
      for (let i = 0; i < 8; i += 1) suffix += characters[Math.floor(Math.random() * characters.length)];
      const candidate = join(tmpdir(), `${prefix}${suffix}`);
      try {
        mkdirSync(candidate, { mode: 0o700 });
        this.name = candidate;
        return;
      } catch (exc) {
        if ((exc as { code?: unknown })?.code !== 'EEXIST') throw exc;
      }
    }
  }

  cleanup(): void {
    rmSync(this.name, { recursive: true, force: true });
  }
}

/** (dataclass) */
export class _RunDirectories {
  constructor(
    public save_dir: string,
    public final_dir: string | null,
    public temp_dir: _TemporaryDirectory | null,
  ) {}
}

/** (dataclass) */
export class _GenerationArtifacts {
  constructor(
    public structure_instantiation: Dict | null,
    public structure_specification: Dict | null,
    public styling_instantiation: Dict | null,
    public styling_specification: Dict | null,
    public layout_instantiation: Dict | null,
    public layout_specification: Dict | null,
    public diagram_manifest: Dict | null,
    public artifact_paths: Record<string, string>,
  ) {}
}

/** Raised when a generator returns an incomplete or malformed result. */
export class GenerationContractError extends ValueError {}

/** (dataclass) */
export class _VerificationPhaseResult {
  constructor(
    public state: any,
    public output_dir: string,
  ) {}
}

/** (dataclass) */
export class _RefinementPhaseResult {
  constructor(
    public manifest: Dict | null,
    public png_path: string | null,
    public state: any = null,
  ) {}
}

/** (dataclass) */
export class _FinalizeResult {
  constructor(
    public manifest: Dict,
    public manifest_path: string | null,
    public png_path: string | null,
  ) {}
}

/** (dataclass, frozen) */
export class _WorkflowOptions {
  constructor(
    readonly mode: string,
    readonly canvas_library: string,
    readonly enable_refiner: boolean,
    readonly refiner_max_iterations: number,
    readonly enable_verifier: boolean,
    readonly verification_only: boolean,
    readonly enable_critic: boolean,
    readonly use_icons: boolean,
    readonly enable_user_memory: boolean,
    readonly user_id: string,
    readonly memory_db_path: string | null,
    readonly full_domain_knowledge: boolean,
    readonly enable_design_memory: boolean,
    readonly design_memory_db_path: string | null,
    readonly design_memory_embedding_model: string | null,
    readonly design_memory_top_k: number,
    readonly design_memory_score_threshold: number,
  ) {
    Object.freeze(this);
  }
}

export function _require_mapping(outputs: Dict, field_name: string, mode: string): Dict {
  const value = pyGet(outputs, field_name);
  if (!isDict(value)) {
    throw new GenerationContractError(
      `${mode} generator result missing required object field `
      + `${pyRepr(field_name)}; got ${pyTypeName(value)}.`,
    );
  }
  return value;
}

export function _optional_mapping(outputs: Dict, field_name: string, mode: string): Dict | null {
  const value = pyGet(outputs, field_name);
  if (value === null || value === undefined) {
    return null;
  }
  if (!isDict(value)) {
    throw new GenerationContractError(
      `${mode} generator result field ${pyRepr(field_name)} must be an object `
      + `when present; got ${pyTypeName(value)}.`,
    );
  }
  return value;
}

export function _coerce_artifact_paths(outputs: Dict, mode: string): Record<string, string> {
  const value = pyGet(outputs, 'artifact_paths');
  if (value === null || value === undefined) {
    return {};
  }
  if (!isDict(value)) {
    throw new GenerationContractError(
      `${mode} generator result field 'artifact_paths' must be an object `
      + `when present; got ${pyTypeName(value)}.`,
    );
  }
  const invalid_keys = Object.entries(value)
    .filter(([key, path]) => !isStr(key) || !isStr(path))
    .map(([key]) => key);
  if (invalid_keys.length) {
    const sample = invalid_keys.slice(0, 5).map((key) => pyRepr(key)).join(', ');
    throw new GenerationContractError(
      `${mode} generator result artifact_paths contains non-string `
      + `key/path entries: ${sample}.`,
    );
  }
  return { ...(value as Record<string, string>) };
}

export function _validate_artifact_field<T>(mode: string, field_name: string, validator: () => T): T {
  try {
    return validator();
  } catch (exc) {
    if (
      exc instanceof StructureValidationError
      || exc instanceof StylingValidationError
      || exc instanceof LayoutValidationError
      || exc instanceof ValueError
    ) {
      const error = new GenerationContractError(
        `${mode} generator result field ${pyRepr(field_name)} violates `
        + `the generation contract: ${_exc_str(exc)}`,
      );
      (error as { cause?: unknown }).cause = exc;
      throw error;
    }
    throw exc;
  }
}

export function _coerce_generation_artifacts(
  mode: string,
  outputs: unknown,
  canvas_library = 'excalidraw',
): _GenerationArtifacts {
  if (!isDict(outputs)) {
    throw new GenerationContractError(
      `${mode} generator result must be a dict; got ${pyTypeName(outputs)}.`,
    );
  }

  const artifact_paths = _coerce_artifact_paths(outputs, mode);

  if (mode === 'oneshot') {
    const structure_instantiation = _validate_artifact_field(
      mode,
      'structure_instantiation',
      () => validate_structure_instantiation(_require_mapping(outputs, 'structure_instantiation', mode)),
    );
    return new _GenerationArtifacts(
      structure_instantiation,
      null,
      null,
      null,
      null,
      null,
      _require_mapping(outputs, 'diagram_manifest', mode),
      artifact_paths,
    );
  }

  const structure_instantiation = _validate_artifact_field(
    mode,
    'structure_instantiation',
    () => validate_structure_instantiation(_require_mapping(outputs, 'structure_instantiation', mode)),
  );
  const styling_instantiation = _validate_artifact_field(
    mode,
    'styling_instantiation',
    () => validate_styling_instantiation(
      _require_mapping(outputs, 'styling_instantiation', mode),
      structure_instantiation,
      canvas_library,
    ),
  );
  const layout_instantiation = _validate_artifact_field(
    mode,
    'layout_instantiation',
    () => validate_layout_instantiation(
      _require_mapping(outputs, 'layout_instantiation', mode),
      structure_instantiation,
      styling_instantiation,
    ) as Dict,
  );

  return new _GenerationArtifacts(
    structure_instantiation,
    _optional_mapping(outputs, 'structure_specification', mode),
    styling_instantiation,
    _optional_mapping(outputs, 'styling_specification', mode),
    layout_instantiation,
    _optional_mapping(outputs, 'layout_specification', mode),
    _optional_mapping(outputs, 'diagram_manifest', mode),
    artifact_paths,
  );
}

/** ``os.path.abspath`` */
function _abspath(path: string): string {
  return resolve(path);
}

/** ``os.path.commonpath([a, b]) == a`` for absolute paths. */
function _is_under(root: string, path: string): boolean {
  const rel = relative(root, path);
  return rel === '' || (!rel.startsWith('..') && !isAbsolute(rel));
}

// ---------------------------------------------------------------------------
// Orchestrator
// ---------------------------------------------------------------------------

/** 5-phase pipeline: Generate → Render → Verify → Refine → Finalize. */
export class Text2DiagramWorkflow {
  mode: string;
  canvas_library: string;
  always_refine: boolean;
  enable_refiner: boolean;
  refiner_max_iterations: number;
  enable_verifier: boolean;
  verification_only: boolean;
  enable_critic: boolean;
  use_icons: boolean;
  enable_user_memory: boolean;
  user_id: string;
  memory_db_path: string | null;
  full_domain_knowledge: boolean;
  enable_design_memory: boolean;
  design_memory_db_path: string | null;
  design_memory_embedding_model: string | null;
  design_memory_top_k: number;
  design_memory_score_threshold: number;
  generator: GeneratorWorkflow;
  save_dir: string;
  user_memory_degraded: boolean;
  user_memory_errors: string[];
  memory_system: UserPreferenceMemorySystemLike | null;
  design_memory_degraded: boolean;
  design_memory_errors: string[];
  design_memory_retrieved_items: Record<string, string>[];
  design_memory_retriever: DesignMemoryRetriever | null;
  design_constraints?: string;

  constructor(
    model: BaseChatModel,
    config: AgenticSystemConfig | null = null,
    // Individual params are used by tests and lightweight programmatic callers.
    save_dir: string = DEFAULT_WORKFLOW_SAVE_DIR,
    canvas_library = 'excalidraw',
    mode = 'multiagent',
    enable_refiner = false,
    always_refine = false,
    refiner_max_iterations = 3,
    enable_verifier = true,
    verification_only = false,
    enable_critic = true,
    use_icons = false,
    enable_user_memory = false,
    user_id = 'default_user',
    memory_db_path: string | null = null,
    router_model: BaseChatModel | null = null,
    full_domain_knowledge = true,
    // Design memory is opt-in on this path and on by default only through
    // AgenticSystemConfig. Bare-kwarg callers include the backend request
    // path and knowledge_evolution's knowledge-free control run, which must
    // keep generating without retrieved knowledge for its baseline to mean
    // anything.
    enable_design_memory = false,
    design_memory_db_path: string | null = null,
    design_memory_embedding_model: string | null = null,
    design_memory_top_k: number = DEFAULT_DESIGN_MEMORY_TOP_K,
    design_memory_score_threshold: number = DEFAULT_DESIGN_MEMORY_SCORE_THRESHOLD,
  ) {
    const options = Text2DiagramWorkflow._resolve_options(
      config,
      mode,
      canvas_library,
      enable_refiner,
      refiner_max_iterations,
      enable_verifier,
      verification_only,
      enable_critic,
      use_icons,
      enable_user_memory,
      user_id,
      memory_db_path,
      full_domain_knowledge,
      enable_design_memory,
      design_memory_db_path,
      design_memory_embedding_model,
      design_memory_top_k,
      design_memory_score_threshold,
    );
    this.mode = normalize_generation_mode(options.mode);
    this.canvas_library = normalize_canvas_library(options.canvas_library);
    this.always_refine = always_refine;
    this.enable_refiner = options.enable_refiner;
    this.refiner_max_iterations = options.refiner_max_iterations;
    this.enable_verifier = options.enable_verifier;
    this.verification_only = options.verification_only;
    this.enable_critic = options.enable_critic;
    this.use_icons = options.use_icons;
    this.enable_user_memory = options.enable_user_memory;
    this.user_id = options.user_id;
    this.memory_db_path = options.memory_db_path;
    this.full_domain_knowledge = options.full_domain_knowledge;
    this.enable_design_memory = options.enable_design_memory;
    this.design_memory_db_path = options.design_memory_db_path;
    this.design_memory_embedding_model = options.design_memory_embedding_model;
    this.design_memory_top_k = options.design_memory_top_k;
    this.design_memory_score_threshold = options.design_memory_score_threshold;

    require_generation_capability(this.canvas_library, this.mode);
    if (this.enable_refiner) {
      require_refiner_capability(this.canvas_library, this.mode);
    }
    if (this.use_icons && this.canvas_library !== 'excalidraw') {
      require_icon_assets_available();
    }

    // Generation workflow (pipeline or one-shot)
    this.generator = create_generator(
      this.mode, model,
      this.canvas_library,
      this.use_icons,
      router_model,
      this.full_domain_knowledge,
    );

    this.save_dir = save_dir;

    // User memory observability: set when preference retrieval fails so the
    // run does not silently pretend preferences were injected.
    this.user_memory_degraded = false;
    this.user_memory_errors = [];
    this.memory_system = this._init_memory_system();

    // Same observability contract for design memory: a run must never look
    // like it used evolved design knowledge when it did not.
    this.design_memory_degraded = false;
    this.design_memory_errors = [];
    this.design_memory_retrieved_items = [];
    this.design_memory_retriever = this._init_design_memory();

    logger.info(`Canvas library: ${this.canvas_library}`);
  }

  static _resolve_options(
    config: AgenticSystemConfig | null,
    mode: string,
    canvas_library: string,
    enable_refiner: boolean,
    refiner_max_iterations: number,
    enable_verifier: boolean,
    verification_only: boolean,
    enable_critic: boolean,
    use_icons: boolean,
    enable_user_memory: boolean,
    user_id: string,
    memory_db_path: string | null,
    full_domain_knowledge: boolean,
    enable_design_memory: boolean,
    design_memory_db_path: string | null,
    design_memory_embedding_model: string | null,
    design_memory_top_k: number,
    design_memory_score_threshold: number,
  ): _WorkflowOptions {
    if (config !== null && config !== undefined) {
      return new _WorkflowOptions(
        config.mode,
        config.canvas_library,
        config.enable_refiner,
        config.refiner_iterations,
        config.enable_verifier,
        config.verification_only,
        config.enable_critic,
        config.use_icons,
        config.enable_user_memory,
        config.user_id,
        getattr(config, 'memory_db_path', null) as string | null,
        getattr(config, 'full_domain_knowledge', true) as boolean,
        // getattr defaults keep config-shaped duck types (and older
        // pickled configs) working, as the fields above already do.
        truthy(getattr(config, 'enable_design_memory', false)),
        getattr(config, 'design_memory_db_path', null) as string | null,
        getattr(config, 'design_memory_embedding_model', null) as string | null,
        Math.trunc(Number(getattr(config, 'design_memory_top_k', DEFAULT_DESIGN_MEMORY_TOP_K))),
        Number(getattr(config, 'design_memory_score_threshold', DEFAULT_DESIGN_MEMORY_SCORE_THRESHOLD)),
      );
    }

    return new _WorkflowOptions(
      mode,
      canvas_library,
      enable_refiner,
      refiner_max_iterations,
      enable_verifier,
      verification_only,
      enable_critic,
      use_icons,
      enable_user_memory,
      user_id,
      memory_db_path,
      full_domain_knowledge,
      enable_design_memory,
      design_memory_db_path,
      design_memory_embedding_model,
      design_memory_top_k,
      design_memory_score_threshold,
    );
  }

  _init_memory_system(): UserPreferenceMemorySystemLike | null {
    if (!this.enable_user_memory) {
      return null;
    }
    const factory = user_memory_hooks.UserPreferenceMemorySystem;
    if (factory === null) {
      // ``except ImportError``: the package is not part of the TS port.
      logger.warning(`Failed to initialize user memory: ${_USER_MEMORY_IMPORT_ERROR}`);
      this.enable_user_memory = false;
      return null;
    }
    const memory_system = factory({ user_id: this.user_id, memory_db_path: this.memory_db_path });
    logger.info(`User memory enabled for user: ${this.user_id}`);
    return memory_system;
  }

  // ------------------------------------------------------------------
  // Design memory
  // ------------------------------------------------------------------

  /**
   * Return the shared design-memory retriever, or ``None`` if unusable.
   *
   * Design knowledge is an enhancement, never a precondition. A missing
   * vector store, a missing optional dependency (chromadb /
   * sentence-transformers) and a failed embedding-model / distance-space
   * consistency check all end the same way: no retriever, a recorded error,
   * a warning, and a run that generates normally without design knowledge.
   */
  _init_design_memory(): DesignMemoryRetriever | null {
    if (!this.enable_design_memory) {
      return null;
    }

    const db_path = this.design_memory_db_path;
    let is_dir = false;
    if (truthy(db_path)) {
      try {
        is_dir = statSync(db_path!).isDirectory();
      } catch {
        is_dir = false;
      }
    }
    if (truthy(db_path) && !is_dir) {
      // Cheap pre-check. It keeps the heavy optional imports out of runs
      // that have no evolved knowledge yet, and stops an empty store from
      // being created where the evolution pipeline never wrote one.
      this._record_design_memory_error(`design memory vector store not found: ${db_path}`);
      logger.warning(
        `Design memory is enabled but no vector store exists at ${db_path}; `
        + 'generating without design knowledge.',
      );
      return null;
    }

    const [retriever, error] = _load_design_memory_retriever(db_path, this.design_memory_embedding_model);
    if (retriever === null) {
      this._record_design_memory_error(error || 'design memory unavailable');
      logger.warning(`Design memory unavailable (${pyStr(error)}); generating without design knowledge.`);
      return null;
    }

    logger.info(`Design memory enabled (vector store: ${pyStr(db_path)})`);
    return retriever;
  }

  /** Mark design memory as degraded and keep the errors for the state. */
  _record_design_memory_error(message: string): void {
    this.design_memory_degraded = true;
    let errors = getattr(this, 'design_memory_errors', null);
    if (!isList(errors)) {
      errors = [];
      this.design_memory_errors = errors as string[];
    }
    if (!(errors as string[]).includes(message)) {
      (errors as string[]).push(message);
    }
  }

  /** Whether evolved design knowledge can actually be retrieved. */
  _design_memory_is_active(): boolean {
    return Boolean(
      truthy(getattr(this, 'enable_design_memory', false))
      && getattr(this, 'design_memory_retriever', null) !== null,
    );
  }

  /**
   * Return prompt-ready design knowledge for this request.
   *
   * Returns ``""`` when design memory answered but holds nothing relevant,
   * and ``None`` when retrieval itself failed. As with user memory, callers
   * must treat ``None`` as "design memory did not take effect" rather than
   * as an empty knowledge set.
   */
  async _retrieve_design_expertise(
    user_query: string | null,
    diagram_type: string | null,
    content_area: string | null,
    retrieval_query = '',
  ): Promise<string | null> {
    const retriever = getattr(this, 'design_memory_retriever', null) as DesignMemoryRetriever | null;
    if (retriever === null) {
      return '';
    }

    const query = pyStr(pyOr(user_query, ''));
    retrieval_query = pyStr(pyOr(retrieval_query, ''));
    if (!(
      pyStrip(query)
      || pyStrip(retrieval_query)
      || truthy(diagram_type)
      || truthy(content_area)
    )) {
      // With no query signal at all a similarity search returns arbitrary
      // knowledge rather than relevant knowledge, so skip it.
      logger.debug('Skipping design memory retrieval: empty query signal.');
      return '';
    }

    let expertise: string | null;
    let retrieved_items: Dict[] | null;
    try {
      [expertise, retrieved_items] = await retriever.retrieve_design_expertise(query, {
        diagram_type: diagram_type || '',
        content_area: content_area || '',
        retrieval_query,
        top_k: getattr(this, 'design_memory_top_k', DEFAULT_DESIGN_MEMORY_TOP_K) as number,
        score_threshold: getattr(this, 'design_memory_score_threshold', DEFAULT_DESIGN_MEMORY_SCORE_THRESHOLD) as number,
      });
    } catch (exc) {
      this._record_design_memory_error(`retrieve_design_expertise: ${_exc_str(exc)}`);
      logger.error(`Design memory retrieval failed: ${_exc_str(exc)}`);
      return null;
    }

    this.design_memory_retrieved_items = (retrieved_items || [])
      .filter((item) => isDict(item))
      .map((item) => Object.fromEntries(Object.entries(item).map(([key, value]) => [pyStr(key), pyStr(value)])));
    return expertise || '';
  }

  // ------------------------------------------------------------------
  // User memory helpers
  // ------------------------------------------------------------------

  /**
   * Return formatted user preferences.
   *
   * Returns ``""`` when the memory system answered but holds nothing for the
   * current scope, and ``None`` when retrieval itself failed.
   */
  async _retrieve_user_preferences(
    diagram_type: string | null,
    content_area: string | null,
    agent_category: string | null = null,
  ): Promise<string | null> {
    if (!truthy(this.memory_system)) {
      return '';
    }
    const scope_parts: string[] = [];
    if (truthy(diagram_type)) {
      scope_parts.push(`${diagram_type} diagrams`);
    }
    if (truthy(content_area)) {
      scope_parts.push(`in ${content_area}`);
    }
    const query_scope = pyStrip(scope_parts.join(' '));
    const query = query_scope ? `User preferences for ${query_scope}` : 'User diagram preferences';
    const categories = truthy(agent_category) ? [agent_category!] : ['Structure', 'Styling', 'Layout'];
    const all_prefs: unknown[] = [];
    const failed_categories: string[] = [];
    for (const cat of categories) {
      // Query per category so one failing category cannot discard the
      // preferences the other categories already returned.
      let prefs: unknown[];
      try {
        prefs = await this.memory_system!.retrieve_preferences({
          query,
          agent_category: cat,
          diagram_type,
          content_area,
          min_confidence: 0.7,
          top_k: 3,
        });
      } catch (exc) {
        failed_categories.push(cat);
        this._record_user_memory_error(`${cat}: ${_exc_str(exc)}`);
        logger.error(`User preference retrieval failed for category ${cat}: ${_exc_str(exc)}`);
        continue;
      }
      all_prefs.push(...prefs);
    }

    if (failed_categories.length && !all_prefs.length) {
      logger.error(
        'User memory is enabled but no preferences could be retrieved '
        + `(failed categories: ${failed_categories.join(', ')}); generation continues without them.`,
      );
      return null;
    }
    if (!all_prefs.length) {
      return '';
    }
    try {
      return await this.memory_system!.format_preferences_for_prompt(all_prefs, 1000);
    } catch (exc) {
      this._record_user_memory_error(`format_preferences_for_prompt: ${_exc_str(exc)}`);
      logger.error(`Failed to format user preferences: ${_exc_str(exc)}`);
      return null;
    }
  }

  /** Mark user memory as degraded and keep the first errors for the state. */
  _record_user_memory_error(message: string): void {
    this.user_memory_degraded = true;
    let errors = getattr(this, 'user_memory_errors', null);
    if (!isList(errors)) {
      errors = [];
      this.user_memory_errors = errors as string[];
    }
    if (!(errors as string[]).includes(message)) {
      (errors as string[]).push(message);
    }
  }

  /**
   * Assemble the design expertise block handed to the generator.
   *
   * Order, highest authority first: the caller's ``design_expertise``, the
   * fenced retrieved design memory, then user preferences — separate
   * segments joined by a blank line (see the Python docstring).
   */
  async build_design_expertise(
    design_expertise: string,
    diagram_type: string | null,
    content_area: string | null,
    user_query = '',
    retrieval_query = '',
  ): Promise<string> {
    const segments: string[] = design_expertise ? [design_expertise] : [];

    if (this._design_memory_is_active()) {
      const retrieved = await this._retrieve_design_expertise(
        user_query,
        diagram_type,
        content_area,
        retrieval_query,
      );
      if (retrieved === null) {
        logger.error(
          'Proceeding without design memory; the generated diagram '
          + 'will not reflect evolved design knowledge for this run.',
        );
      } else if (retrieved) {
        segments.push(
          `${DESIGN_MEMORY_SECTION_HEADER}\n`
          + `${retrieved}\n`
          + `${DESIGN_MEMORY_SECTION_FOOTER}`,
        );
      }
    }

    if (truthy(getattr(this, 'enable_user_memory', false)) && truthy(getattr(this, 'memory_system', null))) {
      const user_prefs = await this._retrieve_user_preferences(diagram_type, content_area);
      if (user_prefs === null) {
        logger.error(
          'Proceeding without user preferences; the generated diagram '
          + 'will not reflect stored user memory for this run.',
        );
      } else if (user_prefs) {
        segments.push(user_prefs);
      }
    }

    return segments.join('\n\n');
  }

  // ------------------------------------------------------------------
  // Stepwise generation API for streaming callers
  // ------------------------------------------------------------------

  /** Return the selected generator if it supports staged execution. */
  _require_stepwise_generator(): any {
    const generator = this.generator as unknown as Dict;
    if (!['begin_pipeline_run', 'run_pipeline_stage'].every((attr) => typeof generator[attr] === 'function')) {
      throw new RuntimeError('Stepwise generation currently supports pipeline mode only.');
    }
    return this.generator;
  }

  /** Start an observable Structure -> Styling -> Layout generation run. */
  async begin_generation_run(
    text_content: string,
    user_query: string,
    design_expertise = '',
    runtime_directives = '',
    diagram_type: string | null = null,
    content_area: string | null = null,
  ): Promise<any> {
    return this._require_stepwise_generator().begin_pipeline_run(
      text_content,
      user_query,
      design_expertise,
      runtime_directives,
      diagram_type,
      content_area,
    );
  }

  /** Advance one staged generation step through the workflow boundary. */
  async run_generation_stage(run_state: unknown, stage_name: string, save_dir: string | null = null): Promise<void> {
    await this._require_stepwise_generator().run_pipeline_stage(run_state, stage_name, save_dir);
  }

  // ------------------------------------------------------------------
  // Pipeline phase helpers
  // ------------------------------------------------------------------

  /** Resolve persistence directories for one workflow run. */
  _resolve_run_directories(save_dir: unknown, final_dir: string | null): _RunDirectories {
    let temp_dir: _TemporaryDirectory | null = null;
    if (save_dir === _DEFAULT_SAVE_DIR) {
      save_dir = this.save_dir;
    } else if (save_dir === null || save_dir === undefined) {
      temp_dir = new _TemporaryDirectory('evodesign_');
      save_dir = temp_dir.name;
      logger.info(`Intermediate persistence disabled; using temporary workflow dir: ${save_dir}`);
    }

    if (final_dir === null || final_dir === undefined) {
      final_dir = save_dir as string;
    }

    return new _RunDirectories(save_dir as string, final_dir, temp_dir);
  }

  /** Run the selected generator and normalize its output contract. */
  async _run_generation_phase(
    text_content: any,
    user_query: any,
    design_expertise: string,
    runtime_directives: string,
    diagram_type: string | null,
    content_area: string | null,
    save_dir: string,
    locked_nodes: string[] | null = null,
  ): Promise<_GenerationArtifacts> {
    // ``retrieval_query`` stays empty here: the Router that produces one
    // runs inside the generator, after this point, so design memory falls
    // back to the user query as its semantic query.
    const full_design_expertise = await this.build_design_expertise(
      design_expertise,
      diagram_type,
      content_area,
      pyStr(pyOr(user_query, '')),
    );

    if (locked_nodes === null || locked_nodes === undefined) {
      locked_nodes = _locked_nodes_from_runtime_directives(runtime_directives);
    }
    this.design_constraints = build_design_constraints(
      pyStr(pyOr(text_content, '')), pyStr(pyOr(user_query, '')),
      design_expertise, diagram_type,
      getattr(this, 'use_icons', false) as boolean, [...locked_nodes],
    );
    const gen_outputs = await this.generator.run(
      text_content,
      user_query,
      full_design_expertise,
      runtime_directives,
      diagram_type,
      content_area,
      save_dir,
    );

    return _coerce_generation_artifacts(this.mode, gen_outputs, this.canvas_library);
  }

  /** Render generator output to a manifest JSON and PNG. */
  async _render_generation_output(generation: _GenerationArtifacts, save_dir: string): Promise<RenderResult> {
    logger.info('='.repeat(60));
    logger.info('[Phase 2] Rendering manifest + PNG...');
    const render_dir = join(save_dir, '4_render');
    mkdirSync(render_dir, { recursive: true });

    if (this.mode === 'oneshot') {
      const render_result = await this._render_oneshot_manifest(generation.diagram_manifest, render_dir);
      logger.info(`[Phase 2] One-shot render complete: ${render_result.png_path}`);
      return render_result;
    }

    const render_result = await render_manifest(
      generation.layout_instantiation as Dict,
      generation.structure_instantiation as Dict,
      this.canvas_library,
      render_dir,
      undefined,
      undefined,
      generation.layout_specification,
      (getattr(this, 'design_constraints', '') as string),
    );
    if (!truthy(render_result.png_path) || !existsSync(render_result.png_path)) {
      throw new RuntimeError(`Render failed: PNG not found at ${pyStr(render_result.png_path)}`);
    }
    logger.info(`[Phase 2] Render complete: ${render_result.png_path}`);
    return render_result;
  }

  /** Persist and render the manifest produced by one-shot generation. */
  async _render_oneshot_manifest(diagram_manifest: Dict | null, render_dir: string): Promise<RenderResult> {
    if (!isDict(diagram_manifest)) {
      throw new RuntimeError('One-shot generator produced no diagram_manifest');
    }

    const manifest_path = join(render_dir, 'diagram_manifest.json');
    _save_json(manifest_path, diagram_manifest);
    const png_path = join(render_dir, 'diagram_manifest.png');
    const render_result = await render_png_result(diagram_manifest, png_path, this.canvas_library);
    if (!render_result.ok) {
      const detail = render_result.error ? `: ${render_result.error}` : '';
      throw new RuntimeError(`One-shot render failed: ${png_path}${detail}`);
    }

    return new RenderResult(diagram_manifest, png_path, manifest_path);
  }

  /** Run verification when enabled and return its state and output dir. */
  async _run_verification_phase(
    render_result: RenderResult,
    generation: _GenerationArtifacts,
    text_content: any,
    save_dir: string,
    output_subdir = '6_verification',
    phase_label = 'Phase 3',
    artifact_report_keys: readonly string[] = ['verification_report_path'],
  ): Promise<_VerificationPhaseResult> {
    const verification_dir = join(save_dir, output_subdir);

    if (!this.enable_verifier) {
      logger.info(`[${phase_label}] Verification skipped (--no-verifier)`);
      return new _VerificationPhaseResult(null, verification_dir);
    }

    logger.info('='.repeat(60));
    logger.info(`[${phase_label}] Running verification...`);
    mkdirSync(verification_dir, { recursive: true });

    const structure_path = (pyGet(generation.artifact_paths, 'structure_instantiation_path') as string | null);
    let layout_path = (pyGet(generation.artifact_paths, 'layout_instantiation_path') as string | null);
    if (this.mode === 'oneshot') {
      // Unified mode carries a Structure-shaped semantic sidecar but has
      // no Layout IR, so keep structure_path when present and skip only
      // layout-dependent checks.
      layout_path = null;
    }

    const verifier = new VerifierWorkflow();
    const verifier_state = await verifier.run(
      render_result.manifest_path,
      render_result.png_path,
      this.canvas_library,
      structure_path,
      layout_path,
      text_content,
      (getattr(this, 'design_constraints', '') as string),
      verification_dir,
      !this.enable_critic,
      this.mode === 'oneshot' ? ['layout_audit'] : null,
      true,
    );
    logger.info(
      `[${phase_label}] Verification complete: status=${verifier_state.status}, `
      + `findings=${verifier_state.objective_findings.length}`,
    );
    if (truthy(verifier_state.report_path)) {
      for (const key of artifact_report_keys) {
        generation.artifact_paths[key] = verifier_state.report_path!;
      }
    }

    return new _VerificationPhaseResult(verifier_state, verification_dir);
  }

  /** Verify immutable refinement artifacts before selecting the final pair. */
  async _run_final_verification_phase(
    finalize: _FinalizeResult,
    generation: _GenerationArtifacts,
    text_content: any,
    save_dir: string,
    initial_verification: _VerificationPhaseResult,
    refinement: _RefinementPhaseResult,
  ): Promise<_VerificationPhaseResult> {
    if (refinement.manifest === null && refinement.png_path === null) {
      return initial_verification;
    }

    if (!truthy(finalize.manifest_path) || !truthy(finalize.png_path)) {
      throw new RuntimeError('Candidate verification requires persisted refinement artifacts.');
    }

    const final_render_result = new RenderResult(finalize.manifest, finalize.png_path!, finalize.manifest_path!);
    return this._run_verification_phase(
      final_render_result,
      generation,
      text_content,
      save_dir,
      '8_final_verification',
      'Phase 5 final',
      ['verification_report_path', 'final_verification_report_path'],
    );
  }

  _should_refine(): boolean {
    const should_run = (
      this.enable_refiner
      && !this.verification_only
    );
    return should_run;
  }

  /** Run optional deterministic + LLM refinement loop. */
  async _run_refinement_phase(
    render_result: RenderResult,
    generation: _GenerationArtifacts,
    verification: _VerificationPhaseResult,
    save_dir: string,
  ): Promise<_RefinementPhaseResult> {
    if (this.verification_only) {
      logger.info('[Phase 3] Verification-only mode. Skipping refinement.');
    }

    if (!this._should_refine() || !should_refine(verification.state, truthy(getattr(this, 'always_refine', false)))) {
      logger.info('[Phase 4] Refinement skipped.');
      return new _RefinementPhaseResult(null, null);
    }
    if (_has_blocking_verification_errors(verification.state)) {
      logger.warning(
        '[Phase 4] Refinement skipped because verification reported '
        + `blocking errors: ${pyRepr(getattr(verification.state, 'blocking_errors', getattr(verification.state, 'errors', [])))}`,
      );
      return new _RefinementPhaseResult(null, null, null);
    }

    logger.info('='.repeat(60));
    logger.info('[Phase 4] Running refinement loop...');
    const refiner_dir = join(save_dir, '7_refiner');
    mkdirSync(refiner_dir, { recursive: true });

    const verifier_report_path = (
      truthy(verification.state)
        ? getattr(verification.state, 'report_path', null) as string | null
        : null
    );
    const refiner_kwargs = {
      manifest_path: render_result.manifest_path,
      image_path: render_result.png_path,
      structure_path: pyGet(generation.artifact_paths, 'structure_instantiation_path') as string | null,
      layout_path: pyGet(generation.artifact_paths, 'layout_instantiation_path') as string | null,
      verifier_report_path,
      design_constraints: (getattr(this, 'design_constraints', '') as string),
      output_dir: refiner_dir,
      canvas_library: this.canvas_library,
      max_iterations: this.refiner_max_iterations,
      skip_checks: this.mode === 'oneshot' ? ['layout_audit'] : null,
      emit_markdown: true,
    };
    let refiner_state: VerifierRefinerState;
    try {
      refiner_state = await new IterativeRefinerWorkflow().run(
        refiner_kwargs.manifest_path,
        refiner_kwargs.image_path,
        refiner_kwargs.verifier_report_path,
        refiner_kwargs.design_constraints,
        refiner_kwargs.structure_path,
        refiner_kwargs.layout_path,
        refiner_kwargs.output_dir,
        refiner_kwargs.canvas_library,
        refiner_kwargs.max_iterations,
        undefined,
        refiner_kwargs.skip_checks,
        refiner_kwargs.emit_markdown,
      );
    } catch (exc) {
      // Same contract as a refiner that reports status=failed below: an
      // unexpected exception must not discard the verified render.
      logger.exception('[Phase 4] Refiner raised');
      const name = exc instanceof Error ? (exc.name === 'PyTypeError' ? 'TypeError' : exc.name) : pyTypeName(exc);
      refiner_state = _model_construct(VerifierRefinerState as never, {
        ...refiner_kwargs,
        skip_checks: refiner_kwargs.skip_checks || [],
        status: 'failed',
        errors: [`refiner raised ${name}: ${_exc_str(exc)}`],
      }) as VerifierRefinerState;
    }
    const refiner_converged = getattr(refiner_state, 'converged', null);
    logger.info(
      `[Phase 4] Refinement complete: status=${refiner_state.status}, `
      + `iterations=${refiner_state.current_iteration}, converged=${pyStr(refiner_converged)}`,
    );
    const refiner_report_path = getattr(refiner_state, 'refiner_report_path', null);
    if (isStr(refiner_report_path) && refiner_report_path) {
      generation.artifact_paths.refiner_report_path = refiner_report_path;
    }

    if (refiner_state.status === 'failed') {
      // Refinement is an optional enhancement stage. A refiner failure must
      // not discard an already rendered and verified diagram; degrade to the
      // original render and let the state carry the failure signal.
      Text2DiagramWorkflow._record_refiner_candidate_artifacts(refiner_state, generation);
      logger.error(
        `[Phase 4] Refinement failed (${(truthy(refiner_state.errors) ? refiner_state.errors : ['unknown refiner error']).join('; ')}); `
        + 'keeping original render as final output (refiner_degraded=True).',
      );
      return new _RefinementPhaseResult(null, null, refiner_state);
    }

    if (refiner_converged !== true) {
      Text2DiagramWorkflow._record_refiner_candidate_artifacts(refiner_state, generation);
      logger.warning(
        '[Phase 4] Refinement did not converge (termination_reason='
        + `${pyStr(getattr(refiner_state, 'termination_reason', null))}); `
        + 'keeping original render as final output.',
      );
      return new _RefinementPhaseResult(null, null, refiner_state);
    }

    if (!truthy(refiner_state.refined_manifest_path)) {
      return new _RefinementPhaseResult(null, null, refiner_state);
    }

    const refined_manifest = pyJsonLoadsExact(readFileSync(refiner_state.refined_manifest_path!, 'utf-8')) as Dict;

    const refined_png_path = refiner_state.refined_image_path;
    if (!truthy(refined_png_path)) {
      throw new RuntimeError(
        'Refiner produced a refined manifest but no refined PNG; '
        + 'refusing to mix refined JSON with the original render.',
      );
    }

    generation.artifact_paths.refined_manifest_path = refiner_state.refined_manifest_path!;
    generation.artifact_paths.refined_png_path = refined_png_path!;

    return new _RefinementPhaseResult(refined_manifest, refined_png_path, refiner_state);
  }

  /** Expose non-adopted refiner artifacts so degraded runs stay debuggable. */
  static _record_refiner_candidate_artifacts(refiner_state: unknown, generation: _GenerationArtifacts): void {
    const candidate_manifest_path = getattr(refiner_state, 'candidate_manifest_path', null);
    const candidate_image_path = getattr(refiner_state, 'candidate_image_path', null);
    if (isStr(candidate_manifest_path) && candidate_manifest_path) {
      generation.artifact_paths.refiner_candidate_manifest_path = candidate_manifest_path;
    }
    if (isStr(candidate_image_path) && candidate_image_path) {
      generation.artifact_paths.refiner_candidate_png_path = candidate_image_path;
    }
  }

  /** Select final artifacts and copy them to the run's final directory. */
  async _finalize_outputs(
    render_result: RenderResult,
    refinement: _RefinementPhaseResult,
    generation: _GenerationArtifacts,
    final_dir: string | null,
  ): Promise<_FinalizeResult> {
    logger.info('='.repeat(60));
    logger.info('[Phase 5] Finalizing...');

    const final_manifest = pyOr(refinement.manifest, render_result.manifest) as Dict;
    const final_source_png_path = pyOr(refinement.png_path, render_result.png_path) as string | null;
    let final_manifest_path: string | null = null;
    let final_png_path: string | null = null;

    if (truthy(final_dir)) {
      mkdirSync(final_dir!, { recursive: true });
      final_manifest_path = join(final_dir!, 'final_diagram_manifest.json');
      final_png_path = join(final_dir!, 'rendered_diagram.png');
      _save_json(final_manifest_path, final_manifest);
      if (!truthy(final_source_png_path) || !existsSync(final_source_png_path!)) {
        throw new RuntimeError(`Final PNG source missing: ${pyStr(final_source_png_path)}`);
      }
      if (_abspath(final_source_png_path!) !== _abspath(final_png_path)) {
        copyFileSync(final_source_png_path!, final_png_path);
      }
      generation.artifact_paths.final_manifest_path = final_manifest_path;
      generation.artifact_paths.final_png_path = final_png_path;
    }

    return new _FinalizeResult(final_manifest, final_manifest_path, final_png_path);
  }

  /** Build the public WorkflowState from phase results. */
  async _build_state(
    text_content: any,
    user_query: any,
    generation: _GenerationArtifacts,
    render_result: RenderResult,
    verification: _VerificationPhaseResult,
    refinement: _RefinementPhaseResult,
    finalize: _FinalizeResult,
  ): Promise<WorkflowState> {
    const verifier_state = verification.state;
    const refiner_state = refinement.state;
    return new WorkflowState({
      text_content,
      user_query,
      quality_status: quality_status(quality_summary(verifier_state)),
      structure_instantiation: generation.structure_instantiation,
      structure_specification: generation.structure_specification,
      styling_instantiation: generation.styling_instantiation,
      styling_specification: generation.styling_specification,
      layout_instantiation: generation.layout_instantiation,
      layout_specification: generation.layout_specification,
      diagram_manifest: render_result.manifest,
      manifest_path: render_result.manifest_path,
      png_path: render_result.png_path,
      refined_diagram_manifest: refinement.manifest,
      refined_manifest_path: pyGet(generation.artifact_paths, 'refined_manifest_path'),
      refined_png_path: refinement.png_path,
      refiner_status: _optional_str(getattr(refiner_state, 'status', null)),
      refiner_converged: _optional_bool(getattr(refiner_state, 'converged', null)),
      refiner_degraded: Boolean(
        refiner_state !== null && refiner_state !== undefined
        && (
          _has_error_values(getattr(refiner_state, 'errors', null))
          || ['reported_degraded', 'failed'].includes(getattr(refiner_state, 'status', null) as string)
        ),
      ),
      refiner_errors: _optional_string_list(getattr(refiner_state, 'errors', null)),
      refiner_termination_reason: _optional_str(getattr(refiner_state, 'termination_reason', null)),
      refiner_latest_findings_summary: _refiner_findings_summary(refiner_state),
      refiner_candidate_manifest_path: _optional_str(
        pyOr(pyGet(generation.artifact_paths, 'refiner_candidate_manifest_path'), getattr(refiner_state, 'candidate_manifest_path', null)),
      ),
      refiner_candidate_png_path: _optional_str(
        pyOr(pyGet(generation.artifact_paths, 'refiner_candidate_png_path'), getattr(refiner_state, 'candidate_image_path', null)),
      ),
      final_diagram_manifest: finalize.manifest,
      final_manifest_path: finalize.manifest_path,
      final_png_path: finalize.png_path,
      verification_report_path: truthy(verifier_state) ? verifier_state.report_path : null,
      verification_status: _optional_str(getattr(verifier_state, 'status', null)),
      verification_quality_passed: _optional_bool(getattr(verifier_state, 'quality_passed', null)),
      verification_cli_exit_code: _optional_int(getattr(verifier_state, 'cli_exit_code', null)),
      verification_objective_summary: _optional_int_dict(getattr(verifier_state, 'objective_summary', null)),
      verification_errors: _optional_string_list(getattr(verifier_state, 'errors', null)),
      refiner_report_path: pyGet(generation.artifact_paths, 'refiner_report_path'),
      user_memory_enabled: Boolean(
        truthy(getattr(this, 'enable_user_memory', false))
        && getattr(this, 'memory_system', null) !== null,
      ),
      user_memory_degraded: truthy(getattr(this, 'user_memory_degraded', false)),
      user_memory_errors: _optional_string_list(getattr(this, 'user_memory_errors', null)),
      design_memory_enabled: Boolean(
        truthy(getattr(this, 'enable_design_memory', false))
        && getattr(this, 'design_memory_retriever', null) !== null,
      ),
      design_memory_degraded: truthy(getattr(this, 'design_memory_degraded', false)),
      design_memory_errors: _optional_string_list(getattr(this, 'design_memory_errors', null)),
      design_memory_retrieved_items: _optional_retrieved_items(getattr(this, 'design_memory_retrieved_items', null)),
      artifact_paths: generation.artifact_paths,
    });
  }

  /** Remove file paths that point into an already-cleaned temp run dir. */
  static _clear_temp_paths(state: WorkflowState, directories: _RunDirectories): void {
    const temp_root = _abspath(directories.save_dir);

    const _is_temp_path = (path: unknown): boolean => {
      if (!isStr(path) || !path) {
        return false;
      }
      return _is_under(temp_root, _abspath(path));
    };

    for (const field_name of [
      'manifest_path',
      'png_path',
      'refined_manifest_path',
      'refined_png_path',
      'refiner_candidate_manifest_path',
      'refiner_candidate_png_path',
      'verification_report_path',
      'refiner_report_path',
      'final_manifest_path',
      'final_png_path',
    ] as const) {
      if (_is_temp_path(state[field_name])) {
        (state as unknown as Dict)[field_name] = null;
      }
    }

    if (isDict(state.artifact_paths)) {
      state.artifact_paths = Object.fromEntries(
        Object.entries(state.artifact_paths).filter(([, value]) => !_is_temp_path(value)),
      );
    }
  }

  // ------------------------------------------------------------------
  // Main pipeline
  // ------------------------------------------------------------------

  /**
   * Run the full Text2Diagram pipeline.
   *
   * ``locked_nodes`` is the structured list of node ids the user locked.
   * When omitted it is recovered from ``runtime_directives`` (legacy).
   *
   * Optional per-run LLM caps come from ``EVO_LLM_RUN_MAX_CALLS`` and
   * ``EVO_LLM_RUN_DEADLINE_SECONDS`` (unset by default).
   */
  async run(
    text_content: any,
    user_query: any,
    runtime_directives: string | null = null,
    save_dir: unknown = _DEFAULT_SAVE_DIR,
    final_dir: string | null = null,
    design_expertise: string | null = null,
    diagram_type: string | null = null,
    content_area: string | null = null,
    locked_nodes: string[] | null = null,
  ): Promise<WorkflowState> {
    return llm_run_budget_from_env(() => this._run_pipeline(
      text_content,
      user_query,
      runtime_directives,
      save_dir,
      final_dir,
      design_expertise,
      diagram_type,
      content_area,
      locked_nodes,
    ));
  }

  async _run_pipeline(
    text_content: any,
    user_query: any,
    runtime_directives: string | null,
    save_dir: unknown,
    final_dir: string | null,
    design_expertise: string | null,
    diagram_type: string | null,
    content_area: string | null,
    locked_nodes: string[] | null,
  ): Promise<WorkflowState> {
    const directories = this._resolve_run_directories(save_dir, final_dir);
    let state: WorkflowState | null = null;
    try {
      const generation = await this._run_generation_phase(
        text_content,
        user_query,
        design_expertise || '',
        runtime_directives || '',
        diagram_type,
        content_area,
        directories.save_dir,
        locked_nodes,
      );
      const render_result = await this._render_generation_output(generation, directories.save_dir);
      generation.artifact_paths.render_manifest_path = render_result.manifest_path;
      generation.artifact_paths.render_png_path = render_result.png_path;

      const verification = await this._run_verification_phase(
        render_result,
        generation,
        text_content,
        directories.save_dir,
        undefined,
        undefined,
        ['pre_refine_verification_report_path', 'verification_report_path'],
      );
      let refinement = await this._run_refinement_phase(
        render_result,
        generation,
        verification,
        directories.save_dir,
      );
      // Verify immutable refinement artifacts before promoting them.
      // Reports must continue to point at the candidate even if it is
      // rejected; never overwrite the image that a report evaluated.
      const candidate_artifacts = new _FinalizeResult(
        pyOr(refinement.manifest, render_result.manifest) as Dict,
        pyOr(pyGet(generation.artifact_paths, 'refined_manifest_path'), render_result.manifest_path) as string,
        pyOr(refinement.png_path, render_result.png_path) as string,
      );
      let final_verification = await this._run_final_verification_phase(
        candidate_artifacts,
        generation,
        text_content,
        directories.save_dir,
        verification,
        refinement,
      );
      const rejection = _refinement_regression_reason(verification.state, final_verification.state);
      if (truthy(rejection) && refinement.manifest !== null) {
        logger.warning(`[Phase 5] Rejecting refined candidate: ${rejection}`);
        generation.artifact_paths.refiner_candidate_manifest_path = candidate_artifacts.manifest_path!;
        generation.artifact_paths.refiner_candidate_png_path = candidate_artifacts.png_path!;
        const candidate_report = pyPop(generation.artifact_paths, 'final_verification_report_path', null);
        if (truthy(candidate_report)) {
          generation.artifact_paths.refiner_candidate_verification_report_path = candidate_report as string;
        }
        pyPop(generation.artifact_paths, 'refined_manifest_path', null);
        pyPop(generation.artifact_paths, 'refined_png_path', null);
        const original_report = pyGet(generation.artifact_paths, 'pre_refine_verification_report_path');
        if (truthy(original_report)) {
          generation.artifact_paths.verification_report_path = original_report as string;
        }
        refinement = new _RefinementPhaseResult(null, null, refinement.state);
        final_verification = verification;
      }
      const finalize = await this._finalize_outputs(
        render_result,
        refinement,
        generation,
        directories.final_dir,
      );
      state = await this._build_state(
        text_content,
        user_query,
        generation,
        render_result,
        final_verification,
        refinement,
        finalize,
      );
      logger.info('Workflow completed!');
      return state;
    } finally {
      if (directories.temp_dir !== null) {
        if (state !== null) {
          Text2DiagramWorkflow._clear_temp_paths(state, directories);
        }
        directories.temp_dir.cleanup();
        logger.info(`Cleaned temporary workflow dir: ${directories.save_dir}`);
      }
    }
  }
}
