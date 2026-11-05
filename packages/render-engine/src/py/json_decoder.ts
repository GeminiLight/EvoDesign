// CPython 3.11 ``json`` decoder (the C scanner in Modules/_json.c), exact to
// the error message and position. Added by WP13 (phase 2): the LLM JSON-repair
// loop feeds ``JSONDecodeError.msg/lineno/colno`` back into the prompt, so the
// text must be byte-identical to Python's (PHASE2_PLAN.md §2 rule 4).
//
// Positions are Python string indices (code points), not UTF-16 offsets.
// ``pyJsonLoads`` in json.ts stays as it is (phase-1 callers rely on it).
import { ValueError } from './errors.ts';

/** ``json.JSONDecodeError(msg, doc, pos)`` with CPython's attributes and ``str()``. */
export class PyJSONDecodeError extends ValueError {
  readonly msg: string;
  readonly doc: string;
  readonly pos: number;
  readonly lineno: number;
  readonly colno: number;

  constructor(msg: string, doc: string, pos: number) {
    const chars = Array.isArray(doc) ? (doc as string[]) : [...doc];
    let lineno = 1;
    let lastNewline = -1;
    for (let i = 0; i < pos && i < chars.length; i += 1) {
      if (chars[i] === '\n') {
        lineno += 1;
        lastNewline = i;
      }
    }
    const colno = pos - lastNewline;
    super(`${msg}: line ${lineno} column ${colno} (char ${pos})`);
    this.name = 'JSONDecodeError';
    this.msg = msg;
    this.doc = Array.isArray(doc) ? (doc as string[]).join('') : doc;
    this.pos = pos;
    this.lineno = lineno;
    this.colno = colno;
  }
}

/**
 * Integral Python floats in decoded JSON (``80.0``). A JS number cannot carry
 * the int/float distinction, but ``json.dumps`` of that value prints ``80.0``
 * in Python. The decoder records, per decoded object/array, the keys (array
 * indices as strings) whose literal was an integral float. Nothing in the
 * decoded value changes; consumers that re-serialize model output (e.g. the
 * layout stage's conversation history, WP17) consult this map. Added by WP17,
 * see migration/notes/ISSUES.md.
 */
export const PY_FLOAT_MARKS: WeakMap<object, Set<string>> = new WeakMap();

function markIntegralFloat(container: object, key: string, value: unknown, s: string[], start: number, end: number): void {
  let keys = PY_FLOAT_MARKS.get(container);
  const integralFloat = typeof value === 'number' && Number.isInteger(value)
    && s.slice(start, end).some((ch) => ch === '.' || ch === 'e' || ch === 'E');
  if (!integralFloat) {
    keys?.delete(key); // a duplicate key replaced an earlier float
    return;
  }
  if (!keys) {
    keys = new Set();
    PY_FLOAT_MARKS.set(container, keys);
  }
  keys.add(key);
}

/** ``StopIteration(idx)`` raised by the scanner; turned into "Expecting value". */
class ScanStop {
  constructor(readonly value: number) {}
}

const WS = new Set([' ', '\t', '\n', '\r']);
const isDigit = (ch: string | undefined): boolean => ch !== undefined && ch >= '0' && ch <= '9';

class Scanner {
  constructor(private readonly s: string[], private readonly doc: string[], private readonly strict: boolean) {}

  private fail(msg: string, pos: number): never {
    throw new PyJSONDecodeError(msg, this.doc as unknown as string, pos);
  }

