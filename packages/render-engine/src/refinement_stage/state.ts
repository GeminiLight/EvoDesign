// Ported from evodesign/agentic_system/refinement_stage/state.py — keep in sync.
//
// refinement_stage.state — Pydantic v2 state, edit ops, iteration logs.
//
// EditOp is the **shared primitive vocabulary** between deterministic fixers
// and the VLM agent. Every fix — rule-driven or LLM-driven — flows through
// this edit DSL, which makes the audit log uniform and `apply_edits` a single
// dispatch table.
//
// pydantic → TS (PHASE2_PLAN.md §2 rule 5): classes on ``py/pydantic.ts``
// ``BaseModel`` with explicit field validators raising under the same
// conditions as pydantic (lax mode). ``EditOp`` is ``extra="forbid"``: unknown
// keys add one "Extra inputs are not permitted" error each, so the error count
// in the first line of the ``ValidationError`` (which reaches the iteration
// log through ``_coerce_to_edits``) matches pydantic.

import { normalize_canvas_library } from '../canvas_runtime.ts';
import { ValueError } from '../py/errors.ts';
import { BaseModel, ValidationError, field, type FieldSpec } from '../py/pydantic.ts';
import { PY_FLOAT_MARKS } from '../py/json_decoder.ts';
import { pyRepr } from '../py/str.ts';
import { isDict } from '../py/truthy.ts';
import { Finding } from '../verification_stage/checks/finding.ts';

type Dict = Record<string, any>;

export const SUPPORTED_REFINER_CANVAS_LIBRARIES = ['excalidraw'] as const;

// Each op is one row in the iteration log; ``payload`` carries op-specific
// kwargs validated lazily by the dispatcher in fixers/apply_edits.py.
export type EditOpName =
  | 'set_icon' // payload: {"name": bundled Material icon name}; targets the host node
  | 'set_position' // payload: {"x": float, "y": float}
  | 'set_size' // payload: {"width": float, "height": float}
  | 'set_style' // payload: {"backgroundColor"?, "strokeColor"?, "strokeWidth"?, "strokeStyle"?, "fillStyle"?}
  | 'set_text' // payload: {"text": str}
  | 'delete_element' // payload: {}
  | 'clear_arrow_binding' // payload: {"side": "start" | "end"}
  | 'clear_container_binding' // payload: {"container_id"?: str}
  | 'append_bound_element' // payload: {"bound_id": str, "type": "arrow" | "text"}
  | 'remove_bound_element' // payload: {"bound_id": str}
  | 'set_index'; // payload: {"index": str}  fractional index for z-order

/** ``typing.get_args(EditOpName)`` */
export const EditOpName: readonly EditOpName[] = [
  'set_icon',
  'set_position',
  'set_size',
  'set_style',
  'set_text',
  'delete_element',
  'clear_arrow_binding',
  'clear_container_binding',
  'append_bound_element',
  'remove_bound_element',
  'set_index',
];

// ---------------------------------------------------------------- validators

/** ``Literal[...]`` (strict: only the exact strings). */
function _literal(allowed: readonly string[]): (value: unknown) => unknown {
  return (value: unknown) => {
    if (typeof value === 'string' && allowed.includes(value)) return value;
    const options = allowed.map((v) => `'${v}'`);
    const text = options.length > 1 ? `${options.slice(0, -1).join(', ')} or ${options[options.length - 1]}` : options[0];
    throw new Error(`Input should be ${text}`);
  };
}

/** ``List[str]`` (no coercion in pydantic v2). */
function _str_list(value: unknown): string[] {
  let items: unknown[];
  if (Array.isArray(value)) items = value;
  else if (value instanceof Set) items = [...value];
  else throw new Error('Input should be a valid list');
  for (const item of items) {
    if (typeof item !== 'string') throw new Error('Input should be a valid string');
  }
  return [...items] as string[];
}

