// Loading and decoding the Python fixtures written by tools/export_fixtures.py.
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

export const PACKAGE_ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
export const FIXTURES = join(PACKAGE_ROOT, 'fixtures');

export interface Param {
  name: string;
  kind: 'POSITIONAL_ONLY' | 'POSITIONAL_OR_KEYWORD' | 'VAR_POSITIONAL' | 'KEYWORD_ONLY' | 'VAR_KEYWORD';
  has_default: boolean;
}

export interface Vector {
  args: unknown[];
  kwargs: Record<string, unknown>;
  result?: unknown;
  args_after?: unknown[];
  kwargs_after?: Record<string, unknown>;
  raises?: string;
  message?: string;
  source: 'examples' | 'pytest' | `run:${string}`;
  line: number;
}

/** Python values that JSON cannot carry, decoded into their TS counterparts. */
export function decode(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(decode);
  if (value === null || typeof value !== 'object') return value;
  const record = value as Record<string, unknown>;
  const keys = Object.keys(record);
  if (keys.length === 1 && '__tuple__' in record) return (record.__tuple__ as unknown[]).map(decode);
  if (keys.length === 1 && '__set__' in record) return new Set((record.__set__ as unknown[]).map(decode));
  if (keys.length === 1 && '__float__' in record) return parsePythonFloat(record.__float__ as string);
  if (keys.length === 1 && '__dict__' in record) {
    const entries = (record.__dict__ as [unknown, unknown][]).map(([k, v]) => [decode(k), decode(v)] as const);
    // String-keyed dicts with dunder keys are tagged only to avoid confusion.
    if (entries.every(([k]) => typeof k === 'string')) return Object.fromEntries(entries);
    return new Map(entries);
  }
  if (keys.length === 2 && ('__dataclass__' in record || '__model__' in record)) {
    return decode(record.fields);
  }
  // Phase 2 encodings (tools/export_fixtures.py encode()).
  if (keys.length === 2 && '__message__' in record) {
    // langchain message → { type, content, [name], [tool_calls], [tool_call_id] }
    return { type: record.__message__, ...(decode(record.fields) as Record<string, unknown>) };
  }
  if (keys.length === 1 && '__path__' in record) return record.__path__;
  if (keys.length === 2 && '__enum__' in record) return decode(record.value);
  return Object.fromEntries(keys.map((key) => [key, decode(record[key])]));
}

function parsePythonFloat(text: string): number {
  if (text === 'nan') return Number.NaN;
  if (text === 'inf') return Number.POSITIVE_INFINITY;
  if (text === '-inf') return Number.NEGATIVE_INFINITY;
  return Number(text);
}

export function pythonModuleDir(pythonModule: string): string {
  return join(FIXTURES, 'functions', pythonModule);
}

export function listFunctionFixtures(pythonModule: string): string[] {
  const dir = pythonModuleDir(pythonModule);
  if (!existsSync(dir)) return [];
  return readdirSync(dir)
    .filter((name) => name.endsWith('.jsonl'))
    .map((name) => name.slice(0, -'.jsonl'.length))
    .sort();
}

export function loadVectors(pythonModule: string, func: string): Vector[] {
  const text = readFileSync(join(pythonModuleDir(pythonModule), `${func}.jsonl`), 'utf-8');
  return text
    .split('\n')
    .filter(Boolean)
    .map((line, index) => {
      const raw = JSON.parse(line) as Record<string, unknown>;
      return {
        ...raw,
        args: decode(raw.args) as unknown[],
        kwargs: decode(raw.kwargs) as Record<string, unknown>,
        result: 'result' in raw ? decode(raw.result) : undefined,
        args_after: raw.args_after === undefined ? undefined : (decode(raw.args_after) as unknown[]),
        kwargs_after: raw.kwargs_after === undefined ? undefined : (decode(raw.kwargs_after) as Record<string, unknown>),
        line: index + 1,
      } as Vector;
    });
}

let signatures: Record<string, Param[]> | undefined;

export function signatureOf(pythonModule: string, func: string): Param[] | undefined {
  signatures ??= JSON.parse(readFileSync(join(FIXTURES, 'functions', '_signatures.json'), 'utf-8'));
  return signatures![`${pythonModule}/${func}`];
}

/**
 * Bind a recorded Python call to the TS calling convention: every Python
 * parameter becomes a positional TS parameter in declaration order (keyword-
 * only ones included); unspecified ones are passed as undefined so TS
 * defaults apply. ``*args`` is spread; ``**kwargs`` becomes a trailing object.
 */
export function bindArguments(params: Param[], vector: Vector): unknown[] {
  const bound: unknown[] = [];
  const kwargs = { ...vector.kwargs };
  let index = 0;
  for (const param of params) {
    if (param.kind === 'VAR_POSITIONAL') {
      bound.push(...vector.args.slice(index));
      index = vector.args.length;
    } else if (param.kind === 'VAR_KEYWORD') {
      bound.push(kwargs);
    } else if ((param.kind === 'POSITIONAL_ONLY' || param.kind === 'POSITIONAL_OR_KEYWORD') && index < vector.args.length) {
      bound.push(vector.args[index++]);
    } else if (param.name in kwargs) {
      bound.push(kwargs[param.name]);
      delete kwargs[param.name];
    } else {
      bound.push(undefined);
    }
  }
  while (bound.length && bound[bound.length - 1] === undefined) bound.pop();
  return bound;
}
