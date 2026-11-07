// Ported from evodesign/agentic_system/refinement_stage/fixers/deterministic.py — keep in sync.
//
// Deterministic fixers — verifier finding → EditOp list, no LLM involved.
//
// Each fixer is a pure function that consumes the current manifest and the
// list of Findings, and returns a List[EditOp]. The fixer NEVER mutates the
// manifest itself — that's apply_edits's job. This keeps the workflow
// auditable: every change shows up as an EditOp before being applied.
//
// Fixers are idempotent by construction: re-running a fixer on a manifest
// that already satisfies the invariant returns ``[]``.

import { CANVAS_MARGIN, CANVAS_MAX_X, CANVAS_MAX_Y } from '../../canvas_environment/constants.ts';
import { detect_group_frame_ids, repair_manifest_zorder } from '../../canvas_environment/validation.ts';
import { id_map_from_manifest } from '../../common/semantic_ids.ts';
import { pyGet } from '../../py/dict.ts';
import { KeyError, PyTypeError, RuntimeError, ValueError } from '../../py/errors.ts';
import { sha256Hex } from '../../py/hash.ts';
import { getLogger } from '../../py/logging.ts';
import { pyFloatParse, pyInt } from '../../py/number.ts';
import { cpCompare, pyMax } from '../../py/sort.ts';
import { cpChars, cpLen, cpSlice, floatRepr, pyFormatFixed, pyRepr, pyStr, pyStrip } from '../../py/str.ts';
import { isDict, isList, isMapping, isStr, pyTypeName, truthy } from '../../py/truthy.ts';
import { EditOp, type EditOpLike } from './apply_edits.ts';

type Dict = Record<string, unknown>;
type BBox = [number, number, number, number];
type RGB = [number, number, number];

/** Structural view of ``verification_stage.checks.finding.Finding``. */
export interface FindingLike {
  category: string;
  severity: string;
  message: string;
  element_id: string | null;
  location: Dict | null;
}

const logger = getLogger('evodesign.agentic_system.refinement_stage.fixers.deterministic');

function _float(value: unknown): number {
  if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'string') return pyFloatParse(value);
  throw new PyTypeError(`float() argument must be a string or a real number, not '${pyTypeName(value)}'`);
}

function _isConversionError(error: unknown): boolean {
  return error instanceof PyTypeError || error instanceof ValueError || error instanceof TypeError;
}

/** ``x or default`` */
function _or<T>(value: unknown, default_: T): unknown {
  return truthy(value) ? value : default_;
}

/** ``d[key]`` with KeyError. */
function _item(mapping: Dict, key: string): unknown {
  if (!Object.prototype.hasOwnProperty.call(mapping, key)) throw new KeyError(pyRepr(key));
  return mapping[key];
}

function _edit(op: string, id: unknown, payload: Dict, rationale: string): EditOpLike {
  return new EditOp({ op, id, payload, rationale, source: 'deterministic' });
}

/** Raised when a deterministic fixer crashes instead of producing edits. */
export class DeterministicFixerError extends RuntimeError {
  readonly fixer_name: string;
  override readonly cause: unknown;

  constructor(fixer_name: string, cause: unknown) {
    super(`deterministic fixer ${pyRepr(fixer_name)} failed: ${cause instanceof Error ? cause.message : pyStr(cause)}`);
    this.fixer_name = fixer_name;
    this.cause = cause;
  }
}

export function _get_bbox(elem: Dict): BBox | null {
  let x: number;
  let y: number;
  let w: number;
  let h: number;
  try {
    x = _float(_or(pyGet(elem, 'x', 0), 0));
    y = _float(_or(pyGet(elem, 'y', 0), 0));
    w = _float(_or(pyGet(elem, 'width', 0), 0));
    h = _float(_or(pyGet(elem, 'height', 0), 0));
  } catch (error) {
    if (_isConversionError(error)) return null;
    throw error;
  }
  if (w <= 0 || h <= 0) {
    return null;
  }
  return [x, y, w, h];
}

/** ``{id: element}`` of live elements; a Map so integer-like ids keep insertion order. */
export function _by_id(manifest: Dict): Map<unknown, Dict> {
  const elements = pyGet(manifest, 'elements', []);
  const out = new Map<unknown, Dict>();
  if (!isList(elements)) {
    return out;
  }
  for (const elem of elements) {
    if (isDict(elem) && truthy(pyGet(elem, 'id')) && !truthy(pyGet(elem, 'isDeleted'))) {
      out.set(pyGet(elem, 'id'), elem);
    }
  }
  return out;
}

