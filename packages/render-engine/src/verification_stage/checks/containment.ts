// Ported from evodesign/agentic_system/verification_stage/checks/containment.py — keep in sync.
//
// Containment checks: group bbox vs children, swimlane lane membership.
//
// 1. **group_bbox_contains_children** — for every child of a group, the
//    shape's full bounding box must lie within that group's bbox (with a
//    small tolerance). When ``structure.groups[].members`` is available,
//    explicit membership is used; otherwise falls back to centroid-based
//    geometric inference (smallest-containing group wins when groups nest).
//
// 2. **swimlane_lane_membership** — for ``chart_type == "swimlane"``, every
//    non-lane shape MUST have its centroid land inside exactly one lane,
//    and its full y-band must fit within that lane's y-band.

import {
  group_frame_render_id,
  id_map_from_manifest,
  resolve_group_id_map,
  reverse_base_id_map,
} from '../../common/semantic_ids.ts';
import { pyGet, pyGetItem, pySetdefault } from '../../py/dict.ts';
import { PyTypeError, ValueError } from '../../py/errors.ts';
import { pyFloatParse } from '../../py/number.ts';
import { pySort } from '../../py/sort.ts';
import { pyFormatFixed, pyRepr } from '../../py/str.ts';
import { isDict, isList, isStr, truthy } from '../../py/truthy.ts';
import { Finding, Severity } from './finding.ts';

type Dict = Record<string, any>;

export const _BBOX_TOLERANCE_PX = 4; // padding allowance for full-bbox containment
export const _CENTROID_TOLERANCE_PX = 2;

export type _BBox = [number, number, number, number]; // (x, y, w, h)

export interface _Group {
  id: string;
  bg_id: string;
  bg_bbox: _BBox;
  title_id: string | null;
}

/** ``@dataclass(frozen=True)`` */
export class _MembershipContext {
  readonly elements: unknown[];
  readonly groups: _Group[];
  readonly groups_by_id: Record<string, _Group>;
  readonly background_ids: Set<unknown>;
  readonly title_ids: Set<unknown>;
  readonly reverse_id_map: Record<string, string>;
  readonly explicit_member_to_group: Record<string, string>;

  constructor(init: {
    elements: unknown[];
    groups: _Group[];
    groups_by_id: Record<string, _Group>;
    background_ids: Set<unknown>;
    title_ids: Set<unknown>;
    reverse_id_map: Record<string, string>;
    explicit_member_to_group: Record<string, string>;
  }) {
    this.elements = init.elements;
    this.groups = init.groups;
    this.groups_by_id = init.groups_by_id;
    this.background_ids = init.background_ids;
    this.title_ids = init.title_ids;
    this.reverse_id_map = init.reverse_id_map;
    this.explicit_member_to_group = init.explicit_member_to_group;
    Object.freeze(this);
  }

  get use_explicit(): boolean {
    return truthy(this.explicit_member_to_group);
  }
}

/** Python ``float(value)``. */
function _float(value: unknown): number {
  if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'string') return pyFloatParse(value);
  throw new PyTypeError('float() argument must be a string or a real number');
}

function _or0(value: unknown): unknown {
  return truthy(value) ? value : 0;
}

export function _get_bbox(elem: Dict): _BBox | null {
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
    if (error instanceof PyTypeError || error instanceof ValueError || error instanceof TypeError) return null;
    throw error;
  }
  if (w <= 0 || h <= 0) {
    return null;
  }
  return [x, y, w, h];
}

export function _centroid(bbox: readonly number[]): [number, number] {
  const [x, y, w, h] = bbox;
  return [x + w / 2.0, y + h / 2.0];
}

export function _bbox_area(bbox: readonly number[]): number {
  const [, , w, h] = bbox;
  return w * h;
}

export function _point_in_bbox(point: readonly number[], bbox: readonly number[], tol: number = _CENTROID_TOLERANCE_PX): boolean {
  const [px, py] = point;
  const [x, y, w, h] = bbox;
  return (x - tol) <= px && px <= (x + w + tol) && (y - tol) <= py && py <= (y + h + tol);
}

export function _bbox_contains(parent: readonly number[], child: readonly number[], tol: number = _BBOX_TOLERANCE_PX): boolean {
  const [px, py, pw, ph] = parent;
  const [cx, cy, cw, ch] = child;
  return (
    cx >= px - tol
    && cy >= py - tol
    && cx + cw <= px + pw + tol
    && cy + ch <= py + ph + tol
  );
}

