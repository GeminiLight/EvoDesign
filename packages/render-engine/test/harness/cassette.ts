// LLM cassette replay for the TS pipeline (phase 2, PHASE2_PLAN.md §3).
//
// fixtures/runs/<run>/cassette.jsonl holds every chat-model call the Python
// pipeline made (tools/llm_cassette.py). ReplayChatModel is a @langchain/core
// BaseChatModel: on its N-th call (counted across every model of the run) it
// builds the same request record Python recorded — messages (type, content
// parts verbatim, tool calls), invocation options (bound tools, tool_choice,
// stop …), the model's init params and its LLMFactory role — and compares it
// with entry N. Any difference fails with JSON paths; otherwise the recorded
// response is returned (or the recorded transport error is raised, after
// streaming its partial text to the callbacks, exactly like Python).
//
// The first mismatch is also stored on the session, so a TS retry loop that
// swallows the thrown error cannot hide it (Python raises a BaseException).
//
// Image parts: see compareImages() and the PHASE2_PLAN.md appendix.
import { createHash } from 'node:crypto';
import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import type { CallbackManagerForLLMRun } from '@langchain/core/callbacks/manager';
import { BaseChatModel, type BaseChatModelCallOptions, type BindToolsInput } from '@langchain/core/language_models/chat_models';
import { AIMessage, HumanMessage, SystemMessage, ToolMessage, type BaseMessage } from '@langchain/core/messages';
import type { ChatResult } from '@langchain/core/outputs';
import { convertToOpenAITool } from '@langchain/core/utils/function_calling';
import { PNG } from 'pngjs';

export interface ImageRef {
  mime: string;
  sha256: string;
  bytes: number;
  width?: number;
  height?: number;
  rgba_sha256?: string;
  file: string;
}

export interface CassetteEntry {
  index: number;
  caller: string;
  role: string | null;
  model_params: Record<string, unknown>;
  request: { messages: Record<string, unknown>[]; invocation: Record<string, unknown> };
  response: { content?: unknown; tool_calls?: { name: string; args?: Record<string, unknown>; id?: string }[] }
    | { error: { type: string; message?: string; partial?: string } };
  source?: string;
  note?: string;
}

export interface CassetteMismatchInfo {
  call: number;
  caller: string | null;
  diffs: string[];
  /** Value of the session clock when the mismatch happened (event ordering). */
  order?: number;
}

/** Max per-channel difference tolerated between decoded image parts (see appendix). */
export const IMAGE_CHANNEL_TOLERANCE = Number(process.env.PARITY_IMAGE_TOLERANCE ?? 1);

/** Python passes the agent class as `caller`; TS cannot read it off the stack. */
export type CallerResolver = (model: ReplayChatModel, messages: BaseMessage[]) => string | null;

export class CassetteMismatchError extends Error {
  constructor(readonly info: CassetteMismatchInfo) {
    super(`LLM call ${info.call} differs from cassette: ${info.diffs.join('; ')}`);
    this.name = 'CassetteMismatch';
  }
}

export function loadCassette(runDir: string): CassetteEntry[] {
  return readFileSync(join(runDir, 'cassette.jsonl'), 'utf-8')
    .split('\n')
    .filter((line) => line.trim())
    .map((line) => JSON.parse(line) as CassetteEntry);
}

export class CassetteSession {
  readonly calls: { entry: CassetteEntry; tolerated: string[] }[] = [];
  mismatch: CassetteMismatchInfo | null = null;
  /** Called with every request record (debug / smoke tests). */
  onRequest?: (index: number, record: Record<string, unknown>) => void;
  /** Shared event clock (tools/parity-runs.ts orders LLM vs snapshot divergences). */
  clock?: () => number;

  constructor(readonly runDir: string, readonly entries: CassetteEntry[] = loadCassette(runDir)) {}

  get index(): number {
    return this.calls.length;
  }

  /**
   * Compare a TS request with entry N and return it. Throws (and remembers)
   * CassetteMismatchError on any difference.
   */
  next(actual: { caller: string | null; role: string | null; model_params: Record<string, unknown>; request: Record<string, unknown> }): CassetteEntry {
    if (this.mismatch) throw new CassetteMismatchError(this.mismatch);
    const index = this.calls.length;
    this.onRequest?.(index, actual.request);
    const expected = this.entries[index];
    if (!expected) {
      return this.fail({ call: index, caller: actual.caller, diffs: [`call ${index}: cassette has only ${this.entries.length} entries`] });
    }
    const tolerated: string[] = [];
    const diffs: string[] = [];
    const want: Record<string, unknown> = { role: expected.role, model_params: expected.model_params, request: expected.request };
    const got: Record<string, unknown> = { role: actual.role, model_params: actual.model_params, request: actual.request };
    if (actual.caller !== null) {
      want.caller = expected.caller;
      got.caller = actual.caller;
    }
    jsonDiff(want, got, '$', diffs, 8, (exp, act, path) => compareImages(exp, act, path, this.runDir, tolerated));
    if (diffs.length) return this.fail({ call: index, caller: expected.caller, diffs });
    this.calls.push({ entry: expected, tolerated });
    return expected;
  }

