// Ported from evodesign/agentic_system/verification_stage/checks/binding_consistency.py — keep in sync.
//
// Arrow ↔ shape binding consistency — id level and geometry level.
//
// For every Excalidraw arrow with `startBinding`/`endBinding`, the referenced
// shape's `boundElements` MUST list the arrow id back. Mismatch causes visual
// disconnects (arrows not following their endpoints when the shape is moved
// in Excalidraw, or rendering glitches in headless export).
//
// Also catches:
// - arrow startBinding/endBinding pointing at non-existent element ids
// - text element containerId pointing at non-existent shape
// - shape boundElements listing arrow ids that no longer exist
// - arrow endpoints that drifted away from the shape they connect
//   (``check_arrow_endpoint_geometry``)
//
// **Derived projections.** ``objective_manifest`` synthesises Excalidraw-shaped
// bindings for TLDraw snapshots, including the very ``boundElements`` back-refs
// the id-level check verifies. Verifying synthesised data is not verification, so
// both the back-ref sub-check and the geometry check stand down on a projected
// manifest and say so with an INFO finding instead of silently passing.

import { id_map_from_manifest } from '../../common/semantic_ids.ts';
import { pyGet, type PyMapping } from '../../py/dict.ts';
import { IndexError, KeyError, PyTypeError, ValueError } from '../../py/errors.ts';
import { pyFloatParse } from '../../py/number.ts';
import { pyFormatFixed, pyRepr } from '../../py/str.ts';
import { isDict, isList, isMapping, isStr, truthy } from '../../py/truthy.ts';
import { Finding, Severity } from './finding.ts';

type Dict = Record<string, any>;
type BBox = [number, number, number, number];
type Point = [number, number];

// An arrow endpoint sits on the face of its shape, so any real gap is drift.
// The tolerance absorbs binding ``gap``, rounding, and stroke width.
export const ARROW_ENDPOINT_TOLERANCE_PX = 12.0;

export const DERIVED_BINDINGS_META_KEY = 'derived_bindings';

/** Python ``float(value)``: TypeError for non-numeric types, ValueError for bad strings. */
function _float(value: unknown): number {
  if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'string') return pyFloatParse(value);
  throw new PyTypeError(`float() argument must be a string or a real number, not '${value === null ? 'NoneType' : typeof value}'`);
}

/** Python ``except (TypeError, ValueError)`` around ``float()``. */
function _isConversionError(error: unknown): boolean {
  return error instanceof PyTypeError || error instanceof ValueError || error instanceof TypeError;
}

/** True when arrow bindings in this manifest were synthesised by projection. */
export function has_derived_bindings(manifest: unknown): boolean {
  if (!isMapping(manifest)) {
    return false;
  }
  const meta = pyGet(manifest, '_meta');
  if (!isMapping(meta)) {
    return false;
  }
  return truthy(pyGet(meta, DERIVED_BINDINGS_META_KEY));
}

function _active_by_id(elements: unknown[]): Map<unknown, Dict> {
  const by_id = new Map<unknown, Dict>();
  for (const elem of elements) {
    if (isDict(elem) && truthy(pyGet(elem, 'id')) && !truthy(pyGet(elem, 'isDeleted'))) {
      by_id.set(pyGet(elem, 'id'), elem);
    }
  }
  return by_id;
}

