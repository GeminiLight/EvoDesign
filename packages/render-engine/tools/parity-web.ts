// Web-run parity (PHASE3_PLAN.md WP26): compare the TS web runtime with the
// backend's streaming endpoint recorded in fixtures/web_runs/<case>/
// (tools/record_web_runs.py), and report each case's FIRST divergence:
//   llm     — LLM call N: the TS request differs from cassette entry N (JSON path)
//   event   — SSE event k: name, payload path (events[k].data.…), key order, or
//             its position relative to the LLM calls (events[k].llm_calls)
//   result  — the terminal payloads differ (result.result.… / result.error.…)
//   error   — the TS runtime threw before any comparable divergence
//   not_ported — src/web_runtime/index.ts does not export streamDiagram yet
//
// Usage:
//   npm run parity:web [-- --case <substring>]...
//       run the TS web runtime on every case (cassette replay) → reports/web_runs.json
//   npm run parity:web -- --expected <case dir> --actual <case dir>
//       offline: compare two recorded case directories (cassette requests,
//       events, result), e.g. a deliberately altered copy against the fixture
//       or a Python replay against the fixture. Exit code 1 on divergence.
//   npm run parity:web -- --self-check
//       offline: every fixture against itself (all must be identical).
//
// Runtime contract (implemented by WP29 in src/web_runtime/index.ts):
//
//   export async function streamDiagram(
//     request: Record<string, unknown>,        // input.request: the HTTP JSON body
//     options: {
//       chatModelFactory: (params: Record<string, unknown>, role: string | null) => BaseChatModel;
//       onEvent: (name: string, payload: Record<string, unknown>) => void;  // SSE event sequence
//       settings: Record<string, unknown>;     // input.settings (backend Settings fields; results_dir resolved)
//       engine: Record<string, unknown>;       // input.engine: Text2DiagramWorkflow overrides (mode, enable_critic)
//       env: Record<string, string>;           // input.env (role-model LLM_* config, renderer URL)
//       rendererUrl: string;                   // Node renderer page for parity (port 3001)
//       resultsDir: string;                    // backend results_dir (fresh temp dir per case)
//       signal?: AbortSignal;
//     },
//   ): Promise<Record<string, unknown> | null>;  // the result event payload (null when the stream ended with error)
//
// Every model the runtime creates (LLMFactory.create / create_for_role) must
// come from options.chatModelFactory with Python init_chat_model parameter
// names, as in parity:runs. WP29 may extend the options (fs, renderer); this
// harness is the place to wire them.
import { existsSync, mkdirSync, mkdtempSync, readdirSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pyDeepcopy } from '../src/py/float_marks.ts';
import { CassetteSession } from '../test/harness/cassette.ts';
import { PACKAGE_ROOT } from '../test/harness/fixtures.ts';
import {
  WEB_RUNS, WebNormalizer, compareEvent, compareRecorded, compareResult, loadWebRun,
  type ActualEvent, type RecordedWebRun, type WebDivergence,
} from '../test/harness/web_runs.ts';

const DEFAULT_RENDER_URL = 'http://127.0.0.1:3001/renderers/excalidraw';
const ENTRY = join(PACKAGE_ROOT, 'src/web_runtime/index.ts');

type StreamDiagram = (request: Record<string, unknown>, options: Record<string, unknown>) => Promise<Record<string, unknown> | null>;

interface CaseReport {
  case: string;
  ok: boolean;
  firstDivergence: WebDivergence | null;
  llm: { expected: number; matched: number; unverifiedCallers: number; toleratedImages: string[] };
  events: { expected: number; matched: number };
  seconds: number;
}

const argv = process.argv.slice(2);
const options = (name: string) => argv.flatMap((arg, i) => (arg === `--${name}` && argv[i + 1] ? [argv[i + 1]] : []));
const flag = (name: string) => argv.includes(`--${name}`);

if (options('actual').length || options('expected').length) {
  process.exitCode = offline(options('expected')[0], options('actual')[0]);
} else if (flag('self-check')) {
  let failures = 0;
  for (const name of caseNames([])) {
    const run = loadWebRun(name);
    const divergence = compareRecorded(run, run);
    if (divergence) failures += 1;
    console.log(`${divergence ? 'DIFF' : 'OK  '} ${name}${divergence ? `  ${describe(divergence)}` : ''}`);
  }
  process.exitCode = failures ? 1 : 0;
} else {
  process.exitCode = await live(options('case'));
}

function caseNames(filters: string[]): string[] {
  if (!existsSync(WEB_RUNS)) return [];
  return readdirSync(WEB_RUNS)
    .filter((name) => !name.startsWith('_') && statSync(join(WEB_RUNS, name)).isDirectory() && existsSync(join(WEB_RUNS, name, 'events.jsonl')))
    .filter((name) => !filters.length || filters.some((f) => name.includes(f)))
    .sort();
}

function describe(divergence: WebDivergence): string {
  return `${divergence.kind} @ ${divergence.where}: ${divergence.diffs[0] ?? ''}`;
}

function offline(expectedDir: string | undefined, actualDir: string | undefined): number {
  if (!expectedDir || !actualDir) {
    console.error('usage: parity:web -- --expected <case dir> --actual <case dir>');
    return 2;
  }
  const expected = loadWebRun(expectedDir);
  const actual = loadWebRun(actualDir);
  const divergence = compareRecorded(expected, actual);
  if (!divergence) {
    console.log(`OK   ${expected.name}: ${expected.cassette.length} LLM calls, ${expected.events.length} events and the result are identical`);
    return 0;
  }
  console.log(`DIFF ${expected.name}  first divergence: ${divergence.kind} @ ${divergence.where}`);
  for (const diff of divergence.diffs) console.log(`     ${diff}`);
  return 1;
}

