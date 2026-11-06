// End-to-end replay parity: run the TS pipeline on every recorded Python run
// (fixtures/runs/<run>/, tools/record_runs.py) with the LLM cassette and report
// each run's FIRST divergence:
//   llm       — LLM call N: the TS request differs from cassette entry N (JSON path)
//   snapshot  — node snapshot k (workflow phase or LangGraph node) differs (JSON path)
//   artifact  — an output file differs / is missing / is extra (file + JSON path or line)
//   result    — process_example()'s return value differs
//   error     — the TS pipeline threw before any comparable divergence
//
// Usage: npm run parity:runs [-- --case <substring>]... [--until <node>] [--fs node|memory]
//   --fs memory (PHASE3_PLAN.md WP27) runs the pipeline on a MemoryFS: the work
//   directory is a deterministic pseudo path (/tmp/evodesign-run-00000001),
//   evodesign/agentic_system is mounted read-only from the asset provider, the
//   repository config files the pipeline reads are seeded (MEMORY_SEED_FILES),
//   and artifacts are read back from memory. Nothing is written to disk.
//   --until stops comparing after the first snapshot of that node (workflow
//   phase or graph node name); artifacts/result are then not compared.
// Writes reports/runs.json.
//
// Pipeline contract (implemented by WP23 in src/agentic_system/main.ts):
//
//   export async function runRecordedPipeline(
//     input: RunInput,                         // fixtures/runs/<run>/input.json
//     options: {
//       chatModelFactory: (params: Record<string, unknown>, role: string | null) => BaseChatModel;
//       outputDir: string;                     // process_example()'s output_dir (fresh, empty)
//       datasetPath: string;                   // JSON file holding [input.item]
//       argv: string[];                        // input.argv with <OUT> resolved (CLI flags after `main`)
//       env: Record<string, string>;           // input.env: the environment the run used
//       rendererUrl: string;                   // Excalidraw renderer page (port 3001)
//     },
//   ): Promise<Record<string, unknown>>;      // process_example()'s return dict
//
// It must do what tools/record_runs.py worker() does in Python: parse_arguments
// (argv) → build_config → validate_config → load_dataset → determine_items →
// initialize_model / initialize_router_model (LLMFactory creating every model
// through options.chatModelFactory(init_chat_model kwargs in Python naming,
// LLMFactory role) instead of initChatModel) → process_example(…, outputDir).
// Snapshots are taken by test/harness/runs.ts instrumentSnapshots(): every
// LangGraph.js StateGraph node and the Text2DiagramWorkflow phase methods.
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, relative } from 'node:path';
import { AGENTIC_SYSTEM_ROOT, getAssetProvider } from '../src/py/assets.ts';
import { MemoryFS, setFS, type RuntimeFS } from '../src/py/fs.ts';
import { CassetteSession } from '../test/harness/cassette.ts';
import { compare } from '../test/harness/compare.ts';
import { PACKAGE_ROOT } from '../test/harness/fixtures.ts';
import {
  Normalizer, REPO_ROOT, RUNS, expectedValue, instrumentSnapshots, loadRun, pngInfo, setSnapshotSink, sha256, toPlain,
  type RecordedRun, type RunInput,
} from '../test/harness/runs.ts';

const DEFAULT_RENDER_URL = 'http://127.0.0.1:3001/renderers/excalidraw';
const ENTRY = join(PACKAGE_ROOT, 'src/agentic_system/main.ts');

interface Divergence {
  kind: 'llm' | 'snapshot' | 'artifact' | 'result' | 'error' | 'not_ported';
  where: string;
  diffs: string[];
}

interface RunReport {
  run: string;
  fs: 'node' | 'memory';
  ok: boolean;
  firstDivergence: Divergence | null;
  llm: { expected: number; matched: number; unverifiedCallers: number; toleratedImages: string[] };
  snapshots: { expected: number; matched: number };
  artifacts: { expected: number; matched: number } | null;
  until: string | null;
  seconds: number;
  /** --fs memory: files the run left in memory and paths it probed that did not exist (outside the work dir). */
  memory?: { files: number; misses: string[] };
}

type Pipeline = (input: RunInput, options: Record<string, unknown>) => Promise<Record<string, unknown>>;

