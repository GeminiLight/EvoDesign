// Python truthiness and type predicates (MIGRATION_PLAN.md §4).
//
// ``if x:`` / ``x or y`` / ``x and y`` must go through ``truthy`` because JS
// treats ``[]``, ``{}`` and ``NaN`` differently from Python:
//   Python: bool([]) is False, bool({}) is False, bool(float('nan')) is True.

import { PyTypeError } from './errors.ts';
import { PyFloat } from './number.ts';

/** ``bool(value)`` with Python semantics. */
export function truthy(value: unknown): boolean {
  if (value === null || value === undefined) return false;
  switch (typeof value) {
    case 'boolean':
      return value;
    case 'number':
      // NaN is truthy in Python; only 0 / -0.0 are falsy.
      return value !== 0;
    case 'bigint':
      return value !== 0n;
    case 'string':
      return value.length > 0;
    case 'function':
      return true;
    default:
      break;
  }
  if (Array.isArray(value)) return value.length > 0;
  if (value instanceof Map || value instanceof Set) return value.size > 0;
  if (value instanceof PyFloat) return value.value !== 0;
  if (isDict(value)) return Object.keys(value).length > 0;
  return true;
}

/** ``x or y`` — returns the first truthy operand, else the last one. */
export function pyOr<T, U>(left: T, right: U): T | U {
  return truthy(left) ? left : right;
}

/** ``x and y`` — returns the first falsy operand, else the last one. */
export function pyAnd<T, U>(left: T, right: U): T | U {
  return truthy(left) ? right : left;
}

/** ``not x`` */
export function pyNot(value: unknown): boolean {
  return !truthy(value);
}

/**
 * ``isinstance(x, dict)`` for the JSON-ish values the engine handles:
 * a plain object (prototype Object or null). Arrays, Maps, Sets and class
 * instances are not dicts. Use ``isMapping`` to also accept ``Map``.
 */
export function isDict(value: unknown): value is Record<string, unknown> {
  if (value === null || typeof value !== 'object') return false;
  const proto = Object.getPrototypeOf(value);
  return proto === Object.prototype || proto === null;
}

/** ``isinstance(x, Mapping)`` — a plain object or a ``Map``. */
export function isMapping(value: unknown): value is Record<string, unknown> | Map<unknown, unknown> {
  return value instanceof Map || isDict(value);
}

/** ``isinstance(x, str)`` */
export function isStr(value: unknown): value is string {
  return typeof value === 'string';
}

/** ``isinstance(x, bool)`` */
export function isBool(value: unknown): value is boolean {
  return typeof value === 'boolean';
}

/**
 * ``isinstance(x, (int, float)) and not isinstance(x, bool)`` — a real number.
 * (Python bools are ints; use ``isNumberOrBool`` when the Python code does
 * not exclude bool.)
 */
export function isNumber(value: unknown): value is number {
  return typeof value === 'number';
}

/** ``isinstance(x, (int, float))`` including ``bool`` (Python bool is an int). */
export function isNumberOrBool(value: unknown): value is number | boolean {
  return typeof value === 'number' || typeof value === 'boolean';
}

/**
 * ``isinstance(x, int)`` best effort: TS cannot tell ``3`` from ``3.0``, so
 * integral numbers count as int. Python's ``isinstance(True, int)`` is True,
 * so pass ``includeBool`` to match code that does not exclude bools.
 */
export function isInt(value: unknown, includeBool = false): value is number {
  if (typeof value === 'boolean') return includeBool;
  return typeof value === 'number' && Number.isInteger(value) && !Object.is(value, -0);
}

/** ``isinstance(x, (list, tuple))`` */
export function isList(value: unknown): value is unknown[] {
  return Array.isArray(value);
}

/** ``isinstance(x, (set, frozenset))`` */
export function isSet(value: unknown): value is Set<unknown> {
  return value instanceof Set;
}

/** ``len(x)`` for containers and strings (strings counted in code points). */
export function pyLen(value: unknown): number {
  if (typeof value === 'string') {
    let count = 0;
    for (const _ of value) count += 1;
    return count;
  }
  if (Array.isArray(value)) return value.length;
  if (value instanceof Map || value instanceof Set) return value.size;
  if (isDict(value)) return Object.keys(value).length;
  throw new PyTypeError(`object of type '${typeof value}' has no len()`);
}

/** Python ``type(x).__name__`` for error messages. */
export function pyTypeName(value: unknown): string {
  if (value === null || value === undefined) return 'NoneType';
  if (typeof value === 'boolean') return 'bool';
  if (typeof value === 'number') return Number.isInteger(value) ? 'int' : 'float';
  if (typeof value === 'string') return 'str';
  if (Array.isArray(value)) return 'list';
  if (value instanceof Set) return 'set';
  if (value instanceof Map || isDict(value)) return 'dict';
  if (value instanceof PyFloat) return 'float';
  if (typeof value === 'function') return 'function';
  return (value as object).constructor?.name ?? 'object';
}
