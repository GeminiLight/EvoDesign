// Ported from evodesign/agentic_system/render_engine/excalidraw/architecture_style_normalizer.py — keep in sync.
//
// Normalize architecture scenes to a formal, draw.io-like visual language.
//
// Dict representation: the Python ``group_roles``, ``member_group_roles``,
// ``node_roles`` and ``node_render_roles`` dicts are only looked up (never
// emitted), so they are ``Map``s keyed by the same strings.

import { pyDeepcopy } from '../../py/float_marks.ts';
import { pyGet, pySetdefault, type PyMapping } from '../../py/dict.ts';
import { pyInt } from '../../py/number.ts';
import { pyLower, pyStr, pyStrip } from '../../py/str.ts';
import { isDict, isList, isMapping, isNumberOrBool, isStr, pyOr, truthy } from '../../py/truthy.ts';
import {
  BACKGROUND_SUFFIX,
  TITLE_SUFFIX,
  group_frame_render_id,
  id_map_from_manifest,
  reverse_id_map,
} from '../../common/semantic_ids.ts';
import { unwrap_structure_instantiation } from '../../common/spec_utils.ts';

type Dict = Record<string, unknown>;

const _ARCHITECTURE_TYPES = new Set(['architecture', 'architecture_diagram']);
const _HELVETICA = 2;
const _GROUP_TITLE_FONT_SIZE = 18;
const _NODE_FONT_SIZE = 16;
const _EDGE_LABEL_FONT_SIZE = 13;
const _MAIN_CONNECTOR_WIDTH = 1.5;
const _CONNECTOR_ARROWHEAD = 'triangle';
const _DARK_INK = '#1F2937';
const _CONNECTOR_INK = '#4B5563';

// Draw.io's strongest default diagrams use a small set of paired light fills
// and darker borders. Keep that grammar, but reserve each pair for a stable
// architecture role instead of cycling colours for decoration.
const _ROLE_STYLES: Record<string, [string, string]> = {
  presentation: ['#DAE8FC', '#6C8EBF'],
  business: ['#D5E8D4', '#82B366'],
  data: ['#E1D5E7', '#9673A6'],
  external: ['#FFF2CC', '#D6B656'],
  governance: ['#F8CECC', '#B85450'],
  neutral: ['#F5F5F5', '#666666'],
};

// A light surface makes the group boundary legible without turning the
// architecture diagram into a collection of heavy dashed boxes.
const _FRAME_TINTS: Record<string, string> = {
  presentation: '#F7FAFE',
  service: '#F7FAF6',
  business: '#F7FAF6',
  data: '#FAF8FC',
  cross: '#FFF8F7',
  governance: '#FFF8F7',
};

// Group frames are orientation aids, not primary content.
const _FRAME_OPACITY = 72;

function _anyIn(token: string, parts: readonly string[]): boolean {
  return parts.some((part) => token.includes(part));
}

export function _role_from_token(value: unknown): string {
  const token = pyLower(pyStrip(pyStr(pyOr(value, '')))).replaceAll('-', '_');
  if (_anyIn(token, ['cross', 'governance', 'security', 'operational', 'communication'])) {
    return 'governance';
  }
  if (_anyIn(token, ['external', 'gateway', 'queue', 'message'])) {
    return 'external';
  }
  if (_anyIn(token, ['data', 'database', 'store', 'persistence', 'integration'])) {
    return 'data';
  }
  if (_anyIn(token, ['service', 'business', 'api', 'domain'])) {
    return 'business';
  }
  if (_anyIn(token, ['presentation', 'ui', 'client', 'user'])) {
    return 'presentation';
  }
  return 'neutral';
}

export function _semantic_id_for_element(reverse_map: PyMapping, element: PyMapping): string {
  return pyStr(pyGet(reverse_map, pyStr(pyGet(element, 'id', '')), ''));
}

export function _is_group_frame(element: PyMapping, semantic_id: string, group_frame_ids: Set<string>): boolean {
  const element_id = pyLower(pyStr(pyGet(element, 'id', '')));
  const type = pyGet(element, 'type');
  return (
    (type === 'rectangle' || type === 'ellipse')
    && (
      element_id.startsWith('frame-')
      || group_frame_ids.has(pyStr(pyGet(element, 'id', '')))
      || semantic_id.endsWith(BACKGROUND_SUFFIX)
    )
  );
}

