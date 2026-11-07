// Ported from evodesign/agentic_system/render_engine/excalidraw/design_theme.py — keep in sync.
//
// Shared visual treatment for non-architecture diagrams.
//
// Architecture diagrams get the full card design system. Other diagram types
// keep their own layout and shapes (decisions stay diamonds, start and end stay
// ellipses), but take the same treatment so every diagram reads as one design:
// the style agent's family becomes a light fill and a coloured border, text is
// one dark ink, connectors are thin, solid-headed and coloured by their source,
// edge labels are muted, and icons use the outline set.
//
// Representation notes (see migration/notes/WP09.md):
// - Python tuples (colours, points, walk results) are arrays.
// - ``by_eid`` is a ``Map`` keyed by the raw ``e.get("id")`` (``null`` when absent);
//   ``host_ink``/``node_ink``/``children``/``parent``/``best`` are ``Map``s.
// - ``_main_path`` returns a ``Set``; ``_tree_emphasis`` iterates the Python
//   ``ids`` set, whose order only affects the key order of the returned dict.

import { assignF, isF, markF, pyDeepcopy } from '../../py/float_marks.ts';
import { pyGet, pyGetItem, pyItems, pySetdefault, type PyMapping } from '../../py/dict.ts';
import { pyEq } from '../../py/eq.ts';
import { getLogger } from '../../py/logging.ts';
import { pyFloatParse, pyInt, pyRound } from '../../py/number.ts';
import { pyMax, pyMaxN, pyMinN } from '../../py/sort.ts';
import { pyLower, pyStr } from '../../py/str.ts';
import { isDict, pyOr, truthy } from '../../py/truthy.ts';
import { normalize_diagram_type } from '../../common/diagram_types.ts';
import { ICON_KEY, bundled_icons, icon_file } from '../../common/node_icons.ts';
import { unwrap_structure_instantiation } from '../../common/spec_utils.ts';
import { preserve_explicit_design } from '../../common/design_constraints.ts';
import { CAPTION_TYPES, is_caption, place_captions } from './caption_placer.ts';
import {
  _ICON_KEYWORDS,
  _MUTED,
  _MUTED_TITLE_INK,
  _PRIMARY_STROKE_WIDTH,
  aesthetic_enabled,
  emphasis_of,
  _SUBLABEL_INK,
  _TITLE_INK,
  _hex,
  _mix,
  is_enabled,
} from './architecture_design_system.ts';

type Dict = Record<string, unknown>;
type Point = [number, number];

export const logger = getLogger('evodesign.agentic_system.render_engine.excalidraw.design_theme');

// Node-and-link types take the full treatment. Area types (blocks whose fill
// is the content) keep more of their colour so neighbouring blocks stay
// distinct. Venn diagrams are excluded: their overlaps are drawn by
// translucent fills that a lighter tint washes out.
export const LINK_TYPES = new Set([
  'flowchart', 'swimlane', 'data_flow_diagram', 'state_diagram', 'sequence_diagram',
  'class_diagram', 'er_diagram', 'network_topology', 'orgchart', 'tree', 'mindmap',
  'concept_map', 'fishbone', 'dependency_graph', 'cycle', 'deployment',
]);
export const AREA_TYPES = new Set([
  'gantt', 'timeline', 'funnel', 'pyramid', 'swot', 'matrix', 'infographic',
  'layer_stack', 'nested', 'quadrant', 'user_journey', 'kanban', 'story_map',
]);
export const THEMED_TYPES = new Set([...LINK_TYPES, ...AREA_TYPES]);
// Chen-notation ER links carry no direction, whatever heads the agents drew.
export const UNDIRECTED_TYPES = new Set(['er_diagram', 'user_journey']);
export const _LINK_TINT = 0.55;
export const _LEAF_TINT = 0.75;
// Types whose hierarchy is the tree itself: the root leads and leaves recede.
export const TREE_TYPES = new Set(['mindmap', 'tree', 'orgchart']);
export const _AREA_TINT = 0.3;
export const THEME_KEY = 'evoDesignTheme';
export const _STROKE_WIDTH = 1.5;

function hasOwn(obj: object, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(obj, key);
}

function _float(value: unknown): number {
  return pyFloatParse(value as number | string | boolean);
}

