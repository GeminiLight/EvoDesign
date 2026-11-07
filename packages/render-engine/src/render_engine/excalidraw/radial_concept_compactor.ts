// Ported from evodesign/agentic_system/render_engine/excalidraw/radial_concept_compactor.py — keep in sync.
//
// Choose a compact, topology-aware layout for concept maps.
//
// Representation notes (see migration/notes/WP06.md):
// - ``elements_by_id`` built here is a ``Map<string, Dict>`` (insertion order
//   preserved for any id); functions also accept a plain object, as the parity
//   fixtures pass one.
// - ``_dependency_layers`` returns ``Map<number, string[]>`` (Python int keys).
// - Branch interactions are ``Map<[string, string], number>`` (Python tuple
//   keys); lookups go through a string index.
// - Python sets are ``Set``. Where Python iterates a set and order could leak
//   into the output (``_stacked_branch_rows`` semantic targets), the port uses
//   insertion order; see notes.

import { markF, pyDeepcopy, pyUpdate } from '../../py/float_marks.ts';
import { id_map_from_manifest } from '../../common/semantic_ids.ts';
import { unwrap_structure_instantiation } from '../../common/spec_utils.ts';
import { _estimate_text_dimensions } from '../../generation_stage/layout/element_shape_estimator.ts';
import { pySetItem, pyGet, pyGetItem, pyItems, pyKeys, pyPop, pySetdefault, pyValues } from '../../py/dict.ts';
import { pyEq, pyIn } from '../../py/eq.ts';
import { PyTypeError, StopIteration, ValueError } from '../../py/errors.ts';
import { sha256Hex } from '../../py/hash.ts';
import { getLogger } from '../../py/logging.ts';
import { ceil, hypot, log } from '../../py/math.ts';
import { floorDiv, pyFloatParse, pyInt, pyMod, pyRound, pySum } from '../../py/number.ts';
import { pyLt, pyMax, pyMaxN, pyMin, pyMinN, pySort, pySorted } from '../../py/sort.ts';
import { cpChars, pyEndswith, pyLower, pyRsplit, pySlice, pyStr, pyStrip } from '../../py/str.ts';
import { isDict, isMapping, isStr, pyOr, truthy } from '../../py/truthy.ts';

type Dict = Record<string, any>;
type ElementsById = Map<string, Dict> | Record<string, Dict>;
type StrMapping = Record<string, any> | Map<unknown, any>;
type Interactions = Map<unknown, number> | Record<string, number>;
type Sector = [number, number, number, number];

export const _CONCEPT_MAP: ReadonlySet<string> = new Set(['concept_map', 'concept map', 'conceptmap']);
export const logger = getLogger('evodesign.agentic_system.render_engine.excalidraw.radial_concept_compactor');
export const _SLOT_ORDER = ['upper_left', 'upper_right', 'lower_left', 'lower_right'] as const;
export const _NODE_FONT_SIZE = 16;
export const _SECTION_FONT_SIZE = 18;
export const _RELATION_FONT_SIZE = 14;

// Stable semantic colors make repeated generations comparable and keep the
// branch meaning visible even when the styling model chooses a different
// palette family on each call. These are intentionally light fills paired with
// the same-family dark strokes used by the styling contract.
export const _CONCEPT_PALETTE: Record<string, Record<string, string>> = {
  core: {
    anchor: '#202124',
    leaf: '#202124',
    frame: '#FFFFFF',
    stroke: '#202124',
    text: '#FFFFFF',
  },
  upper_left: {
    anchor: '#F3D6D8',
    leaf: '#FCEBED',
    frame: '#FFF7F8',
    stroke: '#9E4F61',
    text: '#43242C',
  },
  lower_left: {
    anchor: '#D8E6D1',
    leaf: '#ECF4E8',
    frame: '#F8FCF6',
    stroke: '#56765A',
    text: '#243D28',
  },
  upper_right: {
    anchor: '#D2E9EB',
    leaf: '#E9F5F6',
    frame: '#F5FBFB',
    stroke: '#3F7E8C',
    text: '#173D45',
  },
  lower_right: {
    anchor: '#F1E4C7',
    leaf: '#FAF2E2',
    frame: '#FFFAF0',
    stroke: '#8A6A2F',
    text: '#493817',
  },
  branch_1: {
    anchor: '#DDE7F5',
    leaf: '#EFF4FB',
    frame: '#F8FAFD',
    stroke: '#4D6D99',
    text: '#243A59',
  },
  branch_2: {
    anchor: '#E6DFF0',
    leaf: '#F3EFF8',
    frame: '#FBF9FD',
    stroke: '#75608F',
    text: '#372A49',
  },
  branch_3: {
    anchor: '#F2DED4',
    leaf: '#FAEEE8',
    frame: '#FDF9F7',
    stroke: '#9A6650',
    text: '#4B3025',
  },
  branch_4: {
    anchor: '#DDE8DE',
    leaf: '#EEF5EF',
    frame: '#F8FBF8',
    stroke: '#607A63',
    text: '#2D402F',
  },
};

export const _NEUTRAL_CONNECTOR = '#64707A';
export const _STRUCTURAL_CONNECTOR = '#A8B0B7';
export const _STRUCTURAL_RELATION_TYPES: ReadonlySet<string> = new Set(['hierarchy', 'composition', 'exemplification']);
export const _STRUCTURAL_RELATION_LABELS: ReadonlySet<string> = new Set([
  'organized into',
  'has subtype',
  'includes',
  'contains',
  'has example',
  'exemplifies',
]);

// ---------------------------------------------------------------------------
// Private helpers (TS only)
// ---------------------------------------------------------------------------

/** ``str(x).strip().lower()`` */
function _norm(value: unknown): string {
  return pyLower(pyStrip(pyStr(value)));
}

/** ``x in set_like`` for the Python sets passed around in this module. */
function _has(container: unknown, item: unknown): boolean {
  if (container instanceof Set) return container.has(item);
  return pyIn(item, container);
}

/** Python ``set == set`` (both operands are sets of strings here). */
function _setEq(a: unknown, b: unknown): boolean {
  return pyEq(a instanceof Set ? a : new Set(a as Iterable<unknown>), b instanceof Set ? b : new Set(b as Iterable<unknown>));
}

/** ``for x in iterable`` over what a structure field may hold. */
function _iter(value: unknown): unknown[] {
  if (Array.isArray(value)) return value;
  if (value instanceof Set) return [...value];
  if (value instanceof Map) return [...value.keys()];
  if (isDict(value)) return Object.keys(value);
  if (typeof value === 'string') return cpChars(value);
  throw new PyTypeError(`'${value === null ? 'NoneType' : typeof value}' object is not iterable`);
}

function _pairKey(pair: readonly unknown[]): string {
  return JSON.stringify(pair);
}

/** ``itertools.permutations(pool)`` — CPython's algorithm, same emission order. */
export function* _permutations<T>(iterable: Iterable<T>, r?: number): Generator<T[]> {
  const pool = [...iterable];
  const n = pool.length;
  const k = r === undefined ? n : r;
  if (k > n) return;
  const indices = Array.from({ length: n }, (_, i) => i);
  const cycles = Array.from({ length: k }, (_, i) => n - i);
  yield indices.slice(0, k).map((i) => pool[i]);
  if (n === 0) return;
  for (;;) {
    let i = k - 1;
    for (; i >= 0; i -= 1) {
      cycles[i] -= 1;
      if (cycles[i] === 0) {
        const moved = indices[i];
        indices.splice(i, 1);
        indices.push(moved);
        cycles[i] = n - i;
      } else {
        const j = cycles[i];
        const swapIndex = n - j;
        const tmp = indices[i];
        indices[i] = indices[swapIndex];
        indices[swapIndex] = tmp;
        yield indices.slice(0, k).map((index) => pool[index]);
        break;
      }
    }
    if (i < 0) return;
  }
}

/** ``itertools.combinations(pool, 2)`` */
function* _combinations2<T>(pool: readonly T[]): Generator<[T, T]> {
  for (let i = 0; i < pool.length; i += 1) {
    for (let j = i + 1; j < pool.length; j += 1) yield [pool[i], pool[j]];
  }
}

function _elementsByIdFromManifest(manifest: Dict, mappingCheck: boolean): Map<string, Dict> {
  const elements_by_id = new Map<string, Dict>();
  for (const element of _iter(pyGet(manifest, 'elements', []))) {
    if ((mappingCheck ? isMapping(element) : isDict(element)) && truthy(pyGet(element, 'id'))) {
      elements_by_id.set(pyStr(pyGet(element, 'id')), element as Dict);
    }
  }
  return elements_by_id;
}

function _ebGet(elements_by_id: ElementsById, key: string): Dict | null {
  return pyGet(elements_by_id as StrMapping, key, null) as Dict | null;
}

function _ebValues(elements_by_id: ElementsById): Dict[] {
  return pyValues(elements_by_id as StrMapping) as Dict[];
}

function _ebSet(elements_by_id: ElementsById, key: string, value: Dict): void {
  pySetItem(elements_by_id, key, value);
}

// ---------------------------------------------------------------------------
// Ported functions
// ---------------------------------------------------------------------------

/** Return a stable palette without depending on the branch's subject text. */
export function _palette_for_branch(branch_id: unknown): Record<string, string> {
  if (Array.isArray(branch_id) || isMapping(branch_id) || branch_id instanceof Set) {
    throw new PyTypeError('unhashable type');
  }
  if (isStr(branch_id) && Object.prototype.hasOwnProperty.call(_CONCEPT_PALETTE, branch_id)) {
    return _CONCEPT_PALETTE[String(branch_id)];
  }
  if (isStr(branch_id) && branch_id.startsWith('branch_')) {
    let branch_number: number;
    try {
      branch_number = pyInt(pyRsplit(branch_id, '_', 1)[1]);
    } catch (error) {
      if (error instanceof PyTypeError || error instanceof ValueError) branch_number = 1;
      else throw error;
    }
    const overflow_keys = ['branch_1', 'branch_2', 'branch_3', 'branch_4'];
    return _CONCEPT_PALETTE[overflow_keys[pyMod(branch_number - 1, overflow_keys.length)]];
  }
  return _CONCEPT_PALETTE.upper_left;
}

/** Reserve four sectors around a center gap at any supported viewport. */
export function _sectors(width: number, height: number): Record<string, Sector> {
  const margin_x = pyMaxN(40.0, width * 0.04);
  const margin_y = pyMaxN(40.0, height * 0.05);
  const gap_x = pyMaxN(180.0, width * 0.15);
  const gap_y = pyMaxN(140.0, height * 0.16);
  const sector_width = pyMaxN(260.0, (width - 2.0 * margin_x - gap_x) / 2.0);
  const sector_height = pyMaxN(220.0, (height - 2.0 * margin_y - gap_y) / 2.0);
  const left = margin_x;
  const right = width - margin_x - sector_width;
  const top = margin_y;
  const bottom = height - margin_y - sector_height;
  return {
    upper_left: [left, top, sector_width, sector_height],
    lower_left: [left, bottom, sector_width, sector_height],
    upper_right: [right, top, sector_width, sector_height],
    lower_right: [right, bottom, sector_width, sector_height],
  };
}

/** ``float(value)`` falling back to ``default`` on TypeError/ValueError. */
export function _number(value: unknown, default_: number = 0.0): number {
  if (typeof value === 'number') return value;
  if (typeof value === 'boolean') return value ? 1 : 0;
  if (typeof value === 'string') {
    try {
      return pyFloatParse(value);
    } catch (error) {
      if (error instanceof ValueError) return default_;
      throw error;
    }
  }
  return default_;
}

