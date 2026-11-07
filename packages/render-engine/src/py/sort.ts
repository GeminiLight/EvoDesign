// Python ordering: comparisons, sorted(), min(), max() (MIGRATION_PLAN.md §4).
//
//   a < b (numbers, strings, tuples)   -> pyLt(a, b) / pyCmp(a, b)
//   sorted(xs, key=k, reverse=r)       -> pySorted(xs, k, r)      stable
//   xs.sort(key=k, reverse=r)          -> pySort(xs, k, r)        in place
//   min(xs, key=k[, default=d])        -> pyMin(xs, k[, d])       first minimum wins
//   max(xs, key=k[, default=d])        -> pyMax(xs, k[, d])       first maximum wins
//   min(a, b, c) / max(a, b, c)        -> pyMin([a, b, c]) / pyMax([a, b, c])
//
// Strings compare by Unicode code point (JS ``<`` compares UTF-16 units),
// tuples/lists lexicographically, bools as ints. Comparing incompatible types
// raises ``PyTypeError`` like Python. ``Math.min``/``Math.max`` must not be
// used where NaN can appear or ties pick an element (key functions).

import { PyTypeError, ValueError } from './errors.ts';
import { pyEq } from './eq.ts';
import { PyFloat } from './number.ts';

/** Compare two strings by code point: negative, zero or positive. */
export function cpCompare(a: string, b: string): number {
  if (a === b) return 0;
  const n = Math.min(a.length, b.length);
  for (let i = 0; i < n; i += 1) {
    const x = a.charCodeAt(i);
    const y = b.charCodeAt(i);
    if (x === y) continue;
    // Surrogates (0xD800-0xDFFF) encode code points above 0xFFFF, which sort
    // after every BMP character, including 0xE000-0xFFFF.
    const xs = x >= 0xd800 && x <= 0xdfff;
    const ys = y >= 0xd800 && y <= 0xdfff;
    if (xs !== ys) return xs ? 1 : -1;
    return x - y;
  }
  return a.length - b.length;
}

function asNumber(value: unknown): number | undefined {
  if (typeof value === 'number') return value;
  if (typeof value === 'boolean') return value ? 1 : 0;
  if (value instanceof PyFloat) return value.value;
  return undefined;
}

function typeName(value: unknown): string {
  if (value === null || value === undefined) return 'NoneType';
  if (Array.isArray(value)) return 'list';
  if (typeof value === 'string') return 'str';
  if (typeof value === 'number') return Number.isInteger(value) ? 'int' : 'float';
  if (typeof value === 'boolean') return 'bool';
  return typeof value;
}

function unorderable(a: unknown, b: unknown): never {
  throw new PyTypeError(`'<' not supported between instances of '${typeName(a)}' and '${typeName(b)}'`);
}

/** ``a < b`` with Python semantics (NaN compares false). */
export function pyLt(a: unknown, b: unknown): boolean {
  const x = asNumber(a);
  const y = asNumber(b);
  if (x !== undefined && y !== undefined) return x < y;
  if (typeof a === 'string' && typeof b === 'string') return cpCompare(a, b) < 0;
  if (Array.isArray(a) && Array.isArray(b)) {
    const n = Math.min(a.length, b.length);
    for (let i = 0; i < n; i += 1) {
      if (!pyEq(a[i], b[i])) return pyLt(a[i], b[i]);
    }
    return a.length < b.length;
  }
  if (a instanceof Set && b instanceof Set) {
    // Proper subset.
    if (a.size >= b.size) return false;
    for (const item of a) if (!b.has(item)) return false;
    return true;
  }
  return unorderable(a, b);
}

/** ``a > b`` */
export function pyGt(a: unknown, b: unknown): boolean {
  return pyLt(b, a);
}

/** ``a <= b`` (Python evaluates ``__le__``, equivalent here to ``a < b or a == b``). */
export function pyLe(a: unknown, b: unknown): boolean {
  const x = asNumber(a);
  const y = asNumber(b);
  if (x !== undefined && y !== undefined) return x <= y;
  if (Array.isArray(a) && Array.isArray(b)) {
    const n = Math.min(a.length, b.length);
    for (let i = 0; i < n; i += 1) {
      if (!pyEq(a[i], b[i])) return pyLe(a[i], b[i]);
    }
    return a.length <= b.length;
  }
  return pyEq(a, b) || pyLt(a, b);
}

/** ``a >= b`` */
export function pyGe(a: unknown, b: unknown): boolean {
  return pyLe(b, a);
}

/** Three-way comparison built from ``<`` only, the way Python's sort sees values. */
export function pyCmp(a: unknown, b: unknown): number {
  if (pyLt(a, b)) return -1;
  if (pyLt(b, a)) return 1;
  return 0;
}

type KeyFn<T> = ((item: T) => unknown) | null | undefined;

/** ``list.sort(key=key, reverse=reverse)`` in place (stable). Returns the same array. */
export function pySort<T>(items: T[], key?: KeyFn<T>, reverse = false): T[] {
  const decorated = items.map((item, index) => ({ item, index, k: key ? key(item) : item }));
  decorated.sort((left, right) => {
    const order = reverse ? pyCmp(right.k, left.k) : pyCmp(left.k, right.k);
    return order !== 0 ? order : left.index - right.index;
  });
  for (let i = 0; i < decorated.length; i += 1) items[i] = decorated[i].item;
  return items;
}

/** ``sorted(iterable, key=key, reverse=reverse)`` (stable; reverse keeps ties in input order). */
export function pySorted<T>(items: Iterable<T>, key?: KeyFn<T>, reverse = false): T[] {
  return pySort([...items], key, reverse);
}

/** Sentinel meaning "no ``default=`` argument" for ``pyMin`` / ``pyMax``. */
export const NO_DEFAULT: unique symbol = Symbol('NO_DEFAULT');

/** ``min(iterable, key=key[, default=d])`` — the first of equal minima wins. */
export function pyMin<T, D = never>(items: Iterable<T>, key?: KeyFn<T>, defaultValue: D | typeof NO_DEFAULT = NO_DEFAULT): T | D {
  let first = true;
  let best: T | undefined;
  let bestKey: unknown;
  for (const item of items) {
    const k = key ? key(item) : item;
    if (first) {
      best = item;
      bestKey = k;
      first = false;
    } else if (pyLt(k, bestKey)) {
      best = item;
      bestKey = k;
    }
  }
  if (first) {
    if (defaultValue === NO_DEFAULT) throw new ValueError('min() arg is an empty sequence');
    return defaultValue;
  }
  return best as T;
}

/** ``max(iterable, key=key[, default=d])`` — the first of equal maxima wins. */
export function pyMax<T, D = never>(items: Iterable<T>, key?: KeyFn<T>, defaultValue: D | typeof NO_DEFAULT = NO_DEFAULT): T | D {
  let first = true;
  let best: T | undefined;
  let bestKey: unknown;
  for (const item of items) {
    const k = key ? key(item) : item;
    if (first) {
      best = item;
      bestKey = k;
      first = false;
    } else if (pyLt(bestKey, k)) {
      best = item;
      bestKey = k;
    }
  }
  if (first) {
    if (defaultValue === NO_DEFAULT) throw new ValueError('max() arg is an empty sequence');
    return defaultValue;
  }
  return best as T;
}

/** ``min(a, b, ...)`` over numbers with Python semantics (NaN handling, first wins). */
export function pyMinN(...values: number[]): number {
  return pyMin(values);
}

/** ``max(a, b, ...)`` over numbers with Python semantics (NaN handling, first wins). */
export function pyMaxN(...values: number[]): number {
  return pyMax(values);
}
