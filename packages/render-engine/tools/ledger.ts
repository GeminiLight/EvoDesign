// Render migration/LEDGER.md: per work package and module, what is ported and
// how many recorded Python calls it reproduces. Inputs: migration/modules.json,
// reports/functions/*.json (npm run parity), reports/stages.json
// (npm run parity:stages) and migration/notes/<WP>.md.
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { PACKAGE_ROOT, listFunctionFixtures } from '../test/harness/fixtures.ts';

interface ModuleEntry { python: string | null; source?: string; ts: string; wp: string }
interface FunctionOutcome { vectors: number; passed: number; failed: number; skipped: number; tolerated: number; skip: string | null; missing: boolean }

const plan = JSON.parse(readFileSync(join(PACKAGE_ROOT, 'migration/modules.json'), 'utf-8')) as {
  work_packages: { id: string; title: string; depends_on: string[] }[];
  modules: ModuleEntry[];
};

const lines: string[] = ['# Migration ledger', '', `Generated ${new Date().toISOString()} by \`npm run ledger\`. Do not edit by hand.`, ''];
lines.push('| WP | Module | TS file | Ported | Functions | Vectors passed | Failed | Skipped | Tolerated |');
lines.push('|---|---|---|---|---|---|---|---|---|');
const totals = { vectors: 0, passed: 0, failed: 0, skipped: 0 };
for (const entry of plan.modules) {
  const ported = existsSync(join(PACKAGE_ROOT, entry.ts));
  if (!entry.python) {
    lines.push(`| ${entry.wp} | (runtime helpers) | \`${entry.ts}\` | ${ported ? 'yes' : 'no'} | | | | | |`);
    continue;
  }
  const reportPath = join(PACKAGE_ROOT, 'reports/functions', `${entry.python}.json`);
  const functions = listFunctionFixtures(entry.python);
  let row = { vectors: 0, passed: 0, failed: 0, skipped: 0, tolerated: 0 };
  if (existsSync(reportPath)) {
    const report = JSON.parse(readFileSync(reportPath, 'utf-8')) as { functions: Record<string, FunctionOutcome> };
    for (const outcome of Object.values(report.functions)) {
      row = {
        vectors: row.vectors + outcome.vectors,
        passed: row.passed + outcome.passed,
        failed: row.failed + outcome.failed,
        skipped: row.skipped + outcome.skipped,
        tolerated: row.tolerated + outcome.tolerated,
      };
    }
  }
  totals.vectors += row.vectors;
  totals.passed += row.passed;
  totals.failed += row.failed;
  totals.skipped += row.skipped;
  const name = entry.python.replace('evodesign.agentic_system.', '');
  lines.push(`| ${entry.wp} | \`${name}\` | \`${entry.ts}\` | ${ported ? 'yes' : 'no'} | ${functions.length} | ${row.passed}/${row.vectors} | ${row.failed} | ${row.skipped} | ${row.tolerated} |`);
}
lines.push('', `**Total** vectors passed ${totals.passed}/${totals.vectors}, failed ${totals.failed}, skipped ${totals.skipped}.`, '');

const stagesPath = join(PACKAGE_ROOT, 'reports/stages.json');
if (existsSync(stagesPath)) {
  const stages = JSON.parse(readFileSync(stagesPath, 'utf-8')) as { cases: { case: string; ok: boolean; firstDivergence?: { node: string; diffs: string[] } }[] };
  const ok = stages.cases.filter((c) => c.ok).length;
  lines.push('## Stage parity', '', `${ok}/${stages.cases.length} example cases reproduce every workflow snapshot.`, '');
  const byNode = new Map<string, string[]>();
  for (const c of stages.cases.filter((item) => !item.ok)) {
    const node = c.firstDivergence?.node ?? '(error)';
    byNode.set(node, [...(byNode.get(node) ?? []), c.case]);
  }
  for (const [node, cases] of byNode) lines.push(`- first divergence at \`${node}\`: ${cases.length} case(s), e.g. ${cases.slice(0, 3).join(', ')}`);
  lines.push('');
}

// Phase 2: end-to-end replay of the recorded Python runs (npm run parity:runs).
const runsIndexPath = join(PACKAGE_ROOT, 'fixtures/runs/_index.json');
const runsReportPath = join(PACKAGE_ROOT, 'reports/runs.json');
if (existsSync(runsIndexPath) || existsSync(runsReportPath)) {
  lines.push('## End-to-end runs (phase 2)', '');
  const recorded = existsSync(runsIndexPath)
    ? (JSON.parse(readFileSync(runsIndexPath, 'utf-8')) as { run: string; ok: boolean; llm_calls?: number; snapshots?: number; artifacts?: number }[])
    : [];
  if (recorded.length) {
    const calls = recorded.reduce((sum, r) => sum + (r.llm_calls ?? 0), 0);
    lines.push(`Recorded: ${recorded.length} runs (${recorded.filter((r) => r.ok).length} recorded twice identically), ${calls} LLM calls in cassettes.`, '');
  }
  if (existsSync(runsReportPath)) {
    const report = JSON.parse(readFileSync(runsReportPath, 'utf-8')) as {
      generated: string; until: string | null;
      runs: { run: string; ok: boolean; firstDivergence: { kind: string; where: string; diffs: string[] } | null; llm: { expected: number; matched: number }; snapshots: { expected: number; matched: number } }[];
    };
    const ok = report.runs.filter((r) => r.ok).length;
    lines.push(`Replay (${report.generated}${report.until ? `, --until ${report.until}` : ''}): **${ok}/${report.runs.length}** runs identical.`, '');
    lines.push('| Run | OK | LLM calls matched | Snapshots matched | First divergence |');
    lines.push('|---|---|---|---|---|');
    for (const r of report.runs) {
      const first = r.firstDivergence ? `${r.firstDivergence.kind} @ ${r.firstDivergence.where}: ${(r.firstDivergence.diffs[0] ?? '').replace(/\|/g, '\\|').slice(0, 140)}` : '';
      lines.push(`| ${r.run} | ${r.ok ? 'yes' : 'no'} | ${r.llm.matched}/${r.llm.expected} | ${r.snapshots.matched}/${r.snapshots.expected} | ${first} |`);
    }
    lines.push('');
  } else {
    lines.push('No replay report yet (`npm run parity:runs`).', '');
  }
}

lines.push('## Work package notes', '');
for (const wp of plan.work_packages) {
  const notes = join(PACKAGE_ROOT, 'migration/notes', `${wp.id}.md`);
  lines.push(`- ${wp.id} ${wp.title}: ${existsSync(notes) ? `[notes](notes/${wp.id}.md)` : 'no notes yet'}`);
}
writeFileSync(join(PACKAGE_ROOT, 'migration/LEDGER.md'), `${lines.join('\n')}\n`);
console.log(`ledger: ${totals.passed}/${totals.vectors} vectors passed, ${totals.failed} failed, ${totals.skipped} skipped`);
