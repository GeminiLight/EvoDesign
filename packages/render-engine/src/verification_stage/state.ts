// Ported from evodesign/agentic_system/verification_stage/state.py — keep in sync.
//
// Verifier state — Pydantic v2 model that survives every workflow node.
//
// Mirrors the pattern used by refinement_stage/state.py but stays fully
// independent (does not import any refiner type).
//
// pydantic → TS (PHASE2_PLAN.md §2 rule 5): classes on ``py/pydantic.ts``
// ``BaseModel``. Constrained floats (``Field(..., ge=0.0, le=10.0)``),
// ``List[str]`` and nested models are checked by explicit field validators
// that raise under the same conditions as pydantic (lax mode).

import { BaseModel, ValidationError, field, type FieldSpec } from '../py/pydantic.ts';
import { isDict, truthy } from '../py/truthy.ts';
import { Finding, Severity } from './checks/finding.ts';

type Dict = Record<string, any>;

// ---------------------------------------------------------------- validators

/** ``float`` field with ``ge=0.0, le=10.0`` (pydantic lax float + range check). */
function _score_0_10(value: unknown): number {
  let score: number;
  if (typeof value === 'number') score = value;
  else if (typeof value === 'boolean') score = value ? 1 : 0;
  else if (typeof value === 'string' && value.trim() && !Number.isNaN(Number(value.trim()))) score = Number(value.trim());
  else throw new Error('Input should be a valid number');
  if (!(score >= 0.0)) throw new Error('Input should be greater than or equal to 0');
  if (!(score <= 10.0)) throw new Error('Input should be less than or equal to 10');
  return score;
}

/** ``List[str]``: a list (or tuple/set) whose items are all ``str`` (no coercion in pydantic v2). */
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

/** ``str`` (strict: pydantic v2 does not coerce numbers to str). */
function _str(value: unknown): string {
  if (typeof value !== 'string') throw new Error('Input should be a valid string');
  return value;
}

/** Nested model field: instances pass through (revalidate_instances='never'), dicts are validated. */
function _model<T extends BaseModel>(cls: new (data: Dict) => T, optional: boolean): (value: unknown) => T | null {
  return (value: unknown) => {
    if (value === null && optional) return null;
    if (value instanceof cls) return value;
    if (value instanceof BaseModel) return new cls(value.model_dump());
    if (isDict(value)) return new cls(value);
    throw new Error(`Input should be a valid dictionary or instance of ${cls.name}`);
  };
}

/** ``List[Finding]``. */
function _findings(value: unknown): Finding[] {
  if (!Array.isArray(value)) throw new Error('Input should be a valid list');
  const toFinding = _model(Finding as unknown as new (data: Dict) => Finding, false);
  return value.map((item) => toFinding(item) as Finding);
}

// ---------------------------------------------------------------- models

/** One dimension's worth of the VLM's three-section output. */
export class DimensionCritique extends BaseModel {
  static override pythonName = 'evodesign.agentic_system.verification_stage.state.DimensionCritique';
  static override model_fields: Record<string, FieldSpec> = {
    score: field({ before: _score_0_10, required: true, py_float: true }),
    strengths: field({ before: _str_list, default_factory: () => [] }),
    weaknesses: field({ before: _str_list, default_factory: () => [] }),
    suggestions: field({ before: _str_list, default_factory: () => [] }),
  };

  declare score: number;
  declare strengths: string[];
  declare weaknesses: string[];
  declare suggestions: string[];
}

/** Full structured response from the single VLM call. */
export class Critique extends BaseModel {
  static override pythonName = 'evodesign.agentic_system.verification_stage.state.Critique';
  static override model_fields: Record<string, FieldSpec> = {
    structure: field({ before: _model(DimensionCritique, false), required: true }),
    styling: field({ before: _model(DimensionCritique, false), required: true }),
    layout: field({ before: _model(DimensionCritique, false), required: true }),
    overall_score: field({ before: _score_0_10, required: true, py_float: true }),
    constraint_violations: field({ before: _str_list, default_factory: () => [] }),
    summary: field({ before: _str, default: '' }),
    call_metrics: field({ type: 'dict', default_factory: () => ({}) }),
    // Full raw LLM response, kept for debugging when JSON parse fails.
    raw_response: field({ type: 'optional_str', default: null }),
  };

  declare structure: DimensionCritique;
  declare styling: DimensionCritique;
  declare layout: DimensionCritique;
  declare overall_score: number;
  declare constraint_violations: string[];
  declare summary: string;
  declare call_metrics: Dict;
  declare raw_response: string | null;
}

const _FAILED_STATUSES = new Set(['failed', 'reported_with_errors']);

/**
 * Workflow-wide state for the verifier pipeline.
 *
 * Shared across the 4 LangGraph nodes (load → check → critic → report).
 */
