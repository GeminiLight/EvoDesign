// Ported from evodesign/agentic_system/render_engine/shared/render_audit.py — keep in sync.
//
// Render-time audits for silent fidelity losses. Inspects
// ``layout_instantiation`` and the post-arrow Excalidraw/TLDraw manifest,
// logs suspicious gaps under the ``[RenderAudit]`` prefix, never raises.

import { unwrap_structure_instantiation } from '../../common/spec_utils.ts';
import { TITLE_SUFFIX, group_frame_render_id, id_map_from_manifest } from '../../common/semantic_ids.ts';
import { pyGet, pyItems } from '../../py/dict.ts';
import { pyIn } from '../../py/eq.ts';
import { PyTypeError, ValueError } from '../../py/errors.ts';
import { getLogger } from '../../py/logging.ts';
import { pow } from '../../py/math.ts';
import { pyInt } from '../../py/number.ts';
import { pyGt, pyMaxN, pyMinN, pySort, pySorted } from '../../py/sort.ts';
import { cpChars, cpLen, cpSlice, pyFormatFixed, pyFormatPercent, pyLstrip, pyRepr, pyStr, pyStrip } from '../../py/str.ts';
import { isDict, isStr, pyOr, truthy } from '../../py/truthy.ts';

type Dict = Record<string, unknown>;

const logger = getLogger('evodesign.agentic_system.render_engine.shared.render_audit');

export const _AUDIT_PREFIX = '[RenderAudit]';

/** One structured audit finding, with element_id for targeted fixing. */
export class AuditIssue {
  constructor(
    public category: string, // "zorder" | "contrast" | "empty_text" | "arrow_coverage" | ...
    public message: string,
    public element_id: string | null = null,
    public severity: string = 'MAJOR', // MAJOR | MINOR
  ) {}
}

/** Combined output: human-readable warnings + machine-parseable issues. */
export class AuditReport {
  constructor(
    public warnings: string[] = [],
    public issues: AuditIssue[] = [],
  ) {}
}

/** ``for x in value`` over a list-ish value (``None`` raises like Python). */
function _iter(value: unknown): unknown[] {
  if (Array.isArray(value)) return value;
  if (typeof value === 'string') return [...value];
  if (value instanceof Map || value instanceof Set) return [...value.keys()];
  if (isDict(value)) return Object.keys(value);
  throw new PyTypeError(`'${value === null || value === undefined ? 'NoneType' : typeof value}' object is not iterable`);
}

function _setDifference<T>(a: Set<T>, b: Set<T>): Set<T> {
  return new Set([...a].filter((item) => !b.has(item)));
}

function _setIntersection<T>(a: Set<T>, b: Set<T>): Set<T> {
  return new Set([...a].filter((item) => b.has(item)));
}

export function _is_title_key(element_id: unknown): boolean {
  return isStr(element_id) && element_id.endsWith(TITLE_SUFFIX);
}

/** Return True if the entry is a text element without renderable text. */
export function _text_empty(element_data: unknown): boolean {
  if (!isDict(element_data)) {
    return true;
  }
  const label = pyGet(element_data, 'label');
  if (isDict(label) && truthy(pyGet(label, 'text'))) {
    return false;
  }
  const props = pyGet(element_data, 'props');
  if (isDict(props) && truthy(pyGet(props, 'text'))) {
    return false;
  }
  return !truthy(pyGet(element_data, 'text'));
}

/** Heuristic: dict with start+end subdicts is structurally an edge. */
export function _looks_like_edge(element_data: unknown): boolean {
  if (!isDict(element_data)) {
    return false;
  }
  const start = pyGet(element_data, 'start');
  const end = pyGet(element_data, 'end');
  return isDict(start) && isDict(end);
}

export function _merged_edge_ids(meta: Dict): string[] {
  const merged = pyGet(meta, 'merged_semantic_edge_ids');
  return Array.isArray(merged) ? merged.filter((i): i is string => isStr(i) && truthy(i)) : [];
}

