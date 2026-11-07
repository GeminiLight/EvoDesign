// Ported from evodesign/agentic_system/common/semantic_ids.py — keep in sync.
//
// Shared helpers for semantic IDs and manifest ``_meta.id_map``.

import { ValueError } from '../py/errors.ts';
import { pyGet, pyItems, type PyMapping } from '../py/dict.ts';
import { pyIn } from '../py/eq.ts';
import { pyRepr, pyStrip } from '../py/str.ts';
import { isMapping, isStr } from '../py/truthy.ts';

export const BACKGROUND_SUFFIX = ':background';
export const TITLE_SUFFIX = ':title';
export const LABEL_SUFFIX = ':label';
export const ICON_SUFFIX = ':icon';

export const GROUP_FRAME_SUFFIXES = [BACKGROUND_SUFFIX] as const;
export const GROUP_TITLE_SUFFIXES = [TITLE_SUFFIX, LABEL_SUFFIX] as const;
export const COMPANION_ID_SUFFIXES = [
  BACKGROUND_SUFFIX,
  TITLE_SUFFIX,
  LABEL_SUFFIX,
  ICON_SUFFIX,
] as const;

// Canvas-level captions that Styling or Layout sometimes add on their own.
export const CANVAS_DECORATION_IDS: ReadonlySet<string> = new Set([
  'title', 'subtitle', 'caption', 'heading',
  'diagram_title', 'main_title', 'canvas_title',
]);

/** Remove stand-alone canvas captions that no upstream stage declared. */
export function drop_canvas_decorations(
  entries: Record<string, unknown>,
  known_ids: Set<string>,
): [Record<string, unknown>, string[]] {
  const dropped = Object.keys(entries).filter((key) =>
    isStr(key) && CANVAS_DECORATION_IDS.has(pyStrip(key).toLowerCase())
    && !known_ids.has(key));
  if (!dropped.length) {
    return [entries, []];
  }
  const kept: Record<string, unknown> = Object.create(null);
  for (const [key, value] of Object.entries(entries)) {
    if (!dropped.includes(key)) kept[key] = value;
  }
  return [kept, dropped];
}

/** Resolved group render IDs from a manifest id_map. */
export class GroupIdMap {
  readonly background_by_group: Record<string, string>;
  readonly title_by_group: Record<string, string>;

  constructor(background_by_group: Record<string, string>, title_by_group: Record<string, string>) {
    this.background_by_group = background_by_group;
    this.title_by_group = title_by_group;
    Object.freeze(this);
  }

  get background_ids(): Set<string> {
    return new Set(Object.values(this.background_by_group));
  }

  get title_ids(): Set<string> {
    return new Set(Object.values(this.title_by_group));
  }
}

/** Return the base semantic id for a companion key, otherwise the id itself. */
export function semantic_id_base(semantic_id: unknown): string | null {
  if (!isStr(semantic_id) || !pyStrip(semantic_id)) {
    return null;
  }
  for (const suffix of COMPANION_ID_SUFFIXES) {
    if (semantic_id.endsWith(suffix)) {
      const base = semantic_id.slice(0, -suffix.length);
      return base || null;
    }
  }
  return semantic_id;
}

/** Return the base id only when ``semantic_id`` uses a known companion suffix. */
export function companion_base_id(semantic_id: unknown): string | null {
  if (!isStr(semantic_id) || !pyStrip(semantic_id)) {
    return null;
  }
  for (const suffix of COMPANION_ID_SUFFIXES) {
    if (semantic_id.endsWith(suffix)) {
      const base = semantic_id.slice(0, -suffix.length);
      return base || null;
    }
  }
  return null;
}

/** Build a companion semantic id from a base id and one canonical suffix. */
export function companion_id(base_id: string, suffix: string): string {
  if (!pyIn(suffix, COMPANION_ID_SUFFIXES as readonly string[])) {
    throw new ValueError(`Unknown semantic companion suffix: ${pyRepr(suffix)}`);
  }
  return `${base_id}${suffix}`;
}

/** Extract a string-to-string ``_meta.id_map`` from a manifest. */
export function id_map_from_manifest(manifest: unknown): Record<string, string> {
  const meta = isMapping(manifest) ? pyGet(manifest, '_meta') : null;
  if (!isMapping(meta)) {
    return {};
  }
  const id_map = pyGet(meta, 'id_map');
  if (!isMapping(id_map)) {
    return {};
  }
  const result: Record<string, string> = Object.create(null);
  for (const [key, value] of pyItems(id_map)) {
    if (isStr(key) && isStr(value)) result[key] = value;
  }
  return result;
}

