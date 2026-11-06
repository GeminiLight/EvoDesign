import { mkdtempSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import type { Adapter } from '../parity/functions.test.ts';
import { FIXTURES, type Vector } from '../harness/fixtures.ts';
import { VerifierState } from '../../src/verification_stage/state.ts';
import { _report_writer } from '../../src/verification_stage/workflow.ts';
import { ModelConfig } from '../../src/config/model_loader.ts';
import { ensure_env_loaded } from '../../src/utils/env_loader.ts';

// Load .env before any vector overrides LLM_* (it is loaded once per process
// and never overrides variables that are already set).
ensure_env_loaded();

// The recorded paths point into each run's temporary directory
// (<tmp>/evodesign-run-XXXXXXXX/out/...), deleted after recording. Every file
// the pipeline left there is kept as fixtures/runs/<run>/artifacts/<path>,
// normalized (the run directory written as "<OUT>"). The adapters
//   * rewrite recorded paths in the arguments to the artifact copies,
//   * rebuild VerifierState instances from the recorded field dicts,
//   * map artifact paths and "<OUT>" in the result back to the recorded paths.
// The nodes return the (mutated) state, so the result comparison covers the
// mutation; args_after holds the unmapped paths and is not compared.

type Dict = Record<string, any>;

const RUN_OUT = /([^\s"'<>]*\/evodesign-run-[A-Za-z0-9_]+)\/out(?=\/|$)/;

interface Mapping { run: string; runDir: string; artifacts: string }

const mappings = new WeakMap<Vector, Mapping>();

function findRunDir(value: unknown): string | null {
  const text = JSON.stringify(value);
  const match = RUN_OUT.exec(text ?? '');
  return match ? match[1] : null;
}

function mapStrings(value: unknown, fn: (text: string) => string): unknown {
  if (typeof value === 'string') return fn(value);
  if (Array.isArray(value)) return value.map((item) => mapStrings(item, fn));
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, mapStrings(item, fn)]));
  }
  return value;
}

function mappingFor(vector: Vector, args: unknown[]): Mapping | null {
  const run = vector.source.startsWith('run:') ? vector.source.slice(4) : null;
  const runDir = findRunDir(args);
  if (!run || !runDir) return null;
  const mapping = { run, runDir, artifacts: join(FIXTURES, 'runs', run, 'artifacts') };
  mappings.set(vector, mapping);
  return mapping;
}

function mapIn(value: unknown, mapping: Mapping | null): unknown {
  if (!mapping) return value;
  return mapStrings(value, (text) => text.split(`${mapping.runDir}/out`).join(mapping.artifacts));
}

/** Plain JSON form of the TS result with artifact paths / "<OUT>" mapped back. */
function mapOut(value: unknown, vector: Vector, extra: [string, string][] = []): unknown {
  const plain = JSON.parse(JSON.stringify(value ?? null));
  const mapping = mappings.get(vector);
  return mapStrings(plain, (text) => {
    let out = text;
    for (const [from, to] of extra) out = out.split(from).join(to);
    if (mapping) out = out.split(mapping.artifacts).join(`${mapping.runDir}/out`).split('<OUT>').join(mapping.runDir);
    return out;
  });
}

function stateArgs(bound: unknown[], vector: Vector): unknown[] {
  const mapping = mappingFor(vector, bound);
  return [new VerifierState(mapIn(bound[0], mapping) as Dict), ...bound.slice(1)];
}

const stateNode: Adapter = {
  args: stateArgs,
  result: (actual, vector) => mapOut(actual, vector),
  checkMutation: false,
};

// ---- _node_build_report: environment, output directory, timestamp ----

const TIMESTAMP = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/;
let outputRoot: string | null = null;
const redirected = new WeakMap<Vector, { from: string; to: string }>();
const savedEnv = new WeakMap<Vector, Record<string, string | undefined>>();
const originalWriteReport = _report_writer.write_report;

function buildReportArgs(bound: unknown[], vector: Vector): unknown[] {
  const [state, ...rest] = stateArgs(bound, vector) as [VerifierState, ...unknown[]];
  // The run used the recorded environment (LLM_* placeholders: the verifier
  // model is "cassette-model"); pytest used the local configuration.
  const mapping = mappings.get(vector);
  if (mapping) {
    const env = JSON.parse(readFileSync(join(FIXTURES, 'runs', mapping.run, 'input.json'), 'utf-8')).env as Record<string, string>;
    const saved: Record<string, string | undefined> = {};
    for (const [key, value] of Object.entries(env)) {
      saved[key] = process.env[key];
      process.env[key] = value;
    }
    savedEnv.set(vector, saved);
    ModelConfig._instance = null;
  }
  // The pytest vector monkeypatched write_report to raise.
  const expectedErrors = ((vector.result as Dict)?.errors ?? []) as string[];
  const failure = expectedErrors.find((error) => error.startsWith('failed to write report: '));
  _report_writer.write_report = failure
    ? () => { throw new Error(failure.slice('failed to write report: '.length)); }
    : originalWriteReport;
  // Write into a fresh directory instead of the deleted temp directory.
  outputRoot ??= mkdtempSync(join(tmpdir(), 'wp20-build-report-'));
  const target = join(outputRoot, String(vector.line));
  const from = state.output_dir ?? '';
  redirected.set(vector, { from, to: target });
  state.output_dir = target;
  return [state, ...rest];
}

function buildReportResult(actual: unknown, vector: Vector): unknown {
  _report_writer.write_report = originalWriteReport;
  const saved = savedEnv.get(vector);
  if (saved) {
    for (const [key, value] of Object.entries(saved)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
    ModelConfig._instance = null;
  }
  const { from, to } = redirected.get(vector)!;
  const state = mapOut(actual, vector, [[to, from]]) as Dict;
  const expected = vector.result as Dict;
  for (const report of [state.report]) {
    if (report?.metadata && TIMESTAMP.test(report.metadata.timestamp)) report.metadata.timestamp = expected.report.metadata.timestamp;
  }
  return state;
}

export default {
  _load_json: {
    args: (bound, vector) => mapIn(bound, mappingFor(vector, bound)) as unknown[],
    result: (actual, vector) => mapOut(actual, vector),
    checkMutation: false,
  },
  _resolve_layout_path: {
    args: (bound, vector) => mapIn(bound, mappingFor(vector, bound)) as unknown[],
    result: (actual, vector) => mapOut(actual, vector),
    checkMutation: false,
  },
  _node_load_inputs: stateNode,
  _node_run_objective_checks: stateNode,
  _node_run_subjective_critic: {
    skip: 'async (VLM call); covered by the verifier-graph cassette replay over all recorded runs (notes/WP20.md)',
  },
  _node_build_report: {
    args: buildReportArgs,
    result: buildReportResult,
    checkMutation: false,
  },
} satisfies Record<string, Adapter>;
