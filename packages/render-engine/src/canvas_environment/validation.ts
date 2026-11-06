// Ported from evodesign/canvas_environment/validation.py — keep in sync.
// server-only (validate_png_file reads the file system)
//
// Validation, normalization, and audit facade for canvas manifests.

import { normalize_canvas_library } from '../canvas_runtime.ts';
import { pyGet } from '../py/dict.ts';
import { NotImplementedError, ValueError } from '../py/errors.ts';
import { pyRepr, pyStr } from '../py/str.ts';
import { isDict, pyOr } from '../py/truthy.ts';
import * as _render_engine_adapter from './_render_engine_adapter.ts';

type Dict = Record<string, unknown>;

/** Public, backend-neutral render audit finding. */
export class CanvasAuditIssue {
  constructor(
    public category: string,
    public message: string,
    public element_id: string | null = null,
    public severity: string = 'MAJOR',
  ) {}
}

/** Public, backend-neutral audit report for canvas manifests. */
export class CanvasAuditReport {
  constructor(
    public warnings: string[] = [],
    public issues: CanvasAuditIssue[] = [],
  ) {}
}

function _isIterable(value: unknown): value is Iterable<unknown> {
  return value !== null && typeof value === 'object' && typeof (value as { [Symbol.iterator]?: unknown })[Symbol.iterator] === 'function';
}

export function _as_list(value: unknown): unknown[] {
  if (value === null || value === undefined) {
    return [];
  }
  if (Array.isArray(value)) {
    return value;
  }
  if (typeof value === 'string') {
    return [value];
  }
  if (isDict(value)) {
    return [value];
  }
  if (value instanceof Map) {
    return [...value.keys()];
  }
  if (_isIterable(value)) {
    return [...value];
  }
  return [value];
}

/** ``getattr(obj, name, None)`` */
function _getattr(obj: unknown, name: string, defaultValue: unknown = null): unknown {
  if (obj === null || obj === undefined || (typeof obj !== 'object' && typeof obj !== 'function')) return defaultValue;
  const value = (obj as Record<string, unknown>)[name];
  return value === undefined ? defaultValue : value;
}

export function _coerce_audit_issue(issue: unknown): CanvasAuditIssue {
  if (issue instanceof CanvasAuditIssue) {
    return issue;
  }

  let category: unknown;
  let message: unknown;
  let element_id: unknown;
  let severity: unknown;
  if (isDict(issue)) {
    category = pyGet(issue, 'category');
    message = pyGet(issue, 'message');
    element_id = pyGet(issue, 'element_id');
    severity = pyGet(issue, 'severity');
  } else {
    category = _getattr(issue, 'category');
    message = _getattr(issue, 'message');
    element_id = _getattr(issue, 'element_id');
    severity = _getattr(issue, 'severity');
  }

  return new CanvasAuditIssue(
    pyStr(pyOr(category, 'unknown')),
    pyStr(pyOr(message, '')),
    typeof element_id === 'string' ? element_id : null,
    pyStr(pyOr(severity, 'MAJOR')),
  );
}

export function _audit_report_field(report: unknown, field: string, default_: unknown): unknown {
  if (isDict(report)) {
    return pyGet(report, field, default_);
  }
  return _getattr(report, field, default_);
}

export function _coerce_audit_report(report: unknown): CanvasAuditReport {
  if (report instanceof CanvasAuditReport) {
    return report;
  }

  const warnings = _as_list(_audit_report_field(report, 'warnings', [])).map((warning) => pyStr(warning));
  const issues = _as_list(_audit_report_field(report, 'issues', [])).map((issue) => _coerce_audit_issue(issue));
  return new CanvasAuditReport(warnings, issues);
}

/**
 * Normalize a canvas manifest in place and return it.
 *
 * Excalidraw manifests are normalized through the renderer's z-order/title
 * pass. TLDraw normalization is currently a passthrough because the active
 * normalizer is Excalidraw-specific.
 */
export function normalize_manifest(manifest: Dict, canvas_library = 'excalidraw'): Dict {
  canvas_library = normalize_canvas_library(canvas_library);
  if (canvas_library === 'excalidraw') {
    _render_engine_adapter.normalize_excalidraw_manifest(manifest);
    return manifest;
  }

  if (canvas_library === 'tldraw') {
    return manifest;
  }

  throw new NotImplementedError(`normalize_manifest is not implemented for ${pyRepr(canvas_library)}`);
}

/** Validate a canvas manifest for the selected backend. */
export function validate_manifest(manifest: Dict, canvas_library = 'excalidraw'): Dict {
  canvas_library = normalize_canvas_library(canvas_library);
  if (canvas_library === 'excalidraw') {
    return _render_engine_adapter.validate_excalidraw_manifest(manifest);
  }

  if (canvas_library === 'tldraw') {
    return _render_engine_adapter.validate_tldraw_manifest(manifest);
  }

  throw new ValueError(`Unknown canvas library: ${canvas_library}`);
}

/** Run backend-specific render audit and return a stable facade report. */
export function audit_manifest(
  manifest: Dict,
  structure_instantiation: Dict | null = null,
  canvas_library = 'excalidraw',
): CanvasAuditReport {
  canvas_library = normalize_canvas_library(canvas_library);
  if (canvas_library === 'excalidraw') {
    return _coerce_audit_report(
      _render_engine_adapter.audit_excalidraw_manifest(manifest, structure_instantiation),
    );
  }

  if (canvas_library === 'tldraw') {
    return _coerce_audit_report(
      _render_engine_adapter.audit_tldraw_manifest(manifest, structure_instantiation),
    );
  }

  throw new NotImplementedError(`audit_manifest is not implemented for ${pyRepr(canvas_library)}`);
}

/** Audit layout-stage output before backend-specific conversion. */
export function audit_layout_instantiation(layout_instantiation: Dict, structure_instantiation: Dict | null = null): string[] {
  return _render_engine_adapter.audit_layout_instantiation(layout_instantiation, structure_instantiation);
}

/**
 * Repair backend-specific manifest z-order through the canvas facade.
 *
 * Excalidraw manifests are repaired in place; TLDraw is currently a
 * passthrough because its z-order model is handled in the TLDraw converter.
 */
export function repair_manifest_zorder(manifest: Dict, canvas_library = 'excalidraw'): Dict {
  canvas_library = normalize_canvas_library(canvas_library);
  if (canvas_library === 'excalidraw') {
    return _render_engine_adapter.repair_excalidraw_zorder(manifest);
  }

  if (canvas_library === 'tldraw') {
    return manifest;
  }

  throw new NotImplementedError(`repair_manifest_zorder is not implemented for ${pyRepr(canvas_library)}`);
}

/** Detect backend group-frame element ids through the canvas facade. */
export function detect_group_frame_ids(elements: Dict[], structural = false, id_map: unknown = null): Set<string> {
  return _render_engine_adapter.detect_group_frame_ids(elements, structural, id_map);
}

/** Validate a rendered PNG artifact through the canvas facade. */
export function validate_png_file(output_file: string, context: string): void {
  _render_engine_adapter.validate_png_file(output_file, context);
}

export const __all__ = [
  'CanvasAuditIssue',
  'CanvasAuditReport',
  'normalize_manifest',
  'validate_manifest',
  'audit_manifest',
  'audit_layout_instantiation',
  'repair_manifest_zorder',
  'detect_group_frame_ids',
  'validate_png_file',
];