/** Resolve group background/title render IDs from semantic companion keys. */
export function resolve_group_id_map(id_map: PyMapping): GroupIdMap {
  const background_by_group: Record<string, string> = Object.create(null);
  const title_by_group: Record<string, string> = Object.create(null);
  for (const [key, value] of pyItems(id_map)) {
    if (!isStr(key) || !isStr(value)) {
      continue;
    }
    let matchedFrame = false;
    for (const suffix of GROUP_FRAME_SUFFIXES) {
      if (key.endsWith(suffix)) {
        const base = key.slice(0, -suffix.length);
        if (base) {
          background_by_group[base] = value;
        }
        matchedFrame = true;
        break;
      }
    }
    if (!matchedFrame) {
      for (const suffix of GROUP_TITLE_SUFFIXES) {
        if (key.endsWith(suffix)) {
          const base = key.slice(0, -suffix.length);
          if (base) {
            title_by_group[base] = value;
          }
          break;
        }
      }
    }
  }
  return new GroupIdMap(background_by_group, title_by_group);
}

/** Return the rendered frame id for a semantic group id, if mapped. */
export function group_frame_render_id(id_map: PyMapping, group_id: unknown): string | null {
  if (!isStr(group_id) || !group_id) {
    return null;
  }
  const direct = pyGet(id_map, group_id);
  if (isStr(direct) && direct) {
    return direct;
  }
  const background = pyGet(id_map, companion_id(group_id, BACKGROUND_SUFFIX));
  return isStr(background) && background ? background : null;
}

/** Build rendered element id -> raw semantic id from an id_map. */
export function reverse_id_map(id_map: PyMapping): Record<string, string> {
  const result: Record<string, string> = Object.create(null);
  for (const [key, value] of pyItems(id_map)) {
    if (isStr(key) && key && isStr(value) && value) {
      result[value] = key;
    }
  }
  return result;
}

/** Build rendered element id -> base semantic id from an id_map. */
export function reverse_base_id_map(id_map: PyMapping): Record<string, string> {
  const reverse: Record<string, string> = Object.create(null);
  for (const [key, value] of pyItems(id_map)) {
    if (!isStr(value) || !value) {
      continue;
    }
    const base = semantic_id_base(key);
    if (base !== null) {
      reverse[value] = base;
    }
  }
  return reverse;
}

// A JS object moves keys that look like array indices ("0", "7", ...) ahead of
// all other keys, in ascending order, so a semantic id of that shape would
// reorder every id-keyed dict here and change the output. Such ids are
// rejected at Structure and at the render entry.
const _ARRAY_INDEX_LIMIT = 2 ** 32 - 1;

export function is_integer_like_id(value: unknown): boolean {
  return isStr(value) && /^(0|[1-9][0-9]*)$/.test(value) && Number(value) < _ARRAY_INDEX_LIMIT;
}

export function integer_like_semantic_ids(structure: unknown, layout: unknown): string[] {
  const found: string[] = [];
  if (isMapping(structure)) {
    for (const category of ['nodes', 'edges', 'groups']) {
      const items = pyGet(structure, category);
      for (const item of Array.isArray(items) ? items : []) {
        const item_id = isMapping(item) ? pyGet(item, 'id') : null;
        if (is_integer_like_id(item_id) && !found.includes(item_id as string)) found.push(item_id as string);
      }
    }
  }
  if (isMapping(layout)) {
    for (const [key] of pyItems(layout)) {
      if (is_integer_like_id(key) && !found.includes(key as string)) found.push(key as string);
    }
  }
  return found;
}

export function ensure_no_integer_like_semantic_ids(structure: unknown, layout: unknown): void {
  const found = integer_like_semantic_ids(structure, layout);
  if (found.length) {
    throw new ValueError(
      'Semantic ids must not be bare integers (got '
        + found.map((item) => pyRepr(item)).join(', ')
        + "); use descriptive ids such as 'n_login'.",
    );
  }
}

export const __all__ = [
  'BACKGROUND_SUFFIX',
  'TITLE_SUFFIX',
  'LABEL_SUFFIX',
  'ICON_SUFFIX',
  'GROUP_FRAME_SUFFIXES',
  'GROUP_TITLE_SUFFIXES',
  'COMPANION_ID_SUFFIXES',
  'GroupIdMap',
  'semantic_id_base',
  'companion_base_id',
  'companion_id',
  'id_map_from_manifest',
  'resolve_group_id_map',
  'group_frame_render_id',
  'reverse_id_map',
  'reverse_base_id_map',
  'is_integer_like_id',
  'integer_like_semantic_ids',
  'ensure_no_integer_like_semantic_ids',
];
