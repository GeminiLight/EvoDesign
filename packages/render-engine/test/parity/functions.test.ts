// Function-level parity: replay every recorded Python call against the TS port.
//
// For each module in migration/modules.json whose TS file exists, every
// fixtures/functions/<python module>/<function>.jsonl vector is bound with
// the shared calling convention (harness/fixtures.ts bindArguments) and the
// return value, the arguments after the call (in-place mutation) and raised
// exceptions are compared. Results land in reports/functions/<module>.json,
// which tools/ledger.ts turns into migration/LEDGER.md.
//
// Filter with PARITY_MODULE=<substring> (e.g. arrow_routing.geometry) or
// PARITY_WP=WP07. A module may declare per-function adapters or skips in
// test/adapters/<python module>.ts (see test/adapters/README.md).
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { compare } from '../harness/compare.ts';
import { installPytestFiles } from '../harness/pytest_files.ts';
import { PACKAGE_ROOT, bindArguments, listFunctionFixtures, loadVectors, signatureOf, type Vector } from '../harness/fixtures.ts';

interface ModuleEntry { python: string | null; ts: string; wp: string }
export interface Adapter {
  /** Reason this function is not replayed (counted as skipped in the ledger). */
  skip?: string;
  /** Rebuild TS arguments when the port's representation differs. */
  args?: (bound: unknown[], vector: Vector) => unknown[];
  /** Convert the TS result into the Python fixture's shape before comparing. */
  result?: (actual: unknown, vector: Vector) => unknown;
  /** Compare arguments after the call (default true). */
  checkMutation?: boolean;
  /** TS export name when it differs from the Python name (e.g. class methods). */
  exportName?: string;
}

const manifest = JSON.parse(readFileSync(join(PACKAGE_ROOT, 'migration/modules.json'), 'utf-8')) as { modules: ModuleEntry[] };
const moduleFilter = process.env.PARITY_MODULE;
const wpFilter = process.env.PARITY_WP;
const MAX_REPORTED_FAILURES = 5;

const selected = manifest.modules.filter((entry) =>
  entry.python
  && existsSync(join(PACKAGE_ROOT, entry.ts))
  && (!moduleFilter || entry.python.includes(moduleFilter))
  && (!wpFilter || entry.wp === wpFilter));

for (const entry of selected) {
  const pythonModule = entry.python!;
  describe(pythonModule, async () => {
    const mod = (await import(join(PACKAGE_ROOT, entry.ts))) as Record<string, unknown>;
    const adapterPath = join(PACKAGE_ROOT, 'test/adapters', `${pythonModule}.ts`);
    const adapters = existsSync(adapterPath)
      ? ((await import(adapterPath)).default as Record<string, Adapter>)
      : {};
    const report: Record<string, unknown> = {};

    for (const func of listFunctionFixtures(pythonModule)) {
      it(func, async () => {
        const adapter = adapters[func] ?? {};
        const vectors = loadVectors(pythonModule, func);
        const outcome = { vectors: vectors.length, passed: 0, failed: 0, skipped: 0, tolerated: 0, keyOrder: 0, failures: [] as unknown[], skip: adapter.skip ?? null, missing: false };
        report[func] = outcome;
        if (adapter.skip) {
          outcome.skipped = vectors.length;
          return;
        }
        const exportName = adapter.exportName ?? func;
        const fn = mod[exportName];
        const params = signatureOf(pythonModule, func);
        if (typeof fn !== 'function' || !params) {
          // Class methods (Class.method) need an adapter with exportName.
          outcome.missing = true;
          outcome.failed = vectors.length;
          expect.fail(`${entry.ts} does not export ${exportName}${params ? '' : ' (no Python signature)'}`);
        }
        for (const vector of vectors) {
          // Large vector groups can occupy the worker for over a minute.
          // Drain Vitest's status RPC replies between independent vectors.
          await yieldEventLoop();
          const restoreFiles = installPytestFiles(pythonModule, func, vector, vectors);
          try {
          const record = (problems: string[]) => {
            outcome.failed += 1;
            if (outcome.failures.length < MAX_REPORTED_FAILURES) {
              outcome.failures.push({ line: vector.line, source: vector.source, problems });
            }
          };
          let args = bindArguments(params!, vector);
          if (adapter.args) args = adapter.args(args, vector);
          let actual: unknown;
          try {
            actual = (fn as (...a: unknown[]) => unknown)(...args);
          } catch (error) {
            if (vector.raises) {
              outcome.passed += 1;
            } else {
              record([`threw ${(error as Error)?.stack?.split('\n').slice(0, 3).join(' | ') ?? String(error)}`]);
            }
            continue;
          }
          if (vector.raises) {
            record([`expected ${vector.raises}: ${vector.message}`]);
            continue;
          }
          const result = compare(vector.result, adapter.result ? adapter.result(actual, vector) : actual);
          const problems = result.diffs.map((d) => `result ${d}`);
          let tolerated = result.tolerated;
          if (adapter.checkMutation !== false && vector.args_after) {
            const mutated = compare(vector.args_after.slice(0, Math.min(vector.args_after.length, args.length)), args.slice(0, vector.args_after.length));
            problems.push(...mutated.diffs.map((d) => `args_after ${d}`));
            tolerated += mutated.tolerated;
          }
          if (problems.length) record(problems);
          else outcome.passed += 1;
          outcome.tolerated += tolerated;
          outcome.keyOrder += result.keyOrder.length;
          } finally { restoreFiles(); }
        }
        expect(outcome.failures, JSON.stringify(outcome.failures, null, 1).slice(0, 4000)).toEqual([]);
      });
    }

    it('_report', () => {
      const dir = join(PACKAGE_ROOT, 'reports/functions');
      mkdirSync(dir, { recursive: true });
      writeFileSync(join(dir, `${pythonModule}.json`), JSON.stringify({ module: pythonModule, ts: entry.ts, wp: entry.wp, functions: report }, null, 1));
    });
  });
}

if (!selected.length) {
  it('no ported modules selected', () => {
    expect(true).toBe(true);
  });
}
import { setImmediate as yieldEventLoop } from 'node:timers/promises';
