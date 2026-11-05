// WP25 acceptance-review script (see migration/PHASE2_REPORT.md §3).
// WP25 (acceptance review): replay extra Python-generated vectors that live
// outside fixtures/functions (so `npm run fixtures:phase2` never overwrites
// them). Same binding/compare rules and adapters as test/parity/functions.test.ts.
//
// Usage: npx tsx tools/wp25/run_vectors.ts [fixtures/wp25/vectors]
//   layout: <dir>/<python module>/<function>.jsonl
// Generators: tools/wp25/gen_fixers.py, tools/wp25/gen_loop.py (see migration/PHASE2_REPORT.md).
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { compare } from '../../test/harness/compare.ts';
import { PACKAGE_ROOT, bindArguments, decode, signatureOf, type Vector } from '../../test/harness/fixtures.ts';
import type { Adapter } from '../../test/parity/functions.test.ts';

const root = process.argv[2] ?? join(PACKAGE_ROOT, 'fixtures/wp25/vectors');
const modules = JSON.parse(readFileSync(join(PACKAGE_ROOT, 'migration/modules.json'), 'utf-8')).modules as { python: string | null; ts: string }[];
let total = 0;
let failed = 0;
for (const pythonModule of readdirSync(root).sort()) {
  const entry = modules.find((m) => m.python === pythonModule);
  if (!entry) throw new Error(`unknown module ${pythonModule}`);
  const mod = (await import(join(PACKAGE_ROOT, entry.ts))) as Record<string, unknown>;
  const adapterPath = join(PACKAGE_ROOT, 'test/adapters', `${pythonModule}.ts`);
  const adapters = existsSync(adapterPath) ? ((await import(adapterPath)).default as Record<string, Adapter>) : {};
  for (const file of readdirSync(join(root, pythonModule)).filter((f) => f.endsWith('.jsonl')).sort()) {
    const func = file.slice(0, -6);
    const adapter = adapters[func] ?? {};
    const fn = mod[adapter.exportName ?? func] as (...a: unknown[]) => unknown;
    const params = signatureOf(pythonModule, func)!;
    let ok = 0;
    const lines = readFileSync(join(root, pythonModule, file), 'utf-8').split('\n').filter(Boolean);
    lines.forEach((line, index) => {
      const raw = JSON.parse(line);
      const vector = { ...raw, args: decode(raw.args), kwargs: decode(raw.kwargs), result: 'result' in raw ? decode(raw.result) : undefined,
        args_after: raw.args_after && decode(raw.args_after), kwargs_after: raw.kwargs_after && decode(raw.kwargs_after), line: index + 1 } as Vector;
      let args = bindArguments(params, vector);
      if (adapter.args) args = adapter.args(args, vector);
      const problems: string[] = [];
      try {
        const actual = fn(...args);
        if (vector.raises) problems.push(`expected ${vector.raises}`);
        else problems.push(...compare(vector.result, adapter.result ? adapter.result(actual, vector) : actual).diffs);
        if (!vector.raises && adapter.checkMutation !== false && vector.args_after) {
          problems.push(...compare(vector.args_after, args.slice(0, vector.args_after.length)).diffs.map((d) => `args_after ${d}`));
        }
      } catch (error) {
        if (!vector.raises) problems.push(`threw ${String(error).slice(0, 200)}`);
      }
      if (problems.length) {
        failed += 1;
        if (failed <= 10) console.log(`FAIL ${pythonModule}/${func} line ${index + 1}: ${problems.slice(0, 3).join(' | ')}`);
      } else ok += 1;
    });
    total += lines.length;
    console.log(`${ok === lines.length ? 'OK  ' : 'DIFF'} ${pythonModule}/${func}: ${ok}/${lines.length}`);
  }
}
console.log(`\n${total - failed}/${total} extra vectors pass.`);
process.exitCode = failed ? 1 : 0;
