// Python ``==`` and ``in`` for structured values (MIGRATION_PLAN.md §4).
//
// JS ``===`` compares objects by reference; Python compares lists, tuples,
// dicts and sets by value. ``True == 1`` and ``1 == 1.0`` hold in Python.
// Lists and tuples are both arrays here, so ``[1] == (1,)`` (False in Python)
// compares equal; ported code must not rely on that distinction.

import { PyTypeError, ValueError } from './errors.ts';
import { PyFloat } from './number.ts';
import { isDict } from './truthy.ts';

function scalar(value: unknown): unknown {
  if (value instanceof PyFloat) return value.value;
  if (typeof value === 'boolean') return value ? 1 : 0;
  if (value === undefined) return null;
  return value;
}

function entriesOf(value: unknown): [unknown, unknown][] | null {
  if (value instanceof Map) return [...value.entries()];
  if (isDict(value)) return Object.entries(value);
  return null;
}

/** ``a == b`` */
export function pyEq(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  const x = scalar(a);
  const y = scalar(b);
  if (typeof x === 'number' || typeof y === 'number') return x === y;
  if (x === null || y === null) return x === y;
  if (typeof x !== 'object' || typeof y !== 'object') return x === y;
  if (Array.isArray(x)) {
    if (!Array.isArray(y) || x.length !== y.length) return false;
    for (let i = 0; i < x.length; i += 1) if (!pyEq(x[i], y[i])) return false;
    return true;
  }
  if (x instanceof Set) {
    if (!(y instanceof Set) || x.size !== y.size) return false;
    for (const item of x) if (!pyIn(item, y)) return false;
    return true;
  }
  const left = entriesOf(x);
  const right = entriesOf(y);
  if (left && right) {
    if (left.length !== right.length) return false;
    for (const [key, value] of left) {
      const match = right.find(([other]) => pyEq(key, other));
      if (!match || !pyEq(value, match[1])) return false;
    }
    return true;
  }
  return false;
}

/** ``a != b`` */
export function pyNe(a: unknown, b: unknown): boolean {
  return !pyEq(a, b);
}

/** ``item in container`` for str, list/tuple, set, dict (keys) and Map (keys). */
export function pyIn(item: unknown, container: unknown): boolean {
  if (typeof container === 'string') {
    if (typeof item !== 'string') throw new PyTypeError("'in <string>' requires string as left operand");
    return container.includes(item);
  }
  if (Array.isArray(container)) {
    for (const value of container) if (pyEq(item, value)) return true;
    return false;
  }
  if (container instanceof Set || container instanceof Map) {
    if (container.has(item)) return true;
    if (item !== null && typeof item === 'object') {
      for (const key of container.keys()) if (pyEq(item, key)) return true;
    } else if (typeof item === 'number' || typeof item === 'boolean') {
      for (const key of container.keys()) if ((typeof key === 'number' || typeof key === 'boolean') && pyEq(item, key)) return true;
    }
    return false;
  }
  if (isDict(container)) {
    return typeof item === 'string' && Object.prototype.hasOwnProperty.call(container, item);
  }
  if (container === null || container === undefined) throw new PyTypeError("argument of type 'NoneType' is not iterable");
  throw new PyTypeError('argument is not iterable');
}

/** ``item not in container`` */
export function pyNotIn(item: unknown, container: unknown): boolean {
  return !pyIn(item, container);
}

/** ``seq.index(item)`` — first index whose element ``== item``; ``ValueError`` if absent. */
export function pyIndex(seq: readonly unknown[], item: unknown): number {
  for (let i = 0; i < seq.length; i += 1) if (pyEq(seq[i], item)) return i;
  throw new ValueError('value is not in list');
}

/** ``seq.count(item)`` */
export function pyCount(seq: readonly unknown[], item: unknown): number {
  let count = 0;
  for (const value of seq) if (pyEq(value, item)) count += 1;
  return count;
}

/** ``list.remove(item)`` — removes the first equal element in place. */
export function pyRemove(seq: unknown[], item: unknown): void {
  seq.splice(pyIndex(seq, item), 1);
}