export function _node_shape(elements_by_id: ElementsById, id_map: StrMapping, node_id: string): Dict | null {
  const element = _ebGet(elements_by_id, pyStr(pyGet(id_map, node_id, '')));
  if (!truthy(element) || ['arrow', 'text', 'image'].includes(pyGet(element, 'type') as string)) {
    return null;
  }
  return element;
}

export function _move_node(
  elements_by_id: ElementsById,
  id_map: StrMapping,
  node_id: string,
  x: number,
  y: number,
): null {
  const shape = _node_shape(elements_by_id, id_map, node_id);
  if (shape === null) {
    return null;
  }
  const dx = x - _number(pyGet(shape, 'x'));
  const dy = y - _number(pyGet(shape, 'y'));
  shape.x = x;
  shape.y = y;
  // Every caller passes float positions (_number() / ``... / 2.0`` arithmetic).
  markF(shape, 'x', true);
  markF(shape, 'y', true);
  for (const element of _ebValues(elements_by_id)) {
    if (element === shape) {
      continue;
    }
    if (pyEq(pyGet(element, 'containerId'), pyGet(shape, 'id'))) {
      element.x = _number(pyGet(element, 'x')) + dx;
      element.y = _number(pyGet(element, 'y')) + dy;
      markF(element, 'x', true);
      markF(element, 'y', true);
    }
  }
  return null;
}

export function _bound_text_elements(elements_by_id: ElementsById, shape: Dict): Dict[] {
  const shape_id = pyGet(shape, 'id');
  return _ebValues(elements_by_id).filter(
    (element) => pyGet(element, 'type') === 'text' && pyEq(pyGet(element, 'containerId'), shape_id),
  );
}

export function _sync_bound_text(elements_by_id: ElementsById, shape: Dict): null {
  for (const text of _bound_text_elements(elements_by_id, shape)) {
    const dimensions = _estimate_text_dimensions(
      pyStr(pyOr(pyGet(text, 'text'), '')),
      pyInt(pyOr(pyGet(text, 'fontSize'), 16) as number | string | boolean),
    );
    pyUpdate(text, dimensions);
    text.x = _number(pyGet(shape, 'x')) + (_number(pyGet(shape, 'width')) - _number(pyGet(text, 'width'))) / 2.0;
    text.y = _number(pyGet(shape, 'y')) + (_number(pyGet(shape, 'height')) - _number(pyGet(text, 'height'))) / 2.0;
    markF(text, 'x', true);
    markF(text, 'y', true);
  }
  return null;
}

/** Resize around the current center and keep bound text centered. */
export function _resize_node(
  elements_by_id: ElementsById,
  id_map: StrMapping,
  node_id: string,
  width: number,
  height: number,
): null {
  const shape = _node_shape(elements_by_id, id_map, node_id);
  if (shape === null) {
    return null;
  }
  const [center_x, center_y] = _shape_center(shape);
  shape.width = width;
  shape.height = height;
  shape.x = center_x - width / 2.0;
  shape.y = center_y - height / 2.0;
  // Every caller passes float sizes (float constants / _number() arithmetic).
  for (const key of ['width', 'height', 'x', 'y']) markF(shape, key, true);
  _sync_bound_text(elements_by_id, shape);
  return null;
}

export function _stable_element_number(namespace: string, semantic_id: string): number {
  const digest = sha256Hex(`${pyStr(namespace)}:${pyStr(semantic_id)}`);
  return (parseInt(digest.slice(0, 12), 16) % 2_000_000_000) + 1;
}

export function _concept_frame(
  anchor_id: string,
  slot_name: string,
  x: number,
  y: number,
  width: number,
  height: number,
): Dict {
  const palette = _palette_for_branch(slot_name);
  const render_id = sha256Hex(`concept-frame:${pyStr(anchor_id)}`).slice(0, 20);
  const frame: Dict = {
    id: render_id,
    type: 'rectangle',
    x,
    y,
    width,
    height,
    angle: 0,
    strokeColor: palette.stroke,
    backgroundColor: palette.frame,
    fillStyle: 'solid',
    strokeWidth: 1,
    strokeStyle: 'solid',
    roughness: 0,
    opacity: 100,
    groupIds: [],
    frameId: null,
    index: 'a00000',
    roundness: { type: 3 },
    seed: _stable_element_number('concept-frame-seed', anchor_id),
    version: 2,
    versionNonce: _stable_element_number('concept-frame-version', anchor_id),
    isDeleted: false,
    boundElements: [],
    updated: 1,
    link: null,
    locked: false,
    is_group: true,
  };
  // Callers pass float geometry (``40.0 + ...`` / band sizes).
  for (const key of ['x', 'y', 'width', 'height']) markF(frame, key, true);
  return frame;
}

/** Apply a compact draw.io-like rounded-rectangle shape system. */
export function _normalize_concept_shape_language(
  elements_by_id: ElementsById,
  id_map: StrMapping,
  node_ids: Iterable<string>,
  core_id: string,
  sectors: StrMapping,
  ownership: StrMapping,
  category_ids: Set<string> | null = null,
): null {
  const nodeIdList = [...node_ids];
  const anchor_ids = new Set(pyValues(sectors) as string[]);
  const leaf_widths: Record<string, number> = Object.create(null);
  for (const branch_id of pyKeys(sectors) as string[]) {
    const excluded = new Set<unknown>([core_id, ...anchor_ids]);
    const widths: number[] = [];
    for (const node_id of nodeIdList) {
      if (excluded.has(node_id) || pyGet(ownership, node_id) !== branch_id) continue;
      const shape = _node_shape(elements_by_id, id_map, node_id);
      if (shape === null) continue;
      for (const text of _bound_text_elements(elements_by_id, shape)) {
        widths.push(_estimate_text_dimensions(pyStr(pyOr(pyGet(text, 'text'), '')), _NODE_FONT_SIZE).width + 32.0);
      }
    }
    const natural_width = pyMax(widths, null, 160.0);
    // Styling has already changed the display font. Old layout widths
    // reflect the previous font and needlessly enlarge every peer card.
    // Never cap below the final label width, including CJK and long text.
    leaf_widths[branch_id] = pyMaxN(160.0, ceil(natural_width / 8.0) * 8.0);
  }

  let anchor_width = pyMax(
    [...anchor_ids].map((anchor_id) => _number(pyGet(_node_shape(elements_by_id, id_map, anchor_id) ?? {}, 'width'))),
    null,
    240.0,
  );
  anchor_width = pyMinN(304.0, pyMaxN(240.0, ceil(anchor_width / 8.0) * 8.0));

  for (const node_id of nodeIdList) {
    const shape = _node_shape(elements_by_id, id_map, node_id);
    if (shape === null) {
      continue;
    }
    const is_core = node_id === core_id;
    const is_anchor = anchor_ids.has(node_id);
    const is_category = (category_ids !== null && category_ids !== undefined && truthy(category_ids) ? _has(category_ids, node_id) : false)
      && !is_core && !is_anchor;
    const branch_id = pyGet(ownership, node_id) as string | null;
    const palette_key = is_core ? 'core' : branch_id;
    const palette = _palette_for_branch(palette_key);

    shape.type = 'rectangle';
    shape.roundness = { type: 3 };
    shape.roughness = 0;
    shape.fillStyle = 'solid';
    shape.strokeStyle = 'solid';
    shape.opacity = 100;
    shape.backgroundColor = palette[(is_core || is_anchor || is_category) ? 'anchor' : 'leaf'];
    shape.strokeColor = palette.stroke;
    shape.strokeWidth = (is_core || is_anchor) ? 2.0 : (is_category ? 1.5 : 1.25);
    markF(shape, 'roughness', false);
    markF(shape, 'opacity', false);
    markF(shape, 'strokeWidth', true);

    let target_width: number;
    let target_height: number;
    if (is_core) {
      target_width = pyMinN(440.0, pyMaxN(360.0, _number(pyGet(shape, 'width'))));
      target_height = 64.0;
    } else if (is_anchor) {
      target_width = anchor_width;
      target_height = 56.0;
    } else {
      target_width = pyGet(leaf_widths, (pyOr(branch_id, '') as string), 168.0) as number;
      target_height = pyMaxN(52.0, pyMax(
        _bound_text_elements(elements_by_id, shape).map(
          (text) => _estimate_text_dimensions(pyStr(pyOr(pyGet(text, 'text'), '')), _NODE_FONT_SIZE).height + 24.0,
        ),
        null,
        52.0,
      ));
    }
    _resize_node(elements_by_id, id_map, node_id, target_width, target_height);

    for (const text of _bound_text_elements(elements_by_id, shape)) {
      text.fontFamily = 2;
      text.fontSize = is_core ? 24 : (is_anchor ? _SECTION_FONT_SIZE : _NODE_FONT_SIZE);
      text.fontStyle = (is_core || is_anchor) ? 1 : 0;
      for (const key of ['fontFamily', 'fontSize', 'fontStyle']) markF(text, key, false);
      text.strokeColor = palette.text;
      text.lineHeight = 1.2;
    }
    _sync_bound_text(elements_by_id, shape);
  }
  return null;
}

export function _edge_endpoints(edge: StrMapping): [string | null, string | null] {
  const source = pyOr(pyGet(edge, 'source'), pyGet(edge, 'from'));
  const target = pyOr(pyGet(edge, 'target'), pyGet(edge, 'to'));
  return [
    isStr(source) ? String(source) : null,
    isStr(target) ? String(target) : null,
  ];
}

export function _edge_is_structural(edge: StrMapping): boolean {
  const evidence_basis = _norm(pyGet(edge, 'evidence_basis', ''));
  if (evidence_basis) {
    return evidence_basis === 'structural';
  }
  const relation_type = _norm(pyGet(edge, 'relation_type', ''));
  if (relation_type) {
    return _STRUCTURAL_RELATION_TYPES.has(relation_type);
  }
  const label = _norm(pyOr(pyOr(pyGet(edge, 'label'), pyGet(edge, 'relation')), ''));
  if (!label) {
    return true;
  }
  return _STRUCTURAL_RELATION_LABELS.has(label);
}

/**
 * Return whether local placement already expresses this membership fact.
 *
 * This is a visual encoding decision only. The explicit edge remains in the
 * semantic graph and fact ledger; it is not reclassified as a structural
 * organizer merely because a frame can communicate it without another arrow.
 */
export function _edge_uses_containment_encoding(
  edge: StrMapping,
  anchor_ids: Set<string>,
  ownership: StrMapping,
): boolean {
  const [source, target] = _edge_endpoints(edge);
  const relation_type = _norm(pyGet(edge, 'relation_type', ''));
  const label = _norm(pyOr(pyOr(pyGet(edge, 'label'), pyGet(edge, 'relation')), ''));
  const membership = relation_type === 'composition' || relation_type === 'exemplification';
  const topical_focus = relation_type === 'association'
    && ['emphasizes', 'highlights', 'focuses on', 'addresses', 'covers'].includes(label);
  return Boolean(
    _has(anchor_ids, source)
    && truthy(target)
    && pyEq(pyGet(ownership, pyOr(source, '')), pyGet(ownership, target))
    && (membership || topical_focus),
  );
}

/** Use a concise canonical label without changing the semantic artifact. */
export function _display_relation_label(edge: StrMapping, label: string): string {
  const relation_type = _norm(pyGet(edge, 'relation_type', ''));
  if (relation_type === 'exemplification') {
    // The concept-map contract fixes exemplification direction as
    // category -> example, so this wording is both short and unambiguous.
    return 'has example';
  }
  return label;
}

