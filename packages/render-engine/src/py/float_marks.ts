// Python int/float tracking for values that end up in ``json.dumps`` text
// (MIGRATION_PLAN.md §4: "str(float) … 1.0 not 1"). Added by WP24, see
// migration/notes/ISSUES.md WP24-1.
//
// A JS number cannot tell ``120`` from ``120.0``. Where the distinction is
// observable (``json.dumps`` of a manifest that is hashed, written or put into a
// prompt) the containers that hold the numbers carry side-channel marks:
// ``PY_FLOAT_MARKS`` (shared with the JSON decoder, WP17-1) maps an object /
// array to the keys (array indices as strings) whose value is a Python
// ``float``. The values themselves never change, so value-level parity is
// unaffected by construction.
//
// Conventions:
//   isF(c, k)            — is ``c[k]`` a Python float (marked, or non-integral)
//   setF(c, k, v, f)     — ``c[k] = v`` with float-ness ``f``
//   markF(c, k, f)       — set/clear the mark only
//   copyF(src, sk, dst, dk) — ``dst[dk]`` gets the float-ness of ``src[sk]``
//   pyDeepcopy(v)        — ``copy.deepcopy`` (keeps marks)
//   pyDictCopy(d)        — ``dict(d)`` / ``d.copy()`` / ``{**d}`` (keeps marks)
//   withPyFloats(v)      — copy with marked numbers wrapped in ``PyFloat`` for pyJsonDumps

import { PY_FLOAT_MARKS } from './json_decoder.ts';
import { PyFloat, pyFloat } from './number.ts';

export { PY_FLOAT_MARKS };

/** A number together with whether Python holds it as a ``float``. */
export interface PyNum { v: number; f: boolean }

export function num(v: number, f: boolean): PyNum {
  return { v, f: f || !Number.isInteger(v) };
}

/** Python float-ness of ``c[k]``: a marked key, or any non-integral / non-finite number. */
export function isF(c: unknown, k: string | number): boolean {
  if (c === null || typeof c !== 'object') return false;
  const key = String(k);
  const v = (c as Record<string, unknown>)[key];
  if (v instanceof PyFloat) return true;
  if (typeof v === 'number' && !Number.isInteger(v)) return true;
  return PY_FLOAT_MARKS.get(c)?.has(key) ?? false;
}

/** Float-ness of a number value with an explicit flag (non-integral numbers are always floats). */
export function fOf(v: unknown, f: boolean): boolean {
  return typeof v === 'number' && (f || !Number.isInteger(v));
}

/** Set (``f`` true) or clear the float mark of ``c[k]``. */
export function markF(c: unknown, k: string | number, f: boolean): void {
  if (c === null || typeof c !== 'object') return;
  const key = String(k);
  let keys = PY_FLOAT_MARKS.get(c);
  if (!f) {
    keys?.delete(key);
    return;
  }
  if (!keys) {
    keys = new Set();
    PY_FLOAT_MARKS.set(c, keys);
  }
  keys.add(key);
}

/** ``c[k] = v`` where Python's value has float-ness ``f``. */
export function setF<T>(c: Record<string, unknown> | unknown[], k: string | number, v: T, f: boolean): T {
  (c as Record<string, unknown>)[String(k)] = v;
  markF(c, k, typeof v === 'number' ? f : false);
  return v;
}

/** ``c[k] = n.v`` with ``n.f``. */
export function setN(c: Record<string, unknown> | unknown[], k: string | number, n: PyNum): number {
  return setF(c, k, n.v, n.f);
}

/** Read ``c[k]`` as a tracked number (``v`` is the raw value cast to number). */
export function getN(c: unknown, k: string | number): PyNum {
  const v = (c as Record<string, unknown>)[String(k)];
  return { v: v as number, f: isF(c, k) };
}

/** ``dst[dk]`` takes the float-ness of ``src[sk]`` (value is not touched). */
export function copyF(src: unknown, sk: string | number, dst: unknown, dk: string | number = sk): void {
  markF(dst, dk, isF(src, sk));
}

/** Copy every mark of ``src`` onto ``dst`` (same keys), e.g. after ``{...src}``. */
export function copyMarks<T>(src: unknown, dst: T): T {
  if (src === null || typeof src !== 'object' || dst === null || typeof dst !== 'object') return dst;
  const keys = PY_FLOAT_MARKS.get(src);
  if (keys && keys.size) {
    const existing = PY_FLOAT_MARKS.get(dst as object);
    if (existing) for (const k of keys) existing.add(k);
    else PY_FLOAT_MARKS.set(dst as object, new Set(keys));
  }
  return dst;
}

/** Python ``dict(d)`` / ``d.copy()`` / ``{**d}``: shallow copy that keeps the marks. */
export function pyDictCopy<T extends object>(d: T): T {
  return copyMarks(d, { ...d } as T);
}

