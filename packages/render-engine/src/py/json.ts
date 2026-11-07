// Python ``json.dumps`` / ``json.loads`` (MIGRATION_PLAN.md §4).
//
//   json.dumps(v, sort_keys=True, ensure_ascii=False, default=str)
//     -> pyJsonDumps(v, { sortKeys: true, ensureAscii: false, default: pyStr })
//   json.dumps(v, ensure_ascii=False, separators=(",", ":"))
//     -> pyJsonDumps(v, { ensureAscii: false, separators: [',', ':'] })
//   json.loads(text) -> pyJsonLoads(text)
//
// Output is byte-for-byte what CPython 3.11 produces, because element IDs are
// sha256 digests of these strings:
//   * default separators are ", " and ": " (", " -> "," when indent is set);
//   * ensure_ascii defaults to True (non-ASCII -> \uXXXX, lowercase hex);
//   * floats use repr ("1.5", "1e+16", "NaN", "Infinity", "-0.0");
//   * sort_keys sorts by code point.
//
// Number caveat: TS cannot tell ``1`` from ``1.0``. Integral safe integers
// are written as ints; wrap a value in ``PyFloat`` to force ``1.0``. Values
// that the Python side hashes are ints/strings in practice (see notes/WP01.md).

import { JSONDecodeError, PyTypeError, ValueError } from './errors.ts';
import { PyFloat } from './number.ts';
import { cpCompare } from './sort.ts';
import { floatRepr, pyStr } from './str.ts';
import { isDict } from './truthy.ts';

export interface JsonDumpsOptions {
  /** ``sort_keys`` (default false). */
  sortKeys?: boolean;
  /** ``ensure_ascii`` (default true, like Python). */
  ensureAscii?: boolean;
  /** ``separators`` as ``[item, key]``. */
  separators?: readonly [string, string] | null;
  /** ``indent`` (number of spaces or an indent string). */
  indent?: number | string | null;
  /** ``default`` — called for values JSON cannot encode; ``pyStr`` for ``default=str``. */
  default?: ((value: unknown) => unknown) | null;
  /** ``allow_nan`` (default true). */
  allowNan?: boolean;
  /** ``skipkeys`` (default false). */
  skipKeys?: boolean;
}

function escapeString(text: string, ensureAscii: boolean): string {
  let out = '"';
  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i];
    const code = text.charCodeAt(i);
    switch (ch) {
      case '"':
        out += '\\"';
        continue;
      case '\\':
        out += '\\\\';
        continue;
      case '\n':
        out += '\\n';
        continue;
      case '\r':
        out += '\\r';
        continue;
      case '\t':
        out += '\\t';
        continue;
      case '\b':
        out += '\\b';
        continue;
      case '\f':
        out += '\\f';
        continue;
      default:
        break;
    }
    if (code < 0x20 || (ensureAscii && code > 0x7e)) {
      // ensure_ascii writes UTF-16 code units, i.e. surrogate pairs for astral chars.
      out += `\\u${code.toString(16).padStart(4, '0')}`;
    } else {
      out += ch;
    }
  }
  return `${out}"`;
}

function floatJson(value: number, allowNan: boolean): string {
  if (!Number.isFinite(value)) {
    if (!allowNan) throw new ValueError(`Out of range float values are not JSON compliant: ${floatRepr(value)}`);
    if (Number.isNaN(value)) return 'NaN';
    return value > 0 ? 'Infinity' : '-Infinity';
  }
  return floatRepr(value);
}

function numberJson(value: number, allowNan: boolean): string {
  if (Number.isSafeInteger(value) && !Object.is(value, -0)) return String(value);
  return floatJson(value, allowNan);
}

function keyText(key: unknown, allowNan: boolean): string | undefined {
  if (typeof key === 'string') return key;
  if (key instanceof PyFloat) return floatJson(key.value, allowNan);
  if (typeof key === 'number') return numberJson(key, allowNan);
  if (key === true) return 'true';
  if (key === false) return 'false';
  if (key === null || key === undefined) return 'null';
  if (typeof key === 'bigint') return key.toString();
  return undefined;
}