/** Map relation semantics to a consistent draw.io-style connector grammar. */
export function _semantic_connector_style(
  edge: StrMapping,
  cross_branch: boolean,
  local_color: string,
): Dict {
  const relation_type = _norm(pyGet(edge, 'relation_type', ''));
  let directionality = _norm(pyGet(edge, 'directionality', ''));
  if (!directionality) {
    directionality = relation_type === 'association' ? 'undirected' : 'directed';
  }

  const style: Dict = {
    strokeColor: cross_branch ? _NEUTRAL_CONNECTOR : local_color,
    strokeWidth: 1.35,
    strokeStyle: 'solid',
    opacity: 82,
    roughness: 0,
    startArrowhead: null,
    endArrowhead: directionality === 'directed' ? 'arrow' : null,
  };
  if (relation_type === 'association') {
    Object.assign(style, {
      strokeColor: local_color,
      strokeStyle: 'dashed',
      strokeWidth: 1.35,
      opacity: 78,
    });
  } else if (relation_type === 'dependency') {
    Object.assign(style, { strokeStyle: 'dashed', strokeWidth: 1.1, opacity: 62 });
  } else if (relation_type === 'composition' || relation_type === 'exemplification') {
    Object.assign(style, { strokeWidth: 1.1, opacity: 68 });
  }
  return style;
}

/** Resolve the concept root from roles first, then directed topology. */
export function _infer_core_id(nodes: StrMapping[], edges: StrMapping[]): string | null {
  const node_ids = nodes
    .filter((node) => isStr(pyGet(node, 'id')))
    .map((node) => String(pyGetItem(node, 'id')));
  let explicit: string | null = null;
  for (const node of nodes) {
    if (isStr(pyGet(node, 'id')) && ['core_concept', 'core'].includes(pyLower(pyStr(pyGet(node, 'class', ''))))) {
      explicit = String(pyGetItem(node, 'id'));
      break;
    }
  }
  if (explicit !== null) {
    return explicit;
  }

  const outgoing = new Map<string, string[]>();
  const incoming_count = new Map<string, number>();
  for (const node_id of node_ids) outgoing.set(node_id, []);
  for (const node_id of node_ids) incoming_count.set(node_id, 0);
  for (const edge of edges) {
    const [source, target] = _edge_endpoints(edge);
    if (source === null || target === null || !outgoing.has(source) || !incoming_count.has(target)) {
      continue;
    }
    if (!outgoing.get(source)!.includes(target)) {
      outgoing.get(source)!.push(target);
      incoming_count.set(target, incoming_count.get(target)! + 1);
    }
  }

  const reachable_count = (start: string): number => {
    const seen = new Set<string>([start]);
    const frontier = [...outgoing.get(start)!];
    while (frontier.length) {
      const node_id = frontier.pop()!;
      if (seen.has(node_id)) {
        continue;
      }
      seen.add(node_id);
      frontier.push(...(outgoing.get(node_id) ?? []));
    }
    return seen.size - 1;
  };

  const source_index = new Map<string, number>();
  node_ids.forEach((node_id, index) => source_index.set(node_id, index));
  let candidates = node_ids.filter(
    (node_id) => incoming_count.get(node_id) === 0 && outgoing.get(node_id)!.length >= 2,
  );
  if (!candidates.length) {
    candidates = node_ids.filter((node_id) => outgoing.get(node_id)!.length >= 2);
  }
  if (!candidates.length) {
    return null;
  }
  return pyMax(candidates, (node_id) => [
    reachable_count(node_id),
    outgoing.get(node_id)!.length,
    -source_index.get(node_id)!,
  ]);
}

export function _infer_profile(node_count: number): [number, number] {
  if (node_count <= 8) {
    return [1200.0, 800.0];
  }
  if (node_count <= 16) {
    return [1600.0, 900.0];
  }
  // A concept map is cropped to its content. Keeping this logical profile
  // tight makes the root and branch anchors read as one composition instead
  // of four unrelated diagrams at the corners of a large canvas.
  return [1880.0, 1080.0];
}

/** Group branch-local nodes by longest-path depth. */
export function _dependency_layers(node_ids: Iterable<string>, edges: Iterable<StrMapping>): Map<number, string[]> {
  const members = [...node_ids];
  const member_set = new Set(members);
  const adjacency = new Map<string, string[]>();
  const indegree = new Map<string, number>();
  for (const node_id of members) adjacency.set(node_id, []);
  for (const node_id of members) indegree.set(node_id, 0);
  for (const edge of edges) {
    const [source, target] = _edge_endpoints(edge);
    if (source !== null && target !== null && member_set.has(source) && member_set.has(target)
      && !adjacency.get(source)!.includes(target)) {
      adjacency.get(source)!.push(target);
      indegree.set(target, indegree.get(target)! + 1);
    }
  }

  const depth = new Map<string, number>();
  for (const node_id of members) depth.set(node_id, 0);
  const queue = members.filter((node_id) => indegree.get(node_id) === 0);
  while (queue.length) {
    const source = queue.shift()!;
    for (const target of adjacency.get(source)!) {
      depth.set(target, pyMaxN(depth.get(target)!, depth.get(source)! + 1));
      indegree.set(target, indegree.get(target)! - 1);
      if (indegree.get(target) === 0) {
        queue.push(target);
      }
    }
  }

  const layers = new Map<number, string[]>();
  for (const node_id of members) {
    const d = depth.get(node_id)!;
    if (!layers.has(d)) layers.set(d, []);
    layers.get(d)!.push(node_id);
  }
  return layers;
}

/** Count relations whose endpoints belong to different branches. */
export function _branch_interactions(edges: Iterable<StrMapping>, ownership: StrMapping): Map<[string, string], number> {
  const interactions = new Map<[string, string], number>();
  const index = new Map<string, [string, string]>();
  for (const edge of edges) {
    const [source, target] = _edge_endpoints(edge);
    const source_branch = pyGet(ownership, pyOr(source, '')) as string | null;
    const target_branch = pyGet(ownership, pyOr(target, '')) as string | null;
    if (!truthy(source_branch) || !truthy(target_branch) || pyEq(source_branch, target_branch)) {
      continue;
    }
    const sortedPair = pySorted([source_branch as string, target_branch as string]) as [string, string];
    const keyText = _pairKey(sortedPair);
    let pair = index.get(keyText);
    if (pair === undefined) {
      pair = sortedPair;
      index.set(keyText, pair);
    }
    const relation_type = _norm(pyGet(edge, 'relation_type', ''));
    const weight = relation_type === 'association' ? 0.25 : 1.0;
    interactions.set(pair, (interactions.has(pair) ? interactions.get(pair)! : 0.0) + weight);
  }
  return interactions;
}

function _interactionItems(interactions: Interactions): [[string, string], number][] {
  return pyItems(interactions as StrMapping) as [[string, string], number][];
}

/** Put strongly connected branches next to one another in a row. */
export function _best_branch_order(branch_ids: Iterable<string>, interactions: Interactions): string[] {
  const original = [...branch_ids];
  if (original.length > 7) {
    return original;
  }
  let best = original;
  let best_cost: [number, number] | null = null;
  const original_index: Record<string, number> = Object.create(null);
  original.forEach((branch_id, index) => {
    original_index[branch_id] = index;
  });
  const items = _interactionItems(interactions);
  for (const candidate of _permutations(original)) {
    const positions: Record<string, number> = Object.create(null);
    candidate.forEach((branch_id, index) => {
      positions[branch_id] = index;
    });
    const distance = pySum(items.map(
      ([[left, right], weight]) => weight * Math.abs(pyGetItem(positions, left) - pyGetItem(positions, right)),
    ));
    const churn = pySum(candidate.map((branch_id, index) => Math.abs(index - pyGetItem(original_index, branch_id))));
    // Keep source order stable unless moving a branch materially shortens
    // cross-branch relations. This avoids long divider-like connectors
    // without letting one weak association reshuffle the document.
    const cost: [number, number] = [distance + churn * 0.35, churn];
    if (best_cost === null || pyLt(cost, best_cost)) {
      best_cost = cost;
      best = [...candidate];
    }
  }
  return best;
}

/** Assign branches to quadrants so cross-branch relations stay local. */
export function _best_radial_slots(branch_ids: Iterable<string>, interactions: Interactions): Record<string, string> {
  const branches = [...branch_ids];
  const slot_names = ['upper_left', 'upper_right', 'lower_left', 'lower_right'];
  const default_: Record<string, string> = Object.create(null);
  for (const branch_id of branches) if (slot_names.includes(branch_id)) default_[branch_id] = branch_id;
  if (branches.length !== 4) {
    return default_;
  }

  const slot_xy: Record<string, [number, number]> = {
    upper_left: [0, 0],
    upper_right: [1, 0],
    lower_left: [0, 1],
    lower_right: [1, 1],
  };
  let best = default_;
  let best_cost: [number, number] | null = null;
  const items = _interactionItems(interactions);
  for (const assigned_slots of _permutations(slot_names)) {
    const candidate: Record<string, string> = Object.create(null);
    branches.forEach((branch_id, index) => {
      candidate[branch_id] = assigned_slots[index];
    });
    let distance = 0.0;
    for (const [[left, right], weight] of items) {
      if (!pyIn(left, candidate) || !pyIn(right, candidate)) {
        continue;
      }
      const [lx, ly] = slot_xy[candidate[left]];
      const [rx, ry] = slot_xy[candidate[right]];
      distance += weight * (Math.abs(lx - rx) + Math.abs(ly - ry));
    }
    const churn = pySum(branches.map((branch_id) => pyGet(candidate, branch_id) !== pyGet(default_, branch_id)));
    const cost: [number, number] = [distance, churn];
    if (best_cost === null || pyLt(cost, best_cost)) {
      best_cost = cost;
      best = candidate;
    }
  }
  return best;
}

export function _shape_center(shape: StrMapping): [number, number] {
  return [
    _number(pyGet(shape, 'x')) + _number(pyGet(shape, 'width')) / 2.0,
    _number(pyGet(shape, 'y')) + _number(pyGet(shape, 'height')) / 2.0,
  ];
}

/** Swap equivalent parent slots to shorten external links without changing ranks. */
export function _place_shared_parents_near_external_peers(
  elements_by_id: ElementsById,
  id_map: StrMapping,
  children: StrMapping,
  parents: StrMapping,
  edges: Iterable<StrMapping>,
  ownership: StrMapping,
): null {
  const external_peers = new Map<string | null, (string | null)[]>();
  for (const edge of edges) {
    const [source, target] = _edge_endpoints(edge);
    if (
      !pyIn(source, ownership) || !pyIn(target, ownership)
      || pyEq(pyGetItem(ownership, source), pyGetItem(ownership, target)) || _edge_is_structural(edge)
    ) {
      continue;
    }
    if (!external_peers.has(source)) external_peers.set(source, []);
    external_peers.get(source)!.push(target);
    if (!external_peers.has(target)) external_peers.set(target, []);
    external_peers.get(target)!.push(source);
  }

  const external_distance = (node_id: string, position: [number, number]): number => {
    let distance = 0.0;
    for (const peer of external_peers.get(node_id) ?? []) {
      const shape = _node_shape(elements_by_id, id_map, peer as string);
      if (truthy(shape)) {
        const [px, py] = _shape_center(shape!);
        distance += Math.abs(position[0] - px) + Math.abs(position[1] - py);
      }
    }
    return distance;
  };

  const hubs = pySorted((pyKeys(children) as string[]).filter(
    (node_id) => _iter(pyGetItem(children, node_id)).length >= 2 && !truthy(pyGetItem(parents, node_id)),
  ));
  for (const [first, second] of _combinations2(hubs)) {
    if (!_setEq(pyGetItem(children, first), pyGetItem(children, second))) {
      continue;
    }
    const a = _node_shape(elements_by_id, id_map, first);
    const b = _node_shape(elements_by_id, id_map, second);
    if (a === null || b === null) {
      continue;
    }
    // Equal-sized slots in one column preserve all occupied rectangles;
    // neither parent has an incoming local fact whose order could reverse.
    if (['x', 'width', 'height'].some((key) => Math.abs(_number(pyGet(a, key)) - _number(pyGet(b, key))) > 0.01)) {
      continue;
    }
    const a_center = _shape_center(a);
    const b_center = _shape_center(b);
    const lowest_bottom = pyMaxN(
      _number(pyGetItem(a, 'y')) + _number(pyGetItem(a, 'height')),
      _number(pyGetItem(b, 'y')) + _number(pyGetItem(b, 'height')),
    );
    if (_iter(pyGetItem(children, first)).some(
      (child) => _number(pyGet(_node_shape(elements_by_id, id_map, child as string) ?? {}, 'y')) <= lowest_bottom,
    )) {
      continue;
    }
    const before = external_distance(first, a_center) + external_distance(second, b_center);
    const after = external_distance(first, b_center) + external_distance(second, a_center);
    if (after >= before - 1.0) {
      continue;
    }
    const ax = _number(pyGetItem(a, 'x'));
    const ay = _number(pyGetItem(a, 'y'));
    const bx = _number(pyGetItem(b, 'x'));
    const by = _number(pyGetItem(b, 'y'));
    _move_node(elements_by_id, id_map, first, bx, by);
    _move_node(elements_by_id, id_map, second, ax, ay);
  }
  return null;
}

