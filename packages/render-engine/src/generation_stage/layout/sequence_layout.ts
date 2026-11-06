// Ported from evodesign/agentic_system/generation_stage/layout/sequence_layout.py — keep in sync.
//
// Initial sequence geometry from participant sizes and semantic chronology.
//
// Excalidraw's sequence renderer owns message rows and lifelines. There is no
// useful free-form coordinate decision for another model call to make here.
//
// TS-only: Python returns a mix of ints and floats here (``max(120.0, ...)``,
// ``max(64.0, ...)``). A JS number cannot carry that, but the geometry is
// later serialized with ``json.dumps`` into the conversation history, where
// ``120.0`` vs ``120`` is visible. ``sequence_layout_geometry`` therefore
// records which fields hold Python floats in ``_PY_FLOAT_FIELDS`` (keyed by
// the entry object, never enumerable, so the values themselves stay plain
// numbers). It is the same map the JSON decoder fills for integral float
// literals in model output (``py/json_decoder.ts PY_FLOAT_MARKS``).
// ``_with_py_floats`` turns those marks into ``PyFloat`` wrappers for
// serialization only.

import { _char_width_factor, _estimate_text_dimensions } from './element_shape_estimator.ts';
import { KeyError, PyTypeError, ValueError } from '../../py/errors.ts';
import { PY_FLOAT_MARKS } from '../../py/json_decoder.ts';
import { pyFloat } from '../../py/number.ts';
import { cpLen, pyRepr, pyStr } from '../../py/str.ts';
import { isDict, pyOr, pyTypeName, truthy } from '../../py/truthy.ts';

type Dict = Record<string, unknown>;

// ── Python float bookkeeping (TS-only, see header) ─────────────────────────

/** entry object → names (array: indices) of its fields whose Python value is a ``float``. */
export const _PY_FLOAT_FIELDS: WeakMap<object, Set<string>> = PY_FLOAT_MARKS;

/** Mark ``entry[field]`` as a Python float (or clear the mark). */
export function _mark_py_float(entry: object, field: string, is_float = true): void {
  let fields = _PY_FLOAT_FIELDS.get(entry);
  if (!is_float) {
    fields?.delete(field);
    return;
  }
  if (!fields) {
    fields = new Set();
    _PY_FLOAT_FIELDS.set(entry, fields);
  }
  fields.add(field);
}

export function _is_py_float(entry: unknown, field: string): boolean {
  return entry !== null && typeof entry === 'object' && (_PY_FLOAT_FIELDS.get(entry)?.has(field) ?? false);
}

/** ``copy.deepcopy`` of a JSON value that keeps the float marks on the copies. */
export function _deepcopy_with_py_floats<T>(value: T): T {
  const copy = structuredClone(value);
  const walk = (src: unknown, dst: unknown): void => {
    if (src === null || typeof src !== 'object' || dst === null || typeof dst !== 'object') return;
    const fields = _PY_FLOAT_FIELDS.get(src);
    if (fields) _PY_FLOAT_FIELDS.set(dst, new Set(fields));
    if (Array.isArray(src)) {
      src.forEach((item, i) => walk(item, (dst as unknown[])[i]));
    } else if (isDict(src)) {
      for (const key of Object.keys(src)) walk(src[key], (dst as Dict)[key]);
    }
  };
  walk(value, copy);
  return copy;
}

/** Copy of ``value`` with every marked float field wrapped in ``PyFloat`` (for ``json.dumps``). */
export function _with_py_floats(value: unknown): unknown {
  if (Array.isArray(value)) {
    const marks = _PY_FLOAT_FIELDS.get(value);
    return value.map((item, i) => (marks?.has(String(i)) && typeof item === 'number' ? pyFloat(item) : _with_py_floats(item)));
  }
  if (!isDict(value)) return value;
  const fields = _PY_FLOAT_FIELDS.get(value);
  const out: Dict = {};
  for (const [key, item] of Object.entries(value)) {
    out[key] = fields?.has(key) && typeof item === 'number' ? pyFloat(item) : _with_py_floats(item);
  }
  return out;
}

// ── helpers ────────────────────────────────────────────────────────────────

function has(d: Dict, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(d, key);
}

function get(d: unknown, key: string, defaultValue: unknown = null): unknown {
  if (!isDict(d)) throw new PyTypeError(`'${pyTypeName(d)}' object has no attribute 'get'`);
  return has(d, key) ? d[key] : defaultValue;
}

function item(d: unknown, key: string): unknown {
  if (!isDict(d)) throw new PyTypeError(`'${pyTypeName(d)}' object is not subscriptable`);
  if (!has(d, key)) throw new KeyError(pyRepr(key));
  return d[key];
}

/** A number together with whether Python holds it as a ``float``. */
interface Num { v: number; f: boolean }

/** ``max(a, b)`` — returns ``a`` unless ``b > a``. */
function max2(a: Num, b: Num): Num {
  return b.v > a.v ? b : a;
}

