// Web-run fixtures (fixtures/web_runs/<case>/, tools/record_web_runs.py):
// the backend streaming endpoint POST /diagram/generate/stream recorded
// in-process with the LLM cassette (PHASE3_PLAN.md WP26).
//
// This module loads a case, normalizes TS values exactly like the recorder
// (tools/run_normalize.py + record_web_runs.py WebNormalizer) and compares
// event streams / results / LLM requests, reporting the FIRST divergence with
// an exact path:
//   llm     — "LLM call 3 (VerifierCriticAgent)"  + JSON path inside the request record
//   event   — "events[5] (stage_complete)"         + path such as events[5].data.message
//   result  — "result"                             + path such as result.metrics_scores.generation.quality_status
import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { compareImages, imageReference, jsonDiff, loadCassette, type CassetteEntry } from './cassette.ts';
import { compare } from './compare.ts';
import { FIXTURES } from './fixtures.ts';
import { Normalizer } from './runs.ts';
import { pyJsonLoadsExact } from '../../src/py/json_decoder.ts';

export const WEB_RUNS = join(FIXTURES, 'web_runs');

export interface WebRunInput {
  run: string;
  spec: Record<string, unknown> & { expect: 'result' | 'error' };
  endpoint: string;
  user: null;
  /** HTTP JSON body, as apiDiagramService.buildGenerateDiagramPayload sends it. */
  request: Record<string, unknown>;
  /** backend Settings fields the run depends on (api key redacted; results_dir is <OUT>/results). */
  settings: Record<string, unknown>;
  /** Text2DiagramWorkflow overrides injected through the engine port ({} = backend defaults). */
  engine: Record<string, unknown>;
  /** Environment of the run: LLM_* role-model config, EXCALIDRAW_RENDER_URL, … */
  env: Record<string, string>;
}

export interface WebEvent {
  index: number;
  event: string;
  /** LLM calls the backend had made when this event was emitted. */
  llm_calls: number;
  data: Record<string, unknown>;
}

export interface RecordedWebRun {
  name: string;
  dir: string;
  input: WebRunInput;
  cassette: CassetteEntry[];
  events: WebEvent[];
  result: { result: Record<string, unknown> | null; error: Record<string, unknown> | null };
}

export function loadWebRun(nameOrDir: string): RecordedWebRun {
  const dir = existsSync(join(nameOrDir, 'events.jsonl')) ? nameOrDir : join(WEB_RUNS, nameOrDir);
  const json = (file: string) => JSON.parse(readFileSync(join(dir, file), 'utf-8'));
  const input = pyJsonLoadsExact(readFileSync(join(dir, 'input.json'), 'utf-8')) as WebRunInput;
  return {
    name: input.run,
    dir,
    input,
    cassette: loadCassette(dir),
    events: readFileSync(join(dir, 'events.jsonl'), 'utf-8').split('\n').filter(Boolean).map((line) => JSON.parse(line) as WebEvent),
    result: json('result.json'),
  };
}

// ── normalization (mirror of record_web_runs.py WebNormalizer; keep in sync) ──

const REQUEST_ID_RE = /req_[0-9a-f]{12}/g;

export class WebNormalizer extends Normalizer {
  override text(value: string): string {
    return super.text(value).replace(REQUEST_ID_RE, 'req_<ID>');
  }

  override value(value: unknown): unknown {
    if (value && typeof value === 'object' && !Array.isArray(value) && !(value instanceof Map) && !(value instanceof Set)) {
      const out: Record<string, unknown> = {};
      for (const [key, item] of Object.entries(value)) {
        const numeric = typeof item === 'number';
        if (numeric && (key.endsWith('_ms') || key === 'elapsed_seconds')) out[key] = 0;
        else if (key === 'timings_ms' && item && typeof item === 'object' && !Array.isArray(item)) {
          out[key] = Object.fromEntries(Object.entries(item).map(([k, v]) => [k, typeof v === 'number' ? 0 : this.value(v)]));
        } else out[key] = this.value(item);
      }
      return out;
    }
    return super.value(value);
  }
}

// ── comparison ───────────────────────────────────────────────────────────

export interface WebDivergence {
  kind: 'llm' | 'event' | 'result' | 'error' | 'not_ported';
  where: string;
  diffs: string[];
}

export interface ActualEvent {
  event: string;
  data: unknown;
  /** LLM calls made before the event (TS: CassetteSession.calls.length at onEvent time). */
  llm_calls: number;
}

/** `$` of compare()/jsonDiff() paths → a readable absolute path. */
function rebase(diffs: string[], root: string): string[] {
  return diffs.map((diff) => (diff.startsWith('$') ? root + diff.slice(1) : `${root}: ${diff}`));
}

/**
 * Compare one actual event with expected event ``index``. Strict: event name,
 * LLM-call position, payload values (numbers within compare()'s tolerance) and
 * — for every event except ``result`` — payload key order (the SSE JSON text
 * is what the frontend parses). Returns [] when equal.
 */