  scanOnce(idx: number): [unknown, number] {
    const s = this.s;
    const length = s.length;
    if (idx >= length) throw new ScanStop(idx);
    switch (s[idx]) {
      case '"':
        return this.scanString(idx + 1);
      case '{':
        return this.parseObject(idx + 1);
      case '[':
        return this.parseArray(idx + 1);
      case 'n':
        if (idx + 3 < length && s[idx + 1] === 'u' && s[idx + 2] === 'l' && s[idx + 3] === 'l') return [null, idx + 4];
        break;
      case 't':
        if (idx + 3 < length && s[idx + 1] === 'r' && s[idx + 2] === 'u' && s[idx + 3] === 'e') return [true, idx + 4];
        break;
      case 'f':
        if (idx + 4 < length && s[idx + 1] === 'a' && s[idx + 2] === 'l' && s[idx + 3] === 's' && s[idx + 4] === 'e') return [false, idx + 5];
        break;
      case 'N':
        if (idx + 2 < length && s[idx + 1] === 'a' && s[idx + 2] === 'N') return [Number.NaN, idx + 3];
        break;
      case 'I':
        if (idx + 7 < length && s.slice(idx, idx + 8).join('') === 'Infinity') return [Number.POSITIVE_INFINITY, idx + 8];
        break;
      case '-':
        if (idx + 8 < length && s.slice(idx, idx + 9).join('') === '-Infinity') return [Number.NEGATIVE_INFINITY, idx + 9];
        break;
      default:
        break;
    }
    return this.matchNumber(idx);
  }

  private matchNumber(start: number): [unknown, number] {
    const s = this.s;
    const endIdx = s.length - 1;
    let idx = start;
    if (s[idx] === '-') {
      idx += 1;
      if (idx > endIdx) throw new ScanStop(start);
    }
    if (s[idx] >= '1' && s[idx] <= '9') {
      idx += 1;
      while (idx <= endIdx && isDigit(s[idx])) idx += 1;
    } else if (s[idx] === '0') {
      idx += 1;
    } else {
      throw new ScanStop(start);
    }
    let isFloat = false;
    if (idx < endIdx && s[idx] === '.' && isDigit(s[idx + 1])) {
      isFloat = true;
      idx += 2;
      while (idx <= endIdx && isDigit(s[idx])) idx += 1;
    }
    if (idx < endIdx && (s[idx] === 'e' || s[idx] === 'E')) {
      const eStart = idx;
      idx += 1;
      if (idx < endIdx && (s[idx] === '-' || s[idx] === '+')) idx += 1;
      while (idx <= endIdx && isDigit(s[idx])) idx += 1;
      if (isDigit(s[idx - 1])) isFloat = true;
      else idx = eStart;
    }
    const text = s.slice(start, idx).join('');
    // Python ints have no negative zero: ``json.loads('-0') == 0``.
    return [isFloat ? Number(text) : Number(text) + 0, idx];
  }

  private scanString(end: number): [string, number] {
    const s = this.s;
    const len = s.length;
    const begin = end - 1;
    let out = '';
    for (;;) {
      let next = end;
      let c = '';
      for (; next < len; next += 1) {
        const d = s[next];
        if (d === '"' || d === '\\') {
          c = d;
          break;
        }
        if (this.strict && d.codePointAt(0)! <= 0x1f) this.fail('Invalid control character at', next);
      }
      if (next >= len) this.fail('Unterminated string starting at', begin);
      out += s.slice(end, next).join('');
      next += 1;
      if (c === '"') {
        end = next;
        break;
      }
      if (next === len) this.fail('Unterminated string starting at', begin);
      const esc = s[next];
      if (esc !== 'u') {
        end = next + 1;
        const mapped: Record<string, string> = { '"': '"', '\\': '\\', '/': '/', b: '\b', f: '\f', n: '\n', r: '\r', t: '\t' };
        if (!(esc in mapped)) this.fail('Invalid \\escape', end - 2);
        out += mapped[esc];
      } else {
        next += 1;
        end = next + 4;
        if (end >= len) this.fail('Invalid \\uXXXX escape', next - 1);
        let code = 0;
        for (; next < end; next += 1) {
          const digit = parseInt(s[next], 16);
          if (!/^[0-9a-fA-F]$/.test(s[next])) this.fail('Invalid \\uXXXX escape', end - 5);
          code = (code << 4) | digit;
        }
        if (code >= 0xd800 && code <= 0xdbff && end + 6 < len && s[next++] === '\\' && s[next++] === 'u') {
          let code2 = 0;
          end += 6;
          for (; next < end; next += 1) {
            const digit = parseInt(s[next], 16);
            if (!/^[0-9a-fA-F]$/.test(s[next])) this.fail('Invalid \\uXXXX escape', end - 5);
            code2 = (code2 << 4) | digit;
          }
          if (code2 >= 0xdc00 && code2 <= 0xdfff) {
            code = 0x10000 + (((code - 0xd800) << 10) | (code2 - 0xdc00));
          } else {
            end -= 6;
          }
        }
        out += String.fromCodePoint(code);
      }
    }
    return [out, end];
  }

