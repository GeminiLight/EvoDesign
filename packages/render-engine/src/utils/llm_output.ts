// Ported from evodesign/utils/llm_output.py — keep in sync.
//
// LLM Output Processing Utilities
//
// Shared utilities for processing LLM outputs across the project.
//
// Index convention: functions taking/returning string positions
// (``_extract_balanced_json_substring``, ``_loads_json_span``) use Python
// indices (code points). JSON parsing goes through ``py/json_decoder.ts`` so
// ``JSONDecodeError`` messages and positions equal CPython 3.11's.

import { PyJSONDecodeError, pyJsonLoadsExact, pyJsonRawDecode } from '../py/json_decoder.ts';
import { pyStr } from '../py/str.ts';
import { pyLstrip, pyStrip } from '../py/str.ts';
import { isDict, truthy } from '../py/truthy.ts';

export { PyJSONDecodeError as JSONDecodeError };

// ``\s`` of Python's ``re`` for str patterns (== str.isspace()).
const S = '[\\t\\n\\v\\f\\r\\x1c-\\x1f \\x85\\u00a0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000]';

// The whole (stripped) response is one ```json / ``` fenced block.
export const _SOLE_FENCE = new RegExp('^(?:```(?:json|JSON)?[ \\t]*\\n([\\s\\S]*?)\\n?[ \\t]*```)$');

/**
 * Split *text* into ``(is_string, chunk)`` runs.
 *
 * String runs include their quotes; an unterminated string runs to the end.
 */
export function _split_json_strings(text: string): [boolean, string][] {
  const parts: [boolean, string][] = [];
  let idx = 0;
  const length = text.length;
  while (idx < length) {
    const quote = text.indexOf('"', idx);
    if (quote < 0) {
      parts.push([false, text.slice(idx)]);
      break;
    }
    if (quote > idx) {
      parts.push([false, text.slice(idx, quote)]);
    }
    let pos = quote + 1;
    while (pos < length) {
      const char = text[pos];
      if (char === '\\') {
        // A surrogate pair counts as one Python character; skipping only its
        // high half lands on the low half, which can never be '"' or '\\', so
        // the run boundaries are the same as Python's.
        pos += 2;
        continue;
      }
      if (char === '"') {
        break;
      }
      pos += 1;
    }
    const end = Math.min(pos + 1, length);
    parts.push([true, text.slice(quote, end)]);
    idx = end;
  }
  return parts;
}

// A value can end with one of these characters right before a missing comma.
export const _VALUE_END_CHARS = new Set('}]0123456789\'');

const DUPLICATE_COMMA = new RegExp(`,(${S}*),`, 'g');
const TRAILING_COMMA = new RegExp(`,(${S}*)(?=[}\\]])`, 'g');

/**
 * Attempt to fix common JSON formatting issues.
 *
 * Repairs (trailing commas, duplicate commas, a missing comma before the
 * next ``"key":``) are applied only to structural text: string literals are
 * copied verbatim, so a label such as ``"a, }"`` is never rewritten.
 */
export function fix_json_string(json_str: string): string {
  const parts = _split_json_strings(json_str);

  // Structural cleanup inside non-string runs.
  const cleaned: [boolean, string][] = [];
  for (const [is_string, original] of parts) {
    let chunk = original;
    if (!is_string) {
      let previous: string | null = null;
      while (previous !== chunk) {
        previous = chunk;
        chunk = chunk.replace(DUPLICATE_COMMA, ',$1');
      }
      chunk = chunk.replace(TRAILING_COMMA, '$1');
    }
    cleaned.push([is_string, chunk]);
  }

  // Missing comma before a key: <value> <ws> "key" <ws> :
  const out: string[] = [];
  cleaned.forEach(([is_string, chunk], index) => {
    if (is_string && index > 0) {
      const following = index + 1 < cleaned.length ? cleaned[index + 1][1] : '';
      let is_key = index + 1 < cleaned.length ? !cleaned[index + 1][0] : false;
      is_key = is_key && pyLstrip(following).startsWith(':');
      if (is_key) {
        const [gap_is_string, gap] = cleaned[index - 1];
        if (gap_is_string) {
          // "value""key": with nothing in between.
          out.push(',');
        } else if (!truthy(pyStrip(gap)) && index >= 2 && cleaned[index - 2][0]) {
          // "value" <ws> "key":
          out[out.length - 1] = ',' + gap;
        } else {
          const stripped = pyRstripWs(gap);
          if (stripped && _VALUE_END_CHARS.has(stripped[stripped.length - 1]) && gap !== stripped) {
            out[out.length - 1] = stripped + ',' + gap.slice(stripped.length);
          }
        }
      }
    }
    out.push(chunk);
  });
  return out.join('');
}

