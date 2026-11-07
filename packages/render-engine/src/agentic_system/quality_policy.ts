// Ported from evodesign/agentic_system/quality_policy.py — keep in sync.
//
// One quality policy for interactive generation, CLI runs and refinement.
//
// Geometry settling is not a visual-quality claim. Candidate adoption requires
// objective convergence; visual targets and user constraints still need verification.
//
// ``getattr(state, name, default)`` reads a property of a state object (TS
// class instance or plain object) and falls back to ``default`` when the
// property is missing.

import { pyInt } from '../py/number.ts';
import { pyGt, pyLt } from '../py/sort.ts';
import { pyOr, truthy } from '../py/truthy.ts';

export const VISUAL_TARGET = 7.0;
export const VISUAL_REGRESSION_TOLERANCE = 0.5;
export const SEVERITIES = ['critical', 'major', 'minor'] as const;

type Summary = Record<string, unknown>;

function getattr(obj: unknown, name: string, defaultValue: unknown = null): unknown {
  if (obj === null || obj === undefined || typeof obj !== 'object') return defaultValue;
  const value = (obj as Record<string, unknown>)[name];
  return value === undefined ? defaultValue : value;
}

function get(mapping: Summary, key: string, defaultValue: unknown = null): unknown {
  if (mapping instanceof Map) return mapping.has(key) ? mapping.get(key) : defaultValue;
  return Object.prototype.hasOwnProperty.call(mapping, key) ? mapping[key] : defaultValue;
}

/** ``isinstance(x, (int, float))`` — bool is an int. */
function isRealNumber(value: unknown): value is number | boolean {
  return typeof value === 'number' || typeof value === 'boolean';
}

export function objective_rank(summary: Summary): number[] {
  return SEVERITIES.map((key) => pyInt(pyOr(get(summary, key, 0), 0) as number));
}

export function quality_summary(state: unknown): Record<string, unknown> {
  const critique = getattr(state, 'critique', null);
  const score = getattr(critique, 'overall_score', null);
  const findings: Record<string, number> = { ...((pyOr(getattr(state, 'objective_summary', {}), {}) as Record<string, number>)) };
  if (!truthy(findings)) {
    for (const finding of (pyOr(getattr(state, 'objective_findings', []), []) as unknown[])) {
      const severity = getattr(finding, 'severity', null);
      const key = String(getattr(severity, 'value', severity));
      findings[key] = (Object.prototype.hasOwnProperty.call(findings, key) ? findings[key] : 0) + 1;
    }
  }
  return {
    findings,
    score: isRealNumber(score) && Number.isFinite(Number(score)) ? Number(score) : null,
    constraint_violations: [...(pyOr(getattr(critique, 'constraint_violations', []), []) as unknown[])],
    ...(blocking_errors(state) ? { blocking_errors: true } : {}),
  };
}

export function blocking_errors(state: unknown): boolean {
  const explicit = getattr(state, 'has_blocking_errors', null);
  if (typeof explicit === 'boolean') {
    return explicit;
  }
  const errors = getattr(state, 'blocking_errors', null);
  if (typeof errors === 'string' || Array.isArray(errors)) {
    return truthy(errors);
  }
  return getattr(state, 'has_errors', false) === true;
}

export function needs_refinement(summary: Summary): boolean {
  const score = get(summary, 'score');
  return (objective_rank(get(summary, 'findings', {}) as Summary).some((value) => truthy(value))
    || truthy(get(summary, 'constraint_violations'))
    || (isRealNumber(score) && Number(score) < VISUAL_TARGET));
}

export function should_refine(state: unknown, force = false): boolean {
  return !blocking_errors(state) && (force || getattr(state, 'has_blocking_findings', false) === true
    || needs_refinement(quality_summary(state)));
}

export function quality_regressed(before: Summary, after: Summary): boolean {
  if (truthy(get(after, 'blocking_errors')) || truthy(get(after, 'constraint_violations'))) {
    return true;
  }
  if (pyGt(objective_rank(get(after, 'findings', {}) as Summary), objective_rank(get(before, 'findings', {}) as Summary))) {
    return true;
  }
  const old = get(before, 'score');
  const next = get(after, 'score');
  return isRealNumber(old) && (
    !isRealNumber(next) || !Number.isFinite(Number(next))
    || Number(next) < Number(old) - VISUAL_REGRESSION_TOLERANCE
  );
}

export function refinement_rejection(initial: unknown, candidate: unknown): string | null {
  if (candidate === null || candidate === undefined || blocking_errors(candidate)) {
    return 'Candidate verification unavailable.';
  }
  const after = quality_summary(candidate);
  if (truthy(after.constraint_violations)) {
    return 'Candidate violates explicit user constraints.';
  }
  if (objective_rank(after.findings as Summary).slice(0, 2).some((value) => truthy(value))) {
    return 'Candidate still has serious objective findings.';
  }
  if (initial !== null && initial !== undefined && quality_regressed(quality_summary(initial), after)) {
    return 'Candidate quality regressed or visual verification is incomplete.';
  }
  return null;
}

export function quality_status(summary: Summary): string {
  if (truthy(get(summary, 'blocking_errors'))) {
    return 'unverified';
  }
  if (needs_refinement(summary)) {
    return 'needs_attention';
  }
  return get(summary, 'score') !== null ? 'passed' : 'unverified';
}

export function verified_learning_gain(before: Summary, after: Summary): boolean {
  const old = get(before, 'score');
  const next = get(after, 'score');
  if (truthy(get(before, 'blocking_errors')) || truthy(get(after, 'blocking_errors'))) {
    return false;
  }
  if (![old, next].every((score) => isRealNumber(score) && Number.isFinite(Number(score)))) {
    return false;
  }
  const o = Number(old);
  const n = Number(next);
  return (quality_status(after) === 'passed' && !quality_regressed(before, after)
    && n >= o && (n >= o + 0.5
    || pyLt(objective_rank(get(after, 'findings', {}) as Summary), objective_rank(get(before, 'findings', {}) as Summary))
    || truthy(get(before, 'constraint_violations'))));
}