  private fail(info: CassetteMismatchInfo): never {
    info.order = this.clock?.();
    this.mismatch = info;
    throw new CassetteMismatchError(info);
  }

  /** Number of calls whose caller could not be read off the JS stack. */
  unverifiedCallers = 0;

  /** Factory with the shape runRecordedPipeline() expects. */
  chatModelFactory(resolveCaller: CallerResolver = stackCallerResolver(this)) {
    return (params: Record<string, unknown>, role: string | null = null): ReplayChatModel =>
      new ReplayChatModel({ session: this, params, role, resolveCaller });
  }
}

/**
 * Default caller attribution: the nearest stack frame whose receiver class is
 * one of the agent classes this cassette knows (V8 prints ``Class.method``
 * with the receiver's class, like Python's ``type(self).__name__``). Returns
 * null — caller not compared, counted in ``unverifiedCallers`` — when async
 * scheduling has dropped the agent frames.
 */
export function stackCallerResolver(session: CassetteSession): CallerResolver {
  const known = new Set(session.entries.map((entry) => entry.caller));
  return () => {
    const previous = Error.stackTraceLimit;
    Error.stackTraceLimit = 200;
    const stack = new Error().stack ?? '';
    Error.stackTraceLimit = previous;
    for (const match of stack.matchAll(/at (?:async )?(?:new )?([A-Za-z_$][\w$]*)\.[\w$<>]+/g)) {
      if (known.has(match[1])) return match[1];
    }
    session.unverifiedCallers += 1;
    return null;
  };
}

// ── request records (mirror tools/llm_cassette.py) ───────────────────────

const RUNNABLE_CONFIG_KEYS = new Set([
  'callbacks', 'tags', 'metadata', 'runName', 'runId', 'configurable', 'recursionLimit', 'maxConcurrency',
  'signal', 'timeout', 'ls_structured_output_format', 'writer', 'store', 'context',
  'promptIndex', // JS-only: index of the prompt inside a batched generate()
  'control', 'executionInfo', // LangGraph.js runtime bookkeeping leaking into call options
]);

export function contentRecord(content: unknown): unknown {
  if (!Array.isArray(content)) return content;
  return content.map((part) => {
    if (part && typeof part === 'object' && (part as Record<string, unknown>).type === 'image_url') {
      const record = part as Record<string, unknown>;
      const imageUrl = record.image_url;
      if (imageUrl && typeof imageUrl === 'object') {
        const inner = imageUrl as Record<string, unknown>;
        return { ...record, image_url: { ...inner, url: imageReference(inner.url) } };
      }
      return { ...record, image_url: imageReference(imageUrl) };
    }
    return part;
  });
}

export function messageRecord(message: BaseMessage): Record<string, unknown> {
  const type = message.getType();
  const record: Record<string, unknown> = { type, content: contentRecord(message.content) };
  const toolCalls = (message as AIMessage).tool_calls;
  if (toolCalls?.length) record.tool_calls = toolCalls.map((call) => ({ name: call.name, args: call.args, id: call.id ?? null }));
  if (type === 'tool') record.tool_call_id = (message as ToolMessage).tool_call_id ?? null;
  if (message.name) record.name = message.name;
  return record;
}

export function invocationRecord(options: Record<string, unknown>): Record<string, unknown> {
  const record: Record<string, unknown> = {};
  for (const key of Object.keys(options).sort()) {
    if (RUNNABLE_CONFIG_KEYS.has(key) || options[key] === undefined || typeof options[key] === 'function') continue;
    // An empty tool list is not sent to the provider (same rule as llm_cassette.py).
    if (key === 'tools' && Array.isArray(options[key]) && (options[key] as unknown[]).length === 0) continue;
    if (process.env.CASSETTE_DEBUG_OPTIONS) console.error('[cassette] call option', key, options[key]);
    const json = JSON.stringify(options[key]);
    if (json === undefined) continue;
    record[key] = JSON.parse(json);
  }
  return record;
}

interface DecodedImage { ref: ImageRef; raw: Buffer }

