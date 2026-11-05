// Unit tests for the Python-semantics runtime (src/py), checked against
// ground truth produced by CPython: test/py/python_expected.json
// (regenerate with test/py/gen_python_expected.py) and the converter's
// recorded _stable_payload / _stable_digest vectors.
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { loadVectors, listFunctionFixtures } from '../harness/fixtures.ts';
import { pyEq, pyIn } from '../../src/py/eq.ts';
import { JSONDecodeError, ValueError } from '../../src/py/errors.ts';
import { md5Hex, sha256Hex } from '../../src/py/hash.ts';
import { pyJsonDumps, pyJsonLoads, pyStableJsonDumps, type JsonDumpsOptions } from '../../src/py/json.ts';
import { dist, hypot } from '../../src/py/math.ts';
import { PyFloat, floorDiv, pyMod, pyRound } from '../../src/py/number.ts';
import { pyMax, pyMin, pySorted } from '../../src/py/sort.ts';
import {
  cpLen, cpSlice, floatRepr, pyFormatFixed, pyFormatPercent, pyIsdigit, pyIslower, pyIsspace, pyIsupper, pyLstrip,
  pyRepr, pyRsplit, pyRstrip, pySplit, pyStr, pyStrip, pyZfill,
} from '../../src/py/str.ts';
import { truthy } from '../../src/py/truthy.ts';
import { UNIDATA_VERSION, east_asian_width } from '../../src/py/unicodedata.ts';
import { getEnv, setEnv, clearEnv } from '../../src/py/env.ts';
import { globAssets, readAssetJson } from '../../src/py/assets.ts';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const expected: any = JSON.parse(readFileSync(join(import.meta.dirname, 'python_expected.json'), 'utf-8'));

/** float.hex() -> number (exact). */
function fromHex(text: string): number {
  if (text === 'inf') return Infinity;
  if (text === '-inf') return -Infinity;
  if (text === 'nan') return NaN;
  const match = /^(-?)0x([01])\.([0-9a-f]+)p([+-]\d+)$/.exec(text);
  if (!match) throw new Error(`bad hex float ${text}`);
  const [, sign, lead, frac, exp] = match;
  let mantissa = BigInt(`0x${lead}${frac}`);
  let exponent = Number(exp) - frac.length * 4;
  // Build exactly: shift mantissa so the conversion to Number is exact.
  let value: number;
  if (mantissa === 0n) value = 0;
  else {
    while (mantissa % 2n === 0n) {
      mantissa /= 2n;
      exponent += 1;
    }
    value = Number(mantissa);
    // Scale in steps that keep intermediate values exact (powers of two).
    while (exponent > 0) {
      const step = Math.min(exponent, 1000);
      value *= 2 ** step;
      exponent -= step;
    }
    while (exponent < 0) {
      const step = Math.max(exponent, -1000);
      // Avoid double rounding into subnormals: divide by 2**k only when exact.
      value /= 2 ** -step;
      exponent -= step;
    }
  }
  return sign ? -value : value;
}

function sameFloat(actual: number, want: number): boolean {
  return Object.is(actual, want) || (Number.isNaN(actual) && Number.isNaN(want));
}

function parseWithFloats(text: string): unknown {
  return pyJsonLoads(text, { parseFloat: (t) => new PyFloat(Number(t)), parseConstant: (t) => new PyFloat(Number(t)) });
}

describe('number', () => {
  it('pyRound matches round(x) and round(x, n)', () => {
    const bad: unknown[] = [];
    for (const [xHex, n, wantHex] of expected.round as [string, number | null, string][]) {
      const got = pyRound(fromHex(xHex), n);
      const want = fromHex(wantHex);
      if (!(got === want || (got === 0 && want === 0))) bad.push([xHex, n, wantHex, got]);
    }
    expect(bad.slice(0, 5)).toEqual([]);
    expect(expected.round.length).toBeGreaterThan(1000);
  });

  it('floorDiv / pyMod match a // b and a % b', () => {
    const bad: unknown[] = [];
    for (const [aHex, bHex, qHex, rHex] of expected.divmod as string[][]) {
      const a = fromHex(aHex);
      const b = fromHex(bHex);
      const q = floorDiv(a, b);
      const r = pyMod(a, b);
      const wantQ = fromHex(qHex);
      const wantR = fromHex(rHex);
      const intCase = Number.isSafeInteger(a) && Number.isSafeInteger(b);
      const okQ = intCase ? q === wantQ : sameFloat(q, wantQ);
      const okR = intCase ? r === wantR : sameFloat(r, wantR);
      if (!okQ || !okR) bad.push([aHex, bHex, qHex, rHex, q, r]);
    }
    expect(bad.slice(0, 5)).toEqual([]);
  });

  it('round half to even', () => {
    expect([0.5, 1.5, 2.5, -0.5, -1.5].map((x) => pyRound(x))).toEqual([0, 2, 2, 0, -2]);
    expect(pyRound(2.675, 2)).toBe(2.67);
    expect(pyRound(0.125, 2)).toBe(0.12);
    expect(() => pyRound(NaN)).toThrow(ValueError);
  });
});