/** Verify arrow.{start,end}Binding ↔ shape.boundElements two-way. */
export function check_arrow_shape_binding(manifest: Dict): Finding[] {
  const findings: Finding[] = [];
  if (!isDict(manifest)) {
    return findings;
  }

  const elements = pyGet(manifest, 'elements', []);
  if (!isList(elements)) {
    return findings;
  }

  // On a projected manifest the back-refs were written by the projection a
  // few microseconds ago, so the sub-check can only ever pass. Report it as
  // NOT RUN rather than letting a MAJOR-severity check fail open.
  const derived = has_derived_bindings(manifest);
  if (derived) {
    findings.push(
      new Finding({
        category: 'binding/missing_back_ref/not_run',
        severity: Severity.INFO,
        message:
          'arrow→shape back-reference check did NOT run: this manifest '
          + 'is a projection whose boundElements back-refs are derived '
          + 'from the source binding records, so the check would verify '
          + 'its own input. Native back-refs are not represented in this '
          + 'canvas format.',
      }),
    );
  }

  const by_id = _active_by_id(elements);
  const all_ids = new Set(by_id.keys());

  for (const elem of elements) {
    if (!isDict(elem)) {
      continue;
    }
    if (truthy(pyGet(elem, 'isDeleted'))) {
      continue;
    }

    const eid = pyGet(elem, 'id', '<no-id>');
    const etype = pyGet(elem, 'type');

    if (etype === 'arrow') {
      for (const side of ['startBinding', 'endBinding']) {
        const binding = pyGet(elem, side);
        if (!isDict(binding)) {
          continue;
        }
        const target_id = pyGet(binding, 'elementId');
        if (!truthy(target_id)) {
          continue;
        }

        if (!all_ids.has(target_id)) {
          findings.push(
            new Finding({
              category: 'binding/dangling_reference',
              severity: Severity.CRITICAL,
              message: `arrow ${pyRepr(eid)} ${side}.elementId=${pyRepr(target_id)} references a non-existent element.`,
              element_id: eid as string,
            }),
          );
          continue;
        }

        const target = by_id.get(target_id)!;
        const bound = pyGet(target, 'boundElements');
        const back_refs = isList(bound)
          ? new Set(bound.filter((b) => isDict(b)).map((b) => pyGet(b, 'id')))
          : new Set<unknown>();
        if (!back_refs.has(eid) && !derived) {
          findings.push(
            new Finding({
              category: 'binding/missing_back_ref',
              severity: Severity.MAJOR,
              message:
                `arrow ${pyRepr(eid)} binds to shape ${pyRepr(target_id)} via `
                + `${side}, but the shape's boundElements does not `
                + 'list this arrow id back.',
              element_id: eid as string,
            }),
          );
        }
      }
    }

    if (etype === 'text') {
      const container_id = pyGet(elem, 'containerId');
      if (truthy(container_id) && !all_ids.has(container_id)) {
        findings.push(
          new Finding({
            category: 'binding/dangling_reference',
            severity: Severity.CRITICAL,
            message: `text ${pyRepr(eid)} containerId=${pyRepr(container_id)} references a non-existent element.`,
            element_id: eid as string,
            location: { missing_container_id: container_id },
          }),
        );
      }
    }

    const bound = pyGet(elem, 'boundElements');
    if (isList(bound)) {
      for (const b of bound) {
        if (!isDict(b)) {
          continue;
        }
        const bid = pyGet(b, 'id');
        if (truthy(bid) && !all_ids.has(bid)) {
          findings.push(
            new Finding({
              category: 'binding/dangling_reference',
              severity: Severity.MAJOR,
              message: `element ${pyRepr(eid)} boundElements lists id=${pyRepr(bid)} but no element with that id exists.`,
              element_id: eid as string,
              location: {
                holder_id: eid,
                missing_bound_id: bid,
              },
            }),
          );
        }
      }
    }
  }

  return findings;
}

// ---------------------------------------------------------------------------
// Geometry-level: do the arrow's endpoints still touch the shapes it connects?
// ---------------------------------------------------------------------------

export function _number(value: unknown, default_ = 0.0): number {
  try {
    return _float(value);
  } catch (error) {
    if (_isConversionError(error)) return default_;
    throw error;
  }
}

/** ``(x, y, w, h)`` of a shape, or None when it has no drawable extent. */
export function element_bbox(elem: Dict): BBox | null {
  let x: number;
  let y: number;
  let w: number;
  let h: number;
  try {
    x = _float(_or0(pyGet(elem, 'x', 0)));
    y = _float(_or0(pyGet(elem, 'y', 0)));
    w = _float(_or0(pyGet(elem, 'width', 0)));
    h = _float(_or0(pyGet(elem, 'height', 0)));
  } catch (error) {
    if (_isConversionError(error)) return null;
    throw error;
  }
  if (w <= 0 || h <= 0) {
    return null;
  }
  return [x, y, w, h];
}

/** ``value or 0`` */
function _or0(value: unknown): unknown {
  return truthy(value) ? value : 0;
}

/**
 * First and last waypoint of an arrow in absolute canvas coordinates.
 *
 * Excalidraw stores ``points`` relative to the arrow's own ``x``/``y``.
 */