/** The border colour, darkened when too light to carry an icon or a connector. */
export function _ink(stroke: readonly number[]): string {
  const luminance = (0.299 * stroke[0] + 0.587 * stroke[1] + 0.114 * stroke[2]) / 255;
  return _mix(luminance < 0.62 ? stroke : stroke.map((c) => pyRound(c * 0.55)), 0);
}

/** The outline twin of the agent's icon, else one matched on the label. */
export function _outline_icon(label: string, current: string): string {
  if (current.startsWith('outline_')) {
    return current;
  }
  const outline = `outline_${current}`;
  if (hasOwn(bundled_icons(), outline)) {
    return outline;
  }
  const haystack = pyLower(label);
  for (const [needles, name] of _ICON_KEYWORDS) {
    if (needles.some((needle) => haystack.includes(needle))) {
      return name;
    }
  }
  return current;
}

/** Plain heads become solid triangles; UML heads (hollow triangle, diamond) keep their meaning. */
export function _head(value: unknown): unknown {
  return value === 'arrow' ? 'triangle' : value;
}

/** Root reads as primary and leaves recede, unless the agent said otherwise. */
export function _tree_emphasis(nodes: Dict[], edges: unknown[], agent: Record<string, string>): Record<string, string> {
  const ids = new Set(nodes.map((n) => pyStr(pyGetItem(n, 'id'))));
  const children = new Map<string, string[]>();
  const parent = new Map<string, string>();
  for (const edge of edges) {
    if (!isDict(edge)) {
      continue;
    }
    const source = pyStr(pyGet(edge, 'source'));
    const target = pyStr(pyGet(edge, 'target'));
    if (ids.has(source) && ids.has(target) && !parent.has(target)) {
      parent.set(target, source);
      if (!children.has(source)) children.set(source, []);
      children.get(source)!.push(target);
    }
  }
  for (const node of nodes) {
    const pid = pyOr(pyGet(node, 'parent_id'), pyGet(node, 'parent'));
    const nid = pyStr(pyGetItem(node, 'id'));
    if (truthy(pid) && ids.has(pyStr(pid)) && !parent.has(nid)) {
      parent.set(nid, pyStr(pid));
      if (!children.has(pyStr(pid))) children.set(pyStr(pid), []);
      children.get(pyStr(pid))!.push(nid);
    }
  }
  const roots = [...ids].filter((i) => !parent.has(i) && children.has(i));
  const result: Record<string, string> = Object.assign(Object.create(null), agent);
  for (const node_id of ids) {
    if (truthy(pyGet(result, node_id))) {
      continue;
    }
    if (roots.includes(node_id) && roots.length === 1) {
      result[node_id] = 'primary';
    } else if (!children.has(node_id) && parent.has(node_id) && !roots.includes(parent.get(node_id)!)) {
      result[node_id] = 'leaf';
    }
  }
  return result;
}

// Process types read along one happy path from start to end.
export const MAIN_PATH_TYPES = new Set(['flowchart', 'swimlane']);
export const _POSITIVE = ['yes', '是', '通过', '成功', 'ok', 'pass', 'approve', '批准', '同意', 'true'];
export const _SIDE_OPACITY = 60;

type Walk = [number, number, unknown[]];

/** Edges of the longest start-to-end run, preferring positive branches; back edges ignored. */
export function _main_path(nodes: Dict[], edges: unknown[]): Set<unknown> {
  const ids = nodes.map((n) => pyStr(pyGetItem(n, 'id')));
  const out = new Map<string, Dict[]>();
  const incoming = new Set<string>();
  for (const edge of edges) {
    if (isDict(edge) && ids.includes(pyStr(pyGet(edge, 'source'))) && ids.includes(pyStr(pyGet(edge, 'target')))) {
      const source = pyStr(pyGetItem(edge, 'source'));
      if (!out.has(source)) out.set(source, []);
      out.get(source)!.push(edge);
      incoming.add(pyStr(pyGetItem(edge, 'target')));
    }
  }
  let starts = nodes.filter((n) => pyGet(n, 'class') === 'start').map((n) => pyStr(pyGetItem(n, 'id')));
  if (!starts.length) starts = ids.filter((i) => !incoming.has(i));
  const best = new Map<string, Walk>();
  const key = (r: Walk) => [r[0], r[1]];

  const walk = (node: string, seen: Set<string>): Walk => {
    if (best.has(node)) {
      return best.get(node)!;
    }
    let result: Walk = [0, 0, []];
    for (const edge of out.get(node) ?? []) {
      const target = pyStr(pyGetItem(edge, 'target'));
      if (seen.has(target)) {
        continue;
      }
      const [length, positive, path] = walk(target, new Set([...seen, target]));
      const label = pyLower(pyStr(pyOr(pyGet(edge, 'label'), '')));
      const candidate: Walk = [
        length + 1,
        positive + (_POSITIVE.some((w) => label.includes(w)) ? 1 : 0),
        [pyGet(edge, 'id'), ...path],
      ];
      result = pyMax([result, candidate], key);
    }
    best.set(node, result);
    return result;
  };

  const paths = starts.map((s) => walk(s, new Set([s])));
  const chosen = pyMax(paths, key, [0, 0, []] as Walk);
  const result = new Set<unknown>(chosen[2]);
  result.delete(null);
  return result;
}