/** Lax ``int`` (ints, bools, integral floats, integer strings). */
function _int_value(value: unknown): number {
  if (typeof value === 'boolean') return value ? 1 : 0;
  if (typeof value === 'number' && Number.isInteger(value)) return value;
  if (typeof value === 'string' && /^\s*[-+]?\d+(_\d+)*\s*$/.test(value)) return Number(value.replace(/_/g, '').trim());
  if (typeof value === 'number') throw new Error('Input should be a valid integer, got a number with a fractional part');
  throw new Error('Input should be a valid integer');
}

/** ``Dict[str, int]`` — a new dict whose values are validated as ints. */
function _str_int_dict(value: unknown): Record<string, number> {
  if (!isDict(value)) throw new Error('Input should be a valid dictionary');
  const out: Record<string, number> = {};
  for (const [key, item] of Object.entries(value)) out[key] = _int_value(item);
  return out;
}

/** ``Optional[float]`` (lax). */
function _optional_float(value: unknown): number | null {
  if (value === null) return null;
  if (typeof value === 'number') return value;
  if (typeof value === 'boolean') return value ? 1 : 0;
  if (typeof value === 'string' && value.trim() && !Number.isNaN(Number(value.trim()))) return Number(value.trim());
  throw new Error('Input should be a valid number');
}

/** ``int`` with ``ge``/``le`` bounds. */
function _bounded_int(ge: number, le: number): (value: unknown) => number {
  return (value: unknown) => {
    const n = _int_value(value);
    if (n < ge) throw new Error(`Input should be greater than or equal to ${ge}`);
    if (n > le) throw new Error(`Input should be less than or equal to ${le}`);
    return n;
  };
}

/** Nested model field: instances pass through (revalidate_instances='never'), dicts are validated. */
function _model<T extends BaseModel>(cls: () => new (data: Dict) => T, optional: boolean): (value: unknown) => T | null {
  return (value: unknown) => {
    if (value === null && optional) return null;
    const ctor = cls();
    if (value instanceof ctor) return value;
    if (isDict(value)) {
      try {
        return new ctor(value);
      } catch (error) {
        // pydantic reports nested errors under the outer model (the per-error
        // detail lines are simplified, see py/pydantic.ts).
        if (error instanceof ValidationError) throw new Error(error.errors.map((e) => `${e.loc}: ${e.msg}`).join('; '));
        throw error;
      }
    }
    throw new Error(`Input should be a valid dictionary or instance of ${ctor.name}`);
  };
}

/** ``List[Model]``. */
function _model_list<T extends BaseModel>(cls: () => new (data: Dict) => T): (value: unknown) => T[] {
  return (value: unknown) => {
    if (!Array.isArray(value)) throw new Error('Input should be a valid list');
    const one = _model(cls, false);
    return value.map((item) => one(item) as T);
  };
}

// ---------------------------------------------------------------- models

/** Atomic edit op. Same shape whether emitted by rule or LLM. */
export class EditOp extends BaseModel {
  static override pythonName = 'evodesign.agentic_system.refinement_stage.state.EditOp';
  static override model_fields: Record<string, FieldSpec> = {
    op: field({ before: _literal(EditOpName), required: true }),
    id: field({ type: 'str', required: true, description: 'Excalidraw element id this edit targets.' }),
    payload: field({ type: 'dict', default_factory: () => ({}) }),
    rationale: field({ type: 'str', default: '', description: 'Short human-readable reason. Logged but not enforced.' }),
    source: field({
      before: _literal(['deterministic', 'llm']),
      default: 'deterministic',
      description: 'Which path emitted this edit. Used in iteration log.',
    }),
  };

  declare op: EditOpName;
  declare id: string;
  declare payload: Dict;
  declare rationale: string;
  declare source: 'deterministic' | 'llm';

  constructor(data: Dict = {}) {
    // model_config = ConfigDict(extra="forbid")
    const source = data ?? {};
    const extra = Object.keys(source).filter(
      (key) => !Object.prototype.hasOwnProperty.call(EditOp.model_fields, key) && source[key] !== undefined,
    );
    let fieldErrors: { loc: string; msg: string }[] = [];
    try {
      super(source);
    } catch (error) {
      if (!(error instanceof ValidationError)) throw error;
      fieldErrors = error.errors;
    }
    const errors = [...fieldErrors, ...extra.map((key) => ({ loc: key, msg: 'Extra inputs are not permitted' }))];
    if (errors.length) throw new ValidationError('EditOp', errors);
  }