/** Return coverage plus any missing stable Structure edge ids. */
export function _edge_coverage(
  expected_edge_count: number,
  expected_edge_ids: Set<string>,
  rendered_arrow_count: number,
  rendered_semantic_edge_ids: Set<string>,
): [number, string[]] {
  if (expected_edge_count <= 0) {
    return [1.0, []];
  }

  const missing_edge_ids = pySorted(_setDifference(expected_edge_ids, rendered_semantic_edge_ids));

  if (expected_edge_ids.size) {
    const matched_named_count = _setIntersection(expected_edge_ids, rendered_semantic_edge_ids).size;
    const anonymous_expected_count = pyMaxN(0, expected_edge_count - expected_edge_ids.size);
    const anonymous_rendered_count = pyMaxN(0, rendered_arrow_count - rendered_semantic_edge_ids.size);
    const matched_anonymous_count = pyMinN(anonymous_expected_count, anonymous_rendered_count);
    return [
      (matched_named_count + matched_anonymous_count) / expected_edge_count,
      missing_edge_ids,
    ];
  }

  return [rendered_arrow_count / expected_edge_count, []];
}

/** Inspect layout output for fidelity gaps. Log + return warnings. */
export function audit_layout_instantiation(
  layout_instantiation: Dict | null,
  structure_instantiation: Dict | null = null,
): string[] {
  const warnings: string[] = [];
  if (!isDict(layout_instantiation)) {
    return warnings;
  }

  const structure = unwrap_structure_instantiation(structure_instantiation);
  const structure_edge_ids = new Set<unknown>();
  for (const edge of _iter(pyOr(pyGet(structure, 'edges', []), []))) {
    if (isDict(edge) && truthy(pyGet(edge, 'id'))) {
      structure_edge_ids.add(pyGet(edge, 'id'));
    }
  }

  for (const [element_id, element_data] of pyItems(layout_instantiation)) {
    if (element_id === 'specification') {
      continue;
    }

    // Check 1: empty title text
    if (_is_title_key(element_id) && _text_empty(element_data)) {
      const msg = (
        `${_AUDIT_PREFIX} empty title text for id=${pyRepr(element_id)}; `
        + 'check that styling emits label.text for every group.'
      );
      warnings.push(msg);
      logger.warning(msg);
    }

    // Check 2: edge-like payload missed by the classifier
    if (_looks_like_edge(element_data)) {
      const is_classified = (
        isStr(element_id) && element_id.startsWith('edge:')
      ) || pyIn(element_id, structure_edge_ids);
      if (!is_classified) {
        const msg = (
          `${_AUDIT_PREFIX} entry id=${pyRepr(element_id)} has start+end dicts `
          + "but is not recognised as an edge (not prefixed with 'edge:' "
          + 'and not present in structure.edges[].id).'
        );
        warnings.push(msg);
        logger.warning(msg);
      }
    }
  }

  return warnings;
}

function _structure_edges(structure: Dict): { edges: Dict[]; ids: Set<string> } {
  const edges = _iter(pyOr(pyGet(structure, 'edges', []), [])).filter((edge): edge is Dict => isDict(edge));
  const ids = new Set<string>();
  for (const edge of edges) {
    const id = pyGet(edge, 'id');
    if (isStr(id) && pyStrip(id)) {
      ids.add(pyStr(edge.id));
    }
  }
  return { edges, ids };
}

function _coverage_message(
  label: string,
  rendered_arrow_count: number,
  expected_edge_count: number,
  coverage: number,
  arrow_coverage_threshold: number,
  missing_edge_ids: string[],
): string {
  let missing_suffix = '';
  if (missing_edge_ids.length) {
    missing_suffix = ` Missing Structure edge ids: ${missing_edge_ids.slice(0, 5).join(', ')}.`;
  }
  return (
    `${_AUDIT_PREFIX} ${label}rendered arrows=${rendered_arrow_count} / `
    + `structure.edges=${expected_edge_count} (coverage `
    + `${pyFormatPercent(coverage, 0)}; threshold ${pyFormatPercent(arrow_coverage_threshold, 0)}). arrow_adder `
    + `likely failed to resolve some edge endpoints.${missing_suffix}`
  );
}