/** Whether a polyline passes through any box (sampled; boxes shrunk by 2px). */
export function _crosses(points: readonly (readonly number[])[], boxes: Dict[]): boolean {
  for (let k = 0; k + 1 < points.length; k++) {
    const [x1, y1] = points[k];
    const [x2, y2] = points[k + 1];
    const steps = Math.max(2, Math.trunc(Math.max(Math.abs(x2 - x1), Math.abs(y2 - y1)) / 8));
    for (let i = 0; i < steps + 1; i++) {
      const x = x1 + (x2 - x1) * i / steps;
      const y = y1 + (y2 - y1) * i / steps;
      if (boxes.some((b) => {
        const bx = b.x as number;
        const by = b.y as number;
        return bx + 2 < x && x < bx + (b.width as number) - 2 && by + 2 < y && y < by + (b.height as number) - 2;
      })) {
        return true;
      }
    }
  }
  return false;
}

function _rect(element: PyMapping): [number, number, number, number] {
  return ['x', 'y', 'width', 'height'].map((k) => _float(pyGetItem(element, k))) as [number, number, number, number];
}

/** The straight branch, else one bend around whatever node it would cross. */
export function _clear_branch(parent: Dict, child: Dict, boxes: Dict[]): Point[] {
  const straight = _branch_points(parent, child);
  if (!_crosses(straight, boxes)) {
    return straight;
  }
  const [px, py, pw, ph] = _rect(parent);
  const [cx, cy, cw, ch] = _rect(child);
  const right = cx + cw / 2 > px + pw / 2;
  const down = cy + ch / 2 > py + ph / 2;
  const vertical_x = px + pw / 2;
  const side_y = py + ph / 2;
  const bends: Point[][] = [
    // Leave through top or bottom, turn into the child's near side.
    [[vertical_x, down ? py + ph : py], [vertical_x, cy + ch / 2], [right ? cx : cx + cw, cy + ch / 2]],
    // Leave through the near side, turn into the child's top or bottom.
    [[right ? px + pw : px, side_y], [cx + cw / 2, side_y], [cx + cw / 2, down ? cy : cy + ch]],
  ];
  return bends.find((b) => !_crosses(b, boxes)) ?? straight;
}

/**
 * A mind-map branch: one straight stroke from the parent's facing side to the child's.
 *
 * Smoothed or elbowed strokes were tried; Excalidraw's curve through the bend
 * points overshoots into loops, and elbows stack into ladders beside the parent.
 *
 * The axis with the wider gap between the two boxes wins, so a child above
 * its parent is reached from the top edge instead of grazing the side.
 */
export function _branch_points(parent: Dict, child: Dict): Point[] {
  const [px, py, pw, ph] = _rect(parent);
  const [cx, cy, cw, ch] = _rect(child);
  const gap_x = pyMaxN(cx - (px + pw), px - (cx + cw));
  const gap_y = pyMaxN(cy - (py + ph), py - (cy + ch));
  if (gap_x >= gap_y) {
    const right = cx + cw / 2 > px + pw / 2;
    const start: Point = [right ? px + pw : px, py + ph / 2];
    return [start, [right ? cx : cx + cw, cy + ch / 2]];
  }
  const down = cy + ch / 2 > py + ph / 2;
  const start: Point = [px + pw / 2, down ? py + ph : py];
  return [start, [cx + cw / 2, down ? cy : cy + ch]];
}