  to_dict(): Dict {
    // self.model_dump(mode="json")
    const out: Dict = {};
    for (const name of Object.keys(EditOp.model_fields)) out[name] = _dump_json((this as Dict)[name]);
    return out;
  }
}

/** ``EditOp.to_dict(self)`` as a function (parity adapter entry point). */
export function EditOp_to_dict(self: EditOp | Dict): Dict {
  return (self instanceof EditOp ? self : new EditOp(self)).to_dict();
}

/**
 * Result of ONE proposed edit. Always recorded — successes, skips, rejects.
 *
 * ``edit`` is None only for a proposal that never became an EditOp at all
 * (an LLM item that failed schema validation). Those used to be dropped with
 * nothing but a log warning, which made "the model proposed 20 malformed
 * edits" indistinguishable from "the model saw nothing to fix"; ``raw`` keeps
 * the offending payload so the iteration log can show what was thrown away.
 */
export class EditApplyOutcome extends BaseModel {
  static override pythonName = 'evodesign.agentic_system.refinement_stage.state.EditApplyOutcome';
  static override model_fields: Record<string, FieldSpec> = {
    edit: field({ before: _model(() => EditOp, true), default: null }),
    applied: field({ type: 'bool', required: true }),
    error: field({ type: 'optional_str', default: null }),
    raw: field({ type: 'optional_dict', default: null }),
  };

  declare edit: EditOp | null;
  declare applied: boolean;
  declare error: string | null;
  declare raw: Dict | null;
}

/** One row of the refinement audit trail. Per refiner iteration. */
export class IterationLog extends BaseModel {
  static override pythonName = 'evodesign.agentic_system.refinement_stage.state.IterationLog';
  static override model_fields: Record<string, FieldSpec> = {
    rolled_back: field({ type: 'bool', default: false }),

    iteration: field({ before: _int_value, required: true }),
    deterministic_edits: field({ before: _model_list(() => EditApplyOutcome), default_factory: () => [] }),
    llm_edits: field({ before: _model_list(() => EditApplyOutcome), default_factory: () => [] }),
    rerouted_arrows: field({ type: 'list_of_dict', default_factory: () => [] }),
    findings_before: field({ before: _str_int_dict, default_factory: () => ({}) }), // severity histogram
    findings_after: field({ before: _str_int_dict, default_factory: () => ({}) }),
    rerender_ok: field({ type: 'bool', default: false }),
    rerender_path: field({ type: 'optional_str', default: null }),
    rerender_error: field({ type: 'optional_str', default: null }),
    notes: field({ before: _str_list, default_factory: () => [] }),
  };

  declare rolled_back: boolean;
  declare iteration: number;
  declare deterministic_edits: EditApplyOutcome[];
  declare llm_edits: EditApplyOutcome[];
  declare rerouted_arrows: Dict[];
  declare findings_before: Record<string, number>;
  declare findings_after: Record<string, number>;
  declare rerender_ok: boolean;
  declare rerender_path: string | null;
  declare rerender_error: string | null;
  declare notes: string[];
}

/** Local deterministic work that can overlap the independent critic. */
export class PreparedIteration extends BaseModel {
  static override pythonName = 'evodesign.agentic_system.refinement_stage.state.PreparedIteration';
  static override model_fields: Record<string, FieldSpec> = {
    iteration: field({ before: _int_value, required: true }),
    findings_before: field({ before: _model_list(() => Finding as unknown as new (data: Dict) => Finding), required: true }),
    snapshot: field({ type: 'optional_dict', required: true }),
    log: field({ before: _model(() => IterationLog, false), required: true }),
    image_note: field({ type: 'optional_str', default: null }),
  };