/** data: URL → {"__image__": ImageRef} (+ the decoded bytes, non-enumerable). */
export function imageReference(url: unknown): unknown {
  if (typeof url !== 'string' || !url.startsWith('data:') || !url.includes(';base64,')) return url;
  const comma = url.indexOf(',');
  const mime = url.slice('data:'.length, url.indexOf(';'));
  const raw = Buffer.from(url.slice(comma + 1), 'base64');
  const sha256 = createHash('sha256').update(raw).digest('hex');
  const ref: ImageRef = { mime, sha256, bytes: raw.length, file: `images/${sha256}.${({ 'image/png': 'png', 'image/jpeg': 'jpg', 'image/svg+xml': 'svg' } as Record<string, string>)[mime] ?? 'bin'}` };
  if (mime === 'image/png') {
    try {
      const png = PNG.sync.read(raw);
      ref.width = png.width;
      ref.height = png.height;
      ref.rgba_sha256 = createHash('sha256').update(png.data).digest('hex');
    } catch {
      // not decodable: byte hash only (same as Python)
    }
  }
  const wrapper = { __image__: ref };
  Object.defineProperty(wrapper, '__raw__', { value: { ref, raw } satisfies DecodedImage, enumerable: false });
  return wrapper;
}

/**
 * Image part rule (PHASE2_PLAN.md appendix):
 *  1. same mime type, and
 *  2. identical bytes (sha256) — or identical size and identical decoded RGBA
 *     pixels — or identical size and every channel within
 *     IMAGE_CHANNEL_TOLERANCE (reported as tolerated, not as a failure).
 * `file`, `bytes` and `sha256` are not compared once pixels match: PNG
 * encoders (PIL vs pngjs/Chromium) may legitimately differ in compression.
 */
export function compareImages(expected: unknown, actual: unknown, path: string, runDir: string, tolerated: string[]): string[] | null {
  const want = (expected as { __image__?: ImageRef } | null)?.__image__;
  const got = (actual as { __image__?: ImageRef } | null)?.__image__;
  if (!want || !got || typeof want !== 'object') return null; // not an image pair: generic diff
  if (want.mime !== got.mime) return [`${path}: image mime ${want.mime} != ${got.mime}`];
  if (want.sha256 === got.sha256) return [];
  if (want.width !== got.width || want.height !== got.height) {
    return [`${path}: image size ${want.width}x${want.height} != ${got.width}x${got.height}`];
  }
  if (want.rgba_sha256 && want.rgba_sha256 === got.rgba_sha256) return [];
  const file = join(runDir, want.file);
  const raw = (actual as { __raw__?: DecodedImage }).__raw__?.raw;
  if (!existsSync(file) || !raw || want.mime !== 'image/png') return [`${path}: image pixels differ (sha256 ${want.sha256} vs ${got.sha256})`];
  const left = PNG.sync.read(readFileSync(file)).data;
  const right = PNG.sync.read(raw).data;
  let maxDelta = 0;
  let differing = 0;
  for (let i = 0; i < left.length; i += 1) {
    const delta = Math.abs(left[i] - right[i]);
    if (delta) differing += 1;
    if (delta > maxDelta) maxDelta = delta;
  }
  if (maxDelta <= IMAGE_CHANNEL_TOLERANCE) {
    tolerated.push(`${path}: ${differing} channel values differ by ≤ ${maxDelta}`);
    return [];
  }
  return [`${path}: image pixels differ (max channel delta ${maxDelta}, ${differing} channel values)`];
}

/** Exact JSON diff with paths; same output format as tools/llm_cassette.py json_diff. */
export function jsonDiff(
  expected: unknown,
  actual: unknown,
  path: string,
  out: string[],
  limit = 8,
  special?: (expected: unknown, actual: unknown, path: string) => string[] | null,
): string[] {
  if (out.length >= limit) return out;
  const custom = special?.(expected, actual, path);
  if (custom) {
    out.push(...custom.slice(0, limit - out.length));
    return out;
  }
  const isObject = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === 'object' && !Array.isArray(v);
  if (isObject(expected) && isObject(actual)) {
    for (const key of Object.keys(expected)) {
      if (!(key in actual) || actual[key] === undefined) out.push(`${path}.${key}: missing (expected ${short(expected[key])})`);
      else jsonDiff(expected[key], actual[key], `${path}.${key}`, out, limit, special);
    }
    for (const key of Object.keys(actual)) {
      if (!(key in expected) && actual[key] !== undefined) out.push(`${path}.${key}: unexpected ${short(actual[key])}`);
    }
    return out;
  }
  if (Array.isArray(expected) && Array.isArray(actual)) {
    if (expected.length !== actual.length) out.push(`${path}: length ${expected.length} != ${actual.length}`);
    for (let i = 0; i < Math.min(expected.length, actual.length); i += 1) jsonDiff(expected[i], actual[i], `${path}[${i}]`, out, limit, special);
    return out;
  }
  if (typeof expected === 'string' && typeof actual === 'string') {
    if (expected !== actual) {
      const a = [...expected];
      const b = [...actual];
      let index = 0;
      while (index < Math.min(a.length, b.length) && a[index] === b[index]) index += 1;
      out.push(`${path}: strings differ at char ${index}: expected ${short(a.slice(Math.max(0, index - 20), index + 40).join(''))}, got ${short(b.slice(Math.max(0, index - 20), index + 40).join(''))}`);
    }
    return out;
  }
  if (expected !== actual) out.push(`${path}: expected ${short(expected)}, got ${short(actual)}`);
  return out;
}