function pyRstripWs(text: string): string {
  // ``str.rstrip()`` keeping UTF-16 offsets aligned with ``gap`` (only
  // whitespace, all BMP, is removed from the end).
  let end = text.length;
  while (end > 0 && WS_RE.test(text[end - 1])) end -= 1;
  return text.slice(0, end);
}

const WS_RE = new RegExp(`^${S}$`);

export function _extract_balanced_json_substring(text: string, start_idx: number): string | null {
  const chars = [...text];
  const opening = chars.at(start_idx);
  const matching: Record<string, string> = { '{': '}', '[': ']' };
  if (opening === undefined || !(opening in matching)) {
    return null;
  }

  const stack = [matching[opening]];
  let in_string = false;
  let escape_next = false;

  for (let idx = start_idx + 1; idx < chars.length; idx += 1) {
    const char = chars[idx];

    if (in_string) {
      if (escape_next) {
        escape_next = false;
      } else if (char === '\\') {
        escape_next = true;
      } else if (char === '"') {
        in_string = false;
      }
      continue;
    }

    if (char === '"') {
      in_string = true;
    } else if (char in matching) {
      stack.push(matching[char]);
    } else if (char === '}' || char === ']') {
      if (!stack.length || char !== stack[stack.length - 1]) {
        return null;
      }
      stack.pop();
      if (!stack.length) {
        return chars.slice(start_idx, idx + 1).join('');
      }
    }
  }

  return null;
}

export function _loads_json_from_start(text: string, start_idx: number): unknown {
  return _loads_json_span(text, start_idx)[0];
}

/** Parse the JSON value at *start_idx*; return ``(value, end_idx)``. */
export function _loads_json_span(text: string, start_idx: number): [unknown, number] {
  try {
    return pyJsonRawDecode(text, start_idx, false);
  } catch (raw_error) {
    if (!(raw_error instanceof PyJSONDecodeError)) throw raw_error;
    const json_str = _extract_balanced_json_substring(text, start_idx);
    if (json_str === null) {
      throw raw_error;
    }

    const fixed_json = fix_json_string(json_str);
    return [pyJsonLoadsExact(fixed_json, false), start_idx + [...json_str].length];
  }
}

/**
 * Return the first *outermost* parsable JSON value embedded in prose.
 *
 * When a candidate fails to parse but is balanced, values nested inside it
 * are only a fallback: a later top-level value is preferred over, e.g., the
 * first inner ``{...}`` of a broken wrapper object.
 */
export function _loads_embedded_json(output: string): unknown {
  let first_error: PyJSONDecodeError | null = null;
  let nested_fallback: [boolean, unknown] = [false, null];
  let skip_until = -1;

  const chars = [...output];
  for (let start = 0; start < chars.length; start += 1) {
    if (chars[start] !== '[' && chars[start] !== '{') continue;
    const nested = start < skip_until;
    if (nested && nested_fallback[0]) {
      continue;
    }
    let value: unknown;
    try {
      [value] = _loads_json_span(output, start);
    } catch (exc) {
      if (!(exc instanceof PyJSONDecodeError)) throw exc;
      if (first_error === null) {
        first_error = exc;
      }
      if (!nested) {
        const balanced = _extract_balanced_json_substring(output, start);
        if (balanced !== null) {
          skip_until = start + [...balanced].length;
        }
      }
      continue;
    }
    if (!nested) {
      return value;
    }
    nested_fallback = [true, value];
  }

  if (nested_fallback[0]) {
    return nested_fallback[1];
  }

  if (first_error !== null) {
    throw first_error;
  }

  throw new PyJSONDecodeError('No JSON object or array start found', output, 0);
}

