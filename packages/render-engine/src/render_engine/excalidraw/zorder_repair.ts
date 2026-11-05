// Ported from evodesign/agentic_system/render_engine/excalidraw/zorder_repair.py — keep in sync.
//
// Z-order repair for Excalidraw manifests.
//
// Runs after the converter / arrow-adder / group-fitter pipeline, reclassifies
// every element from manifest-level attributes (type + id_map semantic-id
// reverse lookup), stable-sorts by (band, original_index), and reassigns
// fractional indices sequentially. Purely geometric and idempotent.
//
// TS-specific: ``is_enabled`` reads ``AppSettings.get_default().render_fix_zorder``
// as ``EVODESIGN_RENDER_FIX_ZORDER`` (via ``getEnv``) when set and non-blank,
// else the ``render.fix_zorder`` value shipped in
// evodesign/config/defaults/settings.yaml (``true``). The YAML is not parsed
// at runtime; if that value changes, update ``_SETTINGS_YAML_FIX_ZORDER``.

import { pyDeepcopy } from '../../py/float_marks.ts';
import { sequential_index } from '../shared/order_keys.ts';
import {
  BACKGROUND_SUFFIX,
  GROUP_TITLE_SUFFIXES,
  id_map_from_manifest,
  reverse_id_map,
  semantic_id_base,
} from '../../common/semantic_ids.ts';
import {
  LAYER_ARROW as _LAYER_ARROW,
  LAYER_GROUP_FRAME as _LAYER_GROUP_FRAME,
  LAYER_ICON as _LAYER_ICON,
  LAYER_NODE as _LAYER_NODE,
  LAYER_TEXT as _LAYER_TEXT,
  detect_group_frame_ids,
} from '../shared/normalization.ts';
import { pyGet, pyKeys, type PyMapping } from '../../py/dict.ts';
import { getEnv } from '../../py/env.ts';
import { pyIn } from '../../py/eq.ts';
import { ValueError } from '../../py/errors.ts';
import { getLogger } from '../../py/logging.ts';
import { pySort } from '../../py/sort.ts';
import { pyEndswith, pyLower, pyRepr, pyStrip } from '../../py/str.ts';
import { isBool, isDict, isInt, isList, isStr, truthy } from '../../py/truthy.ts';

type Dict = Record<string, unknown>;

const logger = getLogger('evodesign.agentic_system.render_engine.excalidraw.zorder_repair');

const _SETTINGS_YAML_FIX_ZORDER: unknown = true;

/** Return semantic ids whose title/label sibling marks them as frames. */
export function _titled_semantic_bases(id_map: PyMapping): Set<string> {
  const result = new Set<string>();
  for (const semantic_id of pyKeys(id_map)) {
    if (!isStr(semantic_id) || !pyEndswith(semantic_id, GROUP_TITLE_SUFFIXES as readonly string[])) {
      continue;
    }
    const base = semantic_id_base(semantic_id);
    if (truthy(base)) {
      result.add(base!);
    }
  }
  return result;
}

/**
 * Return the layer band for a manifest element.
 *
 * Inference order (first match wins):
 *   1. Explicit integer ``zIndex`` on the element itself.
 *   2. ``type == "text"`` → text layer.
 *   3. ``type == "image"`` → icon layer.
 *   4. ``type == "arrow"`` → arrow layer.
 *   5. Shape elements: semantic id via reverse id_map ending ``:background``,
 *      starting ``g_``, or titled → group-frame band.
 *   6. Element id in the structural containment set → group-frame band.
 *   7. Default → node band.
 */
