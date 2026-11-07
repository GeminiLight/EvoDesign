// Python string semantics (MIGRATION_PLAN.md §4).
//
//   str(x) / f"{x}"      -> pyStr(x)       floats use repr: 1.0, 1e+16, 1.5e-05
//   repr(x)              -> pyRepr(x)
//   f"{x:.2f}"           -> pyFormatFixed(x, 2)
//   f"{x:.0%}"           -> pyFormatPercent(x, 0)
//   s.split() / split(sep, maxsplit) / rsplit -> pySplit / pyRsplit
//   s.strip() / lstrip() / rstrip()           -> pyStrip / pyLstrip / pyRstrip
//   len(s), s[i], s[a:b]                      -> cpLen, cpAt, cpSlice (code points)
//   s.zfill(n)                                -> pyZfill
//
// Numbers: TS cannot tell ``3`` from ``3.0``. Integral safe integers format as
// Python ints; wrap a value in ``PyFloat`` (number.ts) to force float format.

import { IndexError, ValueError } from './errors.ts';
import { PyFloat, exactParts } from './number.ts';
import { isDict } from './truthy.ts';

// ---------------------------------------------------------------- numbers

/** ``repr(float)`` — shortest round-trip digits in CPython's layout. */
export function floatRepr(x: number): string {
  if (Number.isNaN(x)) return 'nan';
  if (x === Infinity) return 'inf';
  if (x === -Infinity) return '-inf';
  if (x === 0) return Object.is(x, -0) ? '-0.0' : '0.0';
  const sign = x < 0 ? '-' : '';
  const [mantissa, exp] = Math.abs(x).toExponential().split('e');
  const digits = mantissa.replace('.', '');
  const decpt = Number(exp) + 1; // position of the decimal point in ``digits``
  if (decpt > -4 && decpt <= 16) {
    if (decpt <= 0) return `${sign}0.${'0'.repeat(-decpt)}${digits}`;
    if (decpt >= digits.length) return `${sign}${digits}${'0'.repeat(decpt - digits.length)}.0`;
    return `${sign}${digits.slice(0, decpt)}.${digits.slice(decpt)}`;
  }
  const exponent = decpt - 1;
  const rest = digits.slice(1);
  const expText = `${exponent < 0 ? '-' : '+'}${String(Math.abs(exponent)).padStart(2, '0')}`;
  return `${sign}${digits[0]}${rest ? `.${rest}` : ''}e${expText}`;
}

/** ``str(n)`` for a TS number: integral safe integers as int, otherwise float repr. */
export function numberStr(x: number): string {
  if (Number.isSafeInteger(x) && !Object.is(x, -0)) return String(x);
  return floatRepr(x);
}

/** Exact decimal string of ``|x|`` rounded half-even to ``digits`` places (no sign). */
function fixedDigits(x: number, digits: number): string {
  const { mantissa, exponent } = exactParts(x);
  let num = mantissa;
  let den = 1n;
  if (exponent >= 0) num <<= BigInt(exponent);
  else den <<= BigInt(-exponent);
  num *= 10n ** BigInt(digits);
  let q = num / den;
  const twice = (num % den) * 2n;
  if (twice > den || (twice === den && q % 2n === 1n)) q += 1n;
  let text = q.toString();
  if (digits > 0) {
    text = text.padStart(digits + 1, '0');
    text = `${text.slice(0, -digits)}.${text.slice(-digits)}`;
  }
  return text;
}

/** ``format(x, '.{digits}f')`` — correctly rounded (ties to even on the exact value). */
export function pyFormatFixed(x: number, digits: number): string {
  if (Number.isNaN(x)) return 'nan';
  if (!Number.isFinite(x)) return x > 0 ? 'inf' : '-inf';
  const negative = x < 0 || Object.is(x, -0);
  return `${negative ? '-' : ''}${fixedDigits(x, digits)}`;
}

/** ``format(x, '.{digits}%')`` — ``x * 100`` in fixed notation followed by ``%``. */
export function pyFormatPercent(x: number, digits: number): string {
  return `${pyFormatFixed(x * 100, digits)}%`;
}

// ---------------------------------------------------------------- str / repr

/** ``str(value)`` */
export function pyStr(value: unknown): string {
  if (typeof value === 'string') return value;
  return pyRepr(value);
}

// Characters Python's ``str.isprintable()`` rejects (escaped by ``repr``):
// categories Cc, Cf, Cs, Co, Cn, Zl, Zp and Zs other than the ASCII space.
// (JS uses a newer Unicode version than CPython 3.11 for ``Cn``.)
const NON_PRINTABLE = /[\p{Cc}\p{Cf}\p{Cs}\p{Co}\p{Cn}\p{Zl}\p{Zp}\p{Zs}]/u;

