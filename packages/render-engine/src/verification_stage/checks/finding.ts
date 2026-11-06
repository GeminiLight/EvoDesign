// Ported from evodesign/agentic_system/verification_stage/checks/finding.py — keep in sync.
//
// Finding & severity types — the lingua franca of the objective check layer.
//
// Every check function in `verification_stage/checks/` returns `List[Finding]`.
// The aggregator concatenates them and produces a per-severity histogram.
//
// ``Severity`` is a ``str`` enum in Python; here a finding stores the plain
// string value (``"major"``), which is what ``model_dump(mode="json")`` and
// the recorded vectors carry. ``Severity.MAJOR === "major"``.

import { PY_FLOAT_MARKS } from '../../py/json_decoder.ts';
import { BaseModel, field } from '../../py/pydantic.ts';

/**
 * Severity ladder for objective findings.
 *
 * CRITICAL = render is broken (schema invalid, required field missing)
 * MAJOR    = visual bug (overlap, wrong containment, missing arrow)
 * MINOR    = quality nit (out-of-canvas, redundant element, low contrast)
 * INFO     = observational, not actionable
 */
export const Severity = {
  CRITICAL: 'critical',
  MAJOR: 'major',
  MINOR: 'minor',
  INFO: 'info',
} as const;
export type Severity = (typeof Severity)[keyof typeof Severity];

/** ``list(Severity)`` in declaration order. */
export const SEVERITY_VALUES: readonly Severity[] = [Severity.CRITICAL, Severity.MAJOR, Severity.MINOR, Severity.INFO];

/** pydantic enum coercion: accept a member value, reject anything else. */
function _coerce_severity(value: unknown): Severity {
  if (typeof value === 'string' && (SEVERITY_VALUES as readonly string[]).includes(value)) return value as Severity;
  throw new Error("Input should be 'critical', 'major', 'minor' or 'info'");
}

export interface FindingInit {
  category: string;
  severity: Severity | string;
  message: string;
  element_id?: string | null;
  location?: Record<string, unknown> | null;
}

/**
 * Single objective check finding.
 *
 * `category` groups findings by check kind ("render_validation",
 * "collision", "containment", "binding", "render_audit"). `element_id`
 * points at the offending Excalidraw element when applicable; `location`
 * can carry coordinates / bbox for downstream visualization.
 */
export class Finding extends BaseModel {
  static override pythonName = 'evodesign.agentic_system.verification_stage.checks.finding.Finding';
  static override model_fields = {
    category: field({ type: 'str', required: true }),
    severity: field({ before: _coerce_severity, required: true }),
    message: field({ type: 'str', required: true }),
    element_id: field({ type: 'optional_str', default: null }),
    location: field({ type: 'optional_dict', default: null }),
  };
  declare category: string;
  declare severity: Severity;
  declare message: string;
  declare element_id: string | null;
  declare location: Record<string, unknown> | null;

  constructor(data: FindingInit) {
    super(data as unknown as Record<string, unknown>);
  }

  to_dict(): Record<string, unknown> {
    // model_dump(exclude_none=True, mode="json"): None dropped at the top level only.
    const out: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(this.model_dump())) {
      if (value === null || value === undefined) continue;
      out[key] = _json_mode(value);
    }
    return out;
  }
}

/** ``Finding.to_dict(self)`` as a function (parity adapter entry point). */
export function Finding_to_dict(self: Finding | FindingInit): Record<string, unknown> {
  return (self instanceof Finding ? self : new Finding(self)).to_dict();
}

/** ``mode="json"``: tuples/sets become lists, containers are rebuilt. */
function _json_mode(value: unknown): unknown {
  if (Array.isArray(value)) return _keep_float_marks(value, value.map(_json_mode));
  if (value instanceof Set) return [...value].map(_json_mode);
  if (value instanceof Map) return Object.fromEntries([...value.entries()].map(([k, v]) => [String(k), _json_mode(v)]));
  if (value !== null && typeof value === 'object') {
    return _keep_float_marks(value, Object.fromEntries(Object.entries(value as Record<string, unknown>).map(([k, v]) => [k, _json_mode(v)])));
  }
  return value;
}

/** Rebuilt containers keep the integral-float marks of the source (values unchanged; see ISSUES.md WP22-1). */
function _keep_float_marks<T extends object>(source: object, copy: T): T {
  const marks = PY_FLOAT_MARKS.get(source);
  if (marks) PY_FLOAT_MARKS.set(copy, new Set(marks));
  return copy;
}

/** Histogram findings by severity. Always returns all 4 keys. */
export function summarize_findings(findings: Array<{ severity: Severity | string }>): Record<string, number> {
  const summary: Record<string, number> = {};
  for (const s of SEVERITY_VALUES) summary[s] = 0;
  for (const f of findings) {
    summary[f.severity] = (summary[f.severity] ?? 0) + 1;
  }
  summary.total = findings.length;
  return summary;
}

export const __all__ = ['Severity', 'Finding', 'summarize_findings'];