  declare iteration: number;
  declare findings_before: Finding[];
  declare snapshot: Dict | null;
  declare log: IterationLog;
  declare image_note: string | null;
}

// Each iteration is a full VLM call plus a re-render; beyond this the loop is a
// runaway, not refinement. Also bounds the LangGraph recursion limit.
export const MAX_REFINER_ITERATIONS = 20;

/** LangGraph super-steps for load_inputs + N iterations + finalize, with slack. */
export function refiner_recursion_limit(max_iterations: number): number {
  return Math.max(25, 2 * Math.trunc(Number(max_iterations)) + 10);
}

/** ``@field_validator("canvas_library", mode="before")`` */
function validate_canvas_library(v: unknown): string {
  const value = normalize_canvas_library(v);
  if (!(SUPPORTED_REFINER_CANVAS_LIBRARIES as readonly string[]).includes(value)) {
    throw new ValueError(
      'IterativeRefinerWorkflow currently supports Excalidraw '
      + `manifests only; got canvas_library=${pyRepr(v)}.`,
    );
  }
  return value;
}

/** Workflow-wide state, passed through every LangGraph node. */
export class VerifierRefinerState extends BaseModel {
  static override pythonName = 'evodesign.agentic_system.refinement_stage.state.VerifierRefinerState';
  static override model_fields: Record<string, FieldSpec> = {
    // ---- Inputs ----
    verifier_report_path: field({ type: 'optional_str', default: null }),
    design_constraints: field({ type: 'str', default: '' }),
    manifest_path: field({ type: 'str', required: true }),
    image_path: field({ type: 'str', required: true }),
    structure_path: field({ type: 'optional_str', default: null }),
    layout_path: field({ type: 'optional_str', default: null }),
    output_dir: field({ type: 'optional_str', default: null }),
    canvas_library: field({ before: validate_canvas_library, type: 'str', default: 'excalidraw' }),

    // ---- Controls ----
    max_iterations: field({ before: _bounded_int(1, MAX_REFINER_ITERATIONS), default: 3 }),
    skip_rerender_between_iterations: field({ type: 'bool', default: false }),
    skip_checks: field({ before: _str_list, default_factory: () => [] }),
    emit_markdown: field({ type: 'bool', default: false }),

    // ---- Loaded data ----
    initial_report: field({ type: 'optional_dict', default: null }),
    structure: field({ type: 'optional_dict', default: null }),
    layout_instantiation: field({ type: 'optional_dict', default: null }),
    manifest: field({ type: 'optional_dict', default: null }), // mutated across iterations

    // ---- Mutable per-iteration ----
    current_iteration: field({ before: _int_value, default: 0 }),
    current_image_path: field({ type: 'optional_str', default: null }),
    analysis_manifest_fingerprint: field({ type: 'optional_str', default: null }),
    prepared_iteration: field({ before: _model(() => PreparedIteration, true), default: null }),
    prepared_input_fingerprint: field({ type: 'optional_str', default: null }),
    iteration_logs: field({ before: _model_list(() => IterationLog), default_factory: () => [] }),
    latest_findings: field({ before: _model_list(() => Finding as unknown as new (data: Dict) => Finding), default_factory: () => [] }),
    converged: field({ type: 'bool', default: false }),
    termination_reason: field({ type: 'optional_str', default: null }),
    // Plain field, NOT a PrivateAttr: ``StateGraph`` only builds channels for
    // ``model_fields`` and rebuilds the state from channel values on every node
    // entry, so a private attribute silently reset to None each iteration and
    // stagnation could never be detected.
    prev_findings_fingerprint: field({ type: 'optional_str', default: null }),
    // Lowest (best) weighted finding score reached so far. A round that scores
    // worse than the round it started from is rolled back, so the manifest at
    // every round boundary is the historical best rather than the last attempt.
    best_findings_score: field({ before: _optional_float, default: null, py_float: true }),
    // Objective checks the refiner deliberately did not run this session, with
    // the reason. Surfaced in the report so a clean run cannot be mistaken for
    // a fully verified one.
    skipped_objective_checks: field({ before: _str_list, default_factory: () => [] }),

    // ---- Outputs ----
    refined_manifest_path: field({ type: 'optional_str', default: null }),
    refined_image_path: field({ type: 'optional_str', default: null }),
    candidate_manifest_path: field({ type: 'optional_str', default: null }),
    candidate_image_path: field({ type: 'optional_str', default: null }),
    refiner_report_path: field({ type: 'optional_str', default: null }),

    // ---- Bookkeeping ----
    status: field({ type: 'str', default: 'init' }),
    errors: field({ before: _str_list, default_factory: () => [] }),
    logs: field({ before: _str_list, default_factory: () => [] }),
  };