const argv = process.argv.slice(2);
const options = (name: string) => argv.flatMap((arg, i) => (arg === `--${name}` && argv[i + 1] ? [argv[i + 1]] : []));
const caseFilters = options('case');
const until = options('until')[0] ?? null;
const fsMode = (options('fs')[0] ?? 'node') as 'node' | 'memory';
if (fsMode !== 'node' && fsMode !== 'memory') throw new Error(`--fs must be node or memory, got ${fsMode}`);
const rendererUrl = process.env.EXCALIDRAW_RENDER_URL ?? DEFAULT_RENDER_URL;

/**
 * Repository files outside evodesign/agentic_system that the pipeline reads
 * (config defaults; found with MemoryFS.misses). In the browser these come
 * from the caller instead (WP31); here they are copied in so the memory run
 * reads exactly what the disk run reads. Missing ones are skipped (the
 * pipeline then sees them missing, as on disk).
 */
const MEMORY_SEED_FILES = [
  'configs/settings.yaml',
  'configs/models.yaml',
  'evodesign/config/defaults/settings.yaml',
  'evodesign/config/defaults/models.yaml',
];

/** A fresh MemoryFS for one run (see --fs memory). */
function createMemoryFS(): MemoryFS {
  const memory = new MemoryFS({ cwd: '/workspace', tmpdir: '/tmp', homedir: '/home/user' });
  const assets = getAssetProvider();
  memory.mount(AGENTIC_SYSTEM_ROOT, {
    readText: (path) => assets.readText(path),
    exists: (path) => assets.exists(path),
    isDir: (path) => assets.isDir(path),
    list: (path) => assets.list(path),
  });
  const seed: Record<string, string> = {};
  for (const rel of MEMORY_SEED_FILES) {
    const file = join(REPO_ROOT, rel);
    if (existsSync(file)) seed[file] = readFileSync(file, 'utf-8');
  }
  memory.seed(seed);
  return memory;
}
if (rendererUrl.includes(':3000')) throw new Error('refusing to use the port-3000 renderer; use 3001');

const runNames = existsSync(RUNS)
  ? readdirSync(RUNS).filter((name) => !name.startsWith('_') && statSync(join(RUNS, name)).isDirectory()
      && existsSync(join(RUNS, name, 'cassette.jsonl')) && (!caseFilters.length || caseFilters.some((f) => name.includes(f)))).sort()
  : [];

let pipeline: Pipeline | null = null;
if (existsSync(ENTRY)) {
  const mod = (await import(ENTRY)) as { runRecordedPipeline?: Pipeline };
  pipeline = mod.runRecordedPipeline ?? null;
}
if (pipeline) await instrumentSnapshots();

const reports: RunReport[] = [];
for (const name of runNames) {
  const report = await replay(loadRun(name));
  reports.push(report);
  const first = report.firstDivergence;
  console.log(`${report.ok ? 'OK  ' : 'DIFF'} ${name}${first ? `  ${first.kind} @ ${first.where}: ${first.diffs[0] ?? ''}` : ''}`);
}

mkdirSync(join(PACKAGE_ROOT, 'reports'), { recursive: true });
writeFileSync(join(PACKAGE_ROOT, 'reports/runs.json'), JSON.stringify({ generated: new Date().toISOString(), until, runs: reports }, null, 1));
const ok = reports.filter((r) => r.ok).length;
console.log(`\n${ok}/${reports.length} runs replay identically${until ? ` up to ${until}` : ''}.`);
process.exitCode = ok === reports.length && reports.length > 0 ? 0 : 1;