/** Inspect the post-arrow-adder Excalidraw manifest for render-time gaps. */
export function audit_excalidraw_manifest(
  manifest: Dict | null,
  structure_instantiation: Dict | null = null,
  arrow_coverage_threshold = 0.7,
): AuditReport {
  const report = new AuditReport();
  if (!isDict(manifest)) {
    return report;
  }

  const elements = pyGet(manifest, 'elements', []);
  if (!Array.isArray(elements)) {
    return report;
  }

  const structure = unwrap_structure_instantiation(structure_instantiation);
  const { edges: structure_edges, ids: expected_edge_ids } = _structure_edges(structure);
  const expected_edge_count = structure_edges.length;

  const empty_text_ids: string[] = [];
  let rendered_arrow_count = 0;
  const rendered_semantic_edge_ids = new Set<string>();
  const id_counts = new Map<string, number>();

  for (const elem of elements) {
    if (!isDict(elem)) {
      continue;
    }
    const elem_id = pyGet(elem, 'id');
    if (isStr(elem_id) && elem_id) {
      id_counts.set(elem_id, (id_counts.get(elem_id) ?? 0) + 1);
    }
    const etype = pyGet(elem, 'type');
    if (etype === 'arrow') {
      rendered_arrow_count += 1;
      const meta = pyGet(elem, 'meta');
      if (isDict(meta) && isStr(pyGet(meta, 'semantic_edge_id'))) {
        rendered_semantic_edge_ids.add(meta.semantic_edge_id as string);
        // One connector may stand for duplicate or reverse edges of the same pair.
        for (const id of _merged_edge_ids(meta)) rendered_semantic_edge_ids.add(id);
      }
      continue;
    }
    if (etype === 'text') {
      if (truthy(pyGet(elem, 'containerId'))) {
        continue;
      }
      if (!truthy(pyOr(pyGet(elem, 'text'), pyGet(elem, 'originalText')))) {
        empty_text_ids.push(pyStr(pyGet(elem, 'id', '?')));
      }
    }
  }

  // Duplicate ids: warn-only here, with a targeted per-element issue.
  const duplicate_ids = pySorted([...id_counts.entries()].filter(([, count]) => count > 1).map(([eid]) => eid));
  if (duplicate_ids.length) {
    const sample = duplicate_ids.slice(0, 5).join(', ');
    const msg = (
      `${_AUDIT_PREFIX} ${duplicate_ids.length} element id(s) appear more `
      + `than once in the manifest (sample: ${sample}). Excalidraw keeps `
      + "only one element per id; the converter's id_map likely collapsed "
      + 'two semantic ids onto one render id.'
    );
    report.warnings.push(msg);
    logger.warning(msg);
    for (const eid of duplicate_ids) {
      report.issues.push(new AuditIssue(
        'duplicate_id',
        `element id ${pyRepr(eid)} appears ${id_counts.get(eid)} times`,
        eid,
      ));
    }
  }

  if (empty_text_ids.length) {
    const sample = empty_text_ids.slice(0, 5).join(', ');
    const msg = (
      `${_AUDIT_PREFIX} ${empty_text_ids.length} standalone text element(s) `
      + `have empty text (sample: ${sample}). Likely group titles without `
      + 'label.text — check styling output contract.'
    );
    report.warnings.push(msg);
    logger.warning(msg);
    for (const eid of empty_text_ids) {
      report.issues.push(new AuditIssue(
        'empty_text',
        `standalone text ${eid} has empty text`,
        eid,
      ));
    }
  }

  if (expected_edge_count > 0) {
    const [coverage, missing_edge_ids] = _edge_coverage(
      expected_edge_count,
      expected_edge_ids,
      rendered_arrow_count,
      rendered_semantic_edge_ids,
    );
    if (missing_edge_ids.length || coverage < arrow_coverage_threshold) {
      const msg = _coverage_message('', rendered_arrow_count, expected_edge_count, coverage, arrow_coverage_threshold, missing_edge_ids);
      report.warnings.push(msg);
      logger.warning(msg);
      report.issues.push(new AuditIssue('arrow_coverage', msg));
    }
  }

  // Z-order and contrast — both return (warnings, issues)
  const [z_warnings, z_issues] = _audit_group_frame_zorder(manifest, structure);
  report.warnings.push(...z_warnings);
  report.issues.push(...z_issues);

  const [c_warnings, c_issues] = _audit_text_contrast(manifest);
  report.warnings.push(...c_warnings);
  report.issues.push(...c_issues);

  return report;
}

