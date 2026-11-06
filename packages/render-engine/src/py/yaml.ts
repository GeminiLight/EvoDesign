// ``yaml.safe_load`` (PyYAML, YAML 1.1 core resolver) for the block-style
// config files under ``configs/`` (models.yaml, settings*.yaml). Added by WP13.
//
// Supported: block mappings and sequences by indentation, ``#`` comments,
// flow sequences/mappings of scalars (``[text, vision]``), single/double
// quoted scalars, and PyYAML's implicit scalar types (null ``~``/``null``/
// empty, YAML 1.1 booleans ``true/false/yes/no/on/off``, ints, floats).
// Anchors, tags, multi-line and block scalars raise ``YAMLError`` instead of
// being guessed.

export class YAMLError extends Error {
  override name = 'YAMLError';
}

interface Line {
  indent: number;
  text: string; // without indentation and trailing comment
  number: number;
}

const BOOL_TRUE = new Set(['yes', 'Yes', 'YES', 'true', 'True', 'TRUE', 'on', 'On', 'ON']);
const BOOL_FALSE = new Set(['no', 'No', 'NO', 'false', 'False', 'FALSE', 'off', 'Off', 'OFF']);
const NULLS = new Set(['', '~', 'null', 'Null', 'NULL']);
const INT_RE = /^[-+]?(?:0|[1-9][0-9_]*)$/;
const FLOAT_RE = /^[-+]?(?:[0-9][0-9_]*)?\.[0-9_]*(?:[eE][-+][0-9]+)?$|^[-+]?[0-9][0-9_]*(?:\.[0-9_]*)?[eE][-+][0-9]+$/;

function stripComment(text: string): string {
  let quote: string | null = null;
  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i];
    if (quote) {
      if (ch === quote) {
        if (quote === "'" && text[i + 1] === "'") i += 1;
        else quote = null;
      } else if (ch === '\\' && quote === '"') {
        i += 1;
      }
      continue;
    }
    if ((ch === '"' || ch === "'") && (i === 0 || /[\s:[{,-]/.test(text[i - 1]))) quote = ch;
    else if (ch === '#' && (i === 0 || /\s/.test(text[i - 1]))) return text.slice(0, i);
  }
  return text;
}

function scalar(raw: string, line: number): unknown {
  const text = raw.trim();
  if (text.startsWith('"')) {
    if (!text.endsWith('"') || text.length < 2) throw new YAMLError(`unterminated double-quoted scalar on line ${line}`);
    return JSON.parse(text);
  }
  if (text.startsWith("'")) {
    if (!text.endsWith("'") || text.length < 2) throw new YAMLError(`unterminated single-quoted scalar on line ${line}`);
    return text.slice(1, -1).replace(/''/g, "'");
  }
  if (/^[&*!|>]/.test(text)) throw new YAMLError(`unsupported YAML construct on line ${line}: ${text}`);
  if (text.startsWith('[') || text.startsWith('{')) return flow(text, line);
  if (NULLS.has(text)) return null;
  if (BOOL_TRUE.has(text)) return true;
  if (BOOL_FALSE.has(text)) return false;
  if (INT_RE.test(text)) return Number(text.replace(/_/g, ''));
  if (FLOAT_RE.test(text) && /[0-9]/.test(text)) return Number(text.replace(/_/g, ''));
  if (/^[-+]?\.(?:inf|Inf|INF)$/.test(text)) return text.startsWith('-') ? -Infinity : Infinity;
  if (/^\.(?:nan|NaN|NAN)$/.test(text)) return NaN;
  return text;
}

function splitFlow(body: string, line: number): string[] {
  const items: string[] = [];
  let depth = 0;
  let quote: string | null = null;
  let current = '';
  for (const ch of body) {
    if (quote) {
      current += ch;
      if (ch === quote) quote = null;
      continue;
    }
    if (ch === '"' || ch === "'") quote = ch;
    else if (ch === '[' || ch === '{') depth += 1;
    else if (ch === ']' || ch === '}') depth -= 1;
    if (ch === ',' && depth === 0) {
      items.push(current);
      current = '';
      continue;
    }
    current += ch;
  }
  if (quote || depth) throw new YAMLError(`malformed flow collection on line ${line}`);
  if (current.trim()) items.push(current);
  return items;
}