/** True iff child's full y-band is inside parent's y-band. */
export function _y_band_contains(parent: readonly number[], child: readonly number[], tol: number = _BBOX_TOLERANCE_PX): boolean {
  const [, py, , ph] = parent;
  const [, cy, , ch] = child;
  return cy >= py - tol && cy + ch <= py + ph + tol;
}

// ---------------------------------------------------------------------------
// Group / lane registry — derived from _meta.id_map naming convention.
// ---------------------------------------------------------------------------

/**
 * Walk ``_meta.id_map`` and return ``[groups, background_ids, title_ids]``.
 * ``groups`` is sorted by bg area (smallest first).
 */
export function _collect_groups(manifest: Dict, structure: Dict | null = null): [_Group[], Set<unknown>, Set<unknown>] {
  const elements = pyGet(manifest, 'elements', []);
  if (!isList(elements)) {
    return [[], new Set(), new Set()];
  }

  const by_id = new Map<unknown, Dict>();
  for (const elem of elements) {
    if (isDict(elem) && truthy(pyGet(elem, 'id')) && !truthy(pyGet(elem, 'isDeleted'))) {
      by_id.set(pyGet(elem, 'id'), elem);
    }
  }

  const idm = id_map_from_manifest(manifest);
  const group_id_map = resolve_group_id_map(idm);
  const bg_for: Record<string, string> = Object.assign(Object.create(null), group_id_map.background_by_group);
  const title_for = group_id_map.title_by_group;

  // When Structure is available, a semantic group may map directly to the
  // frame element instead of only using the "<group>:background" companion
  // id convention.
  if (isDict(structure)) {
    for (const group of _orList(pyGet(structure, 'groups'))) {
      if (!isDict(group)) {
        continue;
      }
      const group_id = pyGet(group, 'id');
      const frame_id = group_frame_render_id(idm, group_id);
      if (isStr(group_id) && truthy(frame_id)) {
        pySetdefault(bg_for, group_id, frame_id!);
      }
    }
  }

  const groups: _Group[] = [];
  for (const [group_id, bg_id] of Object.entries(bg_for)) {
    const bg_elem = by_id.get(bg_id);
    if (!truthy(bg_elem)) {
      continue;
    }
    const bg_bbox = _get_bbox(bg_elem!);
    if (bg_bbox === null) {
      continue;
    }
    groups.push({
      id: group_id,
      bg_id,
      bg_bbox,
      title_id: pyGet(title_for, group_id) as string | null,
    });
  }

  // Smallest first — the first match in `_assign_centroid_to_group` is
  // therefore the smallest containing group.
  pySort(groups, (g) => _bbox_area(g.bg_bbox));

  return [groups, new Set(Object.values(bg_for)), new Set(Object.values(title_for))];
}

/** ``value or []`` */
function _orList(value: unknown): unknown[] {
  return truthy(value) ? (value as unknown[]) : [];
}

/** Pick the smallest group whose bg contains the centroid (or None). */
export function _assign_centroid_to_group(centroid: readonly number[], groups: _Group[]): _Group | null {
  for (const g of groups) { // already sorted smallest-first
    if (_point_in_bbox(centroid, g.bg_bbox)) {
      return g;
    }
  }
  return null;
}

/**
 * Build element_id → group_id mapping from structure.groups[].members.
 *
 * Returns an empty dict when the structure lacks explicit membership data.
 */
export function build_explicit_member_map(structure: Dict | null): Record<string, string> {
  if (!isDict(structure)) {
    return {};
  }

  const groups = pyGet(structure, 'groups');
  if (!isList(groups)) {
    return {};
  }

  const member_to_group: Record<string, string> = Object.create(null);
  for (const group of groups) {
    if (!isDict(group)) {
      continue;
    }
    const gid = pyGet(group, 'id');
    const members = pyGet(group, 'members');
    if (!truthy(gid) || !isList(members)) {
      continue;
    }
    for (const mid of members) {
      if (isStr(mid)) {
        member_to_group[mid] = gid as string;
      }
    }
  }
  return member_to_group;
}

/**
 * Should this element be tested against a group bbox?
 *
 * Excluded: arrows, group backgrounds, registered group titles, bound text
 * labels, lines / freedraw.
 */