function strRepr(text: string): string {
  const quote = text.includes("'") && !text.includes('"') ? '"' : "'";
  let out = quote;
  for (const ch of text) {
    const code = ch.codePointAt(0)!;
    if (ch === quote || ch === '\\') out += `\\${ch}`;
    else if (ch === '\n') out += '\\n';
    else if (ch === '\r') out += '\\r';
    else if (ch === '\t') out += '\\t';
    else if (ch !== ' ' && NON_PRINTABLE.test(ch)) {
      if (code < 0x100) out += `\\x${code.toString(16).padStart(2, '0')}`;
      else if (code < 0x10000) out += `\\u${code.toString(16).padStart(4, '0')}`;
      else out += `\\U${code.toString(16).padStart(8, '0')}`;
    } else out += ch;
  }
  return out + quote;
}

/** ``repr(value)`` for the JSON-ish values the engine handles (lists print as lists). */
export function pyRepr(value: unknown): string {
  if (value === null || value === undefined) return 'None';
  if (value === true) return 'True';
  if (value === false) return 'False';
  if (typeof value === 'number') return numberStr(value);
  if (value instanceof PyFloat) return floatRepr(value.value);
  if (typeof value === 'bigint') return value.toString();
  if (typeof value === 'string') return strRepr(value);
  if (Array.isArray(value)) return `[${value.map(pyRepr).join(', ')}]`;
  if (value instanceof Set) return value.size ? `{${[...value].map(pyRepr).join(', ')}}` : 'set()';
  if (value instanceof Map) return `{${[...value.entries()].map(([k, v]) => `${pyRepr(k)}: ${pyRepr(v)}`).join(', ')}}`;
  if (isDict(value)) return `{${Object.entries(value).map(([k, v]) => `${strRepr(k)}: ${pyRepr(v)}`).join(', ')}}`;
  return String(value);
}

// ---------------------------------------------------------------- whitespace

/** Characters for which Python ``str.isspace()`` is True. */
const PY_WHITESPACE = new Set<number>([
  0x09, 0x0a, 0x0b, 0x0c, 0x0d, 0x1c, 0x1d, 0x1e, 0x1f, 0x20, 0x85, 0xa0, 0x1680,
  0x2000, 0x2001, 0x2002, 0x2003, 0x2004, 0x2005, 0x2006, 0x2007, 0x2008, 0x2009, 0x200a,
  0x2028, 0x2029, 0x202f, 0x205f, 0x3000,
]);

export function isPyWhitespace(ch: string): boolean {
  return PY_WHITESPACE.has(ch.codePointAt(0)!);
}

/** ``s.isspace()`` */
export function pyIsspace(text: string): boolean {
  if (!text) return false;
  for (const ch of text) if (!isPyWhitespace(ch)) return false;
  return true;
}

function stripSet(chars: string | null | undefined): (ch: string) => boolean {
  if (chars === null || chars === undefined) return isPyWhitespace;
  const set = new Set([...chars]);
  return (ch) => set.has(ch);
}

/** ``s.strip(chars=None)`` */
export function pyStrip(text: string, chars?: string | null): string {
  return pyRstrip(pyLstrip(text, chars), chars);
}

/** ``s.lstrip(chars=None)`` */
export function pyLstrip(text: string, chars?: string | null): string {
  const strip = stripSet(chars);
  const points = [...text];
  let start = 0;
  while (start < points.length && strip(points[start])) start += 1;
  return points.slice(start).join('');
}

/** ``s.rstrip(chars=None)`` */
export function pyRstrip(text: string, chars?: string | null): string {
  const strip = stripSet(chars);
  const points = [...text];
  let end = points.length;
  while (end > 0 && strip(points[end - 1])) end -= 1;
  return points.slice(0, end).join('');
}

/** ``s.split(sep=None, maxsplit=-1)`` */
export function pySplit(text: string, sep?: string | null, maxsplit = -1): string[] {
  if (sep === null || sep === undefined) {
    const result: string[] = [];
    const points = [...text];
    let i = 0;
    const n = points.length;
    let splits = 0;
    while (true) {
      while (i < n && isPyWhitespace(points[i])) i += 1;
      if (i >= n) break;
      if (maxsplit >= 0 && splits >= maxsplit) {
        // The remainder keeps its trailing whitespace (CPython behaviour).
        result.push(points.slice(i).join(''));
        break;
      }
      let j = i;
      while (j < n && !isPyWhitespace(points[j])) j += 1;
      result.push(points.slice(i, j).join(''));
      splits += 1;
      i = j;
    }
    return result;
  }
  if (sep === '') throw new ValueError('empty separator');
  if (maxsplit < 0) return text.split(sep);
  const result: string[] = [];
  let rest = text;
  while (result.length < maxsplit) {
    const index = rest.indexOf(sep);
    if (index < 0) break;
    result.push(rest.slice(0, index));
    rest = rest.slice(index + sep.length);
  }
  result.push(rest);
  return result;
}

