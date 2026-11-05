import { readFileSync } from 'node:fs';
const R = '/Users/zhanyi/Code/EvoDesign/packages/render-engine/';
const g = await import(R + 'src/render_engine/excalidraw/arrow_routing/grid_router.ts');
const cases = JSON.parse(readFileSync(process.argv[2], 'utf-8'));
const sgn = (v: any): string => JSON.stringify(v, (_k, x) => (Object.is(x, -0) ? '-0' : x));
let shown = 0;
for (const [i, c] of cases.entries()) {
  const r = g._find_orthogonal_visibility_route(...(c.args as [any, any, any, any, any, any]));
  if (sgn(r) !== sgn(c.result) && shown++ < 3) console.log(i, 'start', sgn(c.args[0]), 'end', sgn(c.args[1]), '\n py', sgn(c.result), '\n ts', sgn(r));
}
