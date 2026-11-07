// Ported from evodesign/agentic_system/render_engine/excalidraw/normalizer.py — keep in sync.
//
// Manifest normalization pass for Excalidraw scenes: z-order, title dedup and
// zero-padded index guarantees for any Excalidraw manifest (idempotent).

import { sequential_index } from '../shared/order_keys.ts';
import {
  LAYER_ARROW,
  LAYER_GROUP_FRAME,
  LAYER_ICON,
  LAYER_NODE,
  LAYER_TEXT,
  _elem_id,
  _has_explicit_zindex,
  deduplicate_group_titles,
  detect_group_frame_ids,
} from '../shared/normalization.ts';
import { pyGet, pyGetItem } from '../../py/dict.ts';
import { getLogger } from '../../py/logging.ts';
import { pyInt } from '../../py/number.ts';
import { pySort } from '../../py/sort.ts';
import { isDict, isList, truthy } from '../../py/truthy.ts';

type Dict = Record<string, unknown>;

export const logger = getLogger('evodesign.agentic_system.render_engine.excalidraw.normalizer');

export const _LAYER_GROUP_FRAME = LAYER_GROUP_FRAME;
export const _LAYER_NODE = LAYER_NODE;
export const _LAYER_TEXT = LAYER_TEXT;

/**
 * Classify an already-built Excalidraw element into a z-layer using the
 * pre-computed ``frame_ids`` set.
 */
export function _layer_for_element(elem: Dict, frame_ids: Set<string>): number {
  if (_has_explicit_zindex(elem)) {
    return pyInt(pyGetItem(elem, 'zIndex') as number);
  }

  const t = pyGet(elem, 'type');
  if (t === 'arrow') {
    return LAYER_ARROW;
  }
  if (t === 'text') {
    return LAYER_TEXT;
  }
  if (t === 'image') {
    return LAYER_ICON;
  }

  const eid = _elem_id(elem);
  if (truthy(eid) && frame_ids.has(eid!)) {
    return LAYER_GROUP_FRAME;
  }

  return LAYER_NODE;
}

/** Stable-sort by (layer, original_order) and assign zero-padded indices. */
export function _reassign_indices(elements: Dict[], frame_ids: Set<string>): Dict[] {
  const decorated: [number, number, Dict][] = elements.map(
    (elem, orig_idx) => [_layer_for_element(elem, frame_ids), orig_idx, elem],
  );
  pySort(decorated, (t) => [t[0], t[1]]);

  const ordered = decorated.map((t) => t[2]);
  ordered.forEach((elem, new_idx) => {
    elem.index = sequential_index(new_idx);
  });
  return ordered;
}

/**
 * Apply z-order and dedup guarantees to any Excalidraw manifest.
 * The manifest is mutated in place AND returned.
 */
export function normalize_excalidraw_manifest(
  manifest: Dict | null,
  dedup_titles = true,
  resort_indices = true,
): Dict | null {
  if (!isDict(manifest)) {
    return manifest;
  }

  let elements = pyGet(manifest, 'elements') as Dict[];
  if (!isList(elements) || !truthy(elements)) {
    return manifest;
  }

  // Detect group frames using structural heuristic (unified-mode safe).
  const frame_ids = detect_group_frame_ids(elements, true);

  if (dedup_titles) {
    elements = deduplicate_group_titles(elements, frame_ids);
  }

  if (resort_indices) {
    elements = _reassign_indices(elements, frame_ids);
  }

  manifest.elements = elements;
  return manifest;
}

export const __all__ = [
  'normalize_excalidraw_manifest',
];
