import { readFileSync } from 'node:fs';
const R = '/Users/zhanyi/Code/EvoDesign/packages/render-engine/';
const rc = await import(R + 'src/render_engine/excalidraw/radial_concept_compactor.ts');
const d = JSON.parse(readFileSync(process.argv[2], 'utf-8'));
const res: any = {};
for (const kind of ['branch', 'slots']) {
  let pass = 0; const fails: any[] = [];
  for (const c of d[kind]) {
    const inter = new Map(c.inter.map(([k, v]: any) => [k, v]));
    let out: any, threw: any = null;
    try { out = kind === 'branch' ? rc._best_branch_order(c.ids, inter) : Object.entries(rc._best_radial_slots(c.ids, inter)); } catch (e) { threw = e; }
    if (c.raises) { threw ? pass++ : fails.push({ c, out }); continue; }
    if (threw) { fails.push({ c, threw: String(threw) }); continue; }
    const same = JSON.stringify(out) === JSON.stringify(c.result);
    const sameUnordered = kind === 'slots' && JSON.stringify([...out].sort()) === JSON.stringify([...c.result].sort());
    if (same) pass++; else fails.push({ ids: c.ids, inter: c.inter, py: c.result, ts: out, sameContentDifferentKeyOrder: sameUnordered });
  }
  res[kind] = { total: d[kind].length, pass, fails: fails.slice(0, 3), nfail: fails.length };
}
let pp = 0;
for (const p of d.perms) if (JSON.stringify([...rc._permutations(p.pool, p.r ?? undefined)]) === JSON.stringify(p.result)) pp++;
res.perms = { total: d.perms.length, pass: pp };
console.log(JSON.stringify(res, null, 1));
