// Structural comparison of a Python fixture value with a TS value.
//
// Parity criterion (MIGRATION_PLAN.md §4): same structure and types, same
// strings/booleans/nulls, numbers equal within ABS_TOLERANCE. Python tuples
// and lists are both arrays; sets compare order-free; dict key order is
// reported separately and never fails a vector.

export const ABS_TOLERANCE = 1e-6;
const EXACT = 1e-9;

export interface Comparison {
  diffs: string[];
  tolerated: number; // numbers equal only within ABS_TOLERANCE
  keyOrder: string[]; // object paths whose key order differs
}

export function compare(expected: unknown, actual: unknown, limit = 8): Comparison {
  const state: Comparison = { diffs: [], tolerated: 0, keyOrder: [] };
  walk(expected, actual, '$', state, limit);
  return state;
}

function describe(value: unknown): string {
  if (value instanceof Map) return `Map(${value.size})`;
  if (value instanceof Set) return `Set(${value.size})`;
  const text = JSON.stringify(value);
  return text === undefined ? String(value) : text.length > 120 ? `${text.slice(0, 117)}...` : text;
}

function walk(expected: unknown, actual: unknown, path: string, state: Comparison, limit: number): void {
  if (state.diffs.length >= limit) return;
  const fail = (why: string): void => {
    state.diffs.push(`${path}: ${why}`);
  };

  if (typeof expected === 'number' && typeof actual === 'number') {
    if (Number.isNaN(expected) && Number.isNaN(actual)) return;
    if (expected === actual) return;
    const delta = Math.abs(expected - actual);
    if (delta <= EXACT * Math.max(1, Math.abs(expected))) return;
    if (delta <= ABS_TOLERANCE) {
      state.tolerated += 1;
      return;
    }
    fail(`expected ${expected}, got ${actual}`);
    return;
  }
  if (expected === null || typeof expected !== 'object') {
    if (expected !== actual) fail(`expected ${describe(expected)}, got ${describe(actual)}`);
    return;
  }
  if (expected instanceof Set) {
    if (!(actual instanceof Set) && !Array.isArray(actual)) return fail(`expected ${describe(expected)}, got ${describe(actual)}`);
    const sort = (items: unknown[]) => items.map((item) => JSON.stringify(normalizeForSet(item))).sort();
    const left = sort([...expected]);
    const right = sort([...(actual as Iterable<unknown>)]);
    if (left.join('\u0000') !== right.join('\u0000')) fail(`set differs: expected ${describe(left)}, got ${describe(right)}`);
    return;
  }
  if (expected instanceof Map) {
    const entries = actual instanceof Map ? [...actual.entries()] : actual && typeof actual === 'object' ? Object.entries(actual) : null;
    if (!entries) return fail(`expected ${describe(expected)}, got ${describe(actual)}`);
    const want = [...expected.entries()];
    if (want.length !== entries.length) return fail(`map size ${want.length} != ${entries.length}`);
    want.forEach(([key, value], index) => {
      const match = entries.find(([other]) => compare(key, other, 1).diffs.length === 0) ?? entries[index];
      walk(value, match?.[1], `${path}[${describe(key)}]`, state, limit);
    });
    return;
  }
  if (Array.isArray(expected)) {
    if (!Array.isArray(actual)) return fail(`expected array(${expected.length}), got ${describe(actual)}`);
    if (expected.length !== actual.length) fail(`length ${expected.length} != ${actual.length}`);
    for (let i = 0; i < Math.min(expected.length, actual.length); i += 1) walk(expected[i], actual[i], `${path}[${i}]`, state, limit);
    return;
  }
  if (actual === null || typeof actual !== 'object' || Array.isArray(actual)) {
    return fail(`expected object, got ${describe(actual)}`);
  }
  const want = expected as Record<string, unknown>;
  const got = actual as Record<string, unknown>;
  const wantKeys = Object.keys(want);
  const gotKeys = Object.keys(got).filter((key) => got[key] !== undefined);
  for (const key of wantKeys) {
    if (!(key in got) || got[key] === undefined) {
      fail(`missing key ${JSON.stringify(key)} (expected ${describe(want[key])})`);
      continue;
    }
    walk(want[key], got[key], `${path}.${key}`, state, limit);
  }
  for (const key of gotKeys) if (!(key in want)) fail(`unexpected key ${JSON.stringify(key)} = ${describe(got[key])}`);
  if (wantKeys.join('\u0000') !== gotKeys.join('\u0000') && wantKeys.length === gotKeys.length) state.keyOrder.push(path);
}

function normalizeForSet(value: unknown): unknown {
  if (value instanceof Set) return [...value].map(normalizeForSet).sort();
  if (Array.isArray(value)) return value.map(normalizeForSet);
  return value;
}