export function _hex_to_rgb(hex_str: unknown): RGB | null {
  if (!isStr(hex_str)) {
    return null;
  }
  let s = pyStrip(hex_str).replace(/^#+/, '');
  if (cpLen(s) === 3) {
    s = cpChars(s).map((ch) => ch + ch).join('');
  }
  if (cpLen(s) !== 6) {
    return null;
  }
  try {
    return [pyInt(cpSlice(s, 0, 2), 16), pyInt(cpSlice(s, 2, 4), 16), pyInt(cpSlice(s, 4, 6), 16)];
  } catch (error) {
    if (error instanceof ValueError) return null;
    throw error;
  }
}

/** WCAG relative luminance. */
export function _luminance(rgb: readonly number[]): number {
  const _ch = (v: number): number => {
    const c = v / 255.0;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  const [r, g, b] = rgb;
  return 0.2126 * _ch(r) + 0.7152 * _ch(g) + 0.0722 * _ch(b);
}

/** WCAG contrast ratio between two colors. Range ``[1.0, 21.0]``. */
export function _contrast_ratio(a: readonly number[], b: readonly number[]): number {
  const lum_a = _luminance(a);
  const lum_b = _luminance(b);
  const lighter = lum_b > lum_a ? lum_b : lum_a;
  const darker = lum_b < lum_a ? lum_b : lum_a;
  return (lighter + 0.05) / (darker + 0.05);
}

export function _findings_by_category(findings: FindingLike[], category_prefix: string): FindingLike[] {
  return findings.filter((f) => f.category.startsWith(category_prefix));
}

// ---------------------------------------------------------------------------
// Fixer 1 — clear_dangling_binding
// ---------------------------------------------------------------------------

/**
 * For each ``binding/dangling_reference`` finding, clear the bad binding.
 *
 *   - ``location.missing_bound_id``     → ``remove_bound_element`` (any type)
 *   - ``location.missing_container_id`` → ``clear_container_binding``
 *   - arrow ``start``/``end`` binding   → ``clear_arrow_binding``
 */
export function fix_dangling_bindings(
  manifest: Dict,
  findings: FindingLike[],
  _structure: Dict | null = null,
): EditOpLike[] {
  const edits: EditOpLike[] = [];
  const by_id = _by_id(manifest);
  const live_ids = new Set(by_id.keys());

  const relevant = _findings_by_category(findings, 'binding/dangling_reference');
  for (const finding of relevant) {
    const eid = finding.element_id;
    if (!truthy(eid) || !by_id.has(eid)) {
      continue;
    }
    const elem = by_id.get(eid)!;
    const loc = (isDict(finding.location) ? finding.location : {}) as Dict;

    // --- stale boundElements ref (holder can be any type, arrows included)
    const missing_bound_id = pyGet(loc, 'missing_bound_id');
    if (isStr(missing_bound_id) && missing_bound_id) {
      const holder_id = pyGet(loc, 'holder_id');
      if (isStr(holder_id) && holder_id && holder_id !== eid) {
        logger.warning(
          'Skipping dangling boundElements finding with mismatched holder: element_id=%r location.holder_id=%r',
          eid,
          holder_id,
        );
        continue;
      }
      const bound = pyGet(elem, 'boundElements');
      if (!isList(bound)) {
        continue;
      }
      if (!bound.some((item) => isDict(item) && pyGet(item, 'id') === missing_bound_id)) {
        continue;
      }
      if (live_ids.has(missing_bound_id)) {
        continue;
      }
      edits.push(_edit(
        'remove_bound_element',
        eid,
        { bound_id: missing_bound_id },
        `remove dangling boundElements ref ${pyRepr(missing_bound_id)}`,
      ));
      continue;
    }

    // --- text containerId pointing at a missing shape
    const missing_container_id = pyGet(loc, 'missing_container_id');
    const container_id = pyGet(elem, 'containerId');
    if (isStr(missing_container_id) && missing_container_id) {
      if (isStr(container_id) && container_id && !live_ids.has(container_id)) {
        edits.push(_edit(
          'clear_container_binding',
          eid,
          { container_id },
          `clear dangling text containerId=${pyRepr(container_id)}`,
        ));
      }
      continue;
    }

    // --- arrow side binding pointing at a missing shape
    if (pyGet(elem, 'type') === 'arrow') {
      for (const side of ['start', 'end']) {
        const binding = pyGet(elem, `${side}Binding`);
        if (!isDict(binding)) {
          continue;
        }
        const target = pyGet(binding, 'elementId');
        if (truthy(target) && !live_ids.has(target)) {
          edits.push(_edit(
            'clear_arrow_binding',
            eid,
            { side },
            `${side}Binding.elementId=${pyRepr(target)} does not exist`,
          ));
        }
      }
      continue;
    }

    // --- fallback for findings without location payload
    if (
      pyGet(elem, 'type') === 'text'
      && isStr(container_id)
      && container_id
      && !live_ids.has(container_id)
    ) {
      edits.push(_edit(
        'clear_container_binding',
        eid,
        { container_id },
        `clear dangling text containerId=${pyRepr(container_id)}`,
      ));
    }
  }

  return edits;
}

// ---------------------------------------------------------------------------
// Fixer 2 — repair_back_refs
// ---------------------------------------------------------------------------

/** Append missing arrow→shape back-refs in ``boundElements``. */
export function fix_missing_back_refs(
  manifest: Dict,
  findings: FindingLike[],
  _structure: Dict | null = null,
): EditOpLike[] {
  const edits: EditOpLike[] = [];
  const by_id = _by_id(manifest);
  const elements = pyGet(manifest, 'elements', []);
  if (!isList(elements)) {
    return edits;
  }

  if (!_findings_by_category(findings, 'binding/missing_back_ref').length) {
    return edits;
  }

  for (const elem of elements) {
    if (!isDict(elem) || pyGet(elem, 'type') !== 'arrow') {
      continue;
    }
    const arrow_id = pyGet(elem, 'id');
    if (!truthy(arrow_id)) {
      continue;
    }
    for (const side of ['start', 'end']) {
      const binding = pyGet(elem, `${side}Binding`);
      if (!isDict(binding)) {
        continue;
      }
      const target_id = pyGet(binding, 'elementId');
      if (!truthy(target_id) || !by_id.has(target_id)) {
        continue;
      }
      const target = by_id.get(target_id)!;
      const bound = pyGet(target, 'boundElements');
      const existing = isList(bound)
        ? new Set(bound.filter((b) => isDict(b)).map((b) => pyGet(b, 'id')))
        : new Set<unknown>();
      if (!existing.has(arrow_id)) {
        edits.push(_edit(
          'append_bound_element',
          target_id,
          { bound_id: arrow_id, type: 'arrow' },
          `add missing back-ref for arrow ${pyStr(arrow_id)} via ${side}Binding`,
        ));
      }
    }
  }

  return edits;
}

// ---------------------------------------------------------------------------
// Fixer 3 — snap_to_lane_centerline
// ---------------------------------------------------------------------------

/** For nodes whose y-band crosses or escapes their lane, snap to centerline. */
export function fix_swimlane_lane_membership(
  manifest: Dict,
  findings: FindingLike[],
  _structure: Dict | null = null,
): EditOpLike[] {
  const edits: EditOpLike[] = [];
  const by_id = _by_id(manifest);

  const relevant = _findings_by_category(findings, 'containment/swimlane_lane');
  for (const finding of relevant) {
    const eid = finding.element_id;
    if (!truthy(eid) || !by_id.has(eid)) {
      continue;
    }
    const loc = _or(finding.location, {}) as Dict;
    const lane = pyGet(loc, 'lane');
    if (!isDict(lane)) {
      continue;
    }
    const node = _or(pyGet(loc, 'node'), {}) as Dict;
    let lane_y: number;
    let lane_h: number;
    let node_h: number;
    try {
      lane_y = _float(pyGet(lane, 'y', 0));
      lane_h = _float(pyGet(lane, 'h', 0));
      node_h = _float(pyGet(node, 'h', 0));
    } catch (error) {
      if (_isConversionError(error)) continue;
      throw error;
    }
    if (lane_h <= 0 || node_h <= 0) {
      continue;
    }

    // Centerline placement; preserve x.
    const target_y = lane_y + lane_h / 2 - node_h / 2;
    const elem = by_id.get(eid)!;
    edits.push(_edit(
      'set_position',
      eid,
      { x: _float(pyGet(elem, 'x', 0)), y: target_y },
      `snap to lane '${pyStr(pyGet(loc, 'lane_id', '?'))}' centerline y=${pyFormatFixed(target_y, 0)}`,
    ));
  }

  return edits;
}

// ---------------------------------------------------------------------------
// Fixer 4 — shrink_to_group_bbox
// ---------------------------------------------------------------------------

/** Move/shrink a child whose bbox escapes its group bg. */
export function fix_group_bbox_escape(
  manifest: Dict,
  findings: FindingLike[],
  _structure: Dict | null = null,
): EditOpLike[] {
  const edits: EditOpLike[] = [];
  const by_id = _by_id(manifest);

  const relevant = _findings_by_category(findings, 'containment/group_bbox');
  for (const finding of relevant) {
    const eid = finding.element_id;
    if (!truthy(eid) || !by_id.has(eid)) {
      continue;
    }
    const loc = _or(finding.location, {}) as Dict;
    const child = pyGet(loc, 'child');
    const group = pyGet(loc, 'group');
    if (!(isDict(child) && isDict(group))) {
      continue;
    }
    let cx: number; let cy: number; let cw: number; let ch: number;
    let gx: number; let gy: number; let gw: number; let gh: number;
    try {
      cx = _float(_item(child, 'x'));
      cy = _float(_item(child, 'y'));
      cw = _float(_item(child, 'w'));
      ch = _float(_item(child, 'h'));
      gx = _float(_item(group, 'x'));
      gy = _float(_item(group, 'y'));
      gw = _float(_item(group, 'w'));
      gh = _float(_item(group, 'h'));
    } catch (error) {
      if (_isConversionError(error) || error instanceof KeyError) continue;
      throw error;
    }

    // Strategy: clamp position first; if child too large for group, also resize.
    const target_w = _min2(cw, gw - 8);
    const target_h = _min2(ch, gh - 8);
    const target_x = _max2(gx + 4, _min2(cx, gx + gw - target_w - 4));
    const target_y = _max2(gy + 4, _min2(cy, gy + gh - target_h - 4));

    if (target_x !== cx || target_y !== cy) {
      edits.push(_edit(
        'set_position',
        eid,
        { x: target_x, y: target_y },
        `clamp into group ${pyRepr(pyGet(loc, 'group_id', '?'))} bbox`,
      ));
    }
    if (target_w !== cw || target_h !== ch) {
      edits.push(_edit(
        'set_size',
        eid,
        { width: target_w, height: target_h },
        'shrink to fit group bbox',
      ));
    }
  }

  return edits;
}

/** ``min(a, b)``: first wins unless the second is strictly smaller. */
function _min2(a: number, b: number): number {
  return b < a ? b : a;
}

/** ``max(a, b)``: first wins unless the second is strictly larger. */
function _max2(a: number, b: number): number {
  return b > a ? b : a;
}

// ---------------------------------------------------------------------------
// Fixer 5 — clamp_to_canvas
// ---------------------------------------------------------------------------

export function _bbox_inside(outer: readonly number[], inner: readonly number[], tol = 4.0): boolean {
  const [ox, oy, ow, oh] = outer;
  const [ix, iy, iw, ih] = inner;
  return (
    ix >= ox - tol
    && iy >= oy - tol
    && ix + iw <= ox + ow + tol
    && iy + ih <= oy + oh + tol
  );
}

/**
 * Clamp one axis into ``[CANVAS_MARGIN, limit - CANVAS_MARGIN]``.
 *
 * Returns ``None`` when the element is wider/taller than the safe area.
 */
export function _clamp_axis(value: number, size: number, limit: number): number | null {
  if (size > limit - 2 * CANVAS_MARGIN) {
    return null;
  }
  return _max2(CANVAS_MARGIN, _min2(value, limit - size - CANVAS_MARGIN));
}

/** Pull off-canvas elements back into the safe area. */
export function fix_out_of_canvas(
  manifest: Dict,
  findings: FindingLike[],
  _structure: Dict | null = null,
): EditOpLike[] {
  const edits: EditOpLike[] = [];
  const by_id = _by_id(manifest);
  const elements = (pyGet(manifest, 'elements', []) as unknown[]).filter((elem) => isDict(elem)) as Dict[];
  const frame_ids = detect_group_frame_ids(
    elements,
    true,
    id_map_from_manifest(manifest),
  );
  const moved = new Set<unknown>();

  const relevant = _findings_by_category(findings, 'collision/out_of_canvas');
  for (const finding of relevant) {
    const eid = finding.element_id;
    if (!truthy(eid) || !by_id.has(eid) || moved.has(eid)) {
      continue;
    }
    const elem = by_id.get(eid)!;
    if (pyGet(elem, 'type') === 'arrow') {
      continue;
    }
    const bbox = _get_bbox(elem);
    if (bbox === null) {
      continue;
    }
    const [x, y, w, h] = bbox;
    const clamped_x = _clamp_axis(x, w, CANVAS_MAX_X);
    const clamped_y = _clamp_axis(y, h, CANVAS_MAX_Y);
    const new_x = clamped_x === null ? x : clamped_x;
    const new_y = clamped_y === null ? y : clamped_y;
    if (new_x === x && new_y === y) {
      if (clamped_x === null || clamped_y === null) {
        logger.debug('out_of_canvas: element %r (%.0fx%.0f) cannot fit the safe area; leaving it in place', eid, w, h);
      }
      continue;
    }

    if (frame_ids.has(eid!)) {
      if (clamped_x === null || clamped_y === null) {
        logger.debug('out_of_canvas: frame %r cannot fit the safe area; refusing to drag its members', eid);
        continue;
      }
      const members = elements.filter((child) => (
        truthy(pyGet(child, 'id'))
        && pyGet(child, 'id') !== eid
        && !truthy(pyGet(child, 'isDeleted'))
        && pyGet(child, 'type') !== 'arrow'
        && _get_bbox(child) !== null
        && _bbox_inside(bbox, _get_bbox(child)!)
      ));
      const dx = new_x - x;
      const dy = new_y - y;
      edits.push(_edit(
        'set_position',
        eid,
        { x: new_x, y: new_y },
        `clamp container into canvas safe area (+${members.length} member(s) moved by the same delta)`,
      ));
      moved.add(eid);
      for (const child of members) {
        const child_id = child.id;
        if (moved.has(child_id)) {
          continue;
        }
        const child_bbox = _get_bbox(child);
        if (child_bbox === null) {
          continue;
        }
        edits.push(_edit(
          'set_position',
          child_id,
          { x: child_bbox[0] + dx, y: child_bbox[1] + dy },
          `follow container ${pyRepr(eid)} clamp (dx=${pyFormatFixed(dx, 0)}, dy=${pyFormatFixed(dy, 0)})`,
        ));
        moved.add(child_id);
      }
      continue;
    }

    edits.push(_edit(
      'set_position',
      eid,
      { x: new_x, y: new_y },
      'clamp into canvas safe area',
    ));
    moved.add(eid);
  }
  return edits;
}

// ---------------------------------------------------------------------------
// Fixer 6 — fix_group_frame_zorder
// ---------------------------------------------------------------------------

/** Re-assign indices so group bg paints below its children. */
export function fix_group_frame_zorder(
  manifest: Dict,
  findings: FindingLike[],
  _structure: Dict | null = null,
): EditOpLike[] {
  const edits: EditOpLike[] = [];
  const zorder_findings = findings.filter((f) => f.category === 'render_validation/audit/zorder' && truthy(f.element_id));
  if (!zorder_findings.length) {
    return edits;
  }

  const by_id = _by_id(manifest);
  if (!zorder_findings.some((f) => by_id.has(f.element_id))) {
    return edits;
  }

  const repaired = repair_manifest_zorder(manifest, 'excalidraw');
  const repaired_by_id = _by_id(repaired);
  const reason = cpSlice(zorder_findings[0].message, 0, 80);

  for (const [eid, elem] of by_id) {
    const target = repaired_by_id.get(eid);
    if (!truthy(target)) {
      continue;
    }
    const target_index = pyGet(target!, 'index');
    if (!isStr(target_index) || !target_index) {
      continue;
    }
    if (pyGet(elem, 'index') !== target_index) {
      edits.push(_edit(
        'set_index',
        eid,
        { index: target_index },
        `repair manifest z-order: ${reason}`,
      ));
    }
  }

  return edits;
}

// ---------------------------------------------------------------------------
// Fixer 7 — fix_low_contrast
// ---------------------------------------------------------------------------

export const _DARK = '#1e1e1e';
export const _LIGHT = '#ffffff';
export const _MIN_CONTRAST_RATIO = 4.5; // WCAG AA for normal-size text

/** Return ``(hex_color, ratio)`` — the more readable of _DARK / _LIGHT. */
export function _best_text_color(bg_rgb: readonly number[]): [string, number] | null {
  const scored: [number, string][] = [];
  for (const hex_color of [_DARK, _LIGHT]) {
    const rgb = _hex_to_rgb(hex_color);
    if (rgb === null) {
      continue;
    }
    scored.push([_contrast_ratio(rgb, bg_rgb), hex_color]);
  }
  if (!scored.length) {
    return null;
  }
  const [ratio, hex_color] = pyMax(scored);
  return [hex_color, ratio];
}

/** For each WCAG AA contrast failure, swap text color to dark or light. */
export function fix_low_contrast(
  manifest: Dict,
  findings: FindingLike[],
  _structure: Dict | null = null,
): EditOpLike[] {
  const edits: EditOpLike[] = [];
  const contrast_findings = findings.filter((f) => f.category === 'render_validation/audit/contrast' && truthy(f.element_id));
  if (!contrast_findings.length) {
    return edits;
  }

  const by_id = _by_id(manifest);
  for (const f of contrast_findings) {
    const elem = by_id.get(f.element_id) ?? null;
    if (!truthy(elem)) {
      continue;
    }
    const container_id = pyGet(elem!, 'containerId');
    if (!truthy(container_id)) {
      continue;
    }
    const container = by_id.get(container_id) ?? null;
    if (!truthy(container)) {
      continue;
    }
    const bg = pyGet(container!, 'backgroundColor');
    const rgb = _hex_to_rgb(bg);
    if (rgb === null) {
      continue;
    }
    const best = _best_text_color(rgb);
    if (best === null) {
      continue;
    }
    const [target, ratio] = best;

    if (pyGet(elem!, 'strokeColor') !== target) {
      edits.push(_edit(
        'set_style',
        f.element_id,
        { strokeColor: target },
        `fix contrast (ratio ${pyFormatFixed(ratio, 2)} vs background ${pyStr(bg)}): ${cpSlice(f.message, 0, 60)}`,
      ));
    }

    if (ratio >= _MIN_CONTRAST_RATIO) {
      continue;
    }

    // Mid-tone background: no text color reaches AA against it, so repaint
    // the container to the extreme that maximises contrast with `target`.
    const fallback_bg = target === _DARK ? _LIGHT : _DARK;
    if (pyGet(container!, 'backgroundColor') === fallback_bg) {
      continue;
    }
    edits.push(_edit(
      'set_style',
      container_id,
      { backgroundColor: fallback_bg },
      `background ${pyStr(bg)} caps text contrast at ${pyFormatFixed(ratio, 2)} (<`
      + `${floatRepr(_MIN_CONTRAST_RATIO)}); repaint so ${target} is readable`,
    ));
  }

  return edits;
}

// ---------------------------------------------------------------------------
// Pre-processing — fill_schema_defaults  (mutates manifest directly)
// ---------------------------------------------------------------------------

export function _stable_excalidraw_int_seed(element_id: unknown, field_name: string, position: number): number {
  const key = `${truthy(element_id) ? pyStr(element_id) : `element:${position}`}:${field_name}`;
  const digest = sha256Hex(key);
  return Number(BigInt(`0x${digest.slice(0, 16)}`) % 2_000_000_000n) + 1;
}

function _setdefault(elem: Dict, key: string, value: () => unknown): void {
  if (!Object.prototype.hasOwnProperty.call(elem, key)) elem[key] = value();
}

/**
 * Patch missing required Excalidraw fields in place. Always safe to call.
 *
 * Idempotent — ``setdefault`` only fills fields that are absent.
 */
export function patch_schema_defaults(manifest: Dict): null {
  const elements = pyGet(manifest, 'elements', []);
  if (!isList(elements)) {
    return null;
  }

  elements.forEach((elem, position) => {
    if (!isDict(elem)) {
      return;
    }
    // Python evaluates the default argument even when the key exists.
    const seed = _stable_excalidraw_int_seed(pyGet(elem, 'id'), 'seed', position);
    _setdefault(elem, 'seed', () => seed);
    _setdefault(elem, 'version', () => 1);
    const nonce = _stable_excalidraw_int_seed(pyGet(elem, 'id'), 'versionNonce', position);
    _setdefault(elem, 'versionNonce', () => nonce);
    _setdefault(elem, 'isDeleted', () => false);
    _setdefault(elem, 'groupIds', () => []);
    _setdefault(elem, 'frameId', () => null);
    _setdefault(elem, 'roundness', () => null);
    _setdefault(elem, 'locked', () => false);
    _setdefault(elem, 'link', () => null);
    _setdefault(elem, 'updated', () => 0);
  });
  return null;
}

// ---------------------------------------------------------------------------
// Fixer 8 — fix_node_overlap
// ---------------------------------------------------------------------------

/** ``a, b, c, d = (float(v) for v in seq)`` */
function _unpack4(seq: unknown): BBox {
  let items: unknown[];
  if (isList(seq)) items = seq;
  else if (isStr(seq)) items = cpChars(seq);
  else if (isMapping(seq)) items = seq instanceof Map ? [...seq.keys()] : Object.keys(seq);
  else throw new PyTypeError(`'${pyTypeName(seq)}' object is not iterable`);
  const out: number[] = [];
  for (const item of items) {
    if (out.length === 4) throw new ValueError('too many values to unpack (expected 4)');
    out.push(_float(item));
  }
  if (out.length < 4) throw new ValueError(`not enough values to unpack (expected 4, got ${out.length})`);
  return out as BBox;
}

/**
 * Resolve node overlaps using minimum translation vector (MTV).
 *
 * A per-round displacement ledger accumulates pushes, overlap is re-tested
 * against the ledger position, and each moved element emits exactly one edit.
 */
export function fix_node_overlap(
  manifest: Dict,
  findings: FindingLike[],
  _structure: Dict | null = null,
): EditOpLike[] {
  const edits: EditOpLike[] = [];
  const by_id = _by_id(manifest);
  const elements = (pyGet(manifest, 'elements', []) as unknown[]).filter((elem) => isDict(elem)) as Dict[];
  const frame_ids = detect_group_frame_ids(
    elements,
    true,
    id_map_from_manifest(manifest),
  );

  const origin = new Map<unknown, [number, number]>();
  const ledger = new Map<unknown, [number, number]>();
  const reasons = new Map<unknown, string[]>();

  const _position = (eid: unknown, fallback: [number, number]): [number, number] => {
    if (!ledger.has(eid)) {
      const elem = by_id.get(eid);
      let start_pos: [number, number];
      if (elem === undefined) {
        start_pos = fallback;
      } else {
        start_pos = [
          _float(_or(pyGet(elem, 'x', 0), 0)),
          _float(_or(pyGet(elem, 'y', 0), 0)),
        ];
      }
      origin.set(eid, start_pos);
      ledger.set(eid, start_pos);
    }
    return ledger.get(eid)!;
  };

  const relevant = _findings_by_category(findings, 'collision/node_overlap');
  for (const finding of relevant) {
    const loc = _or(finding.location, {}) as Dict;
    const bbox_a = pyGet(loc, 'a'); // [x, y, w, h]
    const bbox_b = pyGet(loc, 'b'); // [x, y, w, h]
    const other_id = pyGet(loc, 'other_id');
    const eid = finding.element_id;

    if (!(truthy(eid) && truthy(other_id) && truthy(bbox_a) && truthy(bbox_b))) {
      continue;
    }
    if (!by_id.has(eid)) {
      continue;
    }
    if (frame_ids.has(eid!) || frame_ids.has(other_id as string)) {
      continue;
    }
    let _ax: number; let _ay: number; let aw: number; let ah: number;
    let _bx: number; let _by: number; let bw: number; let bh: number;
    try {
      [_ax, _ay, aw, ah] = _unpack4(bbox_a);
      [_bx, _by, bw, bh] = _unpack4(bbox_b);
    } catch (error) {
      if (_isConversionError(error)) continue;
      throw error;
    }

    // Positions come from the ledger so earlier pushes in this same round
    // are visible to later findings (for both sides of the pair).
    const [ax, ay] = _position(eid, [_ax, _ay]);
    const [bx, by_] = _position(other_id, [_bx, _by]);

    // Compute overlap region.
    const overlap_left = _max2(ax, bx);
    const overlap_top = _max2(ay, by_);
    const overlap_right = _min2(ax + aw, bx + bw);
    const overlap_bottom = _min2(ay + ah, by_ + bh);

    if (overlap_right <= overlap_left || overlap_bottom <= overlap_top) {
      continue; // already separated by an earlier push this round
    }

    const overlap_w = overlap_right - overlap_left;
    const overlap_h = overlap_bottom - overlap_top;

    // Push along the shorter axis (minimum translation).
    const padding = 4.0;
    let axis_note: string;
    if (overlap_w < overlap_h) {
      const dx = overlap_w + padding;
      const new_x = (ax + aw / 2) < (bx + bw / 2) ? ax - dx : ax + dx;
      ledger.set(eid, [new_x, ay]);
      axis_note = `horizontal MTV ${pyFormatFixed(overlap_w, 0)}px`;
    } else {
      const dy = overlap_h + padding;
      const new_y = (ay + ah / 2) < (by_ + bh / 2) ? ay - dy : ay + dy;
      ledger.set(eid, [ax, new_y]);
      axis_note = `vertical MTV ${pyFormatFixed(overlap_h, 0)}px`;
    }
    if (!reasons.has(eid)) reasons.set(eid, []);
    reasons.get(eid)!.push(`${pyStr(other_id)} (${axis_note})`);
  }

  for (const [eid, [new_x, new_y]] of ledger) {
    const [start_x, start_y] = origin.get(eid) ?? [new_x, new_y];
    if (new_x === start_x && new_y === start_y) {
      continue;
    }
    if (!by_id.has(eid)) {
      continue;
    }
    const detail = (reasons.get(eid) ?? []).join('; ') || 'overlap';
    edits.push(_edit(
      'set_position',
      eid,
      { x: new_x, y: new_y },
      `resolve overlap with ${detail}`,
    ));
  }

  return edits;
}

/**
 * Sort ``manifest["elements"]`` so the array agrees with ``index``.
 *
 * Returns True when the order changed.
 */
export function reorder_elements_by_index(manifest: Dict): boolean {
  const elements = pyGet(manifest, 'elements');
  if (!isList(elements) || elements.length < 2) {
    return false;
  }

  const decorated: [string, number, Dict][] = [];
  for (let position = 0; position < elements.length; position += 1) {
    const elem = elements[position];
    if (!isDict(elem)) {
      return false; // malformed manifest — the validator owns this case
    }
    const index = pyGet(elem, 'index');
    if (!isStr(index) || !index) {
      return false; // partial indices: any sort order would be arbitrary
    }
    decorated.push([index, position, elem]);
  }

  const ordered = [...decorated]
    .sort((a, b) => cpCompare(a[0], b[0]) || a[1] - b[1])
    .map(([, , elem]) => elem);
  if (ordered.every((elem, i) => elem === elements[i])) {
    return false;
  }
  manifest.elements = ordered;
  return true;
}

// ---------------------------------------------------------------------------
// Aggregator — run every fixer and concatenate
// ---------------------------------------------------------------------------

type Fixer = (manifest: Dict, findings: FindingLike[], structure: Dict | null) => EditOpLike[];

export const _FIXERS: [string, Fixer][] = [
  ['dangling_bindings', fix_dangling_bindings],
  ['missing_back_refs', fix_missing_back_refs],
  ['swimlane_lane', fix_swimlane_lane_membership],
  ['group_bbox', fix_group_bbox_escape],
  ['out_of_canvas', fix_out_of_canvas],
  ['node_overlap', fix_node_overlap],
  ['group_frame_zorder', fix_group_frame_zorder],
  ['low_contrast', fix_low_contrast],
];

/**
 * Run every deterministic fixer in a fixed order; concat results.
 *
 * Note: ``patch_schema_defaults`` is NOT in this pipeline — it mutates the
 * manifest directly without EditOps.
 */
export function run_all_deterministic_fixers(
  manifest: Dict,
  findings: FindingLike[],
  structure: Dict | null = null,
): EditOpLike[] {
  const all_edits: EditOpLike[] = [];
  for (const [name, fixer] of _FIXERS) {
    let edits: EditOpLike[];
    try {
      edits = fixer(manifest, findings, structure);
    } catch (exc) {
      logger.exception('deterministic fixer %s raised', name);
      throw new DeterministicFixerError(name, exc);
    }
    all_edits.push(...edits);
  }
  return all_edits;
}

export const __all__ = [
  'DeterministicFixerError',
  'run_all_deterministic_fixers',
  'patch_schema_defaults',
  'reorder_elements_by_index',
  'fix_dangling_bindings',
  'fix_missing_back_refs',
  'fix_swimlane_lane_membership',
  'fix_group_bbox_escape',
  'fix_out_of_canvas',
  'fix_node_overlap',
  'fix_group_frame_zorder',
  'fix_low_contrast',
];