export function _is_candidate_child(elem: Dict, background_ids: Set<unknown>, title_ids: Set<unknown>): boolean {
  const eid = pyGet(elem, 'id');
  if (!truthy(eid)) {
    return false;
  }
  if (truthy(pyGet(elem, 'isDeleted'))) {
    return false;
  }
  const etype = pyGet(elem, 'type');
  if (etype === 'arrow' || etype === 'freedraw' || etype === 'line') {
    return false;
  }
  if (background_ids.has(eid) || title_ids.has(eid)) {
    return false;
  }
  if (etype === 'text' && truthy(pyGet(elem, 'containerId'))) {
    return false;
  }
  return true;
}

export function _membership_context(manifest: Dict, structure: Dict | null): _MembershipContext | null {
  const [groups, background_ids, title_ids] = _collect_groups(manifest, structure);
  if (!groups.length) {
    return null;
  }

  const elements = pyGet(manifest, 'elements', []);
  if (!isList(elements)) {
    return null;
  }

  const idm = id_map_from_manifest(manifest);
  const reverse_ids = reverse_base_id_map(idm);
  const explicit_members = build_explicit_member_map(structure);
  const groups_by_id: Record<string, _Group> = Object.create(null);
  for (const group of groups) groups_by_id[group.id] = group;
  // Concept-map sections are created from branch ownership, not from the
  // optional structure.groups list. Geometry-based inference would silently
  // reassign a node after a refiner moves its original frame away.
  const nodes = _orList(pyGet(truthy(structure) ? structure : {}, 'nodes'));
  const branch_groups = new Map<unknown, unknown>();
  for (const node of nodes) {
    if (isDict(node)
        && pyGet(node, 'class') === 'branch_anchor'
        && truthy(pyGet(node, 'branch_id'))
        && Object.prototype.hasOwnProperty.call(groups_by_id, pyGet(node, 'id') as string)) {
      branch_groups.set(pyGet(node, 'branch_id'), pyGetItem(node, 'id'));
    }
  }
  for (const node of nodes) {
    if (!isDict(node)) {
      continue;
    }
    const branch = pyGet(node, 'branch_id');
    const group_id = branch_groups.has(branch) ? branch_groups.get(branch) : null;
    if (truthy(group_id) && truthy(pyGet(node, 'id'))) {
      pySetdefault(explicit_members, pyGetItem(node, 'id') as string, group_id as string);
    }
  }
  const frame_groups = new Map<unknown, string>();
  for (const group of groups) frame_groups.set(group.bg_id, group.id);
  for (const element of elements) {
    if (!isDict(element) || !frame_groups.has(pyGet(element, 'id'))) {
      continue;
    }
    const meta = truthy(pyGet(element, 'meta')) ? pyGet(element, 'meta') : {};
    for (const member_id of pyGet(meta, 'memberIds', []) as unknown[]) {
      pySetdefault(
        explicit_members,
        pyGet(reverse_ids, member_id, member_id) as string,
        frame_groups.get(pyGetItem(element, 'id'))!,
      );
    }
  }
  return new _MembershipContext({
    elements,
    groups,
    groups_by_id,
    background_ids,
    title_ids,
    reverse_id_map: reverse_ids,
    explicit_member_to_group: explicit_members,
  });
}

export function* _iter_candidate_children(context: _MembershipContext): Generator<[Dict, _BBox]> {
  for (const elem of context.elements) {
    if (!isDict(elem)) {
      continue;
    }
    if (!_is_candidate_child(elem, context.background_ids, context.title_ids)) {
      continue;
    }
    const elem_bbox = _get_bbox(elem);
    if (elem_bbox === null) {
      continue;
    }
    yield [elem, elem_bbox];
  }
}

export function _resolve_parent_group(elem: Dict, elem_bbox: readonly number[], context: _MembershipContext): _Group | null {
  if (context.use_explicit) {
    const eid = pyGet(elem, 'id');
    const semantic_id = pyGet(context.reverse_id_map, eid, eid);
    const group_id = pyGet(context.explicit_member_to_group, semantic_id);
    return truthy(group_id) ? (pyGet(context.groups_by_id, group_id) as _Group | null) : null;
  }
  return _assign_centroid_to_group(_centroid(elem_bbox), context.groups);
}

// ---------------------------------------------------------------------------
// Public checks
// ---------------------------------------------------------------------------