/** Return whether two center-to-center edge segments cross properly. */
export function _segments_cross(first: Sector, second: Sector): boolean {
  const [ax, ay, bx, by] = first;
  const [cx, cy, dx, dy] = second;

  const orientation = (px: number, py: number, qx: number, qy: number, rx: number, ry: number): number =>
    (qx - px) * (ry - py) - (qy - py) * (rx - px);

  const first_c = orientation(ax, ay, bx, by, cx, cy);
  const first_d = orientation(ax, ay, bx, by, dx, dy);
  const second_a = orientation(cx, cy, dx, dy, ax, ay);
  const second_b = orientation(cx, cy, dx, dy, bx, by);
  return first_c * first_d < 0.0 && second_a * second_b < 0.0;
}

/** Score candidate node geometry before the shared router adds arrows. */
export function _layout_score(
  manifest: Dict,
  id_map: StrMapping,
  node_ids: Iterable<string>,
  edges: Iterable<StrMapping>,
  structural_edge_ids: Set<string> | null = null,
): Dict {
  const elements_by_id = _elementsByIdFromManifest(manifest, true);
  const shapes = new Map<string, Dict>();
  {
    const all = new Map<string, Dict | null>();
    for (const node_id of node_ids) all.set(node_id, _node_shape(elements_by_id, id_map, node_id));
    for (const [node_id, shape] of all) if (shape !== null) shapes.set(node_id, shape);
  }
  if (!shapes.size) {
    return { total: Infinity };
  }

  const overlap_pairs: string[][] = [];
  const shape_items = [...shapes.entries()];
  shape_items.forEach(([left_id, left], index) => {
    const lx = _number(pyGet(left, 'x'));
    const ly = _number(pyGet(left, 'y'));
    const lr = lx + _number(pyGet(left, 'width'));
    const lb = ly + _number(pyGet(left, 'height'));
    for (const [right_id, right] of shape_items.slice(index + 1)) {
      const rx = _number(pyGet(right, 'x'));
      const ry = _number(pyGet(right, 'y'));
      const rr = rx + _number(pyGet(right, 'width'));
      const rb = ry + _number(pyGet(right, 'height'));
      if (pyMinN(lr, rr) > pyMaxN(lx, rx) && pyMinN(lb, rb) > pyMaxN(ly, ry)) {
        overlap_pairs.push([pyStr(left_id), pyStr(right_id)]);
      }
    }
  });

  const overlaps = overlap_pairs.length;

  const edge_segments: [string, string, Sector][] = [];
  let total_edge_length = 0.0;
  let weighted_edge_length = 0.0;
  const structural = structural_edge_ids !== null && structural_edge_ids !== undefined && truthy(structural_edge_ids)
    ? structural_edge_ids
    : new Set<string>();
  for (const edge of edges) {
    const [source, target] = _edge_endpoints(edge);
    if (source === null || target === null || !shapes.has(source) || !shapes.has(target)) {
      continue;
    }
    const [sx, sy] = _shape_center(shapes.get(source)!);
    const [tx, ty] = _shape_center(shapes.get(target)!);
    const edge_length = hypot(tx - sx, ty - sy);
    total_edge_length += edge_length;
    const edge_id = pyGet(edge, 'id');
    const is_structural = _has(structural, edge_id);
    if (!is_structural) {
      edge_segments.push([source, target, [sx, sy, tx, ty]]);
    }
    // In a grouped composition, core-to-section relationships are encoded
    // primarily by containment. Their hidden/quiet connector geometry must
    // not overpower the visible local and cross-branch relationships.
    const edge_weight = is_structural ? 0.12 : 1.0;
    weighted_edge_length += edge_length * edge_weight;
  }

  let crossings = 0;
  edge_segments.forEach(([source, target, segment], index) => {
    for (const [other_source, other_target, other_segment] of edge_segments.slice(index + 1)) {
      if (source === other_source || source === other_target || target === other_source || target === other_target) {
        continue;
      }
      if (_segments_cross(segment, other_segment)) {
        crossings += 1;
      }
    }
  });

  const shapeValues = [...shapes.values()];
  const min_x = pyMin(shapeValues.map((shape) => _number(pyGet(shape, 'x'))));
  const min_y = pyMin(shapeValues.map((shape) => _number(pyGet(shape, 'y'))));
  const max_x = pyMax(shapeValues.map((shape) => _number(pyGet(shape, 'x')) + _number(pyGet(shape, 'width'))));
  const max_y = pyMax(shapeValues.map((shape) => _number(pyGet(shape, 'y')) + _number(pyGet(shape, 'height'))));
  const width = pyMaxN(1.0, max_x - min_x);
  const height = pyMaxN(1.0, max_y - min_y);
  const area = width * height;
  const aspect_ratio = width / height;
  let aspect_penalty: number;
  if (aspect_ratio < 1.15) {
    aspect_penalty = Math.abs(log(aspect_ratio / 1.15));
  } else if (aspect_ratio > 2.05) {
    aspect_penalty = Math.abs(log(aspect_ratio / 2.05));
  } else {
    aspect_penalty = 0.0;
  }
  const extreme_base = pyMaxN(0.0, aspect_ratio - 2.6);
  const extreme_aspect_penalty = extreme_base * extreme_base * 180_000.0;
  const total = (
    overlaps * 1_000_000_000.0
    + crossings * 1_000_000.0
    + weighted_edge_length
    + area / 180.0
    + aspect_penalty * 70_000.0
    + extreme_aspect_penalty
  );
  const score: Dict = {
    total: pyRound(total, 3),
    node_overlaps: overlaps,
    overlap_pairs,
    straight_edge_crossings: crossings,
    edge_length: pyRound(total_edge_length, 3),
    weighted_edge_length: pyRound(weighted_edge_length, 3),
    area: pyRound(area, 3),
    aspect_ratio: pyRound(aspect_ratio, 3),
  };
  // float(...) / round(float, 3): every number here is a Python float.
  for (const key of ['total', 'node_overlaps', 'straight_edge_crossings', 'edge_length', 'weighted_edge_length', 'area', 'aspect_ratio']) {
    markF(score, key, true);
  }
  return score;
}

/** Return dependency-layered positions while reserving the anchor. */
export function _sector_grid(
  node_ids: Iterable<string>,
  elements_by_id: ElementsById,
  id_map: StrMapping,
  sector: Sector,
  anchor_id: string,
  sector_name: string,
  edges: Iterable<StrMapping>,
  ownership: StrMapping,
): [string, number, number][] {
  const [left, top, width, height] = sector;
  const edgeList = [...edges];
  const members = [...node_ids].filter((node_id) => node_id !== anchor_id);
  if (!members.length) {
    return [];
  }

  const member_set = new Set(members);
  const layers = _dependency_layers(members, edgeList);

  // Order same-rank nodes by the corridor needed by their cross-branch
  // relations. In a left sector, a vertical same-column cross-link belongs
  // at the outer (left) edge while a link to a right sector belongs at the
  // inner edge; mirror that rule on the right. This is the radial equivalent
  // of the barycentric sweep used by layered graph layout engines.
  const member_order = new Map<string, number>();
  members.forEach((node_id, index) => member_order.set(node_id, index));
  const external_preferences = new Map<string, number[]>();
  for (const node_id of members) external_preferences.set(node_id, []);
  const sector_is_left = pyEndswith(sector_name, 'left');
  for (const edge of edgeList) {
    const [source, target] = _edge_endpoints(edge);
    let member_id: string;
    let other_id: string | null;
    if (source !== null && member_set.has(source)) {
      [member_id, other_id] = [source, target];
    } else if (target !== null && member_set.has(target)) {
      [member_id, other_id] = [target, source];
    } else {
      continue;
    }
    const other_sector = pyGet(ownership, pyOr(other_id, '')) as string | null;
    if (!truthy(other_sector) || other_sector === sector_name) {
      continue;
    }
    const same_column = pyEndswith(other_sector as string, 'left') === sector_is_left;
    let preference: number;
    if (same_column) {
      preference = sector_is_left ? 0.0 : 1.0;
    } else {
      preference = sector_is_left ? 1.0 : 0.0;
    }
    external_preferences.get(member_id)!.push(preference);
  }

  for (const depth_members of layers.values()) {
    pySort(depth_members, (node_id) => {
      const prefs = external_preferences.get(node_id)!;
      return [
        prefs.length ? pySum(prefs) / prefs.length : 0.5,
        member_order.get(node_id)!,
      ];
    });
  }
  const max_depth = pyMax(layers.keys());
  const upper_sector = sector_name === 'upper_left' || sector_name === 'upper_right';
  const outer_y = top + 20.0;
  // Leave a real routing channel between the upper branch anchor and its
  // nearest dependency layer. The earlier 0.62/0.72 pair put two fitted
  // labels less than half a node-height apart on dense branches.
  const inner_y = top + height * 0.58;
  const layer_gap = max_depth
    ? pyMinN(120.0, pyMaxN(90.0, (inner_y - outer_y) / pyMaxN(1, max_depth)))
    : 0.0;

  const positions: [string, number, number][] = [];
  for (const layer_depth of pySorted(layers.keys())) {
    const layer = layers.get(layer_depth)!;
    const widths: number[] = [];
    const heights: number[] = [];
    for (const node_id of layer) {
      const shape = _node_shape(elements_by_id, id_map, node_id);
      widths.push(shape ? _number(pyGet(shape, 'width'), 180.0) : 180.0);
      heights.push(shape ? _number(pyGet(shape, 'height'), 60.0) : 60.0);
    }
    const gap = pyMinN(72.0, pyMaxN(40.0, (width - pySum(widths)) / (layer.length + 1)));
    const row_width = pySum(widths) + gap * (layer.length - 1);
    let cursor_x = left + (width - row_width) / 2.0;
    const visual_rank = upper_sector ? max_depth - layer_depth : layer_depth;
    const row_y = upper_sector ? outer_y + visual_rank * layer_gap : inner_y + visual_rank * layer_gap;
    layer.forEach((node_id, index) => {
      const node_width = widths[index];
      const node_height = heights[index];
      positions.push([node_id, cursor_x, row_y - node_height / 2.0]);
      cursor_x += node_width + gap;
    });
  }
  return positions;
}