describe('str', () => {
  it('floatRepr / pyStr match repr(float) and str(float)', () => {
    const bad: unknown[] = [];
    for (const [xHex, repr, str] of expected.float_repr as string[][]) {
      const x = fromHex(xHex);
      if (floatRepr(x) !== repr || pyStr(new PyFloat(x)) !== str) bad.push([xHex, repr, floatRepr(x)]);
    }
    expect(bad.slice(0, 5)).toEqual([]);
    expect(pyStr(3)).toBe('3');
    expect(pyStr(new PyFloat(3))).toBe('3.0');
    expect(pyStr(null)).toBe('None');
    expect(pyStr(true)).toBe('True');
    expect(pyRepr(['a', 1, null, { k: false }])).toBe("['a', 1, None, {'k': False}]");
  });

  it('format(x, spec) matches .Nf and .N%', () => {
    const bad: unknown[] = [];
    for (const [xHex, spec, want] of expected.format as string[][]) {
      const x = fromHex(xHex);
      const digits = Number(spec.slice(1, -1));
      const got = spec.endsWith('%') ? pyFormatPercent(x, digits) : pyFormatFixed(x, digits);
      if (got !== want) bad.push([xHex, spec, want, got]);
    }
    expect(bad.slice(0, 5)).toEqual([]);
  });

  it('split / strip / case / slicing match str methods', () => {
    for (const c of expected.strings) {
      const t: string = c.text;
      const got = {
        text: t,
        split: pySplit(t), split1: pySplit(t, null, 1), split_comma: pySplit(t, ','), split_comma1: pySplit(t, ',', 1),
        rsplit1: pyRsplit(t, null, 1), rsplit_comma1: pyRsplit(t, ',', 1),
        strip: pyStrip(t), lstrip: pyLstrip(t), rstrip: pyRstrip(t), strip_chars: pyStrip(t, '-a '),
        lower: t.toLowerCase(), upper: t.toUpperCase(), isupper: pyIsupper(t), islower: pyIslower(t), isspace: pyIsspace(t),
        isdigit: pyIsdigit(t), len: cpLen(t), repr: pyRepr(t), slice: cpSlice(t, 1, -1), slice_step: cpSlice(t, null, null, -2),
        zfill: pyZfill(t, 8),
      };
      expect(got).toEqual(c);
    }
  });
});

describe('sort', () => {
  it('sorts strings by code point', () => {
    expect(pySorted(expected.sorted_strings.input)).toEqual(expected.sorted_strings.sorted);
  });

  it('sorted / min / max on tuples with keys, reverse and ties', () => {
    const t = expected.sorted_tuples;
    const input = t.input as unknown[][];
    expect(pySorted(input)).toEqual(t.sorted);
    expect(pySorted(input, null, true)).toEqual(t.sorted_rev);
    expect(pySorted(input, (x) => x[0])).toEqual(t.sorted_key0);
    expect(pySorted(input, (x) => x[0], true)).toEqual(t.sorted_key0_rev);
    // Identity matters for min/max ties: compare indices of the chosen element.
    const firstIndex = (want: unknown[]) => input.findIndex((x) => pyEq(x, want));
    expect(input.indexOf(pyMin(input, (x) => x[0]))).toBe(firstIndex(t.min_key0));
    expect(input.indexOf(pyMax(input, (x) => x[0]))).toBe(firstIndex(t.max_key0));
    expect(input.indexOf(pyMin(input, (x) => x[2]))).toBe(firstIndex(t.min_key2));
    expect(input.indexOf(pyMax(input, (x) => x[2]))).toBe(firstIndex(t.max_key2));
    expect(() => pyMin([])).toThrow(ValueError);
    expect(pyMin([], null, null)).toBe(null);
    expect(pyMax([NaN, 1, 2])).toBeNaN(); // Python: max([nan, 1, 2]) is nan
    expect(pyMax([1, NaN, 2])).toBe(2);
  });
});

describe('eq / truthy', () => {
  it('deep equality and membership', () => {
    expect(pyEq([1, [2, { a: 3 }]], [1, [2, { a: 3 }]])).toBe(true);
    expect(pyEq({ a: 1, b: 2 }, { b: 2, a: 1 })).toBe(true);
    expect(pyEq(true, 1)).toBe(true);
    expect(pyEq(new Set([1, 2]), new Set([2, 1]))).toBe(true);
    expect(pyEq(null, 0)).toBe(false);
    expect(pyIn([1, 2], [[0, 1], [1, 2]])).toBe(true);
    expect(pyIn('b', { b: 1 })).toBe(true);
    expect(pyIn('toString', {})).toBe(false);
    expect(pyIn('ell', 'hello')).toBe(true);
  });

  it('truthiness', () => {
    expect([[], {}, '', 0, null, undefined, new Map(), new Set(), false].map(truthy)).toEqual(Array(9).fill(false));
    expect([[0], { a: 0 }, ' ', NaN, -1, true].map(truthy)).toEqual(Array(6).fill(true));
  });
});