/** Restyle a non-architecture scene in place of its old treatment; unchanged on any doubt. */
export function apply_design_theme(manifest: unknown, structure_instantiation: unknown,
  layout_instantiation: Dict | null = null,
  design_constraints = ''): unknown {
  if (!is_enabled() || !isDict(manifest)) {
    return manifest;
  }
  if (preserve_explicit_design(manifest, design_constraints)) {
    return manifest;
  }
  const structure = unwrap_structure_instantiation(structure_instantiation);
  const chart_type = normalize_diagram_type(pyStr(pyOr(pyGet(structure, 'chart_type'), '')));
  if (!THEMED_TYPES.has(chart_type)) {
    return manifest;
  }

  const result = pyDeepcopy(manifest) as Dict;
  const elements = pyOr(pyGet(result, 'elements'), []) as Dict[];
  // NB: Python rebinds ``meta`` inside the mind-map/cycle loop below, so
  // ``meta["design_theme"]`` lands on the last arrow's meta there (ported as-is).
  let meta = pySetdefault<unknown>(result, '_meta', {}) as Dict;
  const id_map = pyOr(pyGet(meta, 'id_map'), {}) as PyMapping;
  const by_eid = new Map<unknown, Dict>();
  for (const e of elements) by_eid.set(pyGet(e, 'id'), e);
  const getEid = (key: unknown): Dict | null => (by_eid.has(key) ? by_eid.get(key)! : null);
  const nodes = (pyOr(pyGet(structure, 'nodes'), []) as unknown[])
    .filter((n): n is Dict => isDict(n) && truthy(pyGet(n, 'id')));
  const styling: Dict = isDict(layout_instantiation) ? layout_instantiation : {};
  const files = pySetdefault<unknown>(result, 'files', {}) as Dict;

  let emphasis: Record<string, string> = Object.create(null);
  for (const n of nodes) emphasis[pyStr(n.id)] = emphasis_of(n);
  if (TREE_TYPES.has(chart_type)) {
    emphasis = _tree_emphasis(nodes, pyOr(pyGet(structure, 'edges'), []) as unknown[], emphasis);
  }
  const use_emphasis = aesthetic_enabled('EMPHASIS');

  const host_ink = new Map<unknown, string>();
  const node_ink = new Map<string, string>();
  const muted_hosts = new Set<unknown>();
  for (const node of nodes) {
    const host = getEid(pyGet(id_map, pyStr(node.id), ''));
    if (!truthy(host) || !['rectangle', 'ellipse', 'diamond'].includes(pyGet(host!, 'type') as string)) {
      continue;
    }
    const h = host!;
    if (CAPTION_TYPES.has(chart_type) && is_caption(node)) {
      // Axis names and stated rules caption the figure; they are not items in it.
      assignF(h, {
        backgroundColor: 'transparent', strokeColor: 'transparent', roughness: 0,
        customData: { ...(pyOr(pyGet(h, 'customData'), {}) as Dict), [THEME_KEY]: true },
        version: pyInt(pyGet(h, 'version', 1) as number) + 1,
      });
      host_ink.set(h.id, _TITLE_INK);
      node_ink.set(pyStr(node.id), _TITLE_INK);
      continue;
    }
    const rawStyle = pyGet(styling, node.id);
    const style: Dict = isDict(rawStyle) ? rawStyle : {};
    const fill = _hex(pyGet(style, 'backgroundColor')) ?? _hex(pyGet(h, 'backgroundColor'));
    const tint = AREA_TYPES.has(chart_type) ? _AREA_TINT : _LINK_TINT;
    const stroke = _hex(pyGet(style, 'strokeColor')) ?? _hex(pyGet(h, 'strokeColor'));
    if (!fill || !stroke) {
      continue;
    }
    let ink: unknown = _ink(stroke);
    const level = use_emphasis ? pyGet(emphasis, pyStr(node.id), '') : '';
    let background: unknown = _mix(fill, tint);
    let width: unknown = _STROKE_WIDTH;
    if (level === 'primary') {
      background = _mix(_hex(ink)!, 0.82);
      width = _PRIMARY_STROKE_WIDTH;
    } else if (level === 'leaf') {
      background = _mix(fill, _LEAF_TINT);
      width = 1;
    } else if (level === 'muted') {
      background = _MUTED[0];
      ink = _MUTED[2];
      width = 1;
      muted_hosts.add(h.id);
    }
    // The styling agent has already resolved explicit palette requests.
    // Add defaults only where it left the corresponding property unspecified.
    background = pyGet(style, 'backgroundColor', background);
    ink = pyGet(style, 'strokeColor', ink);
    width = pyGet(style, 'strokeWidth', width);
    // strokeWidth: the styling value keeps its own type; defaults are 1.5 / 2.5 / the int 1.
    assignF(h, {
      backgroundColor: background, strokeColor: ink, strokeWidth: width,
      roughness: 0, fillStyle: 'solid',
      customData: { ...(pyOr(pyGet(h, 'customData'), {}) as Dict), [THEME_KEY]: true },
      version: pyInt(pyGet(h, 'version', 1) as number) + 1,
    });
    if (h.type === 'rectangle') {
      h.roundness = { type: 3 };
    }
    markF(h, 'strokeWidth', hasOwn(style, 'strokeWidth') ? isF(style, 'strokeWidth') : !Number.isInteger(width));
    host_ink.set(h.id, ink as string);
    node_ink.set(pyStr(node.id), ink as string);
  }

  for (const element of elements) {
    const kind = pyGet(element, 'type');
    if (kind === 'text' && host_ink.has(pyGet(element, 'containerId'))) {
      const ink = muted_hosts.has(pyGet(element, 'containerId')) ? _MUTED_TITLE_INK : _TITLE_INK;
      assignF(element, { strokeColor: ink, roughness: 0 });
    } else if (kind === 'image') {
      const data = pyOr(pyGet(pyOr(pyGet(element, 'customData'), {}), ICON_KEY), {}) as Dict;
      const host_id = pyGet(data, 'hostId');
      if (!host_ink.has(host_id) || !truthy(pyGet(data, 'name'))) {
        continue;
      }
      const label = elements
        .filter((t) => pyGet(t, 'type') === 'text' && pyGet(t, 'containerId') === host_id)
        .map((t) => pyStr(pyOr(pyGet(t, 'text'), '')))
        .join(' ');
      const name = _outline_icon(label, pyStr(data.name));
      if (!hasOwn(bundled_icons(), name)) {
        continue;
      }
      const asset = icon_file(name, host_ink.get(host_id)!);
      files[asset.id as string] = asset;
      Object.assign(element, {
        fileId: asset.id,
        customData: { ...(pyOr(pyGet(element, 'customData'), {}) as Dict), [ICON_KEY]: { ...data, name } },
      });
    }
  }

  let main_edges = new Set<unknown>();
  if (MAIN_PATH_TYPES.has(chart_type) && aesthetic_enabled('MAINPATH')) {
    main_edges = _main_path(nodes, pyOr(pyGet(structure, 'edges'), []) as unknown[]);
  }
  const arrow_ids = new Set<unknown>();
  for (const element of elements) {
    if (pyGet(element, 'type') !== 'arrow') {
      continue;
    }
    let source = pyStr(pyOr(pyGet(pyOr(pyGet(element, 'meta'), {}), 'source'), ''));
    if (!source) {
      const binding = pyOr(pyGet(element, 'startBinding'), {}) as Dict;
      const elementId = pyGet(binding, 'elementId');
      const hit = pyItems(id_map).find(([, eid]) => pyEq(eid, elementId));
      source = (hit ? hit[0] : '') as string;
    }
    const on_main = main_edges.has(pyGet(pyOr(pyGet(element, 'meta'), {}), 'semantic_edge_id'));
    const endHead = pyGet(element, 'endArrowhead');
    const startHead = pyGet(element, 'startArrowhead');
    const undirected = UNDIRECTED_TYPES.has(chart_type);
    const plain = (v: unknown) => v === null || v === 'arrow' || v === 'triangle';
    assignF(element, {
      strokeColor: node_ink.has(source) ? node_ink.get(source)! : _SUBLABEL_INK,
      strokeWidth: on_main ? _PRIMARY_STROKE_WIDTH : _STROKE_WIDTH,
      opacity: on_main || !main_edges.size ? 100 : _SIDE_OPACITY,
      // Undirected links (ER, mind map) stay undirected.
      roughness: 0,
      endArrowhead: undirected && plain(endHead) ? null : _head(endHead),
      startArrowhead: undirected && plain(startHead) ? null : _head(startHead),
    });
    arrow_ids.add(pyGet(element, 'id'));
  }
  // Mind-map links show belonging, not flow: no heads, side to side.
  // Mind-map branches, cycle steps and journey feelings link neighbours that
  // face each other; an elbow between near-aligned sides degenerates into a
  // stub, and a feeling curve drawn in steps no longer reads as a curve.
  const mindmap = chart_type === 'mindmap' && aesthetic_enabled('MINDLINKS');
  const headless = mindmap || chart_type === 'user_journey';
  if (headless || chart_type === 'cycle' || chart_type === 'user_journey') {
    for (const element of elements) {
      if (pyGet(element, 'type') !== 'arrow') {
        continue;
      }
      meta = pyOr(pyGet(element, 'meta'), {}) as Dict;
      const emeta = meta;
      const parent = pyOr(
        getEid(pyGet(id_map, pyStr(pyOr(pyGet(emeta, 'source'), '')), '')),
        getEid(pyGet(pyOr(pyGet(element, 'startBinding'), {}), 'elementId')),
      );
      const child = pyOr(
        getEid(pyGet(id_map, pyStr(pyOr(pyGet(emeta, 'target'), '')), '')),
        getEid(pyGet(pyOr(pyGet(element, 'endBinding'), {}), 'elementId')),
      );
      if (!truthy(parent) || !truthy(child)) {
        continue;
      }
      const p = parent!;
      const c = child!;
      const boxes = [...host_ink.keys()].filter((e) => e !== p.id && e !== c.id).map((e) => pyGetItem(by_eid, e));
      const points = _clear_branch(p, c, boxes);
      const [ox, oy] = points[0];
      const xs = points.map((pt) => pt[0]);
      const ys = points.map((pt) => pt[1]);
      // _branch_points / _clear_branch build every coordinate from float(...).
      const relative = points.map(([x, y]) => [x - ox, y - oy]);
      for (const point of relative) {
        markF(point, 0, true);
        markF(point, 1, true);
      }
      assignF(element, {
        x: ox, y: oy, points: relative,
        width: pyMaxN(...xs) - pyMinN(...xs), height: pyMaxN(...ys) - pyMinN(...ys),
        elbowed: false,
        startArrowhead: headless ? null : pyGet(element, 'startArrowhead'),
        endArrowhead: headless ? null : pyGet(element, 'endArrowhead'),
        roundness: null,
        startBinding: { elementId: p.id, focus: 0, gap: 1 },
        endBinding: { elementId: c.id, focus: 0, gap: 1 },
      }, ['x', 'y', 'width', 'height']);
      for (const host of [p, c]) {
        const bindings = pySetdefault(host, 'boundElements', [] as unknown) as Dict[];
        if (!bindings.some((binding) => pyEq(pyGet(binding, 'id'), element.id))) {
          bindings.push({ id: element.id, type: 'arrow' });
        }
      }
      for (const label of elements) {
        if (pyGet(label, 'type') === 'text' && pyEq(pyGet(label, 'containerId'), element.id)) {
          assignF(label, {
            x: (points[0][0] + points[points.length - 1][0] - (label.width as number)) / 2,
            y: (points[0][1] + points[points.length - 1][1] - (label.height as number)) / 2,
          }, ['x', 'y']);
        }
      }
    }
  }
  for (const element of elements) {
    if (pyGet(element, 'type') === 'text' && arrow_ids.has(pyGet(element, 'containerId'))) {
      assignF(element, { strokeColor: _SUBLABEL_INK, fontFamily: 2, roughness: 0 });
    }
  }

  place_captions(chart_type, structure, elements, id_map);

  const used_files = new Set(elements.filter((e) => pyGet(e, 'type') === 'image').map((e) => pyGet(e, 'fileId')));
  result.files = Object.fromEntries(Object.entries(files).filter(([k]) => used_files.has(k)));
  pySetdefault<unknown>(pySetdefault<unknown>(result, 'appState', {}) as Dict, 'viewBackgroundColor', '#FFFFFF');
  meta.design_theme = { chart_type, nodes: host_ink.size };
  logger.info('[DesignTheme] Applied to %d nodes of a %s', host_ink.size, chart_type);
  return result;
}