/** Lay branches around the root, with topology-selected quadrants. */
export function _apply_radial_candidate(
  manifest: Dict,
  id_map: StrMapping,
  node_ids: string[],
  core_id: string,
  sectors: StrMapping,
  assigned: StrMapping,
  edges: StrMapping[],
  interactions: Interactions,
): Dict {
  const elements_by_id = _elementsByIdFromManifest(manifest, false);
  const [width, height] = _infer_profile(node_ids.length);
  const slots = _sectors(width, height);
  const slot_by_branch = _best_radial_slots(pyKeys(sectors) as string[], interactions);
  const physical_ownership: Record<string, string> = Object.create(null);
  for (const [node_id, branch_id] of pyItems(assigned)) {
    physical_ownership[node_id as string] = pyGet(slot_by_branch, branch_id, branch_id) as string;
  }

  const center_shape = _node_shape(elements_by_id, id_map, core_id);
  if (center_shape === null) {
    return manifest;
  }
  _move_node(
    elements_by_id,
    id_map,
    core_id,
    width / 2.0 - _number(pyGet(center_shape, 'width')) / 2.0,
    height / 2.0 - _number(pyGet(center_shape, 'height')) / 2.0,
  );

  for (const [branch_id, anchor_id] of pyItems(sectors) as [string, string][]) {
    const slot_name = pyGet(slot_by_branch, branch_id, branch_id) as string;
    const slot = pyGet(slots, slot_name) as Sector | null;
    if (slot === null) {
      continue;
    }
    const [sx, sy, sw, sh] = slot;
    const anchor_shape = _node_shape(elements_by_id, id_map, anchor_id);
    if (anchor_shape === null) {
      continue;
    }
    const anchor_on_right = slot_name === 'upper_left' || slot_name === 'lower_left';
    const anchor_on_bottom = slot_name === 'upper_left' || slot_name === 'upper_right';
    const anchor_x = sx + sw * (anchor_on_right ? 0.75 : 0.0) - _number(pyGet(anchor_shape, 'width')) / 2.0;
    const anchor_y = sy + sh * (anchor_on_bottom ? 0.84 : 0.12) - _number(pyGet(anchor_shape, 'height')) / 2.0;
    _move_node(elements_by_id, id_map, anchor_id, anchor_x, anchor_y);

    const branch_members = node_ids.filter(
      (node_id) => node_id !== core_id && node_id !== anchor_id && pyGet(assigned, node_id) === branch_id,
    );
    for (const [node_id, x, y] of _sector_grid(
      branch_members,
      elements_by_id,
      id_map,
      slot,
      anchor_id,
      slot_name,
      edges,
      physical_ownership,
    )) {
      _move_node(elements_by_id, id_map, node_id, x, y);
    }
  }

  manifest.elements = [...elements_by_id.values()];
  return manifest;
}

/** Return a barycentric ordering hint for nodes with cross-branch edges. */
export function _layer_external_preferences(
  members: Iterable<string>,
  edges: Iterable<StrMapping>,
  ownership: StrMapping,
  branch_positions: StrMapping,
): Record<string, number> {
  const member_list = [...members];
  const preferences = new Map<string, number[]>();
  for (const node_id of member_list) preferences.set(node_id, []);
  const member_set = new Set(member_list);
  for (const edge of edges) {
    const [source, target] = _edge_endpoints(edge);
    let member_id: string;
    let other_id: string | null;
    if (source !== null && member_set.has(source)) {
      [member_id, other_id] = [source, target];
    } else if (target !== null && member_set.has(target)) {
      [member_id, other_id] = [target, source];
    } else {
      continue;
    }
    const other_branch = pyGet(ownership, pyOr(other_id, ''));
    if (pyIn(other_branch, branch_positions)) {
      preferences.get(member_id)!.push(pyGetItem(branch_positions, other_branch) as number);
    }
  }
  const result: Record<string, number> = Object.create(null);
  for (const [node_id, values] of preferences) {
    result[node_id] = values.length
      ? pySum(values) / values.length
      : (pyGet(branch_positions, pyGet(ownership, node_id, ''), 0) as number);
  }
  return result;
}

/** Lay the root above compact branch lanes ordered by cross-links. */
export function _apply_layered_candidate(
  manifest: Dict,
  id_map: StrMapping,
  node_ids: string[],
  core_id: string,
  sectors: StrMapping,
  assigned: StrMapping,
  edges: StrMapping[],
  interactions: Interactions,
): Dict {
  const elements_by_id = _elementsByIdFromManifest(manifest, false);
  const branch_order = _best_branch_order(pyKeys(sectors) as string[], interactions);
  const branch_positions: Record<string, number> = Object.create(null);
  branch_order.forEach((branch_id, index) => {
    branch_positions[branch_id] = index;
  });
  const layers_by_branch: Record<string, Map<number, string[]>> = Object.create(null);
  const lane_widths: Record<string, number> = Object.create(null);
  const max_nodes_per_row = 3;
  const row_gap = 36.0;

  for (const branch_id of branch_order) {
    const anchor_id = pyGetItem(sectors, branch_id) as string;
    const members = node_ids.filter(
      (node_id) => node_id !== core_id && node_id !== anchor_id && pyGet(assigned, node_id) === branch_id,
    );
    const layers = _dependency_layers(members, edges);
    const preferences = _layer_external_preferences(members, edges, assigned, branch_positions);
    const source_order = new Map<string, number>();
    members.forEach((node_id, index) => source_order.set(node_id, index));
    for (const layer of layers.values()) {
      pySort(layer, (node_id) => [preferences[node_id], source_order.get(node_id)!]);
    }
    layers_by_branch[branch_id] = layers;

    const anchor_shape = _node_shape(elements_by_id, id_map, anchor_id);
    let required_width = anchor_shape ? _number(pyGet(anchor_shape, 'width'), 220.0) : 220.0;
    for (const layer of layers.values()) {
      for (let start = 0; start < layer.length; start += max_nodes_per_row) {
        const chunk = layer.slice(start, start + max_nodes_per_row);
        const chunk_width = pySum(chunk.map(
          (node_id) => _number(pyGet(_node_shape(elements_by_id, id_map, node_id) ?? {}, 'width'), 160.0),
        )) + row_gap * pyMaxN(0, chunk.length - 1);
        required_width = pyMaxN(required_width, chunk_width);
      }
    }
    lane_widths[branch_id] = pyMinN(520.0, pyMaxN(330.0, required_width + 56.0));
  }

  const margin_x = 50.0;
  const lane_gap = 64.0;
  const width = (
    margin_x * 2.0
    + pySum(Object.values(lane_widths))
    + lane_gap * pyMaxN(0, branch_order.length - 1)
  );
  const core_shape = _node_shape(elements_by_id, id_map, core_id);
  if (core_shape === null) {
    return manifest;
  }
  _move_node(
    elements_by_id,
    id_map,
    core_id,
    width / 2.0 - _number(pyGet(core_shape, 'width')) / 2.0,
    36.0,
  );

  let lane_left = margin_x;
  for (const branch_id of branch_order) {
    const lane_width = lane_widths[branch_id];
    const anchor_id = pyGetItem(sectors, branch_id) as string;
    const anchor_shape = _node_shape(elements_by_id, id_map, anchor_id);
    if (anchor_shape === null) {
      lane_left += lane_width + lane_gap;
      continue;
    }
    const anchor_y = 156.0;
    _move_node(
      elements_by_id,
      id_map,
      anchor_id,
      lane_left + (lane_width - _number(pyGet(anchor_shape, 'width'))) / 2.0,
      anchor_y,
    );

    let cursor_y = anchor_y + _number(pyGet(anchor_shape, 'height')) + 70.0;
    const branchLayers = layers_by_branch[branch_id];
    for (const layer_depth of pySorted(branchLayers.keys())) {
      const layer = branchLayers.get(layer_depth)!;
      for (let start = 0; start < layer.length; start += max_nodes_per_row) {
        const chunk = layer.slice(start, start + max_nodes_per_row);
        const shapes = chunk.map((node_id) => _node_shape(elements_by_id, id_map, node_id));
        const widths = shapes.map((shape) => (shape ? _number(pyGet(shape, 'width'), 160.0) : 160.0));
        const heights = shapes.map((shape) => (shape ? _number(pyGet(shape, 'height'), 50.0) : 50.0));
        const row_width = pySum(widths) + row_gap * pyMaxN(0, chunk.length - 1);
        let cursor_x = lane_left + (lane_width - row_width) / 2.0;
        chunk.forEach((node_id, index) => {
          const node_width = widths[index];
          const node_height = heights[index];
          _move_node(elements_by_id, id_map, node_id, cursor_x, cursor_y - node_height / 2.0);
          cursor_x += node_width + row_gap;
        });
        cursor_y += pyMax(heights) + 46.0;
      }
      cursor_y += 24.0;
    }
    lane_left += lane_width + lane_gap;
  }

  manifest.elements = [...elements_by_id.values()];
  return manifest;
}

/** Turn relation ranks into compact rows, keeping short chains horizontal. */
export function _stacked_branch_rows(
  members: string[],
  edges: StrMapping[],
  anchor_id: string | null = null,
  max_nodes_per_row: number = 4,
  horizontal_chains: boolean = true,
): string[][] {
  if (!members.length) {
    return [];
  }
  let layers = _dependency_layers(members, edges);
  if (anchor_id !== null && anchor_id !== undefined) {
    const member_set = new Set(members);
    // Python builds a set here; iteration below uses insertion order (see notes).
    const semantic_targets = new Set<string>();
    for (const edge of edges) {
      const [source, target] = _edge_endpoints(edge);
      if (
        source === anchor_id
        && target !== null && member_set.has(target)
        && ['causal', 'dependency'].includes(_norm(pyGet(edge, 'relation_type', '')))
      ) {
        semantic_targets.add(target);
      }
    }
    if (semantic_targets.size) {
      const depth_by_node = new Map<string, number>();
      for (const [depth, layer] of layers) for (const node_id of layer) depth_by_node.set(node_id, depth);
      for (const target of semantic_targets) {
        const depth = depth_by_node.has(target) ? depth_by_node.get(target)! : 0;
        if (depth > 0) {
          continue;
        }
        layers.set(0, (layers.get(0) ?? []).filter((node_id) => node_id !== target));
        if (!layers.has(1)) layers.set(1, []);
        layers.get(1)!.push(target);
      }
      const filtered = new Map<number, string[]>();
      for (const [depth, layer] of layers) if (layer.length) filtered.set(depth, layer);
      layers = filtered;
    }
  }
  const ordered_depths = pySorted(layers.keys());
  if (horizontal_chains && ordered_depths.length > 1 && ordered_depths.every((depth) => layers.get(depth)!.length === 1)) {
    const chain = ordered_depths.map((depth) => layers.get(depth)![0]);
    const chainSet = new Set(chain);
    const directed_pairs = new Set<string>();
    for (const edge of edges) {
      const [source, target] = _edge_endpoints(edge);
      if (source !== null && target !== null && chainSet.has(source) && chainSet.has(target)) {
        directed_pairs.add(_pairKey([source, target]));
      }
    }
    if (chain.slice(0, -1).every((source, index) => directed_pairs.has(_pairKey([source, chain[index + 1]])))) {
      const out: string[][] = [];
      for (let start = 0; start < chain.length; start += max_nodes_per_row) {
        out.push(chain.slice(start, start + max_nodes_per_row));
      }
      return out;
    }
  }

  const rows: string[][] = [];
  for (const depth of ordered_depths) {
    const layer = layers.get(depth)!;
    for (let start = 0; start < layer.length; start += max_nodes_per_row) {
      rows.push(layer.slice(start, start + max_nodes_per_row));
    }
  }
  return rows;
}