export function compareEvent(expected: WebEvent | undefined, actual: ActualEvent | undefined, index: number): string[] {
  const root = `events[${index}]`;
  if (!expected) return [`${root}: unexpected extra event ${JSON.stringify(actual?.event)} (expected ${index} events)`];
  if (!actual) return [`${root}: missing event ${JSON.stringify(expected.event)} (the stream ended early)`];
  if (expected.event !== actual.event) return [`${root}.event: expected ${JSON.stringify(expected.event)}, got ${JSON.stringify(actual.event)}`];
  const result = compare(expected.data, actual.data);
  if (result.diffs.length) return rebase(result.diffs, `${root}.data`);
  if (expected.event !== 'result' && result.keyOrder.length) {
    return result.keyOrder.map((path) => `${root}.data${path.slice(1)}: key order ${JSON.stringify(Object.keys(pick(expected.data, path)))} != ${JSON.stringify(Object.keys(pick(actual.data, path)))}`);
  }
  if (expected.llm_calls !== actual.llm_calls) {
    return [`${root}.llm_calls: emitted after ${actual.llm_calls} LLM call(s), expected after ${expected.llm_calls}`];
  }
  return [];
}

function pick(value: unknown, path: string): Record<string, unknown> {
  let current: unknown = value;
  for (const match of path.slice(1).matchAll(/\.([^.[\]]+)|\[(\d+)\]/g)) {
    current = (current as Record<string, unknown>)?.[match[1] ?? Number(match[2])];
  }
  return (current ?? {}) as Record<string, unknown>;
}

/** Compare the terminal payloads (result.json shape). */
export function compareResult(expected: RecordedWebRun['result'], actual: RecordedWebRun['result']): string[] {
  return rebase(compare(expected, actual).diffs, 'result');
}

/** Compare a recorded request (cassette entry) with an actual one; images by the phase-2 rule. */
export function compareLlmEntry(expected: CassetteEntry, actual: CassetteEntry, expectedDir: string): string[] {
  const pickRecord = (entry: CassetteEntry) => ({ caller: entry.caller, role: entry.role, model_params: entry.model_params, request: entry.request });
  const diffs: string[] = [];
  jsonDiff(pickRecord(expected), pickRecord(actual), '$', diffs, 8, (exp, act, path) => compareImages(exp, act, path, expectedDir, []));
  return diffs;
}

/**
 * Offline comparison of two recorded case directories (e.g. a deliberately
 * altered copy vs the fixture, or a Python replay vs the fixture). Divergences
 * are ordered the way they would happen in a run: an LLM call k precedes every
 * event whose ``llm_calls`` > k.
 */
export function compareRecorded(expected: RecordedWebRun, actual: RecordedWebRun): WebDivergence | null {
  const llm = firstLlmDivergence(expected, actual);
  const event = firstEventDivergence(expected, actual);
  if (llm && (!event || llm.call < event.position)) return llm.divergence;
  if (event) return event.divergence;
  const result = compareResult(expected.result, actual.result);
  if (result.length) return { kind: 'result', where: 'result', diffs: result };
  return null;
}

function firstLlmDivergence(expected: RecordedWebRun, actual: RecordedWebRun): { call: number; divergence: WebDivergence } | null {
  const count = Math.max(expected.cassette.length, actual.cassette.length);
  for (let call = 0; call < count; call += 1) {
    const want = expected.cassette[call];
    const got = actual.cassette[call] ? withRawImages(actual.cassette[call], actual.dir) : undefined;
    const where = `LLM call ${call} (${want?.caller ?? got?.caller ?? '?'})`;
    if (!want) return { call, divergence: { kind: 'llm', where, diffs: [`unexpected extra LLM call (expected ${expected.cassette.length})`] } };
    if (!got) return { call, divergence: { kind: 'llm', where, diffs: [`missing: only ${actual.cassette.length} LLM call(s) were made`] } };
    const diffs = compareLlmEntry(want, got, expected.dir);
    if (diffs.length) return { call, divergence: { kind: 'llm', where, diffs } };
  }
  return null;
}

function firstEventDivergence(expected: RecordedWebRun, actual: RecordedWebRun): { position: number; divergence: WebDivergence } | null {
  const count = Math.max(expected.events.length, actual.events.length);
  for (let index = 0; index < count; index += 1) {
    const want = expected.events[index];
    const got = actual.events[index];
    const diffs = compareEvent(want, got, index);
    if (diffs.length) {
      return { position: want?.llm_calls ?? got?.llm_calls ?? 0, divergence: { kind: 'event', where: `events[${index}] (${want?.event ?? got?.event})`, diffs } };
    }
  }
  return null;
}

/** Recorded image refs → refs carrying their decoded bytes (needed for the pixel rule). */
function withRawImages(entry: CassetteEntry, dir: string): CassetteEntry {
  const visit = (value: unknown): unknown => {
    if (Array.isArray(value)) return value.map(visit);
    if (!value || typeof value !== 'object') return value;
    const record = value as Record<string, unknown>;
    const ref = record.__image__ as { mime?: string; file?: string } | undefined;
    if (ref && Object.keys(record).length === 1 && ref.file && existsSync(join(dir, ref.file))) {
      const decoded = imageReference(`data:${ref.mime};base64,${readFileSync(join(dir, ref.file)).toString('base64')}`);
      return decoded;
    }
    return Object.fromEntries(Object.entries(record).map(([k, v]) => [k, visit(v)]));
  };
  return { ...entry, request: visit(entry.request) as CassetteEntry['request'] };
}