const JSON_BLOCK = new RegExp(`\`\`\`json${S}*([\\s\\S]*?)${S}*\`\`\``);
const XML_BLOCK = new RegExp(`<([A-Za-z_][\\p{L}\\p{N}_:.-]*)>${S}*([\\s\\S]*?)${S}*</\\1>`, 'gu');

/**
 * Convert raw JSON output from the LLM into structured format.
 *
 * @param output The JSON output from the LLM
 * @param strict_response When true, require the whole response to be exactly one
 *   JSON value after optional reasoning tags are removed.
 */
export function convert_json_output(output: string, strict_response = false): unknown {
  output = pyStrip(output);

  // Strip reasoning wrappers that some providers prepend before the actual JSON.
  if (output.includes('<think>') || output.includes('<thought>')) {
    [, output] = extract_think_and_result(output);
    output = pyStrip(output);
  }

  if (strict_response) {
    // A response that is exactly one fenced block carries the same single
    // JSON value; unwrap it instead of paying for a full regeneration.
    const fenced = _SOLE_FENCE.exec(output);
    if (fenced) {
      output = pyStrip(fenced[1]);
    }
    try {
      return pyJsonLoadsExact(output);
    } catch (exc) {
      if (!(exc instanceof PyJSONDecodeError)) throw exc;
      throw new PyJSONDecodeError(
        'Expected response to be exactly one JSON value; ' + `${exc.msg}`,
        output,
        exc.pos,
      );
    }
  }

  // Try 0: Extract JSON from ```json ... ``` code block first
  const json_block_match = JSON_BLOCK.exec(output);
  if (json_block_match) {
    const json_str = pyStrip(json_block_match[1]);
    try {
      return pyJsonLoadsExact(json_str, false);
    } catch (error) {
      if (!(error instanceof PyJSONDecodeError)) throw error;
      // Try fixing common issues
      try {
        const fixed_json = fix_json_string(json_str);
        return pyJsonLoadsExact(fixed_json, false);
      } catch (inner) {
        if (!(inner instanceof PyJSONDecodeError)) throw inner;
        // Fall through to other methods
      }
    }
  }

  // Try 0.5: Extract JSON from XML-like wrapper tags
  const xml_block_matches = [...output.matchAll(XML_BLOCK)].map((match) => [match[1], match[2]] as const);
  for (const [, inner_content] of xml_block_matches) {
    const candidate = pyStrip(inner_content);
    if (!candidate) {
      continue;
    }
    if (!(
      candidate.startsWith('{')
      || candidate.startsWith('[')
      || candidate.startsWith('```json')
      || candidate.startsWith('```')
      || candidate.includes('{')
      || candidate.includes('[')
    )) {
      continue;
    }
    try {
      return convert_json_output(candidate);
    } catch (error) {
      if (!(error instanceof PyJSONDecodeError)) throw error;
      continue;
    }
  }

  // Remove markdown code blocks (for backward compatibility)
  if (output.startsWith('```json')) {
    output = pyStrip(output.slice(7));
  }
  if (output.startsWith('```')) {
    output = pyStrip(output.slice(3));
  }
  if (output.endsWith('```')) {
    output = pyStrip(output.slice(0, -3));
  }
  if (output.endsWith('```json')) {
    output = pyStrip(output.slice(0, -7));
  }

  // Try 1: Direct parsing
  try {
    return pyJsonLoadsExact(output, false);
  } catch (e1) {
    if (!(e1 instanceof PyJSONDecodeError)) throw e1;
    try {
      return _loads_embedded_json(output);
    } catch (inner) {
      if (!(inner instanceof PyJSONDecodeError)) throw inner;
      throw new PyJSONDecodeError(
        `No valid JSON found in response: ${e1.message}`,
        output,
        0,
      );
    }
  }
}

/**
 * ``hasattr(obj, name)`` for the response objects LangChain hands back.
 * Python dicts are TS plain objects and have no attributes; anything else
 * (message classes, SDK objects) is an object with attributes.
 */
function hasAttr(value: unknown, name: string): boolean {
  if (value === null || value === undefined) return false;
  if (typeof value !== 'object' && typeof value !== 'function') return false;
  if (isDict(value) || Array.isArray(value)) return false;
  return name in (value as object);
}

