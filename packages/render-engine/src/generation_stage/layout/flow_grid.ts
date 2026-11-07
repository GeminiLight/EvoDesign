// Ported from evodesign/agentic_system/generation_stage/layout/flow_grid.py — keep in sync.
//
// Compile model-chosen flowchart cells into measured, non-overlapping boxes.
//
// The model owns rows, columns and every edge port. This only removes pixel
// arithmetic for ungrouped flows; canonical geometry remains the escape hatch.
//
// Python ``set``s of ids become ``Set``s (only used for equality/subset tests,
// never iterated into output). ``cells`` / ``widths`` / ``heights`` /
// ``columns`` / ``rows`` keep Python dict insertion order (``Map`` for the
// integer-keyed ones).

import { pySetItem } from '../../py/dict.ts';
import { CANVAS_DEFAULT_VIEWPORT_HEIGHT, CANVAS_DEFAULT_VIEWPORT_WIDTH } from '../../canvas_runtime.ts';
import { estimate_element_sizes } from './element_shape_estimator.ts';
import { unwrap_structure_instantiation } from '../../common/spec_utils.ts';
import { pyEq } from '../../py/eq.ts';
import { KeyError, PyTypeError, ValueError } from '../../py/errors.ts';
import { pyJsonLoads } from '../../py/json.ts';
import { ceil } from '../../py/math.ts';
import { pyRepr, pyStrip } from '../../py/str.ts';
import { isDict, pyLen, pyOr, pyTypeName, truthy } from '../../py/truthy.ts';

type Dict = Record<string, unknown>;

function has(d: Dict, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(d, key);
}

/** ``d.get(key, default)`` */
function get(d: Dict, key: string, defaultValue: unknown = null): unknown {
  return has(d, key) ? d[key] : defaultValue;
}

/** ``d[key]`` (KeyError when missing). */
function item(d: unknown, key: string): unknown {
  if (!isDict(d)) {
    if (Array.isArray(d) || typeof d === 'string') throw new PyTypeError(`${pyTypeName(d)} indices must be integers or slices, not str`);
    throw new PyTypeError(`'${pyTypeName(d)}' object is not subscriptable`);
  }
  if (!has(d, key)) throw new KeyError(pyRepr(key));
  return d[key];
}

/** ``for x in value`` */
function iterate(value: unknown): unknown[] {
  if (Array.isArray(value)) return value;
  if (typeof value === 'string') return [...value];
  if (isDict(value)) return Object.keys(value);
  throw new PyTypeError(`'${pyTypeName(value)}' object is not iterable`);
}

function setEq(a: ReadonlySet<unknown>, b: ReadonlySet<unknown>): boolean {
  if (a.size !== b.size) return false;
  for (const x of a) if (!b.has(x)) return false;
  return true;
}

function isSubset(a: ReadonlySet<unknown>, b: ReadonlySet<unknown>): boolean {
  for (const x of a) if (!b.has(x)) return false;
  return true;
}

export function supports_flow_grid(structure: Dict, styling: Dict, runtime_directives = ''): boolean {
  const nodes = pyOr(get(structure, 'nodes'), []) as unknown[];
  if (get(structure, 'chart_type') !== 'flowchart' || truthy(get(structure, 'groups'))
    || !(1 <= pyLen(nodes) && pyLen(nodes) <= 32)) {
    return false;
  }
  if (pyStrip(runtime_directives)) {
    // Only the known empty request context is eligible. Existing geometry,
    // locks and arbitrary refinement directives retain the original path.
    const prefix = '=== RUNTIME DIRECTIVES (HIGHEST PRIORITY) ===\n';
    if (!runtime_directives.startsWith(prefix)) {
      return false;
    }
    let context: unknown;
    try {
      context = pyJsonLoads(runtime_directives.slice(prefix.length));
    } catch (exc) {
      if (exc instanceof ValueError) return false;
      throw exc;
    }
    if (!pyEq(context, { locked_nodes: [], current_schema: null })) {
      return false;
    }
  }
  const node_ids = new Set<unknown>(iterate(nodes).map((node) => item(node, 'id')));
  const edge_ids = iterate(get(structure, 'edges', [])).map((edge) => item(edge, 'id'));
  const allowed = new Set<unknown>([
    ...node_ids,
    ...edge_ids,
    ...[...node_ids].map((key) => {
      if (typeof key !== 'string') throw new PyTypeError(`unsupported operand type(s) for +: '${pyTypeName(key)}' and 'str'`);
      return key + ':icon';
    }),
  ]);
  const styling_keys = new Set<unknown>(Object.keys(styling));
  return isSubset(styling_keys, allowed) && isSubset(node_ids, styling_keys);
}

