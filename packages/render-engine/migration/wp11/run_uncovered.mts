import { readFileSync } from 'node:fs';
const R = '/Users/zhanyi/Code/EvoDesign/packages/render-engine/';
const { compare } = await import(R + 'test/harness/compare.ts');
const er = await import(R + 'src/render_engine/shared/edge_routing.ts');
const nm = await import(R + 'src/render_engine/shared/normalization.ts');
const cv = await import(R + 'src/render_engine/excalidraw/converter.ts');
const fns: Record<string, (...a: any[]) => any> = {
  iter_concept_nodes: (h) => [...er.iter_concept_nodes(h)],
  resolve_label_from_node_ref: er.resolve_label_from_node_ref,
  normalize_text: er.normalize_text,
  iter_shape_id_candidates: (r) => [...er.iter_shape_id_candidates(r)],
  sort_and_reindex: nm.sort_and_reindex,
  'converter._extract_icon_dimension': cv._extract_icon_dimension,
  _svg_text_to_data_uri: cv._svg_text_to_data_uri,
  _icon_to_data_url: cv._icon_to_data_url,
};
const vecs = JSON.parse(readFileSync(process.argv[2], 'utf-8'));
let pass = 0; const fails: any[] = [];
vecs.forEach((v: any, i: number) => {
  let res: any, threw: any = null;
  try { res = fns[v.fn](...v.args); } catch (e) { threw = e; }
  if (v.raises) { if (threw) pass++; else fails.push({ i, fn: v.fn, args: v.args, why: 'expected raise ' + v.raises, got: res }); return; }
  if (threw) { fails.push({ i, fn: v.fn, args: v.args, why: 'threw ' + threw }); return; }
  const c = compare(v.result, res); const m = compare(v.args_after, v.args);
  if (c.diffs.length || m.diffs.length) fails.push({ i, fn: v.fn, args: JSON.stringify(v.args).slice(0, 200), diffs: [...c.diffs, ...m.diffs.map((d: string) => 'after ' + d)] });
  else pass++;
});
console.log(JSON.stringify({ total: vecs.length, pass, fails }, null, 1));