/** Inspect the post-arrow-adder TLDraw snapshot for render-time gaps. */
export function audit_tldraw_manifest(
  manifest: Dict | null,
  structure_instantiation: Dict | null = null,
  arrow_coverage_threshold = 0.7,
): AuditReport {
  const report = new AuditReport();
  if (!isDict(manifest)) {
    return report;
  }

  const document = pyGet(manifest, 'document');
  const store = isDict(document) ? pyGet(document, 'store') : null;
  if (!isDict(store)) {
    return report;
  }

  const structure = unwrap_structure_instantiation(structure_instantiation);
  const { edges: structure_edges, ids: expected_edge_ids } = _structure_edges(structure);
  const expected_edge_count = structure_edges.length;

  let rendered_arrow_count = 0;
  const rendered_semantic_edge_ids = new Set<string>();
  const empty_title_ids: string[] = [];
  const empty_text_ids: string[] = [];

  for (const [key, entry] of pyItems(store)) {
    if (!isDict(entry) || pyGet(entry, 'typeName') !== 'shape') {
      continue;
    }

    const shape_id = pyStr(pyOr(pyGet(entry, 'id'), key));
    const shape_type = pyGet(entry, 'type');
    const props = isDict(pyGet(entry, 'props')) ? (pyGet(entry, 'props') as Dict) : {};

    if (shape_type === 'arrow') {
      rendered_arrow_count += 1;
      const meta = pyGet(entry, 'meta');
      if (isDict(meta) && isStr(pyGet(meta, 'semantic_edge_id'))) {
        rendered_semantic_edge_ids.add(meta.semantic_edge_id as string);
        // One connector may stand for duplicate or reverse edges of the same pair.
        for (const id of _merged_edge_ids(meta)) rendered_semantic_edge_ids.add(id);
      }
      continue;
    }

    const text = pyGet(props, 'text');
    const has_text = isStr(text) && Boolean(pyStrip(text));
    const is_title = shape_id.endsWith(TITLE_SUFFIX) || (isStr(key) && key.endsWith(TITLE_SUFFIX));
    if (is_title && !has_text) {
      empty_title_ids.push(shape_id);
    } else if (shape_type === 'text' && !has_text) {
      empty_text_ids.push(shape_id);
    }
  }

  if (empty_title_ids.length) {
    const sample = empty_title_ids.slice(0, 5).join(', ');
    const msg = (
      `${_AUDIT_PREFIX} ${empty_title_ids.length} TLDraw title shape(s) `
      + `have empty props.text (sample: ${sample}). Likely group titles `
      + 'lost their label during Styling/Layout conversion.'
    );
    report.warnings.push(msg);
    logger.warning(msg);
    for (const eid of empty_title_ids) {
      report.issues.push(new AuditIssue(
        'empty_text',
        `TLDraw title shape ${eid} has empty props.text`,
        eid,
      ));
    }
  }

  if (empty_text_ids.length) {
    const sample = empty_text_ids.slice(0, 5).join(', ');
    const msg = (
      `${_AUDIT_PREFIX} ${empty_text_ids.length} TLDraw text shape(s) `
      + `have empty props.text (sample: ${sample}).`
    );
    report.warnings.push(msg);
    logger.warning(msg);
    for (const eid of empty_text_ids) {
      report.issues.push(new AuditIssue(
        'empty_text',
        `TLDraw text shape ${eid} has empty props.text`,
        eid,
      ));
    }
  }

  if (expected_edge_count > 0) {
    const [coverage, missing_edge_ids] = _edge_coverage(
      expected_edge_count,
      expected_edge_ids,
      rendered_arrow_count,
      rendered_semantic_edge_ids,
    );
    if (missing_edge_ids.length || coverage < arrow_coverage_threshold) {
      const msg = _coverage_message('TLDraw ', rendered_arrow_count, expected_edge_count, coverage, arrow_coverage_threshold, missing_edge_ids);
      report.warnings.push(msg);
      logger.warning(msg);
      report.issues.push(new AuditIssue('arrow_coverage', msg));
    }
  }

  return report;
}