  declare verifier_report_path: string | null;
  declare design_constraints: string;
  declare manifest_path: string;
  declare image_path: string;
  declare structure_path: string | null;
  declare layout_path: string | null;
  declare output_dir: string | null;
  declare canvas_library: string;
  declare max_iterations: number;
  declare skip_rerender_between_iterations: boolean;
  declare skip_checks: string[];
  declare emit_markdown: boolean;
  declare initial_report: Dict | null;
  declare structure: Dict | null;
  declare layout_instantiation: Dict | null;
  declare manifest: Dict | null;
  declare current_iteration: number;
  declare current_image_path: string | null;
  declare analysis_manifest_fingerprint: string | null;
  declare prepared_iteration: PreparedIteration | null;
  declare prepared_input_fingerprint: string | null;
  declare iteration_logs: IterationLog[];
  declare latest_findings: Finding[];
  declare converged: boolean;
  declare termination_reason: string | null;
  declare prev_findings_fingerprint: string | null;
  declare best_findings_score: number | null;
  declare skipped_objective_checks: string[];
  declare refined_manifest_path: string | null;
  declare refined_image_path: string | null;
  declare candidate_manifest_path: string | null;
  declare candidate_image_path: string | null;
  declare refiner_report_path: string | null;
  declare status: string;
  declare errors: string[];
  declare logs: string[];

  add_log(message: string): null {
    this.logs.push(message);
    return null;
  }

  add_error(message: string): null {
    this.errors.push(message);
    return null;
  }

  /** ``VerifierRefinerState.validate_canvas_library(v)`` (classmethod). */
  static validate_canvas_library(v: unknown): string {
    return validate_canvas_library(v);
  }
}

/** Unbound-method forms for the parity harness: ``VerifierRefinerState.add_log(self, message)``. */
export function VerifierRefinerState_add_log(self: VerifierRefinerState, message: string): null {
  return self.add_log(message);
}

export function VerifierRefinerState_add_error(self: VerifierRefinerState, message: string): null {
  return self.add_error(message);
}

/**
 * ``model_dump(mode="json")`` of plain values: containers are rebuilt
 * (tuples/sets become lists). Integral-float marks (``PY_FLOAT_MARKS``) are
 * carried over to the rebuilt containers so a later ``json.dumps`` can still
 * print ``128.0``.
 */
function _dump_json(value: unknown): unknown {
  if (value instanceof BaseModel) return _dump_json(value.model_dump());
  let out: unknown = value;
  if (Array.isArray(value)) out = value.map(_dump_json);
  else if (value instanceof Set) out = [...value].map(_dump_json);
  else if (value instanceof Map) out = Object.fromEntries([...value.entries()].map(([k, v]) => [String(k), _dump_json(v)]));
  else if (isDict(value)) out = Object.fromEntries(Object.entries(value).map(([k, v]) => [k, _dump_json(v)]));
  else return value;
  const marks = PY_FLOAT_MARKS.get(value as object);
  if (marks) PY_FLOAT_MARKS.set(out as object, new Set(marks));
  return out;
}

export { ValidationError };

export const __all__ = [
  'EditOp',
  'EditOpName',
  'EditApplyOutcome',
  'IterationLog',
  'PreparedIteration',
  'VerifierRefinerState',
  'SUPPORTED_REFINER_CANVAS_LIBRARIES',
];