async function replay(run: RecordedRun): Promise<RunReport> {
  const started = Date.now();
  const session = new CassetteSession(run.dir);
  const report: RunReport = {
    run: run.name, fs: fsMode, ok: false, firstDivergence: null,
    llm: { expected: session.entries.length, matched: 0, unverifiedCallers: 0, toleratedImages: [] },
    snapshots: { expected: run.snapshots.length, matched: 0 },
    artifacts: null, until, seconds: 0,
  };
  if (!pipeline) {
    report.firstDivergence = { kind: 'not_ported', where: 'src/agentic_system/main.ts', diffs: ['runRecordedPipeline is not exported yet'] };
    return report;
  }

  let clock = 0;
  session.clock = () => clock++;
  const memory = fsMode === 'memory' ? createMemoryFS() : null;
  const io: RunIO = memory ? memoryIO(memory) : nodeIO();
  const workDir = io.mkdtemp(join(io.tmpdir(), 'evodesign-run-'));
  const outputDir = join(workDir, 'out');
  io.mkdir(outputDir);
  const datasetPath = join(workDir, 'dataset.json');
  io.write(datasetPath, JSON.stringify([run.input.item], null, 2));
  if (memory) setFS(memory);
  const normalizer = new Normalizer(workDir);

  let snapshotDivergence: (Divergence & { order: number }) | null = null;
  let stopped = false;
  setSnapshotSink((scope, graph, node, value) => {
    if (snapshotDivergence || stopped) return;
    const index = report.snapshots.matched;
    const expected = run.snapshots[index];
    const where = `snapshot ${index} ${scope}:${node}`;
    if (!expected) {
      snapshotDivergence = { kind: 'snapshot', where, diffs: [`unexpected extra snapshot (Python recorded ${run.snapshots.length})`], order: clock++ };
      return;
    }
    if (expected.scope !== scope || expected.node !== node || (graph !== '<ts>' && graph !== expected.graph)) {
      snapshotDivergence = { kind: 'snapshot', where, diffs: [`expected ${expected.scope}:${expected.graph}:${expected.node}, got ${scope}:${graph}:${node}`], order: clock++ };
      return;
    }
    const result = compare(expectedValue(expected), normalizer.value(toPlain(value)));
    if (result.diffs.length) {
      snapshotDivergence = { kind: 'snapshot', where: `${where} (${expected.graph})`, diffs: result.diffs, order: clock++ };
      return;
    }
    report.snapshots.matched += 1;
    if (until && node === until) stopped = true;
  });

  let result: Record<string, unknown> | null = null;
  let thrown: unknown = null;
  try {
    result = await pipeline(run.input, {
      chatModelFactory: session.chatModelFactory(),
      outputDir,
      datasetPath,
      argv: run.input.argv.map((arg) => arg.split('<OUT>').join(workDir)),
      env: run.input.env,
      rendererUrl,
    });
  } catch (error) {
    thrown = error;
  } finally {
    setSnapshotSink(null);
    if (memory) setFS(null);
  }

  report.llm.matched = session.calls.length;
  report.llm.unverifiedCallers = session.unverifiedCallers;
  report.llm.toleratedImages = session.calls.flatMap((call) => call.tolerated);
  const mismatch = session.mismatch;
  const llmDivergence: (Divergence & { order: number }) | null = mismatch
    ? { kind: 'llm', where: `LLM call ${mismatch.call} (${mismatch.caller ?? '?'})`, diffs: mismatch.diffs, order: mismatch.order ?? 0 }
    : null;
  const candidates = [llmDivergence, snapshotDivergence].filter(Boolean) as (Divergence & { order: number })[];
  candidates.sort((a, b) => a.order - b.order);
  if (candidates.length) {
    const { order: _order, ...first } = candidates[0];
    report.firstDivergence = first;
  } else if (thrown && !stopped) {
    report.firstDivergence = { kind: 'error', where: 'pipeline', diffs: [String((thrown as Error)?.stack ?? thrown).split('\n').slice(0, 6).join(' | ')] };
  } else if (!stopped && report.snapshots.matched < run.snapshots.length) {
    const next = run.snapshots[report.snapshots.matched];
    report.firstDivergence = { kind: 'snapshot', where: `snapshot ${next.seq} ${next.scope}:${next.node}`, diffs: ['missing: the TS run ended before this snapshot'] };
  } else if (!stopped && session.calls.length < session.entries.length) {
    report.firstDivergence = { kind: 'llm', where: `LLM call ${session.calls.length}`, diffs: ['missing: the TS run made fewer LLM calls'] };
  } else if (!stopped) {
    const artifacts = compareArtifacts(run, outputDir, normalizer, io);
    report.artifacts = { expected: run.artifacts.length, matched: artifacts.matched };
    if (artifacts.divergence) report.firstDivergence = artifacts.divergence;
    else {
      const diff = compare(run.result.result, normalizer.value(toPlain(result)));
      if (diff.diffs.length) report.firstDivergence = { kind: 'result', where: 'process_example()', diffs: diff.diffs };
    }
  }
  report.ok = report.firstDivergence === null;
  report.seconds = (Date.now() - started) / 1000;
  if (memory) {
    report.memory = {
      files: memory.files(workDir).length,
      misses: [...memory.misses].filter((path) => !path.startsWith(workDir)).sort(),
    };
  }
  io.remove(workDir);
  return report;
}