/** Generic group containment — used for every chart_type EXCEPT swimlane. */
export function check_group_bbox_contains_children(manifest: Dict, structure: Dict | null = null): Finding[] {
  const findings: Finding[] = [];
  if (!isDict(manifest)) {
    return findings;
  }

  const chart_type = isDict(structure) ? pyGet(structure, 'chart_type') : null;
  if (chart_type === 'swimlane') {
    // Delegate to the specialised check to avoid double-counting.
    return findings;
  }

  const context = _membership_context(manifest, structure);
  if (context === null) {
    return findings;
  }

  for (const [elem, elem_bbox] of _iter_candidate_children(context)) {
    const parent = _resolve_parent_group(elem, elem_bbox, context);

    if (parent === null) {
      // Floating element outside all groups — legal for many chart types.
      continue;
    }

    if (!_bbox_contains(parent.bg_bbox, elem_bbox)) {
      const [px, py, pw, ph] = parent.bg_bbox;
      const [cx, cy, cw, ch] = elem_bbox;
      findings.push(
        new Finding({
          category: 'containment/group_bbox',
          severity: Severity.MAJOR,
          message:
            `child ${pyRepr(pyGet(elem, 'id'))} bbox=(${pyFormatFixed(cx, 0)},${pyFormatFixed(cy, 0)},`
            + `${pyFormatFixed(cw, 0)}x${pyFormatFixed(ch, 0)}) escapes group ${pyRepr(parent.id)} `
            + `bbox=(${pyFormatFixed(px, 0)},${pyFormatFixed(py, 0)},${pyFormatFixed(pw, 0)}x${pyFormatFixed(ph, 0)}).`,
          element_id: pyGet(elem, 'id') as string,
          location: {
            child: { x: cx, y: cy, w: cw, h: ch },
            group: { x: px, y: py, w: pw, h: ph },
            group_id: parent.id,
          },
        }),
      );
    }
  }

  return findings;
}

/** For swimlane charts, every node MUST sit inside exactly one lane y-band. */
export function check_swimlane_lane_membership(manifest: Dict, structure: Dict | null = null): Finding[] {
  const findings: Finding[] = [];
  if (!isDict(manifest)) {
    return findings;
  }

  const chart_type = isDict(structure) ? pyGet(structure, 'chart_type') : null;
  if (chart_type !== 'swimlane') {
    return findings;
  }

  const context = _membership_context(manifest, structure);
  if (context === null) {
    return findings;
  }

  for (const [elem, elem_bbox] of _iter_candidate_children(context)) {
    const eid = pyGet(elem, 'id');
    const [cx, cy] = _centroid(elem_bbox);

    const lane = _resolve_parent_group(elem, elem_bbox, context);

    if (lane === null) {
      findings.push(
        new Finding({
          category: 'containment/swimlane_lane',
          severity: Severity.MAJOR,
          message:
            `node ${pyRepr(eid)} centroid=(${pyFormatFixed(cx, 0)},${pyFormatFixed(cy, 0)}) is not `
            + 'inside any lane — node has escaped the lane system.',
          element_id: eid as string,
          location: {
            node: { x: elem_bbox[0], y: elem_bbox[1], w: elem_bbox[2], h: elem_bbox[3] },
            centroid: { x: cx, y: cy },
          },
        }),
      );
      continue;
    }

    if (!_y_band_contains(lane.bg_bbox, elem_bbox)) {
      const [lx, ly, lw, lh] = lane.bg_bbox;
      const [nx, ny, nw, nh] = elem_bbox;
      findings.push(
        new Finding({
          category: 'containment/swimlane_lane',
          severity: Severity.MAJOR,
          message:
            `node ${pyRepr(eid)} y-band=[${pyFormatFixed(ny, 0)},${pyFormatFixed(ny + nh, 0)}] crosses `
            + `lane ${pyRepr(lane.id)} band [${pyFormatFixed(ly, 0)},${pyFormatFixed(ly + lh, 0)}].`,
          element_id: eid as string,
          location: {
            node: { x: nx, y: ny, w: nw, h: nh },
            lane: { x: lx, y: ly, w: lw, h: lh },
            lane_id: lane.id,
          },
        }),
      );
    }
  }

  return findings;
}

export const __all__ = [
  'check_group_bbox_contains_children',
  'check_swimlane_lane_membership',
  'build_explicit_member_map',
];