export function arrow_absolute_endpoints(arrow: Dict): [Point, Point] | null {
  const points = pyGet(arrow, 'points');
  if (!isList(points) || points.length < 2) {
    return null;
  }
  const origin_x = _number(pyGet(arrow, 'x'));
  const origin_y = _number(pyGet(arrow, 'y'));
  let first: Point;
  let last: Point;
  try {
    first = [origin_x + _float(_item(_item(points, 0), 0)), origin_y + _float(_item(_item(points, 0), 1))];
    last = [origin_x + _float(_item(_item(points, -1), 0)), origin_y + _float(_item(_item(points, -1), 1))];
  } catch (error) {
    if (_isConversionError(error) || error instanceof IndexError) return null;
    throw error;
  }
  return [first, last];
}

/** ``seq[index]`` with Python's TypeError/IndexError. */
function _item(seq: unknown, index: number): unknown {
  if (!Array.isArray(seq) && typeof seq !== 'string') {
    if (isDict(seq)) {
      // dict[int] -> KeyError in Python (not caught there either).
      throw new KeyError(String(index));
    }
    throw new PyTypeError('object is not subscriptable');
  }
  const length = Array.isArray(seq) ? seq.length : [...seq].length;
  const at = index < 0 ? length + index : index;
  if (at < 0 || at >= length) {
    throw new IndexError('index out of range');
  }
  return Array.isArray(seq) ? seq[at] : [...seq][at];
}

/** Distance from ``point`` to the rectangle ``bbox``; 0.0 when inside. */
export function point_gap_to_bbox(point: readonly number[], bbox: readonly number[]): number {
  const [px, py] = point;
  const [x, y, w, h] = bbox;
  const dx = Math.max(x - px, 0.0, px - (x + w));
  const dy = Math.max(y - py, 0.0, py - (y + h));
  return (dx * dx + dy * dy) ** 0.5;
}

/**
 * Best-effort ``(start_shape, end_shape)`` for one arrow.
 *
 * Two sources, in priority order:
 *
 * 1. ``startBinding`` / ``endBinding`` — authoritative when present.
 * 2. ``meta.source`` / ``meta.target`` — the semantic endpoint refs the
 *    renderer's arrow adder stamps on every arrow it emits.
 */
export function resolve_arrow_endpoint_shapes(
  arrow: Dict,
  by_id: PyMapping<Dict>,
  id_map: PyMapping<string> | null = null,
): [Dict | null, Dict | null] {
  const idm: PyMapping<string> = truthy(id_map) ? id_map! : {};
  const lookup = (key: unknown): Dict | null => pyGet(by_id, key) as Dict | null;

  const _by_binding = (side: string): Dict | null => {
    const binding = pyGet(arrow, `${side}Binding`);
    if (!isDict(binding)) {
      return null;
    }
    const target_id = pyGet(binding, 'elementId');
    if (!isStr(target_id)) {
      return null;
    }
    return lookup(target_id);
  };

  const _by_semantic_ref = (key: string): Dict | null => {
    const meta = pyGet(arrow, 'meta');
    if (!isMapping(meta)) {
      return null;
    }
    const ref = pyGet(meta, key);
    if (!isStr(ref) || !ref) {
      return null;
    }
    // Sequence messages terminate on lifelines below their headers. Keep
    // checking real endpoint geometry, using the line only when its actor
    // ownership is explicit and consistent with the semantic endpoint.
    const hasSequenceIdx = meta instanceof Map ? meta.has('sequence_idx') : Object.prototype.hasOwnProperty.call(meta, 'sequence_idx');
    if (hasSequenceIdx) {
      const lifeline = lookup(pyGet(idm, `${ref}:lifeline`, ''));
      if (truthy(lifeline) && pyGet(lifeline, 'type') === 'line'
          && pyGet(truthy(pyGet(lifeline, 'meta')) ? pyGet(lifeline, 'meta') : {}, 'actor_id') === ref) {
        return lifeline;
      }
    }
    for (const candidate of [
      lookup(ref),
      lookup(pyGet(idm, ref, '')),
      lookup(pyGet(idm, `${ref}:background`, '')),
    ]) {
      if (candidate !== null && candidate !== undefined) {
        return candidate;
      }
    }
    return null;
  };

  const start = _orNull(_by_binding('start')) ?? _by_semantic_ref('source');
  const end = _orNull(_by_binding('end')) ?? _by_semantic_ref('target');
  return [start, end];
}

/** ``x or ...`` for an Optional[dict]: an empty dict is falsy. */
function _orNull(value: Dict | null): Dict | null {
  return truthy(value) ? value : null;
}