function compareArtifacts(run: RecordedRun, outputDir: string, normalizer: Normalizer, io: RunIO): { matched: number; divergence: Divergence | null } {
  const produced = io.listFiles(outputDir);
  const expected = new Map(run.artifacts.map((entry) => [entry.path, entry]));
  let matched = 0;
  for (const entry of run.artifacts) {
    const file = join(outputDir, entry.path);
    if (!io.exists(file)) return { matched, divergence: { kind: 'artifact', where: entry.path, diffs: ['missing: the TS run did not write this file'] } };
    const actual = io.read(file);
    const recorded = join(run.dir, 'artifacts', entry.path);
    let diffs: string[] = [];
    if (entry.kind === 'json') {
      const want = JSON.parse(readFileSync(recorded, 'utf-8'));
      diffs = compare(want, normalizer.value(JSON.parse(actual.toString('utf-8')))).diffs;
    } else if (entry.kind === 'text') {
      diffs = lineDiff(readFileSync(recorded, 'utf-8'), normalizer.text(actual.toString('utf-8')));
    } else if (entry.kind === 'png') {
      if (sha256(actual) !== entry.sha256) {
        const info = pngInfo(actual);
        if (info.width !== entry.width || info.height !== entry.height) diffs = [`PNG size ${entry.width}x${entry.height} != ${info.width}x${info.height}`];
        else if (info.rgba_sha256 !== entry.rgba_sha256) diffs = ['PNG pixels differ (decoded RGBA)'];
      }
    } else if (sha256(actual) !== entry.sha256) {
      diffs = ['bytes differ'];
    }
    if (diffs.length) return { matched, divergence: { kind: 'artifact', where: entry.path, diffs } };
    matched += 1;
  }
  const extra = produced.filter((path) => !expected.has(path));
  if (extra.length) return { matched, divergence: { kind: 'artifact', where: extra[0], diffs: [`unexpected file(s): ${extra.join(', ')}`] } };
  return { matched, divergence: null };
}

function lineDiff(expected: string, actual: string): string[] {
  if (expected === actual) return [];
  const a = expected.split('\n');
  const b = actual.split('\n');
  for (let i = 0; i < Math.max(a.length, b.length); i += 1) {
    if (a[i] !== b[i]) return [`line ${i + 1}: expected ${JSON.stringify(a[i] ?? null)?.slice(0, 160)}, got ${JSON.stringify(b[i] ?? null)?.slice(0, 160)}`];
  }
  return ['text differs'];
}

function listFiles(root: string): string[] {
  const out: string[] = [];
  const walk = (dir: string) => {
    for (const name of readdirSync(dir)) {
      const path = join(dir, name);
      if (statSync(path).isDirectory()) walk(path);
      else out.push(relative(root, path).split('\\').join('/'));
    }
  };
  if (existsSync(root)) walk(root);
  return out.sort();
}

/** File access of the replay itself (where the work directory lives). */
interface RunIO {
  tmpdir(): string;
  mkdtemp(prefix: string): string;
  mkdir(path: string): void;
  write(path: string, text: string): void;
  exists(path: string): boolean;
  read(path: string): Buffer;
  listFiles(root: string): string[];
  remove(path: string): void;
}

/** Function declaration (hoisted): replay() runs from top-level await above. */
function nodeIO(): RunIO {
  return {
    tmpdir: () => tmpdir(),
    mkdtemp: (prefix) => mkdtempSync(prefix),
    mkdir: (path) => mkdirSync(path),
    write: (path, text) => writeFileSync(path, text),
    exists: (path) => existsSync(path),
    read: (path) => readFileSync(path),
    listFiles,
    remove: (path) => rmSync(path, { recursive: true, force: true }),
  };
}

function memoryIO(fs: MemoryFS): RunIO {
  const runtime: RuntimeFS = fs;
  return {
    tmpdir: () => runtime.tmpdir(),
    mkdtemp: (prefix) => runtime.mkdtemp(prefix),
    mkdir: (path) => runtime.mkdirp(path, { recursive: false }),
    write: (path, text) => runtime.writeText(path, text),
    exists: (path) => runtime.exists(path),
    read: (path) => Buffer.from(runtime.readBytes(path)),
    listFiles: (root) => fs.files(root).map((path) => relative(root, path)).sort(),
    remove: (path) => runtime.remove(path, { recursive: true, force: true }),
  };
}