/** Compose concept branches as draw.io-like horizontal group bands. */
export function _apply_stacked_bands_candidate(
  manifest: Dict,
  id_map: StrMapping,
  node_ids: string[],
  core_id: string,
  sectors: StrMapping,
  assigned: StrMapping,
  edges: StrMapping[],
  interactions: Interactions,
  columns: number = 1,
): Dict {
  const elements_by_id = _elementsByIdFromManifest(manifest, false);
  const candidate_id_map = id_map_from_manifest(manifest);
  let branch_order = _best_branch_order(pyKeys(sectors) as string[], interactions);
  if (columns > 1) {
    const original = pyKeys(sectors) as string[];
    const original_index: Record<string, number> = Object.create(null);
    original.forEach((branch, index) => {
      original_index[branch] = index;
    });
    const items = _interactionItems(interactions);

    const grid_cost = (order: string[]): [number, number] => {
      const positions = new Map<string, [number, number]>();
      order.forEach((branch, index) => positions.set(branch, [pyMod(index, columns), floorDiv(index, columns)]));
      const distance = pySum(items
        .filter(([[left, right]]) => positions.has(left) && positions.has(right))
        .map(([[left, right], weight]) => weight * (
          Math.abs(positions.get(left)![0] - positions.get(right)![0])
          + Math.abs(positions.get(left)![1] - positions.get(right)![1])
        )));
      return [distance, pySum(order.map((branch, index) => Math.abs(index - original_index[branch])))];
    };

    branch_order = [...pyMin(_permutations(original), grid_cost)];
  }

  const outer_x = 40.0;
  const anchor_ids = new Set(pyValues(sectors) as string[]);
  const connected_anchors = new Set<string>();
  for (const edge of edges) {
    if (_edge_is_structural(edge) || _edge_uses_containment_encoding(edge, anchor_ids, assigned)) continue;
    for (const node_id of _edge_endpoints(edge)) {
      if (node_id !== null && anchor_ids.has(node_id)) connected_anchors.add(node_id);
    }
  }
  const header_text_widths: number[] = [];
  for (const anchor_id of anchor_ids) {
    const shape = _node_shape(elements_by_id, id_map, anchor_id);
    if (shape === null) continue;
    for (const text of _bound_text_elements(elements_by_id, shape)) header_text_widths.push(_number(pyGet(text, 'width')));
  }
  const header_width = pyMinN(
    256.0,
    pyMaxN(
      160.0,
      ceil((pyMax(header_text_widths, null, 136.0) + 24.0) / 8.0) * 8.0,
    ),
  );
  const sectorCount = pyKeys(sectors).length;
  const max_nodes_per_row = columns > 1 ? 3 : (sectorCount === 2 ? 2 : (sectorCount === 3 ? 3 : 4));
  const coreAndAnchors = new Set<string>([core_id, ...anchor_ids]);
  const branch_rows: Record<string, string[][]> = Object.create(null);
  for (const branch_id of pyKeys(sectors) as string[]) {
    branch_rows[branch_id] = _stacked_branch_rows(
      node_ids.filter((node_id) => !coreAndAnchors.has(node_id) && pyGet(assigned, node_id) === branch_id),
      edges,
      pyGetItem(sectors, branch_id) as string,
      max_nodes_per_row,
      columns === 1,
    );
  }
  const branch_row_widths: Record<string, number> = Object.create(null);
  for (const [branch_id, rows] of Object.entries(branch_rows)) {
    branch_row_widths[branch_id] = pyMax(
      rows.map((row) => (
        pySum(row.map((node_id) => _number(pyGet(_node_shape(elements_by_id, id_map, node_id) ?? {}, 'width'), 168.0)))
        + (columns > 1 ? 64.0 : 32.0) * pyMaxN(0, row.length - 1)
      )),
      null,
      0.0,
    );
  }
  const widest_row = pyMax(Object.values(branch_row_widths), null, 0.0);
  let header_x = outer_x + 24.0;
  let content_left = outer_x + 24.0;
  const base_canvas_width = sectorCount <= 3 ? 800.0 : 960.0;
  let canvas_width = pyMaxN(
    base_canvas_width,
    content_left + widest_row + outer_x + 24.0,
  );
  let band_width = canvas_width - 2.0 * outer_x;
  const column_gap = 80.0;
  let column_widths = [band_width];
  if (columns > 1) {
    // Align frames within a column without making a sparse column inherit
    // the widest row of a different column.
    column_widths = [];
    for (let column = 0; column < columns; column += 1) {
      column_widths.push(pyMaxN(620.0, pyMax(
        pySlice(branch_order, column, null, columns).map((branch) => branch_row_widths[branch] + 48.0),
        null,
        0.0,
      )));
    }
    canvas_width = 2.0 * outer_x + pySum(column_widths) + (columns - 1) * column_gap;
  }
  const title_shape = _node_shape(elements_by_id, id_map, core_id);
  if (title_shape === null) {
    return manifest;
  }
  const title_width = columns > 1 ? pyMinN(440.0, _number(pyGet(title_shape, 'width'), 440.0)) : band_width;
  _resize_node(elements_by_id, id_map, core_id, title_width, 52.0);
  _move_node(elements_by_id, id_map, core_id, (canvas_width - title_width) / 2.0, 28.0);
  if (columns > 1) {
    Object.assign(title_shape, { backgroundColor: 'transparent', strokeColor: 'transparent', strokeWidth: 0 });
    markF(title_shape, 'strokeWidth', false);
  }
  for (const text of _bound_text_elements(elements_by_id, title_shape)) {
    text.fontSize = columns > 1 ? 28 : 22;
    markF(text, 'fontSize', false);
    if (columns > 1) {
      text.strokeColor = '#202A36';
    }
    text.lineHeight = 1.15;
  }
  _sync_bound_text(elements_by_id, title_shape);

  let current_y = 112.0;
  const row_gap_y = 56.0;
  const band_gap = columns > 1 ? 48.0 : 24.0;
  const rowMaxHeight = (row: string[]): number => pyMax(
    row.map((node_id) => _number(pyGet(_node_shape(elements_by_id, id_map, node_id) ?? {}, 'height'), 52.0)),
  );
  const branch_heights: Record<string, number> = Object.create(null);
  for (const [branch_id, rows] of Object.entries(branch_rows)) {
    branch_heights[branch_id] = pyMaxN(
      136.0,
      80.0 + pySum(rows.map(rowMaxHeight)) + row_gap_y * pyMaxN(0, rows.length - 1),
    );
  }

  branch_order.forEach((branch_id, branch_index) => {
    const column = pyMod(branch_index, columns);
    band_width = column_widths[column];
    const content_width = band_width - 48.0;
    const band_x = outer_x + pySum(column_widths.slice(0, column)) + column * column_gap;
    header_x = band_x + 24.0;
    content_left = band_x + 24.0;
    const anchor_id = pyGetItem(sectors, branch_id) as string;
    let anchor_shape = _node_shape(elements_by_id, id_map, anchor_id);
    if (anchor_shape === null) {
      return;
    }
    const rows = branch_rows[branch_id];
    const row_heights = rows.map(rowMaxHeight);
    const content_height = rows.length
      ? pySum(row_heights) + row_gap_y * pyMaxN(0, rows.length - 1)
      : 56.0;
    let band_height = pyMaxN(136.0, content_height + 80.0);
    if (columns > 1) {
      const row_start = branch_index - column;
      band_height = pyMax(branch_order.slice(row_start, row_start + columns).map((branch) => branch_heights[branch]));
    }

    // In a stacked composition the frame already carries containment.
    // A heading that also participates in a fact needs a visible boundary
    // so its connector does not appear to originate in empty space.
    const local_header_width = pyMax(
      _bound_text_elements(elements_by_id, anchor_shape).map((text) => _number(pyGet(text, 'width')) + 20.0),
      null,
      header_width,
    );
    _resize_node(elements_by_id, id_map, anchor_id, local_header_width, 32.0);
    _move_node(elements_by_id, id_map, anchor_id, header_x, current_y + 12.0);
    anchor_shape = _node_shape(elements_by_id, id_map, anchor_id);
    if (anchor_shape !== null) {
      const palette = _palette_for_branch(branch_id);
      const connected = connected_anchors.has(anchor_id);
      (pySetdefault(anchor_shape, 'meta', {}) as Dict).conceptFactAnchor = connected;
      anchor_shape.backgroundColor = connected ? palette.leaf : 'transparent';
      anchor_shape.strokeColor = connected ? palette.stroke : 'transparent';
      anchor_shape.strokeWidth = connected ? 1.0 : 0.0;
      markF(anchor_shape, 'strokeWidth', true);
      (pySetdefault(anchor_shape, 'meta', {}) as Dict).conceptSectionColor = _palette_for_branch(branch_id).stroke;
      for (const text of _bound_text_elements(elements_by_id, anchor_shape)) {
        text.fontSize = _SECTION_FONT_SIZE;
        text.fontStyle = 1;
        markF(text, 'fontSize', false);
        markF(text, 'fontStyle', false);
        text.strokeColor = _palette_for_branch(branch_id).text;
        text.lineHeight = 1.15;
      }
      _sync_bound_text(elements_by_id, anchor_shape);
      for (const text of _bound_text_elements(elements_by_id, anchor_shape)) {
        text.x = header_x + 10.0;
        markF(text, 'x', true);
      }
    }

    let row_y = current_y + 56.0;
    rows.forEach((row, rowIndex) => {
      const row_height = row_heights[rowIndex];
      const row_widths = row.map(
        (node_id) => _number(pyGet(_node_shape(elements_by_id, id_map, node_id) ?? {}, 'width'), 168.0),
      );
      let gap_x: number;
      if (row.length > 1) {
        gap_x = pyMinN(
          104.0,
          pyMaxN(32.0, (content_width - pySum(row_widths)) / (row.length - 1)),
        );
      } else {
        gap_x = 0.0;
      }
      const occupied_width = pySum(row_widths) + gap_x * pyMaxN(0, row.length - 1);
      let cursor_x = content_left + pyMaxN(0.0, (content_width - occupied_width) / 2.0);
      row.forEach((node_id, index) => {
        const node_width = row_widths[index];
        const shape = _node_shape(elements_by_id, id_map, node_id);
        const node_height = shape ? _number(pyGet(shape, 'height'), 52.0) : 52.0;
        _move_node(elements_by_id, id_map, node_id, cursor_x, row_y + (row_height - node_height) / 2.0);
        cursor_x += node_width + gap_x;
      });
      row_y += row_height + row_gap_y;
    });

    const frame = _concept_frame(anchor_id, branch_id, band_x, current_y, band_width, band_height);
    frame.meta = {
      conceptBranch: branch_id,
      semanticId: `${anchor_id}:background`,
      memberIds: node_ids
        .filter((node_id) => pyGet(assigned, node_id) === branch_id && pyIn(node_id, candidate_id_map))
        .map((node_id) => candidate_id_map[node_id]),
    };
    _ebSet(elements_by_id, frame.id, frame);
    candidate_id_map[`${anchor_id}:background`] = frame.id;
    if (column === columns - 1 || branch_index === branch_order.length - 1) {
      current_y += band_height + band_gap;
    }
  });

  if (columns > 1) {
    // A cross-section target belongs on the side nearest its peer. For
    // example, a left-hand section should not enter the rightmost card
    // through all the intervening cards in another section's row.
    for (const [branch_id, rows] of Object.entries(branch_rows)) {
      const frame = pyGetItem(elements_by_id, pyGetItem(candidate_id_map, `${pyGetItem(sectors, branch_id)}:background`)) as Dict;
      const center_x = _number(pyGetItem(frame, 'x')) + _number(pyGetItem(frame, 'width')) / 2.0;

      const external_side = (node_id: string): number => {
        const peers: string[] = [];
        for (const edge of edges) {
          const [source, target] = _edge_endpoints(edge);
          if ((node_id === source || node_id === target)
            && pyIn(source, assigned) && pyIn(target, assigned)
            && !pyEq(pyGetItem(assigned, source), pyGetItem(assigned, target))) {
            peers.push((source === node_id ? target : source) as string);
          }
        }
        if (!peers.length) {
          return 0;
        }
        const peer_x = pySum(peers.map((peer) => _shape_center(_node_shape(elements_by_id, id_map, peer) ?? {})[0])) / peers.length;
        const offset = peer_x - center_x;
        const threshold = _number(pyGetItem(frame, 'width')) / 4.0;
        return offset < -threshold ? -1 : (offset > threshold ? 1 : 0);
      };

      for (const row of rows) {
        const slots = row.map((node_id) => [
          _number(pyGet(_node_shape(elements_by_id, id_map, node_id) ?? {}, 'x')),
          _number(pyGet(_node_shape(elements_by_id, id_map, node_id) ?? {}, 'y')),
        ] as [number, number]);
        const ordered = pySorted(row, external_side);
        const n = Math.min(ordered.length, slots.length);
        for (let i = 0; i < n; i += 1) {
          const [x, y] = slots[i];
          _move_node(elements_by_id, id_map, ordered[i], x, y);
        }
      }

      if (pyMax(rows.map((row) => row.length), null, 0) < 3) {
        continue;
      }
      // Python iterates a set here; the dict key order never reaches the
      // output (hubs are sorted, other uses are lookups).
      const members = new Set<string>();
      for (const row of rows) for (const node_id of row) members.add(node_id);
      const children = new Map<string, Set<string>>();
      const parents = new Map<string, Set<string>>();
      for (const node_id of members) children.set(node_id, new Set());
      for (const node_id of members) parents.set(node_id, new Set());
      for (const edge of edges) {
        const [source, target] = _edge_endpoints(edge);
        if (source !== null && target !== null && members.has(source) && members.has(target) && !_edge_is_structural(edge)) {
          children.get(source)!.add(target);
          parents.get(target)!.add(source);
        }
      }

      const place_in_column = (node_id: string, column: number): void => {
        const shape = _node_shape(elements_by_id, id_map, node_id);
        if (shape === null) {
          return;
        }
        const width = _number(pyGet(shape, 'width'));
        const left = _number(pyGetItem(frame, 'x')) + 24.0;
        const span = _number(pyGetItem(frame, 'width')) - 48.0 - width;
        _move_node(elements_by_id, id_map, node_id, left + span * column / 2.0, _number(pyGet(shape, 'y')));
      };

      for (const row of rows) {
        if (row.length !== 2) {
          continue;
        }
        const hubs = row.filter((node_id) => children.get(node_id)!.size >= 2);
        if (hubs.length === 1) {
          // Align the fan-out parent with the center of its outcomes;
          // an unrelated peer can occupy an outer grid column.
          const hub = hubs[0];
          const peer = row.find((node_id) => node_id !== hub);
          if (peer === undefined) throw new StopIteration();
          place_in_column(hub, 1);
          place_in_column(peer, external_side(peer) > 0 ? 2 : 0);
        } else {
          const p0 = parents.get(row[0])!;
          const p1 = parents.get(row[1])!;
          let shared = 0;
          for (const item of p0) if (p1.has(item)) shared += 1;
          if (shared >= 2) {
            // Shared outcomes need separate channels for each parent.
            const ordered = pySorted(row, (node_id) => _number(pyGet(_node_shape(elements_by_id, id_map, node_id) ?? {}, 'x')));
            place_in_column(ordered[0], 0);
            place_in_column(ordered[1], 2);
          }
        }
      }

      _place_shared_parents_near_external_peers(elements_by_id, id_map, children, parents, edges, assigned);
    }
  }

  manifest.elements = [...elements_by_id.values()];
  const metadata = pySetdefault(manifest, '_meta', {});
  if (isDict(metadata)) {
    metadata.id_map = candidate_id_map;
  }
  return manifest;
}