async function live(filters: string[]): Promise<number> {
  const rendererUrl = process.env.EXCALIDRAW_RENDER_URL ?? DEFAULT_RENDER_URL;
  if (rendererUrl.includes(':3000')) throw new Error('refusing to use the port-3000 renderer; use 3001');
  let streamDiagram: StreamDiagram | null = null;
  if (existsSync(ENTRY)) {
    const mod = (await import(ENTRY)) as { streamDiagram?: StreamDiagram };
    streamDiagram = mod.streamDiagram ?? null;
  }
  const reports: CaseReport[] = [];
  for (const name of caseNames(filters)) {
    const report = await replay(loadWebRun(name), streamDiagram, rendererUrl);
    reports.push(report);
    const first = report.firstDivergence;
    console.log(`${report.ok ? 'OK  ' : 'DIFF'} ${name}${first ? `  ${describe(first)}` : ''}`);
  }
  mkdirSync(join(PACKAGE_ROOT, 'reports'), { recursive: true });
  writeFileSync(join(PACKAGE_ROOT, 'reports/web_runs.json'), JSON.stringify({ generated: new Date().toISOString(), cases: reports }, null, 1));
  const ok = reports.filter((r) => r.ok).length;
  console.log(`\n${ok}/${reports.length} web runs replay identically.`);
  return ok === reports.length && reports.length > 0 ? 0 : 1;
}

async function replay(run: RecordedWebRun, streamDiagram: StreamDiagram | null, rendererUrl: string): Promise<CaseReport> {
  const started = Date.now();
  const session = new CassetteSession(run.dir, run.cassette);
  const report: CaseReport = {
    case: run.name, ok: false, firstDivergence: null,
    llm: { expected: run.cassette.length, matched: 0, unverifiedCallers: 0, toleratedImages: [] },
    events: { expected: run.events.length, matched: 0 },
    seconds: 0,
  };
  if (!streamDiagram) {
    report.firstDivergence = { kind: 'not_ported', where: 'src/web_runtime/index.ts', diffs: ['streamDiagram is not exported yet'] };
    return report;
  }

  let clock = 0;
  session.clock = () => clock++;
  const workDir = mkdtempSync(join(tmpdir(), 'evodesign-web-'));
  const resultsDir = join(workDir, 'results');
  const normalizer = new WebNormalizer(workDir);
  const actualEvents: ActualEvent[] = [];
  let eventDivergence: (WebDivergence & { order: number }) | null = null;
  const onEvent = (name: string, payload: Record<string, unknown>) => {
    const index = actualEvents.length;
    const actual: ActualEvent = { event: name, data: normalizer.value(JSON.parse(JSON.stringify(payload))), llm_calls: session.calls.length };
    actualEvents.push(actual);
    if (eventDivergence) return;
    const diffs = compareEvent(run.events[index], actual, index);
    if (diffs.length) eventDivergence = { kind: 'event', where: `events[${index}] (${run.events[index]?.event ?? name})`, diffs, order: clock++ };
    else report.events.matched += 1;
  };

  const settings = { ...run.input.settings, results_dir: resultsDir };
  let result: Record<string, unknown> | null = null;
  let thrown: unknown = null;
  try {
    result = await streamDiagram(pyDeepcopy(run.input.request), {
      chatModelFactory: session.chatModelFactory(),
      onEvent,
      settings,
      engine: run.input.engine,
      env: run.input.env,
      rendererUrl,
      resultsDir,
    });
  } catch (error) {
    thrown = error;
  }

  report.llm.matched = session.calls.length;
  report.llm.unverifiedCallers = session.unverifiedCallers;
  report.llm.toleratedImages = session.calls.flatMap((call) => call.tolerated);
  const mismatch = session.mismatch;
  const llmDivergence = mismatch
    ? { kind: 'llm' as const, where: `LLM call ${mismatch.call} (${mismatch.caller ?? '?'})`, diffs: mismatch.diffs, order: mismatch.order ?? 0 }
    : null;
  const candidates = [llmDivergence, eventDivergence].filter(Boolean) as (WebDivergence & { order: number })[];
  candidates.sort((a, b) => a.order - b.order);
  if (candidates.length) {
    const { order: _order, ...first } = candidates[0];
    report.firstDivergence = first;
  } else if (thrown) {
    report.firstDivergence = { kind: 'error', where: 'streamDiagram', diffs: [String((thrown as Error)?.stack ?? thrown).split('\n').slice(0, 6).join(' | ')] };
  } else if (actualEvents.length < run.events.length) {
    const index = actualEvents.length;
    report.firstDivergence = { kind: 'event', where: `events[${index}] (${run.events[index].event})`, diffs: compareEvent(run.events[index], undefined, index) };
  } else if (session.calls.length < session.entries.length) {
    report.firstDivergence = { kind: 'llm', where: `LLM call ${session.calls.length}`, diffs: ['missing: the TS run made fewer LLM calls'] };
  } else {
    const terminal = actualEvents.find((event) => event.event === 'error')?.data ?? null;
    const actual = { result: result === null ? null : (normalizer.value(JSON.parse(JSON.stringify(result))) as Record<string, unknown>), error: terminal as Record<string, unknown> | null };
    const diffs = compareResult(run.result, actual);
    if (diffs.length) report.firstDivergence = { kind: 'result', where: 'return value', diffs };
  }
  report.ok = report.firstDivergence === null;
  report.seconds = (Date.now() - started) / 1000;
  rmSync(workDir, { recursive: true, force: true });
  return report;
}
