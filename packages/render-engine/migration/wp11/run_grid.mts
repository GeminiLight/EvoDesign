import { readFileSync } from 'node:fs';
const R = '/Users/zhanyi/Code/EvoDesign/packages/render-engine/';
const g = await import(R + 'src/render_engine/excalidraw/arrow_routing/grid_router.ts');
const cases = JSON.parse(readFileSync(process.argv[2], 'utf-8'));
let pass = 0, keyPass = 0, signDiff = 0; const fails: any[] = [];
for (const [i, c] of cases.entries()) {
  const r = g._find_orthogonal_visibility_route(...(c.args as [any, any, any, any, any, any]));
  const a = JSON.stringify(r), b = JSON.stringify(c.result);
  if (a === b) pass++; else fails.push({ i, py: b.slice(0, 200), ts: a.slice(0, 200) });
  // -0 check (JSON.stringify loses sign)
  const sgn = (v: any): string => JSON.stringify(v, (_k, x) => (Object.is(x, -0) ? '-0' : x));
  if (a === b && sgn(r) !== sgn(c.result)) signDiff++;
  if (g._route_memo_key(...(c.args as [any, any, any, any, any, any])) === c.key) keyPass++;
}
console.log({ total: cases.length, pass, keyPass, signDiff, fails: fails.slice(0, 5) });