function flow(text: string, line: number): unknown {
  if (text.startsWith('[')) {
    if (!text.endsWith(']')) throw new YAMLError(`malformed flow sequence on line ${line}`);
    return splitFlow(text.slice(1, -1), line).map((item) => scalar(item, line));
  }
  if (!text.endsWith('}')) throw new YAMLError(`malformed flow mapping on line ${line}`);
  const out: Record<string, unknown> = {};
  for (const item of splitFlow(text.slice(1, -1), line)) {
    const colon = item.indexOf(':');
    if (colon < 0) throw new YAMLError(`malformed flow mapping on line ${line}`);
    out[String(scalar(item.slice(0, colon), line))] = scalar(item.slice(colon + 1), line);
  }
  return out;
}

/** Index of the ``key: value`` separator (a colon followed by space/end, outside quotes). */
function mappingColon(text: string): number {
  let quote: string | null = null;
  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i];
    if (quote) {
      if (ch === quote) quote = null;
      continue;
    }
    if ((ch === '"' || ch === "'") && i === 0) quote = ch;
    else if (ch === ':' && (i + 1 === text.length || text[i + 1] === ' ' || text[i + 1] === '\t')) return i;
  }
  return -1;
}

/** ``yaml.safe_load(text)`` for the supported subset. */
export function yamlSafeLoad(source: string): unknown {
  const lines: Line[] = [];
  source.replace(/^﻿/, '').split(/\r?\n/).forEach((rawLine, index) => {
    if (rawLine.trim() === '---' || rawLine.trim() === '...') return;
    if (/^\s*\t/.test(rawLine)) throw new YAMLError(`tab indentation on line ${index + 1}`);
    const text = stripComment(rawLine).replace(/\s+$/, '');
    if (!text.trim()) return;
    const indent = text.length - text.trimStart().length;
    lines.push({ indent, text: text.trimStart(), number: index + 1 });
  });
  if (!lines.length) return null;
  let pos = 0;

  const parseBlock = (indent: number): unknown => {
    const first = lines[pos];
    if (first.text === '-' || first.text.startsWith('- ')) return parseSequence(indent);
    if (mappingColon(first.text) >= 0) return parseMapping(indent);
    pos += 1;
    return scalar(first.text, first.number);
  };

  const parseValue = (rest: string, parentIndent: number, number: number): unknown => {
    if (rest.trim()) return scalar(rest, number);
    const next = lines[pos];
    if (!next || next.indent < parentIndent || (next.indent === parentIndent && !(next.text === '-' || next.text.startsWith('- ')))) return null;
    if (next.indent === parentIndent) return parseSequence(parentIndent); // "key:\n- item" at the same indent
    return parseBlock(next.indent);
  };

  const parseMapping = (indent: number): Record<string, unknown> => {
    const out: Record<string, unknown> = {};
    while (pos < lines.length && lines[pos].indent === indent) {
      const line = lines[pos];
      if (line.text === '-' || line.text.startsWith('- ')) break;
      const colon = mappingColon(line.text);
      if (colon < 0) throw new YAMLError(`expected "key: value" on line ${line.number}`);
      const key = String(scalar(line.text.slice(0, colon), line.number) ?? 'None');
      pos += 1;
      Object.defineProperty(out, key, { value: parseValue(line.text.slice(colon + 1), indent, line.number), writable: true, enumerable: true, configurable: true });
    }
    if (pos < lines.length && lines[pos].indent > indent) throw new YAMLError(`bad indentation on line ${lines[pos].number}`);
    return out;
  };

  const parseSequence = (indent: number): unknown[] => {
    const out: unknown[] = [];
    while (pos < lines.length && lines[pos].indent === indent && (lines[pos].text === '-' || lines[pos].text.startsWith('- '))) {
      const line = lines[pos];
      const rest = line.text.slice(1);
      if (rest.trim() && mappingColon(rest.trim()) >= 0) {
        // "- key: value" starts a mapping indented at the item's content column.
        const contentIndent = indent + 1 + (rest.length - rest.trimStart().length);
        lines[pos] = { indent: contentIndent, text: rest.trimStart(), number: line.number };
        out.push(parseMapping(contentIndent));
        continue;
      }
      pos += 1;
      out.push(parseValue(rest, indent + 1, line.number));
    }
    return out;
  };

  const value = parseBlock(lines[0].indent);
  if (pos < lines.length) throw new YAMLError(`unexpected content on line ${lines[pos].number}`);
  return value;
}
