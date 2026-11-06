// Ported from evodesign/agentic_system/verification_stage/checks/objective_manifest.py — keep in sync.
//
// Canvas-neutral manifest views for objective verification checks.
//
// The objective checks were originally written for Excalidraw manifests.  TLDraw
// snapshots carry the same verification facts, but in ``document.store`` records.
// This module builds a small read-only Excalidraw-like projection so the existing
// geometry and binding checks can stay focused on their domain logic.

import { normalize_canvas_library } from '../../canvas_runtime.ts';
import { BACKGROUND_SUFFIX, LABEL_SUFFIX, TITLE_SUFFIX, companion_id } from '../../common/semantic_ids.ts';
import { pyGet, pySetdefault } from '../../py/dict.ts';
import { PyTypeError, ValueError } from '../../py/errors.ts';
import { pyFloatParse } from '../../py/number.ts';
import { pyStr } from '../../py/str.ts';
import { isDict, isList, isStr, truthy } from '../../py/truthy.ts';
import { DERIVED_BINDINGS_META_KEY } from './binding_consistency.ts';

type Dict = Record<string, any>;

/** Return the manifest shape consumed by objective geometry checks. */
export function build_objective_manifest(
  manifest: Dict,
  canvas_library = 'excalidraw',
  structure: Dict | null = null,
): Dict {
  canvas_library = normalize_canvas_library(canvas_library);
  if (canvas_library !== 'tldraw') {
    return manifest;
  }
  return _build_tldraw_objective_manifest(manifest, structure);
}

export function _build_tldraw_objective_manifest(manifest: Dict, structure: Dict | null = null): Dict {
  const store = _tldraw_store(manifest);
  if (!truthy(store)) {
    return {
      type: 'objective_view',
      elements: [],
      _meta: { id_map: {}, [DERIVED_BINDINGS_META_KEY]: true },
    };
  }

  const elements: Dict[] = [];
  const id_map: Record<string, string> = {};
  const element_by_id: Record<string, Dict> = {};

  for (const [key, record] of Object.entries(store)) {
    if (!isDict(record) || pyGet(record, 'typeName') !== 'shape') {
      continue;
    }
    const element = _project_shape_record(record, pyStr(key));
    if (element === null) {
      continue;
    }
    elements.push(element);
    element_by_id[element.id] = element;
    const semantic_id = _semantic_id_from_tldraw_shape_id(element.id);
    if (truthy(semantic_id)) {
      id_map[semantic_id!] = element.id;
    }
    const semantic_edge_id = pyGet(element, 'semanticEdgeId');
    if (isStr(semantic_edge_id) && semantic_edge_id) {
      id_map[semantic_edge_id] = element.id;
    }
  }

  _add_structure_group_aliases(id_map, structure, element_by_id);
  _project_arrow_bindings(Object.values(store), element_by_id);

  return {
    type: 'objective_view',
    elements,
    // The arrow bindings above — including the ``boundElements`` back-refs
    // written onto each target shape — are DERIVED from TLDraw binding
    // records, not read from the snapshot.
    _meta: { id_map, [DERIVED_BINDINGS_META_KEY]: true },
  };
}

export function _tldraw_store(manifest: Dict): Dict {
  if (!isDict(manifest)) {
    return {};
  }
  const document = pyGet(manifest, 'document');
  if (!isDict(document)) {
    return {};
  }
  const store = pyGet(document, 'store');
  return isDict(store) ? store : {};
}

export function _project_shape_record(record: Dict, fallback_id: string): Dict | null {
  const shape_id = truthy(pyGet(record, 'id')) ? pyGet(record, 'id') : fallback_id;
  if (!isStr(shape_id) || !shape_id) {
    return null;
  }

  let props = pyGet(record, 'props');
  if (!isDict(props)) {
    props = {};
  }

  const shape_type = pyGet(record, 'type');
  const element: Dict = {
    id: shape_id,
    type: _project_shape_type(shape_type, props as Dict),
    x: _number(pyGet(record, 'x'), 0.0),
    y: _number(pyGet(record, 'y'), 0.0),
    width: _number(pyGet(props, 'w'), 0.0),
    height: _number(pyGet(props, 'h'), 0.0),
  };

  const text = pyGet(props, 'text');
  if (isStr(text)) {
    element.text = text;
    element.originalText = text;
  }

  if (shape_type === 'arrow') {
    const meta = pyGet(record, 'meta');
    if (isDict(meta)) {
      element._meta = { ...meta };
      const semantic_edge_id = pyGet(meta, 'semantic_edge_id');
      if (isStr(semantic_edge_id) && semantic_edge_id) {
        element.semanticEdgeId = semantic_edge_id;
      }
    }
    const start = pyGet(props, 'start');
    const end = pyGet(props, 'end');
    if (isDict(start) && isDict(end)) {
      element.points = _project_tldraw_arrow_points(props as Dict);
      element.tldrawKind = pyGet(props, 'kind');
    }
  }

  return element;
}