/** Python ``list(a)`` / ``a[:]`` / ``a.copy()``: shallow copy that keeps the marks. */
export function pyListCopy<T>(a: readonly T[]): T[] {
  return copyMarks(a, [...a]);
}

/** Recursively copy marks from ``src`` to the structurally identical ``dst``. */
export function copyMarksDeep(src: unknown, dst: unknown): void {
  if (src === null || typeof src !== 'object' || dst === null || typeof dst !== 'object') return;
  copyMarks(src, dst);
  if (Array.isArray(src)) {
    if (!Array.isArray(dst)) return;
    src.forEach((item, i) => copyMarksDeep(item, dst[i]));
  } else if (src instanceof Map) {
    if (!(dst instanceof Map)) return;
    for (const [k, v] of src) copyMarksDeep(v, dst.get(k));
  } else if (!(src instanceof Set)) {
    for (const key of Object.keys(src)) copyMarksDeep((src as Record<string, unknown>)[key], (dst as Record<string, unknown>)[key]);
  }
}

/** ``copy.deepcopy`` of plain data (structuredClone) that keeps the float marks. */
export function pyDeepcopy<T>(value: T): T {
  const copy = structuredClone(value);
  copyMarksDeep(value, copy);
  return copy;
}

/** Copy of ``value`` with every marked number wrapped in ``PyFloat`` (input for ``pyJsonDumps``). */
export function withPyFloats(value: unknown): unknown {
  if (Array.isArray(value)) {
    const marks = PY_FLOAT_MARKS.get(value);
    return value.map((item, i) => (marks?.has(String(i)) && typeof item === 'number' ? pyFloat(item) : withPyFloats(item)));
  }
  if (value === null || typeof value !== 'object' || value instanceof PyFloat || value instanceof Map || value instanceof Set) return value;
  const proto = Object.getPrototypeOf(value);
  if (proto !== Object.prototype && proto !== null) return value;
  const marks = PY_FLOAT_MARKS.get(value);
  const out: Record<string, unknown> = {};
  for (const [key, item] of Object.entries(value)) {
    out[key] = marks?.has(key) && typeof item === 'number' ? pyFloat(item) : withPyFloats(item);
  }
  return out;
}

// ── arithmetic on tracked numbers (Python result types) ────────────────────

/** ``a + b`` / ``a - b`` / ``a * b``: float if either operand is. */
export function fAny(...flags: boolean[]): boolean {
  return flags.some(Boolean);
}

/** ``max(a, b, ...)`` / ``min``: the chosen operand keeps its own type (first wins on ties). */
export function maxNum(...values: PyNum[]): PyNum {
  let best = values[0];
  for (const v of values.slice(1)) if (v.v > best.v) best = v;
  return best;
}

export function minNum(...values: PyNum[]): PyNum {
  let best = values[0];
  for (const v of values.slice(1)) if (v.v < best.v) best = v;
  return best;
}

/**
 * Float-ness of ``a.get(k1) or b.get(k2) or ...``: the first truthy candidate's.
 * When none is truthy the chain yields its last operand: pass ``lastIsFinal``
 * when that operand is the last candidate itself (not a literal default).
 */
export function orF(cands: [unknown, string][], lastIsFinal = false): boolean {
  for (const [c, k] of cands) {
    if (c === null || typeof c !== 'object') continue;
    const v = (c as Record<string, unknown>)[k];
    if (v !== undefined && v !== null && v !== 0 && v !== '' && v !== false
      && !(Array.isArray(v) && v.length === 0)
      && !(typeof v === 'object' && !Array.isArray(v) && Object.keys(v as object).length === 0)) return isF(c, k);
  }
  if (lastIsFinal && cands.length) {
    const [c, k] = cands[cands.length - 1];
    return isF(c, k);
  }
  return false;
}

/** Python ``target.update(src)`` / ``Object.assign``: keys of ``src`` take its float-ness. */
export function pyUpdate<T extends object>(target: T, src: object): T {
  Object.assign(target, src);
  for (const key of Object.keys(src)) markF(target, key, isF(src, key));
  return target;
}

/** Python ``{**a, **b, ...}``: later dicts win, float-ness follows the winning value. */
export function pyMerge<T extends object>(...dicts: object[]): T {
  const out = {} as T;
  for (const d of dicts) pyUpdate(out, d);
  return out;
}

/**
 * ``target.update({...literal})`` where the Python literal's float-valued keys
 * are ``floats``; every other key of ``src`` is not a float (its mark is cleared).
 */
export function assignF<T extends object>(target: T, src: Record<string, unknown>, floats: readonly string[] = []): T {
  Object.assign(target, src);
  for (const key of Object.keys(src)) markF(target, key, floats.includes(key) && typeof src[key] === 'number');
  return target;
}
