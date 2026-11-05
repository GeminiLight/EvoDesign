import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { AIMessage, HumanMessage, SystemMessage, ToolMessage, type BaseMessage } from '@langchain/core/messages';
import type { Adapter } from '../parity/functions.test.ts';
import { bindArguments, decode, pythonModuleDir, signatureOf, type Vector } from '../harness/fixtures.ts';

const MODULE = 'evodesign.utils.llm_output';
const lineCache = new Map<string, string[]>();

function toMessage(type: string, fields: Record<string, unknown>): BaseMessage {
  const content = fields.content as string;
  const extra: Record<string, unknown> = {};
  if (fields.name) extra.name = fields.name;
  switch (type) {
    case 'ai':
      return new AIMessage({ content, ...extra, tool_calls: ((fields.tool_calls as AIMessage['tool_calls']) ?? []) });
    case 'system':
      return new SystemMessage({ content, ...extra });
    case 'tool':
      return new ToolMessage({ content, ...extra, tool_call_id: fields.tool_call_id as string });
    default:
      return new HumanMessage({ content: content as HumanMessage['content'], ...extra });
  }
}

/** Like harness decode(), but ``__message__`` becomes a real LangChain message (an object with attributes, not a dict). */
function decodeWithMessages(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(decodeWithMessages);
  if (value === null || typeof value !== 'object') return value;
  const record = value as Record<string, unknown>;
  const keys = Object.keys(record);
  if (keys.length === 2 && '__message__' in record) {
    return toMessage(record.__message__ as string, decode(record.fields) as Record<string, unknown>);
  }
  if (keys.some((key) => key.startsWith('__') && key.endsWith('__'))) return decode(value);
  return Object.fromEntries(keys.map((key) => [key, decodeWithMessages(record[key])]));
}

/**
 * Re-bind fixture ``vector`` with LangChain message objects. Python's
 * get_text_from_response tells a message (``hasattr(response, 'content')``)
 * from a dict; the shared decoder turns both into plain objects.
 */
export function bindWithMessages(pythonModule: string, func: string, vector: Vector): unknown[] {
  const key = `${pythonModule}/${func}`;
  let lines = lineCache.get(key);
  if (!lines) {
    lines = readFileSync(join(pythonModuleDir(pythonModule), `${func}.jsonl`), 'utf-8').split('\n').filter(Boolean);
    lineCache.set(key, lines);
  }
  const raw = JSON.parse(lines[vector.line - 1]) as Record<string, unknown>;
  return bindArguments(signatureOf(pythonModule, func)!, {
    ...vector,
    args: decodeWithMessages(raw.args) as unknown[],
    kwargs: decodeWithMessages(raw.kwargs) as Record<string, unknown>,
  });
}

const withMessages = (func: string): Adapter => ({
  args: (_bound, vector) => bindWithMessages(MODULE, func, vector),
  // The re-bound arguments hold LangChain message instances whose own keys
  // (lc_kwargs, ...) differ from the fixture's {type, content}; neither
  // function mutates its argument.
  checkMutation: false,
});

export default {
  get_text_from_response: withMessages('get_text_from_response'),
  preprocess_response: withMessages('preprocess_response'),
} satisfies Record<string, Adapter>;