export function flow_grid_sizes(structure: Dict, styling: Dict): Record<string, [number, number]> {
  const estimated = estimate_element_sizes(styling, structure) as Dict;
  const sizes: Record<string, [number, number]> = Object.create(null);
  for (const node of iterate(item(structure, 'nodes'))) {
    const node_id = item(node, 'id') as string;
    const entry = item(estimated, node_id) as Dict;
    const shape = get(entry, 'shape', get(entry, 'type', 'rectangle'));
    const inflate_map: Record<string, number> = { diamond: 1.4, ellipse: 1.2 };
    const inflate = typeof shape === 'string' && has(inflate_map, shape) ? inflate_map[shape] : 1.0;
    sizes[node_id] = [
      Math.max(160, ceil((get(entry, 'min_width', 120) as number) * inflate + 40)),
      Math.max(shape === 'diamond' ? 88 : 64, ceil((get(entry, 'min_height', 24) as number) * inflate + 30)),
    ];
  }
  return sizes;
}

/** ``type(value) is int`` for a JSON value (a JS number cannot tell ``1`` from ``1.0``). */
function isExactInt(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value);
}

export function expand_flow_grid(output: unknown, structure: unknown, styling: Dict): unknown {
  const structureInst = unwrap_structure_instantiation(structure);
  const inst = isDict(output) ? get(output, 'instantiation') : null;
  if (!isDict(inst) || get(inst, 'format') !== 'flow_grid_v1') {
    return output;
  }
  if (!supports_flow_grid(structureInst, styling)) {
    throw new ValueError('Flow grid requires an ungrouped flowchart with no standalone annotations.');
  }
  if (!setEq(new Set(Object.keys(inst)), new Set(['format', 'nodes', 'edges'])) || !isDict(inst.nodes) || !isDict(inst.edges)) {
    throw new ValueError('Flow grid requires exactly format, nodes and edges maps.');
  }
  const inst_nodes = inst.nodes as Dict;
  const sizes = flow_grid_sizes(structureInst, styling);
  const structure_edge_ids = new Set<unknown>(iterate(get(structureInst, 'edges', [])).map((edge) => item(edge, 'id')));
  if (!setEq(new Set(Object.keys(inst_nodes)), new Set(Object.keys(sizes)))
    || !setEq(new Set(Object.keys(inst.edges as Dict)), structure_edge_ids)) {
    throw new ValueError('Flow grid must cover every exact node and edge ID once.');
  }
  const size_count = Object.keys(sizes).length;
  const cells: Map<string, [number, number]> = new Map();
  for (const [node_id, cell] of Object.entries(inst_nodes)) {
    if (!Array.isArray(cell) || cell.length !== 2
      || cell.some((value) => !isExactInt(value) || !(0 <= value && value < size_count))) {
      throw new ValueError('Flow grid cells must be bounded non-negative integer [column,row] pairs.');
    }
    const pair: [number, number] = [cell[0] as number, cell[1] as number];
    if ([...cells.values()].some((other) => other[0] === pair[0] && other[1] === pair[1])) {
      throw new ValueError('Flow grid nodes cannot share a cell.');
    }
    cells.set(node_id, pair);
  }
  const widths: Map<number, number> = new Map();
  for (const [col] of cells.values()) {
    widths.set(col, Math.max(...[...cells].filter(([, cell]) => cell[0] === col).map(([key]) => sizes[key][0])));
  }
  const heights: Map<number, number> = new Map();
  for (const [, row] of cells.values()) {
    heights.set(row, Math.max(...[...cells].filter(([, cell]) => cell[1] === row).map(([key]) => sizes[key][1])));
  }
  // Empty cells remain explicit routing space, never silently compacted away.
  const columns: Map<number, number> = new Map();
  const rows: Map<number, number> = new Map();
  let x = 80;
  let y = 80;
  const maxCol = Math.max(...widths.keys());
  for (let col = 0; col < maxCol + 1; col += 1) {
    const width = widths.has(col) ? widths.get(col)! : 160;
    columns.set(col, x + width / 2);
    x += width + 120;
  }
  const maxRow = Math.max(...heights.keys());
  for (let row = 0; row < maxRow + 1; row += 1) {
    const height = heights.has(row) ? heights.get(row)! : 64;
    rows.set(row, y + height / 2);
    y += height + 64;
  }
  if (x - 120 + 80 > CANVAS_DEFAULT_VIEWPORT_WIDTH || y - 64 + 80 > CANVAS_DEFAULT_VIEWPORT_HEIGHT) {
    throw new ValueError('Flow grid exceeds canvas safety bounds; use a more compact plan or canonical boxes.');
  }
  const expanded = structuredClone(inst.edges) as Dict;
  for (const [key, [col, row]] of cells) {
    const [width, height] = sizes[key];
    // Python: floats (``/ 2``), then the int width/height.
    pySetItem(expanded, key, [columns.get(col)! - width / 2, rows.get(row)! - height / 2, width, height]);
  }
  const result = structuredClone(output) as Dict;
  result.instantiation = expanded;
  return result;
}