export function _is_group_title(element: PyMapping, semantic_id: string): boolean {
  const element_id = pyLower(pyStr(pyGet(element, 'id', '')));
  return pyGet(element, 'type') === 'text' && (
    element_id.startsWith('title-')
    || element_id.endsWith(TITLE_SUFFIX)
    || semantic_id.endsWith(TITLE_SUFFIX)
  );
}

function _iter(value: unknown): unknown[] {
  // ``x or []`` followed by iteration; JSON values only (lists / tuples).
  if (!truthy(value)) return [];
  if (isList(value)) return value;
  if (isStr(value)) return [...value];
  if (value instanceof Set) return [...value];
  if (value instanceof Map) return [...value.keys()];
  if (isDict(value)) return Object.keys(value);
  return value as unknown[];
}

/**
 * Use consistent typography and connector strokes for architecture charts.
 *
 * Styling output may omit font settings for bound labels, which makes the
 * Excalidraw converter fall back to its playful Virgil font. Architecture
 * diagrams are formal technical artifacts, so normalize only this chart
 * family after arrows have been created. Other chart types retain their
 * authored styling.
 */
export function normalize_architecture_style(
  manifest: Dict,
  structure_instantiation: Dict | null,
  layout_instantiation: Dict | null = null,
): Dict {
  if (!isDict(manifest) || !isDict(structure_instantiation)) {
    return manifest;
  }
  const structure = unwrap_structure_instantiation(structure_instantiation);
  if (!_ARCHITECTURE_TYPES.has(pyLower(pyStrip(pyStr(pyGet(structure, 'chart_type', '')))))) {
    return manifest;
  }

  const output = pyDeepcopy(manifest);
  const id_map = id_map_from_manifest(output);
  const reverse_map = reverse_id_map(id_map);
  const groups = _iter(pyGet(structure, 'groups', [])).filter((group) => isMapping(group)) as PyMapping[];
  const group_roles = new Map<string, string>();
  for (const group of groups) {
    group_roles.set(
      pyStr(pyGet(group, 'id', '')),
      _role_from_token(['id', 'label', 'class'].map((key) => pyStr(pyGet(group, key, ''))).join(' ')),
    );
  }
  const member_group_roles = new Map<string, string>();
  for (const group of groups) {
    for (const member_id of _iter(pyGet(group, 'members', []))) {
      if (isStr(member_id)) {
        member_group_roles.set(pyStr(member_id), group_roles.get(pyStr(pyGet(group, 'id', ''))) ?? 'neutral');
      }
    }
  }
  const update = new Map<string, string>();
  for (const node of _iter(pyGet(structure, 'nodes', []))) {
    if (isMapping(node) && isStr(pyGet(node, 'id')) && truthy(pyGet(node, 'group_id'))) {
      update.set(pyStr(pyGet(node, 'id')), group_roles.get(pyStr(pyGet(node, 'group_id', ''))) ?? 'neutral');
    }
  }
  for (const [key, value] of update) member_group_roles.set(key, value);

  const node_roles = new Map<string, string>();
  for (const node of _iter(pyGet(structure, 'nodes', []))) {
    if (!isMapping(node) || !isStr(pyGet(node, 'id'))) {
      continue;
    }
    const node_id = pyStr(pyGet(node, 'id'));
    const own_role = _role_from_token(['id', 'label', 'class'].map((key) => pyStr(pyGet(node, key, ''))).join(' '));
    const group_role = member_group_roles.get(node_id) ?? 'neutral';
    // Architecture layers carry the primary colour meaning. External and
    // governance nodes remain explicit exceptions.
    node_roles.set(
      node_id,
      own_role === 'external' || own_role === 'governance' || group_role === 'neutral' ? own_role : group_role,
    );
  }
  const node_render_roles = new Map<string, string>();
  for (const [semantic_id, role] of node_roles) {
    const render_id = pyGet(id_map, semantic_id);
    if (truthy(render_id) && truthy(role)) {
      node_render_roles.set(render_id as string, node_roles.get(semantic_id)!);
    }
  }
  const group_frame_ids = new Set<string>();
  for (const group of _iter(pyGet(structure, 'groups', []))) {
    if (!isMapping(group)) continue;
    const render_id = group_frame_render_id(id_map, pyGet(group, 'id'));
    if (truthy(render_id)) group_frame_ids.add(render_id!);
  }
  const group_frame_roles = new Map<string, string>();
  for (const group of groups) {
    const render_id = group_frame_render_id(id_map, pyGet(group, 'id'));
    if (truthy(render_id)) {
      group_frame_roles.set(render_id!, group_roles.get(pyStr(pyGet(group, 'id', ''))) ?? 'neutral');
    }
  }
  (pySetdefault<unknown>(output, 'appState', {}) as Dict).viewBackgroundColor = '#FFFFFF';
  for (const element of _iter(pyGet(output, 'elements', [])) as Dict[]) {
    if (!isDict(element)) {
      continue;
    }
    const render_id = pyStr(pyGet(element, 'id', ''));
    const semantic_id = _semantic_id_for_element(reverse_map, element);
    if (_is_group_frame(element, semantic_id, group_frame_ids)) {
      const role = group_frame_roles.has(render_id) ? group_frame_roles.get(render_id)! : _role_from_token(semantic_id);
      element.backgroundColor = _FRAME_TINTS[role] ?? '#F8FAFC';
      element.strokeColor = (_ROLE_STYLES[role] ?? _ROLE_STYLES.neutral)[1];
      element.fillStyle = 'solid';
      element.strokeStyle = 'solid';
      element.strokeWidth = 1;
      element.opacity = _FRAME_OPACITY;
      element.roundness = { type: 3 };
      element.roughness = 0;
      continue;
    }
    const type = pyGet(element, 'type');
    if (type === 'text') {
      element.fontFamily = _HELVETICA;
      element.strokeColor = _DARK_INK;
      if (_is_group_title(element, semantic_id)) {
        element.fontStyle = 1;
        element.fontSize = _GROUP_TITLE_FONT_SIZE;
        element.lineHeight = 1.15;
      } else {
        element.lineHeight = 1.2;
        if (node_render_roles.has(pyStr(pyGet(element, 'containerId', '')))) {
          element.fontSize = _NODE_FONT_SIZE;
        } else if (pyStr(pyGet(element, 'containerId', ''))) {
          const current_font_size = pyGet(element, 'fontSize');
          element.fontSize = isNumberOrBool(current_font_size)
            ? Math.min(16, pyInt(current_font_size))
            : 16;
        }
      }
    } else if (type === 'rectangle' || type === 'ellipse' || type === 'diamond') {
      element.roughness = 0;
      const role = node_render_roles.get(render_id) ?? null;
      if (truthy(role) && pyGet(element, 'type') === 'ellipse') {
        // Architecture components are box-shaped units.
        element.type = 'rectangle';
      }
      // A coherent rounded-rectangle language is easier to scan.
      element.roundness = { type: 3 };
      if (truthy(role)) {
        const [fill, stroke] = _ROLE_STYLES[role!];
        element.backgroundColor = fill;
        element.strokeColor = stroke;
        element.fillStyle = 'solid';
        element.strokeStyle = 'solid';
        element.strokeWidth = 1.5;
        element.opacity = 100;
      }
    } else if (type === 'arrow') {
      element.roughness = 0;
      const meta = pyGet(element, 'meta');
      const target_id = isMapping(meta) ? pyStr(pyGet(meta, 'target', '')) : '';
      const is_supporting = node_roles.get(target_id) === 'governance';
      element.strokeColor = is_supporting ? _ROLE_STYLES.governance[1] : _CONNECTOR_INK;
      // Supporting relationships should recede behind the primary flow.
      element.strokeWidth = is_supporting ? 1.5 : _MAIN_CONNECTOR_WIDTH;
      element.opacity = is_supporting ? 78 : 100;
      element.strokeStyle = is_supporting ? 'dashed' : 'solid';
      element.startArrowhead = null;
      element.endArrowhead = _CONNECTOR_ARROWHEAD;
      const points = pyGet(element, 'points');
      element.elbowed = isList(points) && points.length > 2;
      element.roundness = null;
      const label = pyGet(element, 'label');
      if (isDict(label)) {
        label.fontFamily = _HELVETICA;
        label.fontSize = _EDGE_LABEL_FONT_SIZE;
        label.lineHeight = 1.15;
        label.strokeColor = _DARK_INK;
      }
    }
  }
  // Role colours are defaults. Preserve the explicit palette selected by
  // Styling/Layout instead of silently replacing a user's requested theme.
  if (isDict(layout_instantiation)) {
    for (const element of _iter(pyGet(output, 'elements', [])) as Dict[]) {
      if (!isDict(element)) {
        continue;
      }
      const authored = pyGet(layout_instantiation, _semantic_id_for_element(reverse_map, element));
      if (!isDict(authored)) {
        continue;
      }
      for (const key of ['backgroundColor', 'strokeColor']) {
        const value = pyGet(authored, key);
        if (isStr(value) && pyStrip(value)) {
          element[key] = value;
        }
      }
    }
  }
  return output;
}

export const __all__ = ['normalize_architecture_style'];