export class VerifierState extends BaseModel {
  static override pythonName = 'evodesign.agentic_system.verification_stage.state.VerifierState';
  static override model_fields: Record<string, FieldSpec> = {
    // ---- Inputs ----
    manifest_path: field({ type: 'str', required: true }),
    image_path: field({ type: 'str', required: true }),
    canvas_library: field({ type: 'str', default: 'excalidraw' }),
    structure_path: field({ type: 'optional_str', default: null }),
    layout_path: field({ type: 'optional_str', default: null }),
    source_text: field({ type: 'optional_str', default: null }),
    design_constraints: field({ type: 'str', default: '' }),
    output_dir: field({ type: 'optional_str', default: null }),
    skip_critic: field({ type: 'bool', default: false }),
    skip_checks: field({ before: _str_list, default_factory: () => [] }),
    emit_markdown: field({ type: 'bool', default: false }),

    // ---- Loaded data ----
    manifest: field({ type: 'optional_dict', default: null }),
    structure: field({ type: 'optional_dict', default: null }),
    layout_instantiation: field({ type: 'optional_dict', default: null }), // optional, derived if structure dir holds it

    // ---- Objective output ----
    objective_findings: field({ before: _findings, default_factory: () => [] }),
    objective_summary: field({ type: 'dict', default_factory: () => ({}) }),

    // ---- Subjective output ----
    critique: field({ before: _model(Critique, true), default: null }),

    // ---- Report ----
    report: field({ type: 'optional_dict', default: null }),
    report_path: field({ type: 'optional_str', default: null }),

    // ---- Bookkeeping ----
    // init | loaded | checked | critiqued | reported | reported_with_findings |
    // reported_with_warnings | reported_with_errors | failed
    status: field({ type: 'str', default: 'init' }),
    errors: field({ before: _str_list, default_factory: () => [] }),
    blocking_errors: field({ before: _str_list, default_factory: () => [] }),
    nonblocking_errors: field({ before: _str_list, default_factory: () => [] }),
    logs: field({ before: _str_list, default_factory: () => [] }),
  };

  declare manifest_path: string;
  declare image_path: string;
  declare canvas_library: string;
  declare structure_path: string | null;
  declare layout_path: string | null;
  declare source_text: string | null;
  declare design_constraints: string;
  declare output_dir: string | null;
  declare skip_critic: boolean;
  declare skip_checks: string[];
  declare emit_markdown: boolean;
  declare manifest: Dict | null;
  declare structure: Dict | null;
  declare layout_instantiation: Dict | null;
  declare objective_findings: Finding[];
  declare objective_summary: Record<string, number>;
  declare critique: Critique | null;
  declare report: Dict | null;
  declare report_path: string | null;
  declare status: string;
  declare errors: string[];
  declare blocking_errors: string[];
  declare nonblocking_errors: string[];
  declare logs: string[];

  // Convenience helpers — keep the same names as refinement_stage for
  // consistency, but DO NOT import refiner types.
  add_log(message: string): null {
    this.logs.push(message);
    return null;
  }

  add_error(message: string, blocking = true): null {
    this.errors.push(message);
    if (blocking) {
      this.blocking_errors.push(message);
    } else {
      this.nonblocking_errors.push(message);
    }
    return null;
  }

  get has_errors(): boolean {
    return truthy(this.errors) || _FAILED_STATUSES.has(this.status);
  }

  get has_blocking_errors(): boolean {
    return truthy(this.blocking_errors) || _FAILED_STATUSES.has(this.status);
  }

  get has_nonblocking_errors(): boolean {
    return truthy(this.nonblocking_errors);
  }

  get blocking_finding_count(): number {
    if (truthy(this.objective_summary)) {
      return _int(this.objective_summary.critical || 0) + _int(this.objective_summary.major || 0);
    }
    let count = 0;
    for (const finding of this.objective_findings) {
      if (finding.severity === Severity.CRITICAL || finding.severity === Severity.MAJOR) count += 1;
    }
    return count;
  }

  get has_blocking_findings(): boolean {
    return this.blocking_finding_count > 0;
  }

  get quality_passed(): boolean {
    return !this.has_blocking_errors && !this.has_blocking_findings;
  }

  get cli_exit_code(): number {
    return ['reported', 'reported_with_warnings'].includes(this.status) && this.quality_passed ? 0 : 1;
  }
}

/** ``int(x)`` for the histogram counts (ints, or bools). */
function _int(value: unknown): number {
  if (typeof value === 'boolean') return value ? 1 : 0;
  return Math.trunc(Number(value));
}

/** Unbound-method forms for the parity harness: ``VerifierState.add_log(self, message)``. */
export function VerifierState_add_log(self: VerifierState, message: string): null {
  return self.add_log(message);
}

export function VerifierState_add_error(self: VerifierState, message: string, blocking = true): null {
  return self.add_error(message, blocking);
}

export { ValidationError };

export const __all__ = ['VerifierState', 'Critique', 'DimensionCritique'];