/** Synchronize layout-owned port intent with the selected geometry. */
export function _refresh_edge_ports(
  manifest: Dict,
  id_map: StrMapping,
  edges: Iterable<StrMapping>,
  core_id: string,
  ownership: StrMapping,
): null {
  const metadata = pyGet(manifest, '_meta');
  if (!isDict(metadata)) {
    return null;
  }
  const edge_data = pyGet(metadata, 'edge_data');
  if (!isDict(edge_data)) {
    return null;
  }
  const elements_by_id = _elementsByIdFromManifest(manifest, false);

  for (const edge of edges) {
    const edge_id = pyGet(edge, 'id');
    const [source, target] = _edge_endpoints(edge);
    if (!isStr(edge_id) || source === null || target === null) {
      continue;
    }
    const payload = pyGet(edge_data, edge_id);
    if (!isDict(payload)) {
      continue;
    }
    const source_shape = _node_shape(elements_by_id, id_map, source);
    const target_shape = _node_shape(elements_by_id, id_map, target);
    if (source_shape === null || target_shape === null) {
      continue;
    }
    const [source_x, source_y] = _shape_center(source_shape);
    const [target_x, target_y] = _shape_center(target_shape);
    const source_top = _number(pyGet(source_shape, 'y'));
    const source_bottom = source_top + _number(pyGet(source_shape, 'height'));
    const target_top = _number(pyGet(target_shape, 'y'));
    const target_bottom = target_top + _number(pyGet(target_shape, 'height'));
    const source_branch = pyGet(ownership, source);
    const target_branch = pyGet(ownership, target);
    const hierarchical = (
      source === core_id
      || (source_branch !== null && pyEq(source_branch, target_branch))
    );
    const vertical_clearance = target_y >= source_y
      ? target_top - source_bottom
      : source_top - target_bottom;
    // Center points can differ even while the node bounds overlap. Using
    // top/bottom ports in that case creates a nearly flat path whose long
    // segment rides along (or inside) the target border. Reserve vertical
    // ports for geometry with an actual approach corridor.
    let start_side: string;
    let end_side: string;
    if (hierarchical && vertical_clearance >= 16.0) {
      if (target_y >= source_y) {
        [start_side, end_side] = ['bottom', 'top'];
      } else {
        [start_side, end_side] = ['top', 'bottom'];
      }
    } else if (target_x >= source_x) {
      [start_side, end_side] = ['right', 'left'];
    } else {
      [start_side, end_side] = ['left', 'right'];
    }
    payload.start = { elementId: source, side: start_side };
    payload.end = { elementId: target, side: end_side };
    payload.routing = 'elbowed';
    payload._layoutCrossBranch = Boolean(
      source_branch !== null
      && target_branch !== null
      && !pyEq(source_branch, target_branch),
    );
  }
  return null;
}

/** Hide hierarchy links only when group frames already express ownership. */
export function _set_structural_edge_visibility(
  manifest: Dict,
  edges: Iterable<StrMapping>,
  structural_edge_ids: Set<string>,
  core_id: string,
  ownership: StrMapping,
  hidden_by_containment: boolean,
): null {
  const metadata = pyGet(manifest, '_meta');
  const edge_data = isDict(metadata) ? pyGet(metadata, 'edge_data') : null;
  if (!isDict(edge_data)) {
    return null;
  }
  for (const edge of edges) {
    const edge_id = pyGet(edge, 'id');
    if (!isStr(edge_id) || !_has(structural_edge_ids, edge_id)) {
      continue;
    }
    const payload = pyGet(edge_data, edge_id);
    if (!isDict(payload)) {
      continue;
    }
    const [source] = _edge_endpoints(edge);
    const owner = pyGet(ownership, pyOr(source, '')) as string | null;
    const palette = truthy(owner) ? _palette_for_branch(owner) : null;
    Object.assign(payload, {
      strokeColor: (source === core_id || palette === null) ? _STRUCTURAL_CONNECTOR : palette.stroke,
      strokeWidth: 1.0,
      strokeStyle: 'solid',
      opacity: hidden_by_containment ? 0 : 58,
      roughness: 0,
      startArrowhead: null,
      endArrowhead: null,
      _suppressLabel: true,
    });
    markF(payload, 'strokeWidth', true); // 1.0
    markF(payload, 'opacity', false);
    markF(payload, 'roughness', false);
  }
  return null;
}

/**
 * Select the best deterministic candidate before connector routing.
 *
 * This pass owns only node positions. It compares a compact radial candidate
 * with a layered branch-lane candidate using the semantic graph and real
 * post-fit node sizes. Edge geometry remains owned by ``arrow_adder``.
 */
