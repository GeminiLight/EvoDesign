// Ported from evodesign/agentic_system/render_engine/excalidraw/group_alignment_normalizer.py — keep in sync.
//
// Preserve layout-stage group alignment intent after group fitting.

import { markF, pyDeepcopy } from '../../py/float_marks.ts';
import {
  BACKGROUND_SUFFIX,
  ICON_SUFFIX,
  TITLE_SUFFIX,
  companion_id,
  id_map_from_manifest,
} from '../../common/semantic_ids.ts';
import { base_id } from '../shared/normalization.ts';
import { pyGet, pyItems, type PyMapping } from '../../py/dict.ts';
import { pyIn } from '../../py/eq.ts';
import { PyTypeError, ValueError } from '../../py/errors.ts';
import { pyFloatParse, pyRound } from '../../py/number.ts';
import { pyMin, pyMax, pySorted } from '../../py/sort.ts';
import { isMapping, isStr, pyOr, truthy } from '../../py/truthy.ts';

type Dict = Record<string, unknown>;

export const _SIZE_TOL = 2.0;
export const _POSITION_TOL = 40.0;

export function _num(value: unknown, default_ = 0.0): number {
  try {
    if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'string') return pyFloatParse(value);
    throw new PyTypeError('float() argument must be a string or a real number');
  } catch (error) {
    if (error instanceof PyTypeError || error instanceof ValueError) return default_;
    throw error;
  }
}

export function _dim(data: Dict, key: string): number {
  if (key === 'width') {
    return _num(pyGet(data, 'width', pyGet(data, 'w')));
  }
  if (key === 'height') {
    return _num(pyGet(data, 'height', pyGet(data, 'h')));
  }
  return _num(pyGet(data, key));
}

export function _is_group_candidate(element_id: unknown, layout: PyMapping): boolean {
  if (
    !isStr(element_id)
    || element_id.endsWith(TITLE_SUFFIX)
    || element_id.endsWith(ICON_SUFFIX)
  ) {
    return false;
  }
  if (element_id.endsWith(BACKGROUND_SUFFIX)) {
    return true;
  }
  if (element_id.startsWith('group_') || element_id.startsWith('g_')) {
    return true;
  }
  return pyIn(companion_id(base_id(element_id), TITLE_SUFFIX), layout);
}

export function _group_layout_records(layout_instantiation: PyMapping, id_map: PyMapping): Dict[] {
  const records: Dict[] = [];
  for (const [semantic_id, data] of pyItems(layout_instantiation)) {
    if (!isStr(semantic_id) || !isMapping(data)) {
      continue;
    }
    if (!_is_group_candidate(semantic_id, layout_instantiation)) {
      continue;
    }
    const render_id = pyGet(id_map, semantic_id);
    if (!truthy(render_id)) {
      continue;
    }
    const w = _dim(data as Dict, 'width');
    const h = _dim(data as Dict, 'height');
    if (w <= 0 || h <= 0) {
      continue;
    }
    records.push({
      semantic_id,
      render_id,
      x: _dim(data as Dict, 'x'),
      y: _dim(data as Dict, 'y'),
      width: w,
      height: h,
    });
  }
  return records;
}

export function _cluster_equal_width(records: Dict[]): Dict[][] {
  const clusters: Dict[][] = [];
  for (const record of pySorted(records, (r) => [pyRound((r.x as number) / _POSITION_TOL), r.width, r.y])) {
    let placed = false;
    for (const cluster of clusters) {
      const anchor = cluster[0];
      if (Math.abs((record.x as number) - (anchor.x as number)) <= _POSITION_TOL
        && Math.abs((record.width as number) - (anchor.width as number)) <= _SIZE_TOL) {
        cluster.push(record);
        placed = true;
        break;
      }
    }
    if (!placed) {
      clusters.push([record]);
    }
  }
  return clusters.filter((cluster) => cluster.length >= 2);
}

export function _cluster_equal_height(records: Dict[]): Dict[][] {
  const clusters: Dict[][] = [];
  for (const record of pySorted(records, (r) => [pyRound((r.y as number) / _POSITION_TOL), r.height, r.x])) {
    let placed = false;
    for (const cluster of clusters) {
      const anchor = cluster[0];
      if (Math.abs((record.y as number) - (anchor.y as number)) <= _POSITION_TOL
        && Math.abs((record.height as number) - (anchor.height as number)) <= _SIZE_TOL) {
        cluster.push(record);
        placed = true;
        break;
      }
    }
    if (!placed) {
      clusters.push([record]);
    }
  }
  return clusters.filter((cluster) => cluster.length >= 2);
}

/**
 * Restore equal-width/equal-height group relations expressed by layout.
 *
 * The layout LLM often communicates intent by assigning several group
 * backdrops exactly the same width or height. Later local fitting can expand
 * one group to contain an enlarged child. This pass propagates that expansion
 * across the original equal-size cluster, preserving the layout intent while
 * still keeping every group large enough for its children.
 */
export function preserve_group_alignment_intent(manifest: Dict, layout_instantiation: PyMapping | null): Dict {
  manifest = pyDeepcopy(manifest);
  const elements = pyOr(pyGet(manifest, 'elements'), []) as unknown[];
  const id_map = id_map_from_manifest(manifest);
  const by_id = new Map<unknown, Dict>();
  for (const e of elements) {
    if (isMapping(e) && truthy(pyGet(e, 'id'))) {
      by_id.set(pyGet(e, 'id'), e as Dict);
    }
  }
  const records = _group_layout_records(pyOr(layout_instantiation, {}) as PyMapping, id_map);
  if (!records.length) {
    return manifest;
  }

  for (const cluster of _cluster_equal_width(records)) {
    const elems = cluster.filter((r) => by_id.has(r.render_id)).map((r) => by_id.get(r.render_id)!);
    if (elems.length < 2) {
      continue;
    }
    const common_x = pyMin(elems.map((e) => _num(pyGet(e, 'x'))));
    const common_right = pyMax(elems.map((e) => _num(pyGet(e, 'x')) + _num(pyGet(e, 'width'))));
    const common_w = common_right - common_x;
    for (const elem of elems) {
      elem.x = common_x;
      elem.width = common_w;
      markF(elem, 'x', true); // _num() -> float
      markF(elem, 'width', true);
    }
  }

  for (const cluster of _cluster_equal_height(records)) {
    const elems = cluster.filter((r) => by_id.has(r.render_id)).map((r) => by_id.get(r.render_id)!);
    if (elems.length < 2) {
      continue;
    }
    const common_y = pyMin(elems.map((e) => _num(pyGet(e, 'y'))));
    const common_bottom = pyMax(elems.map((e) => _num(pyGet(e, 'y')) + _num(pyGet(e, 'height'))));
    const common_h = common_bottom - common_y;
    for (const elem of elems) {
      elem.y = common_y;
      elem.height = common_h;
      markF(elem, 'y', true);
      markF(elem, 'height', true);
    }
  }

  manifest.elements = elements;
  return manifest;
}