  private parseObject(start: number): [Record<string, unknown>, number] {
    const s = this.s;
    const endIdx = s.length - 1;
    const obj: Record<string, unknown> = {};
    let idx = start;
    while (idx <= endIdx && WS.has(s[idx])) idx += 1;
    if (idx > endIdx || s[idx] !== '}') {
      for (;;) {
        if (idx > endIdx || s[idx] !== '"') this.fail('Expecting property name enclosed in double quotes', idx);
        const [key, afterKey] = this.scanString(idx + 1);
        idx = afterKey;
        while (idx <= endIdx && WS.has(s[idx])) idx += 1;
        if (idx > endIdx || s[idx] !== ':') this.fail("Expecting ':' delimiter", idx);
        idx += 1;
        while (idx <= endIdx && WS.has(s[idx])) idx += 1;
        const [value, afterValue] = this.scanOnce(idx);
        // Plain assignment would trip the ``__proto__`` setter.
        Object.defineProperty(obj, key, { value, writable: true, enumerable: true, configurable: true });
        markIntegralFloat(obj, key, value, s, idx, afterValue);
        idx = afterValue;
        while (idx <= endIdx && WS.has(s[idx])) idx += 1;
        if (idx <= endIdx && s[idx] === '}') break;
        if (idx > endIdx || s[idx] !== ',') this.fail("Expecting ',' delimiter", idx);
        idx += 1;
        while (idx <= endIdx && WS.has(s[idx])) idx += 1;
      }
    }
    return [obj, idx + 1];
  }

  private parseArray(start: number): [unknown[], number] {
    const s = this.s;
    const endIdx = s.length - 1;
    const arr: unknown[] = [];
    let idx = start;
    while (idx <= endIdx && WS.has(s[idx])) idx += 1;
    if (idx > endIdx || s[idx] !== ']') {
      for (;;) {
        const [value, afterValue] = this.scanOnce(idx);
        arr.push(value);
        markIntegralFloat(arr, String(arr.length - 1), value, s, idx, afterValue);
        idx = afterValue;
        while (idx <= endIdx && WS.has(s[idx])) idx += 1;
        if (idx <= endIdx && s[idx] === ']') break;
        if (idx > endIdx || s[idx] !== ',') this.fail("Expecting ',' delimiter", idx);
        idx += 1;
        while (idx <= endIdx && WS.has(s[idx])) idx += 1;
      }
    }
    if (idx > endIdx || s[idx] !== ']') this.fail('Expecting value', endIdx);
    return [arr, idx + 1];
  }
}

function skipWs(chars: string[], idx: number): number {
  while (idx < chars.length && WS.has(chars[idx])) idx += 1;
  return idx;
}

/**
 * ``json.JSONDecoder(strict=strict).raw_decode(s, idx)`` → ``[value, end]``
 * (Python indices). No leading whitespace is skipped, like CPython.
 */
export function pyJsonRawDecode(text: string, idx = 0, strict = true): [unknown, number] {
  const chars = [...text];
  return rawDecodeChars(chars, idx, strict);
}

function rawDecodeChars(chars: string[], idx: number, strict: boolean): [unknown, number] {
  const scanner = new Scanner(chars, chars, strict);
  try {
    return scanner.scanOnce(idx);
  } catch (error) {
    if (error instanceof ScanStop) throw new PyJSONDecodeError('Expecting value', chars as unknown as string, error.value);
    throw error;
  }
}

/** ``json.loads(text, strict=strict)`` for a ``str`` argument. */
export function pyJsonLoadsExact(text: string, strict = true): unknown {
  const chars = [...text];
  if (chars[0] === '﻿') throw new PyJSONDecodeError('Unexpected UTF-8 BOM (decode using utf-8-sig)', text, 0);
  const [value, afterValue] = rawDecodeChars(chars, skipWs(chars, 0), strict);
  const end = skipWs(chars, afterValue);
  if (end !== chars.length) throw new PyJSONDecodeError('Extra data', text, end);
  return value;
}