export function _infer_band(
  elem: Dict,
  reverse_id_map: PyMapping,
  frame_ids: Set<string> | readonly string[],
  titled_bases: Set<string> | readonly string[],
): number {
  let z = pyGet(elem, 'zIndex');
  if (isBool(z)) {
    z = null;
  }
  if (isInt(z)) {
    return z;
  }

  const etype = pyGet(elem, 'type');
  if (etype === 'text') {
    return _LAYER_TEXT;
  }
  if (etype === 'image') {
    return _LAYER_ICON;
  }
  if (etype === 'arrow') {
    return _LAYER_ARROW;
  }

  const excalidraw_id = pyGet(elem, 'id');
  const semantic_id = isStr(excalidraw_id) ? pyGet(reverse_id_map, excalidraw_id) : null;
  if (isStr(semantic_id)) {
    if (semantic_id.endsWith(BACKGROUND_SUFFIX)) {
      return _LAYER_GROUP_FRAME;
    }
    if (semantic_id.startsWith('g_')) {
      return _LAYER_GROUP_FRAME;
    }
    if (pyIn(semantic_id, titled_bases)) {
      return _LAYER_GROUP_FRAME;
    }
  }

  // Structural containment fallback: geometric heuristic that does not
  // depend on naming conventions.
  if (isStr(excalidraw_id) && pyIn(excalidraw_id, frame_ids)) {
    return _LAYER_GROUP_FRAME;
  }

  return _LAYER_NODE;
}

/**
 * Reclassify + reassign fractional indices on an Excalidraw manifest.
 *
 * Returns a deep-copied manifest with ``elements[*].index`` rewritten to
 * (band, original-order)-sorted ``e00000``-style strings. Other element
 * fields are untouched. Idempotent.
 */
export function repair_zorder(manifest: Dict): Dict {
  if (!isDict(manifest)) {
    return manifest;
  }
  const original_elements = pyGet(manifest, 'elements');
  if (!isList(original_elements) || !original_elements.length) {
    return manifest;
  }

  manifest = pyDeepcopy(manifest);
  const elements = manifest.elements as unknown[];
  const id_map = id_map_from_manifest(manifest);
  const rendered_to_semantic = reverse_id_map(id_map);
  const titled_bases = _titled_semantic_bases(id_map);

  // Structural containment heuristic: detect frames that LLM emits without
  // naming-convention suffixes.
  const frame_ids = detect_group_frame_ids(elements as Dict[], true);

  // Annotate each element with (band, original_position) so the sort is
  // stable and the eventual index order is deterministic.
  const decorated: [number, number, unknown][] = [];
  elements.forEach((elem, position) => {
    if (!isDict(elem)) {
      // Non-dict entries get pushed to the end at the top layer.
      decorated.push([_LAYER_TEXT + 1, position, elem]);
      return;
    }
    const band = _infer_band(elem, rendered_to_semantic, frame_ids, titled_bases);
    decorated.push([band, position, elem]);
  });

  pySort(decorated, (t) => [t[0], t[1]]);

  let reassigned = 0;
  let changed = 0;
  decorated.forEach(([, , elem], new_position) => {
    if (!isDict(elem)) {
      return;
    }
    const new_index = sequential_index(new_position);
    if (pyGet(elem, 'index') !== new_index) {
      elem.index = new_index;
      changed += 1;
    }
    reassigned += 1;
  });

  manifest.elements = decorated.map(([, , elem]) => elem);

  if (changed) {
    logger.info('[ZOrderRepair] Reassigned fractional indices (%d/%d elements changed).', changed, reassigned);
  } else {
    logger.info('[ZOrderRepair] No reassignment needed (%d elements already in band order).', reassigned);
  }

  return manifest;
}

/**
 * Feature-flag gate: ``render.fix_zorder`` in settings.yaml (default on).
 *
 * Set ``EVODESIGN_RENDER_FIX_ZORDER`` to ``"0"`` / ``"false"`` / ``"no"`` to
 * disable and fall back to the converter's first-pass index assignment.
 */
export function is_enabled(): boolean {
  // AppSettings.get_raw: a set-but-blank env var falls back to the YAML value.
  const env_val = getEnv('EVODESIGN_RENDER_FIX_ZORDER');
  const raw: unknown = env_val !== null && pyStrip(env_val) ? env_val : _SETTINGS_YAML_FIX_ZORDER;
  // AppSettings._bool_setting
  if (isBool(raw)) {
    return raw;
  }
  const val = pyLower(pyStrip(String(raw)));
  if (['1', 'true', 'yes', 'on'].includes(val)) {
    return true;
  }
  if (['0', 'false', 'no', 'off'].includes(val)) {
    return false;
  }
  throw new ValueError(
    `Invalid boolean setting render.fix_zorder: ${pyRepr(raw)}. `
    + 'Use true/false, yes/no, on/off, or 1/0.',
  );
}

export const __all__ = ['repair_zorder', 'is_enabled'];