/** Python ordering of dict keys for ``sort_keys`` (same-type keys only). */
function compareKeys(a: unknown, b: unknown): number {
  if (typeof a === 'string' && typeof b === 'string') return cpCompare(a, b);
  const x = typeof a === 'boolean' ? Number(a) : a instanceof PyFloat ? a.value : a;
  const y = typeof b === 'boolean' ? Number(b) : b instanceof PyFloat ? b.value : b;
  if (typeof x === 'number' && typeof y === 'number') return x < y ? -1 : x > y ? 1 : 0;
  throw new PyTypeError("'<' not supported between instances of dict keys");
}

/** ``json.dumps(value, **options)`` */
export function pyJsonDumps(value: unknown, options: JsonDumpsOptions = {}): string {
  const ensureAscii = options.ensureAscii ?? true;
  const allowNan = options.allowNan ?? true;
  const sortKeys = options.sortKeys ?? false;
  const indent = options.indent === null || options.indent === undefined
    ? null
    : typeof options.indent === 'number' ? ' '.repeat(options.indent) : options.indent;
  const [itemSep, keySep] = options.separators ?? (indent !== null ? [',', ': '] : [', ', ': ']);
  const fallback = options.default ?? null;
  const markers = new Set<object>();

  const encode = (item: unknown, level: number): string => {
    if (item === null) return 'null';
    if (item === true) return 'true';
    if (item === false) return 'false';
    if (typeof item === 'string') return escapeString(item, ensureAscii);
    if (typeof item === 'number') return numberJson(item, allowNan);
    if (item instanceof PyFloat) return floatJson(item.value, allowNan);
    if (typeof item === 'bigint') return item.toString();
    const isArray = Array.isArray(item);
    const isMap = item instanceof Map;
    if (isArray || isMap || isDict(item)) {
      const obj = item as object;
      if (markers.has(obj)) throw new ValueError('Circular reference detected');
      markers.add(obj);
      const inner = indent !== null ? `\n${indent.repeat(level + 1)}` : '';
      const outer = indent !== null ? `\n${indent.repeat(level)}` : '';
      let text: string;
      if (isArray) {
        const parts = (item as unknown[]).map((child) => encode(child, level + 1));
        text = parts.length ? `[${inner}${parts.join(itemSep + inner)}${outer}]` : '[]';
      } else {
        let entries: [unknown, unknown][] = isMap ? [...(item as Map<unknown, unknown>).entries()] : Object.entries(item as object);
        if (sortKeys) entries = [...entries].sort((left, right) => compareKeys(left[0], right[0]));
        const parts: string[] = [];
        for (const [key, child] of entries) {
          const text = keyText(key, allowNan);
          if (text === undefined) {
            if (options.skipKeys) continue;
            throw new PyTypeError(`keys must be str, int, float, bool or None, not ${typeof key}`);
          }
          parts.push(`${escapeString(text, ensureAscii)}${keySep}${encode(child, level + 1)}`);
        }
        text = parts.length ? `{${inner}${parts.join(itemSep + inner)}${outer}}` : '{}';
      }
      markers.delete(obj);
      return text;
    }
    if (fallback) {
      if (item !== null && typeof item === 'object') {
        if (markers.has(item)) throw new ValueError('Circular reference detected');
        markers.add(item);
        const text = encode(fallback(item), level);
        markers.delete(item);
        return text;
      }
      return encode(fallback(item), level);
    }
    throw new PyTypeError(`Object of type ${item === undefined ? 'undefined' : (item as object).constructor?.name ?? typeof item} is not JSON serializable`);
  };

  return encode(value, 0);
}

/** ``json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)`` — the engine's stable payload. */
export function pyStableJsonDumps(value: unknown): string {
  return pyJsonDumps(value, { sortKeys: true, ensureAscii: false, default: pyStr });
}

// ---------------------------------------------------------------- loads

const WHITESPACE = new Set([' ', '\t', '\n', '\r']);

/**
 * ``json.loads(text)`` — CPython's decoder: accepts ``NaN``/``Infinity``/
 * ``-Infinity``, rejects control characters inside strings, raises
 * ``JSONDecodeError`` (a ``ValueError``) on malformed input or extra data.
 * Objects become plain objects (duplicate keys: last value wins).
 */
export interface JsonLoadsOptions {
  /** ``parse_float`` — called with the literal text of every number with a fraction or exponent. */
  parseFloat?: (text: string) => unknown;
  /** ``parse_int`` — called with the literal text of every integer. */
  parseInt?: (text: string) => unknown;
  /** ``parse_constant`` — called with ``'NaN'``, ``'Infinity'`` or ``'-Infinity'``. */
  parseConstant?: (text: string) => unknown;
}

