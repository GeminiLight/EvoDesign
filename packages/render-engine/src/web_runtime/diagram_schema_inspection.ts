// Ported from backend/app/services/diagram_schema_inspection.py — keep in sync
// (PHASE3_PLAN.md WP29). Only the parts the generation result needs.

type Dict = Record<string, any>;

export const NODE_COLLECTION_KEYS = ['elements', 'nodes', 'shapes', 'blocks'] as const;
export const CONNECTOR_COLLECTION_KEYS = ['connectors', 'edges', 'links', 'relations', 'arrows'] as const;
export const TL_DRAW_ARROW_TYPES = new Set(['arrow', 'line', 'edge', 'connector']);

const isDict = (value: unknown): value is Dict => Boolean(value) && typeof value === 'object' && !Array.isArray(value);

/** The first list-valued schema collection among the supported keys. */
export function first_schema_collection(schema_blob: unknown, keys: readonly string[]): unknown[] {
  if (!isDict(schema_blob)) return [];
  for (const key of keys) {
    const value = schema_blob[key];
    if (Array.isArray(value)) return value;
  }
  if (keys === NODE_COLLECTION_KEYS) return tldraw_shape_records(schema_blob, false);
  if (keys === CONNECTOR_COLLECTION_KEYS) return tldraw_shape_records(schema_blob, true);
  return [];
}

export function count_schema_collection(schema_blob: unknown, keys: readonly string[]): number {
  return first_schema_collection(schema_blob, keys).length;
}

/** TLDraw shape records from root or document-level records maps. */
export function tldraw_shape_records(schema_blob: Dict, include_arrows: boolean): Dict[] {
  const shapes: Dict[] = [];
  for (const value of Object.values(_tldraw_records(schema_blob))) {
    if (!isDict(value)) continue;
    if (value.typeName !== 'shape') continue;
    const is_arrow = TL_DRAW_ARROW_TYPES.has(String(value.type ?? '').toLowerCase());
    if (is_arrow === include_arrows) shapes.push(value);
  }
  return shapes;
}

function _tldraw_records(schema_blob: Dict): Dict {
  // The editor's getSnapshot() and the TLDraw converter both save
  // {"document": {"store": ...}}; "records" maps stay readable.
  const document = schema_blob.document;
  for (const holder of [document, schema_blob]) {
    if (!isDict(holder)) continue;
    for (const key of ['store', 'records']) {
      const records = holder[key];
      if (isDict(records)) return records;
    }
  }
  return {};
}
