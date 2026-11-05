// WP25 acceptance-review script (see migration/PHASE2_REPORT.md §3).
// For every phase-2 vector that recorded a Python exception, check that the TS
// port raises the same exception class name and message (the parity test only
// checks "raises or not").
import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { PACKAGE_ROOT, bindArguments, listFunctionFixtures, loadVectors, signatureOf } from '../../test/harness/fixtures.ts';
import type { Adapter } from '../../test/parity/functions.test.ts';
const P2 = new Set(['WP12', 'WP13', 'WP14', 'WP15', 'WP16', 'WP17', 'WP18', 'WP19', 'WP20', 'WP21', 'WP22', 'WP23']);
const modules = JSON.parse(readFileSync(join(PACKAGE_ROOT, 'migration/modules.json'), 'utf-8')).modules as { python: string | null; ts: string; wp: string }[];
let total = 0; let sameName = 0; let sameMessage = 0;
for (const entry of modules.filter((m) => m.python && P2.has(m.wp))) {
  const py = entry.python!;
  const funcs = listFunctionFixtures(py);
  if (!funcs.length) continue;
  const mod = (await import(join(PACKAGE_ROOT, entry.ts))) as Record<string, unknown>;
  const adapterPath = join(PACKAGE_ROOT, 'test/adapters', `${py}.ts`);
  const adapters = existsSync(adapterPath) ? ((await import(adapterPath)).default as Record<string, Adapter>) : {};
  for (const func of funcs) {
    const adapter = adapters[func] ?? {};
    if (adapter.skip) continue;
    const vectors = loadVectors(py, func).filter((v) => v.raises);
    if (!vectors.length) continue;
    const fn = mod[adapter.exportName ?? func] as (...a: unknown[]) => unknown;
    for (const vector of vectors) {
      total += 1;
      let args = bindArguments(signatureOf(py, func)!, vector);
      if (adapter.args) args = adapter.args(args, vector);
      let err: Error | null = null;
      try { fn(...args); } catch (e) { err = e as Error; }
      const name = err ? (err.constructor?.name === 'Error' ? err.name : err.constructor?.name) : '(no exception)';
      const okName = name === vector.raises || err?.name === vector.raises;
      const okMsg = !!err && (err.message === vector.message || String(err.message) === String(vector.message));
      if (okName) sameName += 1;
      if (okMsg) sameMessage += 1;
      if (!okName || !okMsg) console.log(`${okName ? 'MSG ' : 'TYPE'} ${py}/${func} line ${vector.line}: py ${vector.raises}: ${String(vector.message).slice(0, 110)} | ts ${name}: ${String(err?.message).slice(0, 110)}`);
    }
  }
}
console.log(`\n${total} exception vectors: same class ${sameName}, same message ${sameMessage}`);