// ---------------------------------------------------------------------------
// Text contrast audit (WCAG AA, warn-only).
// ---------------------------------------------------------------------------

export const _WCAG_AA_BODY = 4.5;

/** Parse '#RRGGBB' (or '#RGB' shorthand) to (r, g, b) ints. None on bad input. */
export function _hex_to_rgb(hex_str: string): [number, number, number] | null {
  if (!isStr(hex_str)) {
    return null;
  }
  let h = pyLstrip(hex_str, '#');
  if (cpLen(h) === 3) {
    h = cpChars(h).map((c) => c + c).join('');
  }
  if (cpLen(h) !== 6) {
    return null;
  }
  try {
    return [0, 2, 4].map((i) => {
      const pair = cpSlice(h, i, i + 2);
      // int(..., 16): a two-character literal can never contain a legal underscore.
      if (pair.includes('_')) throw new ValueError(`invalid literal for int() with base 16: '${pair}'`);
      return pyInt(pair, 16);
    }) as [number, number, number];
  } catch (error) {
    if (error instanceof ValueError) {
      return null;
    }
    throw error;
  }
}

/** WCAG 2.1 relative luminance formula. */
export function _relative_luminance(rgb: readonly number[]): number {
  const chan = (c: number): number => {
    const c_lin = c / 255.0;
    return c_lin <= 0.03928 ? c_lin / 12.92 : pow((c_lin + 0.055) / 1.055, 2.4);
  };
  const [r, g, b] = rgb.map(chan);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** WCAG contrast ratio between two hex colors. None if either won't parse. */
export function _contrast_ratio(hex_a: string, hex_b: string): number | null {
  const rgb_a = _hex_to_rgb(hex_a);
  const rgb_b = _hex_to_rgb(hex_b);
  if (rgb_a === null || rgb_b === null) {
    return null;
  }
  const l_a = _relative_luminance(rgb_a);
  const l_b = _relative_luminance(rgb_b);
  const lighter = pyMaxN(l_a, l_b);
  const darker = pyMinN(l_a, l_b);
  return (lighter + 0.05) / (darker + 0.05);
}

/** Warn when bound text on a shape fails WCAG AA (4.5:1) body-text contrast. */
export function _audit_text_contrast(manifest: Dict): [string[], AuditIssue[]] {
  const warnings: string[] = [];
  const issues: AuditIssue[] = [];
  const elements = pyGet(manifest, 'elements', []);
  if (!Array.isArray(elements)) {
    return [warnings, issues];
  }

  const shapes_by_id = new Map<string, Dict>();
  for (const e of elements) {
    if (isDict(e) && isStr(pyGet(e, 'id')) && ['rectangle', 'ellipse', 'diamond'].includes(pyGet(e, 'type') as string)) {
      shapes_by_id.set(e.id as string, e);
    }
  }

  // (text_label, text_color, fill, ratio, text_id)
  const failures: [string, string, string, number, unknown][] = [];
  for (const elem of elements) {
    if (!isDict(elem) || pyGet(elem, 'type') !== 'text') {
      continue;
    }
    const container_id = pyGet(elem, 'containerId');
    if (!truthy(container_id) || !shapes_by_id.has(container_id as string)) {
      continue;
    }
    const text_color = pyGet(elem, 'strokeColor');
    const fill = pyGet(shapes_by_id.get(container_id as string)!, 'backgroundColor');
    if (!isStr(text_color) || !isStr(fill) || !fill.startsWith('#')) {
      continue;
    }
    const ratio = _contrast_ratio(text_color, fill);
    if (ratio === null) {
      continue;
    }
    if (ratio < _WCAG_AA_BODY) {
      const label = pyOr(pyOr(pyGet(elem, 'text'), pyGet(elem, 'originalText')), '');
      failures.push([cpSlice(pyStr(label), 0, 32), text_color, fill, ratio, pyGet(elem, 'id')]);
    }
  }

  if (failures.length) {
    pySort(failures, (t) => t[3]);
    const sample_lines = failures.slice(0, 5)
      .map(([lbl, tc, f, r]) => `'${lbl}' text=${tc} on fill=${f} → ${pyFormatFixed(r, 2)}:1`)
      .join('; ');
    const msg = (
      `${_AUDIT_PREFIX} ${failures.length} bound-text element(s) fail `
      + `WCAG AA body-text contrast (<${pyStr(_WCAG_AA_BODY)}:1). `
      + `Worst pairs: ${sample_lines}. Likely cause: node backgroundColor `
      + 'is darker than expected — check that styling output uses '
      + 'fill_family.fill values (always light) for backgroundColor.'
    );
    warnings.push(msg);
    logger.warning(msg);

    for (const [lbl, tc, f, r, text_id] of failures) {
      issues.push(new AuditIssue(
        'contrast',
        `text='${lbl}' color=${tc} on fill=${f} → ${pyFormatFixed(r, 2)}:1`,
        text_id as string | null,
      ));
    }
  }

  return [warnings, issues];
}

/**
 * Warn when a group frame's fractional index is higher than any of its
 * semantic children — the frame would paint over the children.
 */
export function _audit_group_frame_zorder(manifest: Dict, structure: Dict): [string[], AuditIssue[]] {
  const warnings: string[] = [];
  const issues: AuditIssue[] = [];
  const id_map = id_map_from_manifest(manifest);
  if (!truthy(id_map)) {
    return [warnings, issues];
  }

  const groups = pyOr(pyGet(structure, 'groups'), []);
  if (!Array.isArray(groups) || !groups.length) {
    return [warnings, issues];
  }

  // Build excalidraw_id -> fractional index lookup.
  const index_by_eid = new Map<unknown, unknown>();
  for (const elem of _iter(pyGet(manifest, 'elements', []))) {
    if (isDict(elem) && truthy(pyGet(elem, 'id')) && truthy(pyGet(elem, 'index'))) {
      index_by_eid.set(elem.id, elem.index);
    }
  }

  for (const group of groups) {
    if (!isDict(group)) {
      continue;
    }
    const gid = pyGet(group, 'id');
    const children = pyOr(pyOr(pyGet(group, 'children'), pyGet(group, 'members')), []);
    if (!truthy(gid) || !Array.isArray(children)) {
      continue;
    }

    const frame_eid = group_frame_render_id(id_map, gid);
    const frame_idx = truthy(frame_eid) ? (index_by_eid.get(frame_eid) ?? null) : null;
    if (!truthy(frame_idx)) {
      continue;
    }

    for (const child_id of children) {
      const child_eid = isStr(child_id) ? pyGet(id_map, child_id) : null;
      const child_idx = truthy(child_eid) ? (index_by_eid.get(child_eid) ?? null) : null;
      if (!truthy(child_idx)) {
        continue;
      }
      if (pyGt(frame_idx, child_idx)) {
        const msg = (
          `${_AUDIT_PREFIX} group frame id=${pyRepr(gid)} has fractional `
          + `index=${pyRepr(frame_idx)} greater than child id=${pyRepr(child_id)} `
          + `index=${pyRepr(child_idx)}; the opaque frame will occlude the `
          + "child in the rendered PNG. Check the converter's layer sort."
        );
        warnings.push(msg);
        logger.warning(msg);
        issues.push(new AuditIssue('zorder', msg, frame_eid));
        break; // one warning per group is enough
      }
    }
  }

  return [warnings, issues];
}

export const __all__ = [
  'AuditIssue',
  'AuditReport',
  'audit_layout_instantiation',
  'audit_excalidraw_manifest',
  'audit_tldraw_manifest',
];
