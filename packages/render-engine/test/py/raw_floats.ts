// Re-read a fixture vector keeping Python floats as ``PyFloat``.
//
// The shared harness decodes fixtures with JSON.parse, which turns Python's
// ``100.0`` into ``100``. Functions whose *output text* depends on int vs float
// (json.dumps / str of a number) need the original float-ness to be replayed
// faithfully; their adapters rebuild the arguments with this helper. In real
// pipeline code the same distinction is made with ``PyFloat`` (src/py/number.ts).
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { PyFloat } from '../../src/py/number.ts';
import { pyJsonLoads } from '../../src/py/json.ts';
import { bindArguments, pythonModuleDir, signatureOf, type Vector } from '../harness/fixtures.ts';

const lineCache = new Map<string, string[]>();

function decodeKeepingFloats(value: unknown): unknown {
  if (value instanceof PyFloat) return value;
  if (Array.isArray(value)) return value.map(decodeKeepingFloats);
  if (value === null || typeof value !== 'object') return value;
  const record = value as Record<string, unknown>;
  const keys = Object.keys(record);
  if (keys.length === 1 && '__tuple__' in record) return (record.__tuple__ as unknown[]).map(decodeKeepingFloats);
  if (keys.length === 1 && '__set__' in record) return new Set((record.__set__ as unknown[]).map(decodeKeepingFloats));
  if (keys.length === 1 && '__float__' in record) {
    const text = record.__float__ as string;
    return new PyFloat(text === 'nan' ? NaN : text === 'inf' ? Infinity : text === '-inf' ? -Infinity : Number(text));
  }
  if (keys.length === 1 && '__dict__' in record) {
    const entries = (record.__dict__ as [unknown, unknown][]).map(([k, v]) => [decodeKeepingFloats(k), decodeKeepingFloats(v)] as const);
    if (entries.every(([k]) => typeof k === 'string')) return Object.fromEntries(entries);
    return new Map(entries);
  }
  if (keys.length === 2 && ('__dataclass__' in record || '__model__' in record)) return decodeKeepingFloats(record.fields);
  return Object.fromEntries(keys.map((key) => [key, decodeKeepingFloats(record[key])]));
}

/** Arguments of fixture ``line`` (1-based) with floats as ``PyFloat``, bound like the harness does. */
export function bindWithFloats(pythonModule: string, func: string, vector: Vector): unknown[] {
  const cacheKey = `${pythonModule}/${func}`;
  let lines = lineCache.get(cacheKey);
  if (!lines) {
    lines = readFileSync(join(pythonModuleDir(pythonModule), `${func}.jsonl`), 'utf-8').split('\n').filter(Boolean);
    lineCache.set(cacheKey, lines);
  }
  const raw = pyJsonLoads(lines[vector.line - 1], { parseFloat: (text) => new PyFloat(Number(text)) }) as Record<string, unknown>;
  const args = decodeKeepingFloats(raw.args) as unknown[];
  const kwargs = decodeKeepingFloats(raw.kwargs) as Record<string, unknown>;
  return bindArguments(signatureOf(pythonModule, func)!, { ...vector, args, kwargs });
}
