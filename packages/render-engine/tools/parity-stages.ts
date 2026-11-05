// Stage-level parity: run the TS Excalidraw workflow node by node on every
// fixtures/stages/<case>.json and compare each node's snapshot with Python's.
//
// Two modes per case, both reported:
//   chained  — TS output of node N feeds node N+1 (what production does).
//   isolated — node N starts from Python's snapshot N-1, so a divergence is
//              attributed to exactly one node even when an earlier one drifts.
//
// Usage: npm run parity:stages [-- --case <substring>] [--node <name>]
// Writes reports/stages.json; prints the first divergence per case.
import { mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { compare } from '../test/harness/compare.ts';
import { FIXTURES, PACKAGE_ROOT } from '../test/harness/fixtures.ts';

interface Snapshot { node: string; layout_instantiation: unknown; diagram_manifest: unknown; validation_report: unknown }
interface StageCase { case: string; input: Record<string, unknown>; snapshots: Snapshot[]; error: unknown }

// Contract with src/render_engine/workflow.ts (WP10).
interface WorkflowModule {
  createWorkflowState(input: Record<string, unknown>): Record<string, unknown>;
  excalidrawNodes(): [string, (state: Record<string, unknown>) => Record<string, unknown>][];
}

const argv = process.argv.slice(2);
const option = (name: string) => {
  const index = argv.indexOf(`--${name}`);
  return index >= 0 ? argv[index + 1] : undefined;
};
const caseFilter = option('case');
const nodeFilter = option('node');

const workflow = (await import(join(PACKAGE_ROOT, 'src/render_engine/workflow.ts'))) as WorkflowModule;
const dir = join(FIXTURES, 'stages');
const files = readdirSync(dir).filter((name) => name.endsWith('.json') && !name.startsWith('_') && (!caseFilter || name.includes(caseFilter)));

function snapshotOf(state: Record<string, unknown>, node: string) {
  return {
    node,
    layout_instantiation: state.layout_instantiation,
    diagram_manifest: state.diagram_manifest,
    validation_report: state.validation_report ?? null,
  };
}

function diffSnapshot(expected: Snapshot, actual: ReturnType<typeof snapshotOf>) {
  const result = compare(
    { layout_instantiation: expected.layout_instantiation, diagram_manifest: expected.diagram_manifest, validation_report: expected.validation_report },
    { layout_instantiation: actual.layout_instantiation, diagram_manifest: actual.diagram_manifest, validation_report: actual.validation_report },
  );
  return result;
}

const results = [];
for (const file of files) {
  const fixture = JSON.parse(readFileSync(join(dir, file), 'utf-8')) as StageCase;
  const nodes = workflow.excalidrawNodes();
  const caseResult: Record<string, unknown> = { case: fixture.case, ok: true, isolated: [] as unknown[] };

  // Chained run.
  let state = workflow.createWorkflowState(structuredClone(fixture.input));
  for (const [index, [node, run]] of nodes.entries()) {
    const expected = fixture.snapshots[index];
    if (!expected) break;
    try {
      state = run(state);
    } catch (error) {
      caseResult.ok = false;
      caseResult.firstDivergence = { node, diffs: [`threw ${(error as Error).stack?.split('\n').slice(0, 4).join(' | ')}`] };
      break;
    }
    const diff = diffSnapshot(expected, snapshotOf(state, node));
    if (diff.diffs.length) {
      caseResult.ok = false;
      caseResult.firstDivergence = { node, diffs: diff.diffs };
      break;
    }
  }
  if (fixture.error && caseResult.ok) {
    caseResult.note = `Python raised at ${(fixture.error as { node: string }).node}`;
  }

  // Isolated runs: node N from Python's snapshot N-1.
  for (const [index, [node, run]] of nodes.entries()) {
    if (nodeFilter && node !== nodeFilter) continue;
    const expected = fixture.snapshots[index];
    if (!expected) break;
    const previous = index === 0 ? null : fixture.snapshots[index - 1];
    const seeded = workflow.createWorkflowState(structuredClone(fixture.input));
    if (previous) {
      seeded.layout_instantiation = structuredClone(previous.layout_instantiation);
      seeded.diagram_manifest = structuredClone(previous.diagram_manifest);
    }
    let outcome: { node: string; ok: boolean; diffs: string[] };
    try {
      const diff = diffSnapshot(expected, snapshotOf(run(seeded), node));
      outcome = { node, ok: diff.diffs.length === 0, diffs: diff.diffs };
    } catch (error) {
      outcome = { node, ok: false, diffs: [`threw ${(error as Error).stack?.split('\n').slice(0, 4).join(' | ')}`] };
    }
    (caseResult.isolated as unknown[]).push(outcome);
  }
  results.push(caseResult);
  const failedIsolated = (caseResult.isolated as { ok: boolean; node: string }[]).filter((item) => !item.ok).map((item) => item.node);
  const first = caseResult.firstDivergence as { node: string; diffs: string[] } | undefined;
  console.log(`${caseResult.ok ? 'OK  ' : 'DIFF'} ${fixture.case}${first ? `  chained→${first.node}: ${first.diffs[0]}` : ''}${failedIsolated.length ? `  isolated✗ ${failedIsolated.join(',')}` : ''}`);
}

mkdirSync(join(PACKAGE_ROOT, 'reports'), { recursive: true });
writeFileSync(join(PACKAGE_ROOT, 'reports/stages.json'), JSON.stringify({ cases: results }, null, 1));
const ok = results.filter((item) => item.ok).length;
console.log(`\n${ok}/${results.length} cases reproduce every snapshot (chained).`);
process.exitCode = ok === results.length ? 0 : 1;