/** ``max(values)`` / ``min(values)`` — the first extreme element wins. */
function maxOf(values: Num[]): Num {
  if (!values.length) throw new ValueError('max() arg is an empty sequence');
  let best = values[0];
  for (const value of values.slice(1)) if (value.v > best.v) best = value;
  return best;
}

function minOf(values: Num[]): Num {
  if (!values.length) throw new ValueError('min() arg is an empty sequence');
  let best = values[0];
  for (const value of values.slice(1)) if (value.v < best.v) best = value;
  return best;
}

/** ``a + b`` / ``a - b`` / ``a * b`` with the float flag propagated. */
const add = (a: Num, b: Num): Num => ({ v: a.v + b.v, f: a.f || b.f });
const sub = (a: Num, b: Num): Num => ({ v: a.v - b.v, f: a.f || b.f });
const int = (v: number): Num => ({ v, f: false });
const flt = (v: number): Num => ({ v, f: true });

function setNum(entry: Dict, field: string, value: Num): void {
  entry[field] = value.v;
  _mark_py_float(entry, field, value.f);
}

function numOf(entry: Dict, field: string): Num {
  return { v: entry[field] as number, f: _is_py_float(entry, field) };
}

export function sequence_layout_geometry(structure: Dict, styling: Dict): Dict {
  const nodes = pyOr(get(structure, 'nodes'), []) as Dict[];
  if (!truthy(nodes)) {
    throw new ValueError('Sequence diagrams require at least one participant');
  }
  // Styling min sizes are ints (estimate_element_sizes) or the int defaults.
  const widths: Record<string, Num> = {};
  for (const node of nodes) {
    widths[item(node, 'id') as string] = max2(flt(120.0), int((get(item(styling, item(node, 'id') as string), 'min_width', 120) as number) + 40));
  }
  const heights: Record<string, Num> = {};
  for (const node of nodes) {
    heights[item(node, 'id') as string] = max2(flt(64.0), int((get(item(styling, item(node, 'id') as string), 'min_height', 24) as number) + 30));
  }
  const gap = add(maxOf(Object.values(widths)), int(64));
  const max_height = maxOf(Object.values(heights));
  const layout: Dict = {};
  nodes.forEach((node, index) => {
    const node_id = node.id as string;
    const entry: Dict = {};
    setNum(entry, 'x', add(int(100), { v: index * gap.v, f: gap.f }));
    setNum(entry, 'y', int(80));
    setNum(entry, 'w', widths[node_id]);
    setNum(entry, 'h', max_height);
    layout[node_id] = entry;
  });
  const indices: Record<string, number> = {};
  nodes.forEach((node, index) => {
    indices[node.id as string] = index;
  });
  const edges = pyOr(get(structure, 'edges'), []) as Dict[];
  for (const edge of edges) {
    const source = item(edge, 'source') as string;
    const target = item(edge, 'target') as string;
    if (!has(indices, source)) throw new KeyError(pyRepr(source));
    if (!has(indices, target)) throw new KeyError(pyRepr(target));
    const forward = indices[source] <= indices[target];
    layout[item(edge, 'id') as string] = {
      start: { elementId: edge.source, side: forward ? 'right' : 'left' },
      end: { elementId: edge.target, side: forward ? 'left' : 'right' },
    };
  }
  for (const group of pyOr(get(structure, 'groups'), []) as Dict[]) {
    const members = (get(group, 'members', []) as unknown[])
      .filter((key) => typeof key === 'string' && has(widths, key))
      .map((key) => item(layout, key as string) as Dict);
    if (!members.length) {
      throw new ValueError(`Sequence lane ${pyRepr(item(group, 'id'))} must contain a participant`);
    }
    const left = sub(minOf(members.map((m) => numOf(m, 'x'))), int(16));
    const right = add(maxOf(members.map((m) => add(numOf(m, 'x'), numOf(m, 'w')))), int(16));
    const group_id = item(group, 'id') as string;
    for (const key of [group_id, group_id + ':background']) {
      if (has(styling, key)) {
        const entry: Dict = {};
        setNum(entry, 'x', left);
        setNum(entry, 'y', int(64));
        setNum(entry, 'w', sub(right, left));
        setNum(entry, 'h', add(add(max_height, int(128)), int(64 * edges.length)));
        layout[key] = entry;
      }
    }
    const title_key = group_id + ':title';
    if (has(styling, title_key)) {
      const text = pyStr(pyOr(get(group, 'label'), ''));
      const dims = _estimate_text_dimensions(text, 18);
      // ``max(width, 10)`` keeps the float width unless 10 > width.
      const lines = text ? text.split('\n') : [''];
      const raw_width = Math.max(...lines.map((line) => cpLen(line))) * 18 * _char_width_factor(text);
      const dims_width: Num = { v: dims.width, f: !(10 > raw_width) };
      const dims_height: Num = flt(dims.height);
      const entry: Dict = {};
      setNum(entry, 'x', add(left, int(8)));
      setNum(entry, 'y', int(40));
      setNum(entry, 'w', max2(int(1), dims_width));
      setNum(entry, 'h', max2(int(24), dims_height));
      layout[title_key] = entry;
    }
  }
  return layout;
}