export function _binding_gap(arrow: Dict, side: string): number {
  const binding = pyGet(arrow, `${side}Binding`);
  if (isDict(binding)) {
    return Math.max(0.0, _number(pyGet(binding, 'gap')));
  }
  return 0.0;
}

/**
 * Report arrows whose endpoints no longer touch the shapes they connect.
 *
 * ``check_arrow_shape_binding`` only compares ids, so a shape that gets moved
 * or resized leaves every reference intact while the arrow keeps pointing at
 * the shape's former location.
 */
export function check_arrow_endpoint_geometry(
  manifest: Dict,
  tolerance: number = ARROW_ENDPOINT_TOLERANCE_PX,
): Finding[] {
  const findings: Finding[] = [];
  if (!isDict(manifest)) {
    return findings;
  }

  const elements = pyGet(manifest, 'elements', []);
  if (!isList(elements)) {
    return findings;
  }

  if (has_derived_bindings(manifest)) {
    return [
      new Finding({
        category: 'binding/arrow_endpoint_drift/not_run',
        severity: Severity.INFO,
        message:
          'arrow endpoint geometry check did NOT run: this manifest is '
          + 'a projection whose arrow polyline is reconstructed from '
          + 'canvas-native anchors rather than stored waypoints, so a '
          + 'gap here would not mean the same thing.',
      }),
    ];
  }

  const by_id = _active_by_id(elements);
  const id_map = id_map_from_manifest(manifest);

  for (const elem of elements) {
    if (!isDict(elem) || truthy(pyGet(elem, 'isDeleted'))) {
      continue;
    }
    if (pyGet(elem, 'type') !== 'arrow') {
      continue;
    }
    const endpoints = arrow_absolute_endpoints(elem);
    if (endpoints === null) {
      continue;
    }
    const [start_shape, end_shape] = resolve_arrow_endpoint_shapes(elem, by_id as PyMapping<Dict>, id_map);
    const start_bbox = truthy(start_shape) ? element_bbox(start_shape!) : null;
    const end_bbox = truthy(end_shape) ? element_bbox(end_shape!) : null;
    const arrow_id = pyGet(elem, 'id', '<no-id>');

    // Re-routing needs a usable bbox at BOTH ends. When only one end can be
    // resolved the drift is real but nothing can repair it, and a permanent
    // MAJOR would stop the refiner converging and get the whole refined
    // artifact thrown away. Report it, do not make it blocking.
    const repairable = start_bbox !== null && end_bbox !== null;

    for (const [side, point, shape, bbox] of [
      ['start', endpoints[0], start_shape, start_bbox],
      ['end', endpoints[1], end_shape, end_bbox],
    ] as const) {
      if (shape === null || bbox === null) {
        continue;
      }
      const gap = point_gap_to_bbox(point, bbox) - _binding_gap(elem, side);
      if (gap <= tolerance) {
        continue;
      }
      const hint = repairable
        ? ''
        : ' Its other endpoint cannot be resolved to a shape, so the '
          + 're-route pass cannot repair this automatically.';
      findings.push(
        new Finding({
          category: 'binding/arrow_endpoint_drift',
          severity: repairable ? Severity.MAJOR : Severity.MINOR,
          message:
            `arrow ${pyRepr(arrow_id)} ${side} point `
            + `(${pyFormatFixed(point[0], 0)},${pyFormatFixed(point[1], 0)}) is ${pyFormatFixed(gap, 0)}px away from `
            + `shape ${pyRepr(pyGet(shape, 'id'))} bbox=(${pyFormatFixed(bbox[0], 0)},`
            + `${pyFormatFixed(bbox[1], 0)},${pyFormatFixed(bbox[2], 0)}x${pyFormatFixed(bbox[3], 0)}); the arrow no `
            + `longer touches the element it connects.${hint}`,
          element_id: arrow_id as string,
          location: {
            side,
            shape_id: pyGet(shape, 'id'),
            point: [point[0], point[1]],
            shape_bbox: [...bbox],
            gap,
            repairable,
          },
        }),
      );
    }
  }

  return findings;
}

export const __all__ = [
  'ARROW_ENDPOINT_TOLERANCE_PX',
  'DERIVED_BINDINGS_META_KEY',
  'arrow_absolute_endpoints',
  'check_arrow_endpoint_geometry',
  'check_arrow_shape_binding',
  'element_bbox',
  'has_derived_bindings',
  'point_gap_to_bbox',
  'resolve_arrow_endpoint_shapes',
];