export function _project_tldraw_arrow_points(props: Dict): number[][] {
  const start = pyGet(props, 'start');
  const end = pyGet(props, 'end');
  if (!isDict(start) || !isDict(end)) {
    return [];
  }

  const sx = _number(pyGet(start, 'x'), 0.0);
  const sy = _number(pyGet(start, 'y'), 0.0);
  const ex = _number(pyGet(end, 'x'), 0.0);
  const ey = _number(pyGet(end, 'y'), 0.0);
  const kind = pyGet(props, 'kind');

  if (kind === 'elbow') {
    const midpoint = _clamp(_number(pyGet(props, 'elbowMidPoint'), 0.5), 0.0, 1.0);
    if (Math.abs(ex - sx) >= Math.abs(ey - sy)) {
      const mx = sx + ((ex - sx) * midpoint);
      return [[sx, sy], [mx, sy], [mx, ey], [ex, ey]];
    }
    const my = sy + ((ey - sy) * midpoint);
    return [[sx, sy], [sx, my], [ex, my], [ex, ey]];
  }

  if (kind === 'curved') {
    let mx = (sx + ex) / 2.0;
    let my = (sy + ey) / 2.0;
    const bend = _number(pyGet(props, 'bend'), 0.0);
    if (truthy(bend)) {
      const dx = ex - sx;
      const dy = ey - sy;
      const length = Math.max((dx * dx + dy * dy) ** 0.5, 1.0);
      mx += (-dy / length) * bend;
      my += (dx / length) * bend;
    }
    return [[sx, sy], [mx, my], [ex, ey]];
  }

  return [[sx, sy], [ex, ey]];
}

export function _clamp(value: number, low: number, high: number): number {
  return Math.max(low, Math.min(high, value));
}

export function _project_shape_type(shape_type: unknown, props: Dict): string {
  if (shape_type === 'arrow') {
    return 'arrow';
  }
  if (shape_type === 'image') {
    return 'image';
  }
  if (shape_type === 'text') {
    return 'text';
  }
  if (shape_type === 'frame' || shape_type === 'group') {
    return 'rectangle';
  }
  if (shape_type === 'geo') {
    const geo = pyGet(props, 'geo');
    if (geo === 'ellipse' || geo === 'diamond' || geo === 'triangle' || geo === 'rectangle') {
      return pyStr(geo);
    }
  }
  return 'rectangle';
}

export function _semantic_id_from_tldraw_shape_id(shape_id: string): string | null {
  if (shape_id.startsWith('shape:')) {
    const semantic_id = shape_id.slice('shape:'.length);
    return semantic_id || null;
  }
  return null;
}

export function _add_structure_group_aliases(
  id_map: Record<string, string>,
  structure: Dict | null,
  element_by_id: Record<string, Dict>,
): null {
  if (!isDict(structure)) {
    return null;
  }
  for (const group of (truthy(pyGet(structure, 'groups')) ? pyGet(structure, 'groups') : []) as unknown[]) {
    if (!isDict(group)) {
      continue;
    }
    const group_id = pyGet(group, 'id');
    if (!isStr(group_id) || !group_id) {
      continue;
    }
    for (const suffix of [BACKGROUND_SUFFIX, TITLE_SUFFIX, LABEL_SUFFIX]) {
      const semantic_id = companion_id(group_id, suffix);
      const shape_id = `shape:${semantic_id}`;
      if (Object.prototype.hasOwnProperty.call(element_by_id, shape_id)) {
        pySetdefault(id_map, semantic_id, shape_id);
      }
    }
  }
  return null;
}

export function _project_arrow_bindings(records: Iterable<unknown>, element_by_id: Record<string, Dict>): null {
  for (const record of records) {
    if (!isDict(record)) {
      continue;
    }
    if (pyGet(record, 'typeName') !== 'binding' || pyGet(record, 'type') !== 'arrow') {
      continue;
    }

    const arrow_id = pyGet(record, 'fromId');
    const target_id = pyGet(record, 'toId');
    if (!isStr(arrow_id) || !isStr(target_id)) {
      continue;
    }

    const arrow = pyGet(element_by_id, arrow_id) as Dict | null;
    if (arrow === null || pyGet(arrow, 'type') !== 'arrow') {
      continue;
    }

    const props = pyGet(record, 'props');
    const terminal = isDict(props) ? pyGet(props, 'terminal') : null;
    const binding_key = terminal === 'start'
      ? 'startBinding'
      : terminal === 'end'
        ? 'endBinding'
        : null;
    if (binding_key === null) {
      continue;
    }

    arrow[binding_key] = { elementId: target_id };
    const target = pyGet(element_by_id, target_id) as Dict | null;
    if (target === null) {
      continue;
    }
    let bound = pyGet(target, 'boundElements');
    if (!isList(bound)) {
      bound = [];
      target.boundElements = bound;
    }
    const already_bound = (bound as unknown[]).some(
      (item) => isDict(item) && pyGet(item, 'id') === arrow_id,
    );
    if (!already_bound) {
      (bound as unknown[]).push({ id: arrow_id, type: 'arrow' });
    }
  }
  return null;
}

export function _number(value: unknown, default_: number): number {
  try {
    if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'string') return pyFloatParse(value);
    throw new PyTypeError('float() argument must be a string or a real number');
  } catch (error) {
    if (error instanceof PyTypeError || error instanceof ValueError || error instanceof TypeError) return default_;
    throw error;
  }
}

export const __all__ = ['build_objective_manifest'];