export function pyJsonLoads(text: string, options: JsonLoadsOptions = {}): unknown {
  if (typeof text !== 'string') {
    throw new PyTypeError(`the JSON object must be str, bytes or bytearray, not ${text === null ? 'NoneType' : typeof text}`);
  }
  let pos = 0;
  const fail = (message: string): never => {
    throw new JSONDecodeError(`${message}: char ${pos}`);
  };
  const skip = (): void => {
    while (pos < text.length && WHITESPACE.has(text[pos])) pos += 1;
  };
  const parseString = (): string => {
    pos += 1; // opening quote
    let out = '';
    while (true) {
      if (pos >= text.length) fail('Unterminated string starting at');
      const ch = text[pos];
      if (ch === '"') {
        pos += 1;
        return out;
      }
      if (ch === '\\') {
        const esc = text[pos + 1];
        pos += 2;
        switch (esc) {
          case '"': out += '"'; break;
          case '\\': out += '\\'; break;
          case '/': out += '/'; break;
          case 'b': out += '\b'; break;
          case 'f': out += '\f'; break;
          case 'n': out += '\n'; break;
          case 'r': out += '\r'; break;
          case 't': out += '\t'; break;
          case 'u': {
            const hex = text.slice(pos, pos + 4);
            if (!/^[0-9a-fA-F]{4}$/.test(hex)) fail('Invalid \\uXXXX escape');
            out += String.fromCharCode(parseInt(hex, 16));
            pos += 4;
            break;
          }
          default:
            pos -= 2;
            fail('Invalid \\escape');
        }
        continue;
      }
      if (ch.charCodeAt(0) < 0x20) fail('Invalid control character at');
      out += ch;
      pos += 1;
    }
  };
  const parseValue = (): unknown => {
    skip();
    const ch = text[pos];
    if (ch === '"') return parseString();
    if (ch === '{') {
      pos += 1;
      const obj: Record<string, unknown> = {};
      skip();
      if (text[pos] === '}') {
        pos += 1;
        return obj;
      }
      while (true) {
        skip();
        if (text[pos] !== '"') fail('Expecting property name enclosed in double quotes');
        const key = parseString();
        skip();
        if (text[pos] !== ':') fail("Expecting ':' delimiter");
        pos += 1;
        const value = parseValue();
        Object.defineProperty(obj, key, { value, writable: true, enumerable: true, configurable: true });
        skip();
        if (text[pos] === ',') {
          pos += 1;
          continue;
        }
        if (text[pos] === '}') {
          pos += 1;
          return obj;
        }
        fail("Expecting ',' delimiter");
      }
    }
    if (ch === '[') {
      pos += 1;
      const arr: unknown[] = [];
      skip();
      if (text[pos] === ']') {
        pos += 1;
        return arr;
      }
      while (true) {
        arr.push(parseValue());
        skip();
        if (text[pos] === ',') {
          pos += 1;
          continue;
        }
        if (text[pos] === ']') {
          pos += 1;
          return arr;
        }
        fail("Expecting ',' delimiter");
      }
    }
    const rest = text.slice(pos);
    for (const [literal, value] of [['null', null], ['true', true], ['false', false]] as const) {
      if (rest.startsWith(literal)) {
        pos += literal.length;
        return value;
      }
    }
    for (const [literal, value] of [['NaN', NaN], ['Infinity', Infinity], ['-Infinity', -Infinity]] as const) {
      if (rest.startsWith(literal)) {
        pos += literal.length;
        return options.parseConstant ? options.parseConstant(literal) : value;
      }
    }
    const match = /^-?(?:0|[1-9]\d*)(\.\d+)?([eE][-+]?\d+)?/.exec(rest);
    if (match) {
      pos += match[0].length;
      const isFloat = match[1] !== undefined || match[2] !== undefined;
      if (isFloat && options.parseFloat) return options.parseFloat(match[0]);
      if (!isFloat && options.parseInt) return options.parseInt(match[0]);
      // Python ints have no negative zero: ``json.loads('-0') == 0``.
      return isFloat ? Number(match[0]) : Number(match[0]) + 0;
    }
    return fail('Expecting value');
  };

  const value = parseValue();
  skip();
  if (pos !== text.length) fail('Extra data');
  return value;
}