describe('json', () => {
  it('pyJsonDumps matches json.dumps for every option set', () => {
    for (const c of expected.json_dumps) {
      const options: JsonDumpsOptions = {
        sortKeys: c.options.sort_keys,
        ensureAscii: c.options.ensure_ascii,
        separators: c.options.separators,
        indent: c.options.indent,
      };
      expect(pyJsonDumps(parseWithFloats(c.value), options), `${c.value} ${JSON.stringify(c.options)}`).toBe(c.expected);
    }
  });

  it('pyJsonLoads matches json.loads', () => {
    for (const [text, dumped] of expected.json_loads as string[][]) {
      expect(pyJsonDumps(parseWithFloats(text))).toBe(dumped);
    }
    for (const text of expected.json_loads_errors as string[]) {
      expect(() => pyJsonLoads(text), text).toThrow(JSONDecodeError);
    }
  });

  it('default=str, circular references and unsupported values', () => {
    expect(pyJsonDumps({ s: new Set(['a']) }, { default: pyStr })).toBe('{"s": "{\'a\'}"}');
    const loop: unknown[] = [];
    loop.push(loop);
    expect(() => pyJsonDumps(loop)).toThrow(ValueError);
    expect(() => pyJsonDumps(new Set())).toThrow();
  });

  // The converter hashes these payloads into every Excalidraw element id.
  const converter = 'evodesign.agentic_system.render_engine.excalidraw.converter';
  const hasConverterVectors = listFunctionFixtures(converter).includes('_stable_payload');
  it.skipIf(!hasConverterVectors)('reproduces converter _stable_payload / _stable_digest vectors', () => {
    const payloads = loadVectors(converter, '_stable_payload');
    expect(payloads.length).toBeGreaterThan(0);
    for (const vector of payloads) {
      expect(pyStableJsonDumps(vector.args[0]), `line ${vector.line}`).toBe(vector.result);
    }
    for (const vector of loadVectors(converter, '_stable_digest')) {
      const [namespace, value] = vector.args as [string, unknown];
      expect(sha256Hex(`${namespace}:${pyStableJsonDumps(value)}`), `line ${vector.line}`).toBe(vector.result);
    }
  });
});

describe('hash', () => {
  it('sha256 / md5 hex match hashlib', () => {
    for (const [text, sha, md5] of expected.hashes as string[][]) {
      expect(sha256Hex(text), JSON.stringify(text)).toBe(sha);
      expect(md5Hex(text), JSON.stringify(text)).toBe(md5);
    }
  });
});

describe('math', () => {
  it('hypot / dist are bit-identical to CPython', () => {
    const bad: unknown[] = [];
    for (const [a, b, want] of expected.hypot as [string | string[], string | string[], string][]) {
      const got = Array.isArray(a) ? dist(a.map(fromHex), (b as string[]).map(fromHex)) : hypot(fromHex(a), fromHex(b as string));
      if (!sameFloat(got, fromHex(want))) bad.push([a, b, want, got]);
    }
    expect(bad.slice(0, 5)).toEqual([]);
  });
});

describe('unicodedata', () => {
  it('east_asian_width matches CPython for every code point', () => {
    expect(UNIDATA_VERSION).toBe(expected.unidata_version);
    const short: Record<string, string> = { N: 'N', Na: 'n', A: 'A', F: 'F', H: 'H', W: 'W' };
    let all = '';
    for (let cp = 0; cp < 0x110000; cp += 1) all += short[east_asian_width(String.fromCodePoint(cp))];
    expect(sha256Hex(all)).toBe(expected.east_asian_width_sha256);
  });
});

describe('env / assets', () => {
  it('getEnv falls back to the Python default', () => {
    expect(getEnv('EVODESIGN_TEST_UNSET_VARIABLE', '1')).toBe('1');
    setEnv('EVODESIGN_TEST_UNSET_VARIABLE', '0');
    expect(getEnv('EVODESIGN_TEST_UNSET_VARIABLE', '1')).toBe('0');
    clearEnv('EVODESIGN_TEST_UNSET_VARIABLE');
    expect(getEnv('EVODESIGN_TEST_UNSET_VARIABLE')).toBe(null);
  });

  it('reads Python-side assets', () => {
    expect(globAssets('system_prompt/type_patterns', '*.md').length).toBeGreaterThan(0);
    expect(typeof readAssetJson('common/assets/material_icons.json')).toBe('object');
  });
});
