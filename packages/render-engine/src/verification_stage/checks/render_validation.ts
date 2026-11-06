// Ported from evodesign/agentic_system/verification_stage/checks/render_validation.py — keep in sync.
//
// Wrap canvas_environment render audit + manifest validation.
//
// Re-exports their string warnings as Finding objects with severity classified
// by the source. Both modules are imported read-only and never mutated.

import { pyGet } from '../../py/dict.ts';
import { pyStr } from '../../py/str.ts';
import { isDict, pyTypeName, truthy } from '../../py/truthy.ts';
import {
  audit_layout_instantiation,
  audit_manifest,
  validate_manifest,
} from '../../canvas_environment/validation.ts';
import { Finding, Severity } from './finding.ts';

type Dict = Record<string, any>;

// Map audit category → Finding severity.
export const _SEVERITY_MAP: Record<string, Severity> = {
  zorder: Severity.MAJOR,
  contrast: Severity.MAJOR,
  empty_text: Severity.MAJOR,
  arrow_coverage: Severity.MAJOR,
};

/** ``value or []`` */
function _orList(value: unknown): unknown[] {
  return truthy(value) ? (value as unknown[]) : [];
}

/**
 * Run the selected canvas backend's schema validator.
 *
 * `errors` from the validator → CRITICAL Findings.
 * `warnings` from the validator → MINOR Findings.
 */
export function check_schema(manifest: Dict, canvas_library = 'excalidraw'): Finding[] {
  const findings: Finding[] = [];
  const report = validate_manifest(manifest, canvas_library);

  for (const err of _orList(pyGet(report, 'errors', []))) {
    findings.push(
      new Finding({
        category: 'render_validation/schema',
        severity: Severity.CRITICAL,
        message: pyStr(err),
      }),
    );
  }
  for (const warn of _orList(pyGet(report, 'warnings', []))) {
    findings.push(
      new Finding({
        category: 'render_validation/schema',
        severity: Severity.MINOR,
        message: pyStr(warn),
      }),
    );
  }

  return findings;
}

/**
 * Run render_audit on the post-arrow canvas manifest.
 *
 * Uses per-element ``AuditIssue`` data for zorder and contrast findings,
 * so downstream fixers can target specific elements instead of scanning all.
 */
export function check_render_audit(
  manifest: Dict,
  structure: Dict | null = null,
  canvas_library = 'excalidraw',
): Finding[] {
  const findings: Finding[] = [];
  const report = audit_manifest(manifest, structure, canvas_library);

  // Use structured issues (per-element) instead of aggregated warnings.
  for (const issue of report.issues) {
    const sev = Object.prototype.hasOwnProperty.call(_SEVERITY_MAP, issue.category) ? _SEVERITY_MAP[issue.category] : Severity.MAJOR;
    findings.push(
      new Finding({
        category: `render_validation/audit/${issue.category}`,
        severity: sev,
        message: issue.message,
        element_id: issue.element_id,
      }),
    );
  }

  return findings;
}

/**
 * Run render_audit's layout-stage check (empty title / edge classifier / dup id).
 *
 * Missing or malformed layout is a blocking finding unless the caller
 * explicitly skips ``layout_audit``.
 */
export function check_layout_audit(layout_instantiation: Dict | null, structure: Dict | null = null): Finding[] {
  const findings: Finding[] = [];
  if (!isDict(layout_instantiation)) {
    const kind = layout_instantiation === null || layout_instantiation === undefined
      ? 'missing'
      : pyTypeName(layout_instantiation);
    return [
      new Finding({
        category: 'render_validation/layout_audit/missing_layout',
        severity: Severity.CRITICAL,
        message:
          'layout_audit requires layout_instantiation as a JSON object; '
          + `got ${kind}. Pass --layout, provide the sibling `
          + '3_layout/layout_instantiation.json, or skip layout_audit '
          + 'explicitly when running manifest-only verification.',
      }),
    ];
  }
  const warnings = audit_layout_instantiation(layout_instantiation, structure);
  for (const warn of warnings) {
    findings.push(
      new Finding({
        category: 'render_validation/layout_audit',
        severity: Severity.MAJOR,
        message: pyStr(warn),
      }),
    );
  }
  return findings;
}

export const __all__ = ['check_schema', 'check_render_audit', 'check_layout_audit'];