export function compact_concept_map_layout(manifest: any, structure_instantiation: any): any {
  if (!isDict(manifest) || !isDict(structure_instantiation)) {
    return manifest;
  }
  const structure = unwrap_structure_instantiation(structure_instantiation);
  const chart_type = _norm(pyGet(structure, 'chart_type', ''));
  if (!_CONCEPT_MAP.has(chart_type)) {
    return manifest;
  }

  const nodes = _iter(pyOr(pyGet(structure, 'nodes', []), [])).filter((node) => isMapping(node)) as StrMapping[];
  const edges = _iter(pyOr(pyGet(structure, 'edges', []), [])).filter((edge) => isMapping(edge)) as StrMapping[];
  if (nodes.length < 5) {
    return manifest;
  }
  const node_ids = nodes.filter((node) => isStr(pyGet(node, 'id'))).map((node) => String(pyGet(node, 'id')));
  const node_by_id = new Map<string, StrMapping>();
  for (const node of nodes) if (isStr(pyGet(node, 'id'))) node_by_id.set(String(pyGet(node, 'id')), node);
  const core_id = _infer_core_id(nodes, edges);
  if (core_id === null) {
    return manifest;
  }

  const outgoing = new Map<string, string[]>();
  const incoming = new Map<string, string[]>();
  for (const node_id of node_ids) outgoing.set(node_id, []);
  for (const node_id of node_ids) incoming.set(node_id, []);
  for (const edge of edges) {
    const [source, target] = _edge_endpoints(edge);
    if (source !== null && target !== null && outgoing.has(source) && incoming.has(target)) {
      outgoing.get(source)!.push(target);
      incoming.get(target)!.push(source);
    }
  }

  const has_explicit_branch_ids = nodes.some((node) => pyIn('branch_id', node));
  const anchor_ids = node_ids.filter((node_id) => node_id !== core_id && (
    ['branch_anchor', 'category'].includes(pyLower(pyStr(pyGet(node_by_id.get(node_id)!, 'class', ''))))
    || (
      has_explicit_branch_ids
      && pyEq(pyGet(node_by_id.get(node_id)!, 'branch_id'), node_id)
    )
    || (
      !has_explicit_branch_ids
      && (
        (incoming.get(node_id) ?? []).includes(core_id)
        || (outgoing.get(node_id) ?? []).includes(core_id)
      )
    )
  ));
  const sectors: Record<string, string> = Object.create(null);
  anchor_ids.forEach((anchor_id, index) => {
    const branch_id = index < _SLOT_ORDER.length
      ? _SLOT_ORDER[index]
      : `branch_${index - _SLOT_ORDER.length + 1}`;
    sectors[branch_id] = anchor_id;
  });
  const sectorCount = Object.keys(sectors).length;
  if (sectorCount < 2) {
    return manifest;
  }

  const output = pyDeepcopy(manifest) as Dict;
  const elements_by_id = _elementsByIdFromManifest(output, false);
  const id_map = id_map_from_manifest(output);
  const center_shape = _node_shape(elements_by_id, id_map, core_id);
  if (center_shape === null) {
    return manifest;
  }

  // Prefer explicit branch ownership; legacy structures fall back to direct
  // anchor children and graph propagation. This mirrors draw.io's compartment
  // model: ownership is structural, while cross-links remain routing-only.
  const assigned: Record<string, string> = Object.create(null);
  for (const [sector, anchor_id] of Object.entries(sectors)) assigned[anchor_id] = sector;
  const sector_by_anchor: Record<string, string> = Object.create(null);
  for (const [sector, anchor_id] of Object.entries(sectors)) sector_by_anchor[anchor_id] = sector;
  for (const node of nodes) {
    const node_id = pyGet(node, 'id');
    const branch_id = pyGet(node, 'branch_id');
    if (!isStr(node_id) || !isStr(branch_id)) {
      continue;
    }
    const sector = pyGet(sector_by_anchor, branch_id) as string | null;
    if (sector !== null && node_id !== core_id) {
      assigned[node_id] = sector;
    }
  }

  const sectorAnchorSet = new Set<string>(Object.values(sectors));
  const coreAndAnchors = new Set<string>([core_id, ...Object.values(sectors)]);
  for (const edge of edges) {
    const [source, target] = _edge_endpoints(edge);
    const sector = pyGet(sector_by_anchor, pyOr(source, '')) as string | null;
    if (sector === null || target === null) {
      continue;
    }
    if (has_explicit_branch_ids && !_edge_is_structural(edge)) {
      continue;
    }
    if (!pyIn(target, assigned) && !coreAndAnchors.has(target)) {
      assigned[target] = sector;
    }
  }

  // Propagate ownership globally in the source edge order.  This is
  // intentionally done across all branches at once: a cross-link must not
  // claim a node already reached through its primary structural path.
  // The first structural path wins; later cross-links remain routed edges.
  let changed = true;
  while (changed) {
    changed = false;
    for (const edge of edges) {
      const [source, target] = _edge_endpoints(edge);
      if (source === null || target === null || pyIn(target, assigned)) {
        continue;
      }
      if (has_explicit_branch_ids && !_edge_is_structural(edge)) {
        continue;
      }
      const owner = pyGet(assigned, source) as string | null;
      if (owner === null || coreAndAnchors.has(target)) {
        continue;
      }
      assigned[target] = owner;
      changed = true;
    }
  }

  // Legacy structures without branch_id may still need a convergence-based
  // ownership correction. Require at least two agreeing parents and a strict
  // majority so a single isolated cross-link cannot steal ownership.
  const reassigned = new Set<string>();
  for (let iteration = 0; iteration < node_ids.length; iteration += 1) {
    const updates: Record<string, string> = Object.create(null);
    for (const target of node_ids) {
      if (coreAndAnchors.has(target)) {
        continue;
      }
      if (has_explicit_branch_ids && isStr(pyGet(node_by_id.get(target)!, 'branch_id'))) {
        continue;
      }
      const owner_counts: Record<string, number> = Object.create(null);
      for (const source of new Set(incoming.get(target) ?? [])) {
        const owner = pyGet(assigned, source) as string | null;
        if (owner !== null) {
          owner_counts[owner] = (pyGet(owner_counts, owner, 0) as number) + 1;
        }
      }
      if (!Object.keys(owner_counts).length) {
        continue;
      }
      const ranked = pySorted(Object.entries(owner_counts), (item) => [-item[1], item[0]]);
      const [best_owner, best_count] = ranked[0];
      const current_owner = pyGet(assigned, target) as string | null;
      const current_count = current_owner === null ? 0 : (pyGet(owner_counts, current_owner, 0) as number);
      const runner_up = ranked.length > 1 ? ranked[1][1] : 0;
      if (best_count >= 2 && best_count > current_count && best_count > runner_up) {
        updates[target] = best_owner;
      }
    }
    if (!Object.keys(updates).length) {
      break;
    }
    Object.assign(assigned, updates);
    for (const key of Object.keys(updates)) reassigned.add(key);
  }

  // Styling is generated before this deterministic graph pass. Keep it
  // semantically aligned with any ownership correction by inheriting the
  // winning branch anchor's palette, without changing size or node shape.
  for (const node_id of reassigned) {
    const owner = pyGet(assigned, node_id) as string | null;
    const anchor_id = pyGet(sectors, pyOr(owner, '')) as string | null;
    const shape = _node_shape(elements_by_id, id_map, node_id);
    const anchor_shape = truthy(anchor_id) ? _node_shape(elements_by_id, id_map, anchor_id as string) : null;
    if (shape === null || anchor_shape === null) {
      continue;
    }
    for (const key of ['backgroundColor', 'strokeColor']) {
      if (pyGet(anchor_shape, key) !== null) {
        shape[key] = anchor_shape[key];
      }
    }
  }

  // Styling models previously encoded hierarchy with wide ellipses and a
  // mix of sharp boxes. Normalize to draw.io's restrained default language:
  // one rounded-rectangle family, consistent peer dimensions, and hierarchy
  // carried by title/header/leaf treatments rather than arbitrary geometry.
  const category_ids = new Set<string>();
  for (const edge of edges) {
    if (_norm(pyGet(edge, 'relation_type', '')) !== 'exemplification') continue;
    const [source, target] = _edge_endpoints(edge);
    if (pyIn(source, assigned) && pyEq(pyGet(assigned, source), pyGet(assigned, target))) {
      category_ids.add(source as string);
    }
  }
  _normalize_concept_shape_language(
    elements_by_id,
    id_map,
    node_ids,
    core_id,
    sectors,
    assigned,
    category_ids,
  );

  const anchor_id_set = sectorAnchorSet;
  const has_relation_metadata = edges.some(
    (edge) => isStr(pyGet(edge, 'relation_type')) && Boolean(pyStrip(pyStr(pyGet(edge, 'relation_type')))),
  );
  const structural_edge_ids = new Set<string>();
  for (const edge of edges) {
    const [source, target] = _edge_endpoints(edge);
    if (
      (
        (source === core_id && target !== null && anchor_id_set.has(target))
        || (
          source !== null && anchor_id_set.has(source)
          && pyEq(pyGet(assigned, pyOr(source, '')), pyGet(assigned, pyOr(target, '')))
        )
      )
      && (!has_relation_metadata || _edge_is_structural(edge))
      && isStr(pyGet(edge, 'id'))
    ) {
      structural_edge_ids.add(String(pyGet(edge, 'id')));
    }
  }
  const containment_edge_ids = new Set<string>();
  for (const edge of edges) {
    if (isStr(pyGet(edge, 'id')) && _edge_uses_containment_encoding(edge, anchor_id_set, assigned)) {
      containment_edge_ids.add(String(pyGet(edge, 'id')));
    }
  }
  const metadata = pyGet(output, '_meta');
  const edge_data = isDict(metadata) ? pyGet(metadata, 'edge_data') : null;
  if (isDict(edge_data)) {
    for (const edge of edges) {
      const edge_id = pyGet(edge, 'id');
      if (!isStr(edge_id)) {
        continue;
      }
      const payload = pyGet(edge_data, edge_id);
      if (!isDict(payload)) {
        continue;
      }
      // Layout selection is replayable. Never inherit a suppression
      // decision from an older topology classification; the current
      // structure below will mark organizer edges again as needed.
      pyPop(payload, '_suppressLabel', null);
      const [source, target] = _edge_endpoints(edge);
      const source_owner = pyGet(assigned, pyOr(source, '')) as string | null;
      const target_owner = pyGet(assigned, pyOr(target, '')) as string | null;
      if (structural_edge_ids.has(edge_id) || containment_edge_ids.has(edge_id)) {
        Object.assign(payload, {
          strokeColor: _STRUCTURAL_CONNECTOR,
          strokeWidth: 1.0,
          strokeStyle: 'solid',
          opacity: 0,
          roughness: 0,
          startArrowhead: null,
          endArrowhead: null,
          _suppressLabel: true,
        });
        markF(payload, 'strokeWidth', true); // 1.0
        markF(payload, 'opacity', false);
        markF(payload, 'roughness', false);
      } else {
        const label_payload = pyGet(payload, 'label');
        let label_text = isMapping(label_payload)
          ? pyStr(pyGet(label_payload, 'text', ''))
          : pyStr(pyOr(label_payload, ''));
        label_text = _display_relation_label(edge, label_text);
        const palette = truthy(source_owner) ? _palette_for_branch(source_owner) : null;
        pyUpdate(payload, _semantic_connector_style(
          edge,
          Boolean(truthy(source_owner) && truthy(target_owner) && source_owner !== target_owner),
          palette ? palette.stroke : _NEUTRAL_CONNECTOR,
        ));
        Object.assign(payload, {
          // Line styles distinguish relation families, but cannot
          // express the predicate. Preserve facts on the canvas;
          // containment already removes organizer-only labels.
          _suppressLabel: false,
          label: {
            text: label_text,
            fontSize: _RELATION_FONT_SIZE,
            fontFamily: 2,
            strokeColor: '#39434D',
          },
        });
      }
    }
  }

  output.elements = [...elements_by_id.values()];
  const interactions = _branch_interactions(edges, assigned);
  const candidates: Record<string, Dict> = {
    stacked_bands: _apply_stacked_bands_candidate(
      pyDeepcopy(output),
      id_map,
      node_ids,
      core_id,
      sectors,
      assigned,
      edges,
      interactions,
    ),
    layered_lanes: _apply_layered_candidate(
      pyDeepcopy(output),
      id_map,
      node_ids,
      core_id,
      sectors,
      assigned,
      edges,
      interactions,
    ),
  };
  if (sectorCount === 2 || sectorCount === 4) {
    candidates.panel_grid = _apply_stacked_bands_candidate(
      pyDeepcopy(output), id_map, node_ids, core_id, sectors, assigned,
      edges, interactions, 2,
    );
  }
  if (sectorCount <= _SLOT_ORDER.length) {
    candidates.compact_radial = _apply_radial_candidate(
      pyDeepcopy(output),
      id_map,
      node_ids,
      core_id,
      sectors,
      assigned,
      edges,
      interactions,
    );
  }
  const scores: Record<string, Dict> = Object.create(null);
  for (const [name, candidate] of Object.entries(candidates)) {
    scores[name] = _layout_score(candidate, id_map, node_ids, edges, structural_edge_ids);
  }
  const stacked_score = pyGet(scores, 'stacked_bands', {}) as Dict;
  const stacked_is_viable = (
    sectorCount >= 2
    && pyEq(pyGet(stacked_score, 'node_overlaps'), 0)
    && 0.85 <= _number(pyGet(stacked_score, 'aspect_ratio'))
    && _number(pyGet(stacked_score, 'aspect_ratio')) <= 2.75
  );
  // Draw.io's composition grammar is organizer-first: once a graph has
  // several stable semantic branches, containment and aligned regions are a
  // stronger readability signal than a center-to-center crossing estimate.
  // The shared router will compute the actual orthogonal paths afterward.
  let selected_name = stacked_is_viable
    ? 'stacked_bands'
    : pyMin(Object.keys(scores), (name) => scores[name].total);
  const panel_score = pyGet(scores, 'panel_grid', {}) as Dict;
  if (
    pyEq(pyGet(panel_score, 'node_overlaps'), 0)
    && 1.15 <= _number(pyGet(panel_score, 'aspect_ratio'))
    && _number(pyGet(panel_score, 'aspect_ratio')) <= 2.5
  ) {
    selected_name = 'panel_grid';
  }
  const selected = candidates[selected_name];
  _set_structural_edge_visibility(
    selected,
    edges,
    structural_edge_ids,
    core_id,
    assigned,
    selected_name === 'stacked_bands' || selected_name === 'panel_grid',
  );
  _refresh_edge_ports(selected, id_map, edges, core_id, assigned);
  const selectedMeta = pySetdefault(selected, '_meta', {});
  if (isDict(selectedMeta)) {
    selectedMeta.concept_layout_selection = {
      strategy: selected_name,
      scores,
    };
  }
  logger.info(
    '[ConceptLayout] selected %s from %s',
    selected_name,
    Object.fromEntries(Object.entries(scores).map(([name, score]) => [name, score.total])),
  );
  return selected;
}

export const __all__ = ['compact_concept_map_layout'];
