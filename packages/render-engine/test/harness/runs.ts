// End-to-end run fixtures (fixtures/runs/<run>/, tools/record_runs.py):
// loading, the normalization rules of tools/run_normalize.py, conversion of TS
// values into the fixture shape, and the snapshot instrumentation that mirrors
// tools/run_snapshots.py on the TS side.
import { createHash } from 'node:crypto';
import { existsSync, readFileSync, realpathSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { PNG } from 'pngjs';
import { FIXTURES, PACKAGE_ROOT, decode } from './fixtures.ts';

export const RUNS = join(FIXTURES, 'runs');
export const REPO_ROOT = join(PACKAGE_ROOT, '..', '..');

export interface RunSnapshot { seq: number; scope: 'workflow' | 'graph'; graph: string; node: string; value: unknown }
export interface ArtifactEntry { path: string; kind: 'json' | 'text' | 'png' | 'binary'; sha256: string; width?: number; height?: number; rgba_sha256?: string }
export interface RunInput {
  run: string;
  spec: Record<string, unknown>;
  item: Record<string, unknown>;
  argv: string[];
  env: Record<string, string>;
  model_name: string;
}
export interface RecordedRun {
  name: string;
  dir: string;
  input: RunInput;
  snapshots: RunSnapshot[];
  artifacts: ArtifactEntry[];
  result: { result: Record<string, unknown> | null; error: string | null };
}

export function loadRun(name: string): RecordedRun {
  const dir = join(RUNS, name);
  const json = (file: string) => JSON.parse(readFileSync(join(dir, file), 'utf-8'));
  return {
    name,
    dir,
    input: json('input.json'),
    snapshots: readFileSync(join(dir, 'snapshots.jsonl'), 'utf-8').split('\n').filter(Boolean).map((line) => JSON.parse(line)),
    artifacts: json('artifacts.json'),
    result: json('result.json'),
  };
}

// ── normalization (port of tools/run_normalize.py; keep in sync) ─────────

const TIMESTAMP_RE = /\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?/g;
const UUID_RE = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/g;
const TEMP_SUFFIX_RE = /(<TMP>\/(?:evodesign_|evodesign-render-|tmp))[A-Za-z0-9_]{8}/g;
const VOLATILE_KEYS: Record<string, number> = { duration_ms: 0, elapsed_seconds: 0 };

export class Normalizer {
  private readonly pairs: [string, string][];

  /** ``workDir`` plays the role of Python's temporary run directory (<OUT>). */
  constructor(workDir: string) {
    const pairs: [string, string][] = [];
    const add = (path: string, token: string) => {
      const variants = new Set([path.replace(/\/+$/, '')]);
      try {
        variants.add(realpathSync(path).replace(/\/+$/, ''));
      } catch {
        // path may not exist (yet)
      }
      for (const variant of variants) if (variant && !pairs.some(([p, t]) => p === variant && t === token)) pairs.push([variant, token]);
    };
    add(workDir, '<OUT>');
    add(REPO_ROOT, '<REPO>');
    add(tmpdir(), '<TMP>');
    add('/tmp', '<TMP>');
    this.pairs = pairs.sort((a, b) => b[0].length - a[0].length);
  }

  text(value: string): string {
    for (const [path, token] of this.pairs) if (value.includes(path)) value = value.split(path).join(token);
    return value.replace(TEMP_SUFFIX_RE, '$1XXXXXXXX').replace(TIMESTAMP_RE, '<TIMESTAMP>').replace(UUID_RE, '<UUID>');
  }

  value(value: unknown): unknown {
    if (typeof value === 'string') return this.text(value);
    if (Array.isArray(value)) return value.map((item) => this.value(item));
    if (value instanceof Map) return new Map([...value].map(([k, v]) => [k, this.value(v)]));
    if (value instanceof Set) return new Set([...value].map((v) => this.value(v)));
    if (value && typeof value === 'object') {
      const out: Record<string, unknown> = {};
      for (const [key, item] of Object.entries(value)) {
        out[key] = key in VOLATILE_KEYS && typeof item === 'number' ? VOLATILE_KEYS[key] : this.value(item);
      }
      return out;
    }
    return value;
  }
}

// ── TS value → fixture shape ─────────────────────────────────────────────

/**
 * Plain form of a TS snapshot value, comparable with ``decode(python value)``:
 * class instances become their own enumerable fields (pydantic models /
 * dataclasses decode to fields too), langchain messages become
 * ``{type, content, ...}`` like ``__message__``, undefined fields are dropped.
 * A value may define ``toFixture()`` to control its shape explicitly.
 */
export function toPlain(value: unknown, seen = new WeakSet<object>()): unknown {
  if (value === null || typeof value !== 'object') return value;
  if (seen.has(value)) return '<cycle>';
  seen.add(value);
  try {
    const custom = (value as { toFixture?: () => unknown }).toFixture;
    if (typeof custom === 'function') return toPlain(custom.call(value), seen);
    if (Array.isArray(value)) return value.map((item) => toPlain(item, seen));
    if (value instanceof Map) return new Map([...value].map(([k, v]) => [toPlain(k, seen), toPlain(v, seen)]));
    if (value instanceof Set) return new Set([...value].map((v) => toPlain(v, seen)));
    const message = value as { getType?: () => string; content?: unknown; lc_serializable?: boolean };
    if (typeof message.getType === 'function' && 'content' in message && message.lc_serializable !== undefined) {
      const record: Record<string, unknown> = { type: message.getType(), content: toPlain(message.content, seen) };
      const extra = value as { name?: string; tool_calls?: { name: string; args: unknown; id?: string }[]; tool_call_id?: string };
      if (extra.name) record.name = extra.name;
      if (extra.tool_calls?.length) record.tool_calls = extra.tool_calls.map((c) => ({ name: c.name, args: toPlain(c.args, seen), id: c.id ?? null }));
      if (record.type === 'tool') record.tool_call_id = extra.tool_call_id ?? null;
      return record;
    }
    const out: Record<string, unknown> = {};
    for (const [key, item] of Object.entries(value)) if (item !== undefined && typeof item !== 'function') out[key] = toPlain(item, seen);
    return out;
  } finally {
    seen.delete(value);
  }
}

export function expectedValue(snapshot: RunSnapshot): unknown {
  return decode(snapshot.value);
}

// ── PNG comparison ────────────────────────────────────────────────────────

export function pngInfo(bytes: Buffer): { width: number; height: number; rgba_sha256: string } {
  const png = PNG.sync.read(bytes);
  return { width: png.width, height: png.height, rgba_sha256: createHash('sha256').update(png.data).digest('hex') };
}

export function sha256(bytes: Buffer | string): string {
  return createHash('sha256').update(bytes).digest('hex');
}

// ── snapshot instrumentation (mirror of tools/run_snapshots.py) ──────────

export const WORKFLOW_PHASES = [
  '_run_generation_phase',
  '_render_generation_output',
  '_run_verification_phase',
  '_run_refinement_phase',
  '_run_final_verification_phase',
  '_finalize_outputs',
  '_build_state',
] as const;

export type SnapshotSink = (scope: 'workflow' | 'graph', graph: string, node: string, value: unknown) => void;

let sink: SnapshotSink | null = null;
let instrumented = false;

/** Route snapshots of the next run to ``onSnapshot`` (null disables). */
export function setSnapshotSink(onSnapshot: SnapshotSink | null): void {
  sink = onSnapshot;
}

/**
 * Wrap every LangGraph.js StateGraph node and the TS Text2DiagramWorkflow
 * phases (src/agentic_system/workflow.ts, when ported) so that each one
 * reports its return value — the TS counterpart of tools/run_snapshots.py.
 * Installed once per process; must run before the pipeline builds graphs.
 */
export async function instrumentSnapshots(): Promise<void> {
  if (instrumented) return;
  instrumented = true;
  const { StateGraph } = await import('@langchain/langgraph');
  const proto = StateGraph.prototype as unknown as { addNode: (...args: unknown[]) => unknown };
  const originalAddNode = proto.addNode;
  const wrap = (name: string, action: unknown, graph: unknown) => {
    if (typeof action !== 'function') return action;
    const label = graphLabel(graph);
    return async function snapshotNode(this: unknown, ...args: unknown[]) {
      const result = await (action as (...a: unknown[]) => unknown).apply(this, args);
      sink?.('graph', label, name, result);
      return result;
    };
  };
  proto.addNode = function addNode(this: unknown, ...args: unknown[]) {
    if (typeof args[0] === 'string') return originalAddNode.call(this, args[0], wrap(args[0], args[1], this), ...args.slice(2));
    if (Array.isArray(args[0])) {
      return originalAddNode.call(this, (args[0] as [string, unknown, ...unknown[]][]).map(([n, a, ...rest]) => [n, wrap(n, a, this), ...rest]), ...args.slice(1));
    }
    if (args[0] && typeof args[0] === 'object') {
      const nodes = Object.fromEntries(Object.entries(args[0] as Record<string, unknown>).map(([n, a]) => [n, wrap(n, a, this)]));
      return originalAddNode.call(this, nodes, ...args.slice(1));
    }
    return originalAddNode.apply(this, args);
  };

  const workflowPath = join(PACKAGE_ROOT, 'src/agentic_system/workflow.ts');
  if (existsSync(workflowPath)) {
    const mod = (await import(workflowPath)) as { Text2DiagramWorkflow?: { prototype: Record<string, unknown> } };
    const target = mod.Text2DiagramWorkflow?.prototype;
    for (const phase of WORKFLOW_PHASES) {
      const original = target?.[phase];
      if (typeof original !== 'function') continue;
      target![phase] = async function phaseSnapshot(this: unknown, ...args: unknown[]) {
        const result = await (original as (...a: unknown[]) => unknown).apply(this, args);
        sink?.('workflow', 'Text2DiagramWorkflow', phase, result);
        return result;
      };
    }
  }
}

/** Python records ``module.Class`` of the state schema; TS schemas may carry ``pythonName``. */
function graphLabel(graph: unknown): string {
  const schema = (graph as { _schemaDefinition?: { pythonName?: string }; pythonName?: string }) ?? {};
  return schema.pythonName ?? schema._schemaDefinition?.pythonName ?? '<ts>';
}