function dictGet(mapping: Record<string, unknown>, key: string, defaultValue: unknown = null): unknown {
  return Object.prototype.hasOwnProperty.call(mapping, key) ? mapping[key] : defaultValue;
}

/**
 * Extract text content from LLM response object.
 *
 * @param response LLM response object
 * @returns Text content string
 */
export function get_text_from_response(response: unknown): string {
  if (hasAttr(response, 'content')) {
    const content = (response as { content: unknown }).content;
    // Handle list of content blocks (e.g. for Anthropic or reasoning models)
    if (Array.isArray(content)) {
      const text_parts: string[] = [];
      for (const block of content) {
        if (isDict(block)) {
          if (dictGet(block, 'type') === 'text') {
            text_parts.push(dictGet(block, 'text', '') as string);
          } else if (dictGet(block, 'type') === 'thought') {
            // We might want to keep thought tags if they're not excluded later
            text_parts.push(`<thought>${pyStr(dictGet(block, 'thought', ''))}</thought>`);
          }
        } else if (hasAttr(block, 'text')) {
          text_parts.push((block as { text: string }).text);
        }
      }
      return text_parts.join('\n');
    }
    return content as string;
  }

  if (isDict(response)) {
    if ('messages' in response) {
      // Recurse so list-of-content-blocks in the last message get
      // flattened by the branch above, not returned raw.
      const messages = response.messages as unknown[];
      return get_text_from_response(messages[messages.length - 1]);
    }
    if ('choices' in response && (response.choices as unknown[]).length > 0) {
      const choice = (response.choices as Record<string, unknown>[])[0];
      if ('message' in choice) {
        const msg = choice.message as Record<string, unknown>;
        let content = dictGet(msg, 'content', '');
        // Some providers put reasoning in reasoning_content
        const reasoning = truthy(dictGet(msg, 'reasoning_content')) ? dictGet(msg, 'reasoning_content') : dictGet(msg, 'reasoning');
        if (truthy(reasoning)) {
          // If content is empty but reasoning has actual content,
          // use reasoning as the response (some providers use this pattern)
          if (!truthy(content) && truthy(pyStrip(reasoning as string))) {
            content = reasoning;
          } else {
            content = `<thought>${pyStr(reasoning)}</thought>\n${pyStr(content)}`;
          }
        }
        return content as string;
      }
      if ('text' in choice) {
        return choice.text as string;
      }
    }
  }

  return pyStr(response);
}

const THINK_SEARCH = /<(?:think|thought)>([\s\S]*?)<\/(?:think|thought)>/;
const THINK_SUB = /<(?:think|thought)>[\s\S]*?<\/(?:think|thought)>/g;

/**
 * Extract think and result content from the response info.
 *
 * @param info Response text containing think tags
 * @returns Tuple of (think_content, result_content)
 */
export function extract_think_and_result(info: string): [string, string] {
  // Match <think>...</think> or <thought>...</thought> tags (used by reasoning models)
  const think_match = THINK_SEARCH.exec(info);
  const think_content = think_match ? pyStrip(think_match[1]) : '';
  const result_content = pyStrip(info.replace(THINK_SUB, ''));
  return [think_content, result_content];
}

/**
 * Preprocess LLM response to extract and format content.
 *
 * @param response Raw LLM response
 * @param only_text Extract only text content
 * @param exclude_think Remove think blocks
 * @param json_output Parse as JSON
 * @param strict_json_output Require the entire response to be exactly JSON
 */
export function preprocess_response(
  response: unknown,
  only_text = true,
  exclude_think = false,
  json_output = false,
  strict_json_output = false,
): unknown {
  if (only_text || exclude_think || json_output) {
    response = get_text_from_response(response);
  }

  if (exclude_think) {
    const [, result_content] = extract_think_and_result(response as string);
    response = result_content;
  }

  if (json_output) {
    try {
      response = convert_json_output(response as string, strict_json_output);
    } catch (e) {
      if (e instanceof PyJSONDecodeError) {
        response = {
          error: 'Invalid JSON output',
          raw_content: response,
          parse_error: e.message,
        };
      }
      throw e;
    }
  }

  return response;
}

// For backward compatibility
export const __all__ = [
  'fix_json_string',
  'convert_json_output',
  'get_text_from_response',
  'extract_think_and_result',
  'preprocess_response',
];