/** ``s.rsplit(sep=None, maxsplit=-1)`` */
export function pyRsplit(text: string, sep?: string | null, maxsplit = -1): string[] {
  if (maxsplit < 0) return pySplit(text, sep);
  if (sep === null || sep === undefined) {
    const points = [...text];
    const result: string[] = [];
    let j = points.length;
    let splits = 0;
    while (true) {
      while (j > 0 && isPyWhitespace(points[j - 1])) j -= 1;
      if (j <= 0) break;
      if (splits >= maxsplit) {
        // The remainder keeps its leading whitespace (CPython behaviour).
        result.push(points.slice(0, j).join(''));
        break;
      }
      let i = j;
      while (i > 0 && !isPyWhitespace(points[i - 1])) i -= 1;
      result.push(points.slice(i, j).join(''));
      splits += 1;
      j = i;
    }
    return result.reverse();
  }
  if (sep === '') throw new ValueError('empty separator');
  const result: string[] = [];
  let rest = text;
  while (result.length < maxsplit) {
    const index = rest.lastIndexOf(sep);
    if (index < 0) break;
    result.push(rest.slice(index + sep.length));
    rest = rest.slice(0, index);
  }
  result.push(rest);
  return result.reverse();
}

/** ``s.lower()`` */
export function pyLower(text: string): string {
  return text.toLowerCase();
}

/** ``s.upper()`` */
export function pyUpper(text: string): string {
  return text.toUpperCase();
}

/** ``s.isupper()``: has a cased character and no lowercase ones. */
export function pyIsupper(text: string): boolean {
  return text !== text.toLowerCase() && text === text.toUpperCase();
}

/** ``s.islower()``: has a cased character and no uppercase ones. */
export function pyIslower(text: string): boolean {
  return text !== text.toUpperCase() && text === text.toLowerCase();
}

/** ``s.isdigit()`` (ASCII and Unicode decimal digits). */
export function pyIsdigit(text: string): boolean {
  return text.length > 0 && /^[\p{Nd}\p{No}]+$/u.test(text);
}

/** ``s.startswith(prefix | tuple)`` */
export function pyStartswith(text: string, prefix: string | readonly string[]): boolean {
  return typeof prefix === 'string' ? text.startsWith(prefix) : prefix.some((p) => text.startsWith(p));
}

/** ``s.endswith(suffix | tuple)`` */
export function pyEndswith(text: string, suffix: string | readonly string[]): boolean {
  return typeof suffix === 'string' ? text.endsWith(suffix) : suffix.some((s) => text.endsWith(s));
}

/** ``s.zfill(width)`` */
export function pyZfill(text: string, width: number): string {
  const length = cpLen(text);
  if (length >= width) return text;
  const fill = '0'.repeat(width - length);
  if (text.startsWith('+') || text.startsWith('-')) return text[0] + fill + text.slice(1);
  return fill + text;
}

// ---------------------------------------------------------------- code points

/** ``len(s)`` in code points. */
export function cpLen(text: string): number {
  let count = 0;
  for (const _ of text) count += 1;
  return count;
}

/** ``list(s)`` — code points. */
export function cpChars(text: string): string[] {
  return [...text];
}

/** ``s[i]`` with negative indices; raises ``IndexError`` when out of range. */
export function cpAt(text: string, index: number): string {
  const points = [...text];
  const i = index < 0 ? index + points.length : index;
  if (i < 0 || i >= points.length) throw new IndexError('string index out of range');
  return points[i];
}

/** Resolve Python slice bounds ``[start:stop:step]`` for a sequence of ``length``. */
export function sliceIndices(length: number, start?: number | null, stop?: number | null, step?: number | null): number[] {
  const s = step ?? 1;
  if (s === 0) throw new ValueError('slice step cannot be zero');
  const clamp = (value: number | null | undefined, fallback: number, lower: number, upper: number): number => {
    if (value === null || value === undefined) return fallback;
    let v = value < 0 ? value + length : value;
    if (v < lower) v = lower;
    if (v > upper) v = upper;
    return v;
  };
  const indices: number[] = [];
  if (s > 0) {
    const begin = clamp(start, 0, 0, length);
    const end = clamp(stop, length, 0, length);
    for (let i = begin; i < end; i += s) indices.push(i);
  } else {
    const begin = clamp(start, length - 1, -1, length - 1);
    const end = clamp(stop, -1, -1, length - 1);
    for (let i = begin; i > end; i += s) indices.push(i);
  }
  return indices;
}

/** ``s[start:stop:step]`` in code points. */
export function cpSlice(text: string, start?: number | null, stop?: number | null, step?: number | null): string {
  const points = [...text];
  return sliceIndices(points.length, start, stop, step).map((i) => points[i]).join('');
}

/** ``seq[start:stop:step]`` for arrays (always a copy). */
export function pySlice<T>(items: readonly T[], start?: number | null, stop?: number | null, step?: number | null): T[] {
  return sliceIndices(items.length, start, stop, step).map((i) => items[i]);
}

/** ``seq[i]`` with negative indices; raises ``IndexError`` when out of range. */
export function pyAt<T>(items: readonly T[], index: number): T {
  const i = index < 0 ? index + items.length : index;
  if (i < 0 || i >= items.length) throw new IndexError('list index out of range');
  return items[i];
}