function short(value: unknown): string {
  const text = JSON.stringify(value) ?? String(value);
  return text.length <= 120 ? text : `${text.slice(0, 117)}...`;
}

// ── the replay model ──────────────────────────────────────────────────────

export interface ReplayChatModelFields {
  session: CassetteSession;
  params: Record<string, unknown>;
  role?: string | null;
  resolveCaller?: CallerResolver;
}

const ERROR_TYPES: Record<string, new (message: string) => Error> = {
  ConnectionError: class ConnectionError extends Error { override name = 'ConnectionError'; },
  TimeoutError: class TimeoutError extends Error { override name = 'TimeoutError'; },
  ValueError: class ValueError extends Error { override name = 'ValueError'; },
};

export class ReplayChatModel extends BaseChatModel {
  readonly session: CassetteSession;
  readonly params: Record<string, unknown>;
  readonly role: string | null;
  readonly resolveCaller?: CallerResolver;

  constructor(fields: ReplayChatModelFields) {
    super({});
    this.session = fields.session;
    this.params = sanitizeParams(fields.params);
    this.role = fields.role ?? null;
    this.resolveCaller = fields.resolveCaller;
  }

  _llmType(): string {
    return 'evodesign-cassette';
  }

  override bindTools(tools: BindToolsInput[], kwargs?: Partial<BaseChatModelCallOptions>) {
    return this.withConfig({ tools: tools.map((tool) => convertToOpenAITool(tool)), ...(kwargs ?? {}) } as Partial<BaseChatModelCallOptions>);
  }

  async _generate(messages: BaseMessage[], options: this['ParsedCallOptions'], runManager?: CallbackManagerForLLMRun): Promise<ChatResult> {
    const request = {
      messages: messages.map(messageRecord),
      invocation: invocationRecord(options as unknown as Record<string, unknown>),
    };
    const entry = this.session.next({
      caller: this.resolveCaller?.(this, messages) ?? null,
      role: this.role,
      model_params: this.params,
      request,
    });
    const response = entry.response;
    if ('error' in response) {
      if (response.error.partial) await runManager?.handleLLMNewToken(response.error.partial);
      const ErrorType = ERROR_TYPES[response.error.type] ?? Error;
      throw new ErrorType(response.error.message ?? '');
    }
    const message = new AIMessage({
      content: (response.content ?? '') as string,
      tool_calls: (response.tool_calls ?? []).map((call) => ({ name: call.name, args: call.args ?? {}, id: call.id, type: 'tool_call' as const })),
      id: `cassette-${entry.index}`,
    });
    return { generations: [{ message, text: typeof message.content === 'string' ? message.content : '' }] };
  }
}

/** api_key never reaches a fixture (tools/llm_cassette.py sanitize_params). */
export function sanitizeParams(params: Record<string, unknown>): Record<string, unknown> {
  const clean: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined) continue;
    clean[key] = key === 'api_key' ? '<redacted>' : JSON.parse(JSON.stringify(value));
  }
  return clean;
}

// ── helpers for tools and smoke tests ─────────────────────────────────────

/** Rebuild the LangChain messages of a recorded request (images from images/). */
export function requestMessages(entry: CassetteEntry, runDir: string): BaseMessage[] {
  return entry.request.messages.map((record) => {
    const content = restoreContent(record.content, runDir);
    switch (record.type) {
      case 'system': return new SystemMessage({ content: content as string });
      case 'ai': return new AIMessage({ content: content as string, tool_calls: (record.tool_calls as AIMessage['tool_calls']) ?? [] });
      case 'tool': return new ToolMessage({ content: content as string, tool_call_id: record.tool_call_id as string });
      default: return new HumanMessage({ content: content as HumanMessage['content'] });
    }
  });
}

function restoreContent(content: unknown, runDir: string): unknown {
  if (!Array.isArray(content)) return content;
  return content.map((part) => {
    const record = part as Record<string, unknown>;
    if (record?.type !== 'image_url') return part;
    const inner = record.image_url as Record<string, unknown>;
    const ref = (inner.url as { __image__?: ImageRef }).__image__;
    if (!ref) return part;
    const data = readFileSync(join(runDir, ref.file)).toString('base64');
    return { ...record, image_url: { ...inner, url: `data:${ref.mime};base64,${data}` } };
  });
}
