// Python ``dict`` / ``Mapping`` access over plain objects and ``Map``
// (MIGRATION_PLAN.md §4: string-keyed dicts are plain objects; dicts with
// non-string or integer-like keys are ``Map``).
//
//   d.get(k, default)   -> pyGet(d, k, default)
//   d.items()/keys()/values() -> pyItems(d) / pyKeys(d) / pyValues(d)
//   k in d              -> pyIn(k, d)  (eq.ts)
//   d.setdefault(k, v)  -> pySetdefault(d, k, v)
//   d.pop(k, default)   -> pyPop(d, k, default)

import { AttributeError, KeyError } from './errors.ts';
import { isDict } from './truthy.ts';

export type PyMapping<V = unknown> = Record<string, V> | Map<unknown, V>;

function hasOwn(obj: object, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(obj, key);
}

/**
 * ``mapping.get(key, default)``; missing ``default`` means ``None`` (``null``).
 * Like Python, calling it on a non-mapping (``None``, a list, a str ...)
 * raises ``AttributeError``.
 */
export function pyGet<V, D = null>(mapping: PyMapping<V>, key: unknown, defaultValue?: D): V | D;
export function pyGet<D = null>(mapping: unknown, key: unknown, defaultValue?: D): unknown;
export function pyGet<V, D = null>(mapping: unknown, key: unknown, defaultValue: D = null as D): V | D {
  if (mapping instanceof Map) return mapping.has(key) ? (mapping.get(key) as V) : defaultValue;
  if (!isDict(mapping)) {
    throw new AttributeError(`'${mapping === null || mapping === undefined ? 'NoneType' : Array.isArray(mapping) ? 'list' : typeof mapping}' object has no attribute 'get'`);
  }
  if (typeof key === 'string' && hasOwn(mapping, key)) return (mapping as Record<string, V>)[key];
  return defaultValue;
}

/** ``mapping[key]`` raising ``KeyError`` when absent. */
export function pyGetItem<V>(mapping: PyMapping<V>, key: unknown): V {
  if (mapping instanceof Map) {
    if (!mapping.has(key)) throw new KeyError(String(key));
    return mapping.get(key) as V;
  }
  if (typeof key !== 'string' || !hasOwn(mapping, key)) throw new KeyError(String(key));
  return mapping[key];
}

/** ``list(mapping.items())`` */
export function pyItems<V>(mapping: PyMapping<V>): [unknown, V][] {
  if (mapping instanceof Map) return [...mapping.entries()];
  return Object.entries(mapping);
}

/** ``list(mapping.keys())`` */
export function pyKeys(mapping: PyMapping): unknown[] {
  if (mapping instanceof Map) return [...mapping.keys()];
  return Object.keys(mapping);
}

/** ``list(mapping.values())`` */
export function pyValues<V>(mapping: PyMapping<V>): V[] {
  if (mapping instanceof Map) return [...mapping.values()];
  return Object.values(mapping);
}

/** ``mapping.setdefault(key, value)`` */
export function pySetdefault<V>(mapping: PyMapping<V>, key: string, value: V): V {
  if (mapping instanceof Map) {
    if (!mapping.has(key)) mapping.set(key, value);
    return mapping.get(key) as V;
  }
  if (!hasOwn(mapping, key)) mapping[key] = value;
  return mapping[key];
}

const NO_DEFAULT = Symbol('NO_DEFAULT');

/** ``mapping.pop(key[, default])`` */
export function pyPop<V, D = never>(mapping: PyMapping<V>, key: unknown, defaultValue: D | typeof NO_DEFAULT = NO_DEFAULT): V | D {
  if (mapping instanceof Map) {
    if (mapping.has(key)) {
      const value = mapping.get(key) as V;
      mapping.delete(key);
      return value;
    }
  } else if (typeof key === 'string' && hasOwn(mapping, key)) {
    const value = mapping[key];
    delete mapping[key];
    return value;
  }
  if (defaultValue === NO_DEFAULT) throw new KeyError(String(key));
  return defaultValue;
}

/** ``isinstance(x, Mapping)`` narrowing helper re-exported for convenience. */
export function isPyMapping(value: unknown): value is PyMapping {
  return value instanceof Map || isDict(value);
}
