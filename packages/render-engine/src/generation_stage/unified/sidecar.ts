// Ported from evodesign/agentic_system/generation_stage/unified/sidecar.py — keep in sync.
//
// Semantic sidecar contract for unified one-shot manifests.
//
// Python sets are only used for membership/difference and every reported list
// is ``sorted`` (pySorted: code-point order), so JS Set order never leaks.

import { BACKGROUND_SUFFIX, companion_base_id, companion_id } from '../../common/semantic_ids.ts';
import {
  StructureValidationError,
  validate_structure_instantiation,
} from '../structure/schemas.ts';
import { ValueError } from '../../py/errors.ts';
import { pySorted } from '../../py/sort.ts';
import { pyRepr, pyStrip } from '../../py/str.ts';
import { isDict, isStr, pyOr, truthy } from '../../py/truthy.ts';

type Dict = Record<string, unknown>;

function get(d: Dict, key: string, defaultValue: unknown = null): unknown {
  return Object.prototype.hasOwnProperty.call(d, key) ? d[key] : defaultValue;
}

/** ``raise ValueError(message) from cause`` */
function valueErrorFrom(message: string, cause: unknown): ValueError {
  const error = new ValueError(message);
  (error as { cause?: unknown }).cause = cause;
  return error;
}

export function _semantic_id_sets(structure: Dict): [Set<string>, Set<string>, Set<string>] {
  const collect = (field_name: string): Set<string> => {
    const out = new Set<string>();
    for (const item of (pyOr(get(structure, field_name, []), []) as unknown[])) {
      if (isDict(item) && isStr(item.id) && pyStrip(item.id)) {
        out.add(item.id);
      }
    }
    return out;
  };

  return [collect('nodes'), collect('groups'), collect('edges')];
}

/**
 * Validate and canonicalize a one-shot manifest semantic sidecar.
 *
 * Unified one-shot generation bypasses the separate Structure/Styling/Layout
 * handoff files, so ``_meta.structure_instantiation`` and ``_meta.id_map`` are
 * the only durable bridge from semantic graph IDs to rendered canvas IDs.
 */
export function validate_semantic_sidecar(manifest: Dict): Dict {
  const meta = get(manifest, '_meta');
  if (!isDict(meta)) {
    throw new ValueError('UnifiedGenerator output missing required _meta object');
  }

  const structure_payload = get(meta, 'structure_instantiation');
  if (!isDict(structure_payload)) {
    throw new ValueError(
      'UnifiedGenerator output _meta.structure_instantiation must be a JSON object',
    );
  }

  let structure: Dict;
  try {
    structure = validate_structure_instantiation(structure_payload);
  } catch (exc) {
    if (exc instanceof StructureValidationError) {
      throw valueErrorFrom(
        `UnifiedGenerator semantic sidecar validation failed: ${exc.message}`,
        exc,
      );
    }
    throw exc;
  }
  meta.structure_instantiation = structure;

  const id_map = get(meta, 'id_map');
  if (!isDict(id_map) || !truthy(id_map)) {
    throw new ValueError('UnifiedGenerator output _meta.id_map must be a non-empty object');
  }
  const invalid_id_map = Object.entries(id_map)
    .filter(([key, value]) => !isStr(key) || !pyStrip(key) || !isStr(value) || !pyStrip(value))
    .map(([key]) => key);
  if (invalid_id_map.length) {
    const sample = invalid_id_map.slice(0, 5).map((key) => pyRepr(key)).join(', ');
    throw new ValueError(`UnifiedGenerator output _meta.id_map has invalid entries: ${sample}`);
  }

  const [node_ids, group_ids, edge_ids] = _semantic_id_sets(structure);
  const expected_semantic_ids = new Set<string>([...node_ids, ...group_ids, ...edge_ids]);
  const id_map_keys = new Set<string>(Object.keys(id_map));
  const missing_semantic_ids = pySorted(
    [...new Set<string>([...node_ids, ...edge_ids])].filter((id) => !id_map_keys.has(id)),
  );
  missing_semantic_ids.push(
    ...pySorted(
      [...group_ids].filter(
        (group_id) => !id_map_keys.has(group_id)
          && !id_map_keys.has(companion_id(group_id, BACKGROUND_SUFFIX)),
      ),
    ),
  );
  if (missing_semantic_ids.length) {
    throw new ValueError(
      'UnifiedGenerator output _meta.id_map is missing semantic id(s): '
      + `${missing_semantic_ids.slice(0, 5).join(', ')}`,
    );
  }

  const unknown_semantic_ids = pySorted(
    [...id_map_keys].filter((key) => {
      if (expected_semantic_ids.has(key)) return false;
      const base = companion_base_id(key);
      return !(base !== null && expected_semantic_ids.has(base));
    }),
  );
  if (unknown_semantic_ids.length) {
    throw new ValueError(
      'UnifiedGenerator output _meta.id_map contains unknown semantic id(s): '
      + `${unknown_semantic_ids.slice(0, 5).join(', ')}`,
    );
  }

  const rendered_ids = new Set<unknown>();
  for (const element of get(manifest, 'elements', []) as unknown[]) {
    if (isDict(element) && isStr(get(element, 'id'))) {
      rendered_ids.add(get(element, 'id'));
    }
  }
  const missing_render_ids = pySorted(
    Object.values(id_map).filter((value) => isStr(value) && !rendered_ids.has(value)) as string[],
  );
  if (missing_render_ids.length) {
    throw new ValueError(
      'UnifiedGenerator output _meta.id_map references missing Excalidraw '
      + `element id(s): ${missing_render_ids.slice(0, 5).join(', ')}`,
    );
  }

  const expected_edge_ids = new Set<string>();
  for (const edge of (pyOr(get(structure, 'edges', []), []) as unknown[])) {
    if (isDict(edge) && isStr(get(edge, 'id'))) {
      expected_edge_ids.add(edge.id as string);
    }
  }
  if (expected_edge_ids.size) {
    const rendered_edge_ids = new Set<string>();
    for (const element of (pyOr(get(manifest, 'elements', []), []) as unknown[])) {
      if (!isDict(element) || get(element, 'type') !== 'arrow') {
        continue;
      }
      const meta_payload = get(element, 'meta');
      if (isDict(meta_payload) && isStr(get(meta_payload, 'semantic_edge_id'))) {
        rendered_edge_ids.add(meta_payload.semantic_edge_id as string);
      }
    }
    const missing_edge_ids = pySorted([...expected_edge_ids].filter((id) => !rendered_edge_ids.has(id)));
    if (missing_edge_ids.length) {
      throw new ValueError(
        'UnifiedGenerator output missing arrow meta.semantic_edge_id for '
        + `Structure edge id(s): ${missing_edge_ids.slice(0, 5).join(', ')}`,
      );
    }
  }

  return structure;
}

export const __all__ = ['validate_semantic_sidecar'];
