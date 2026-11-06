import { readFileSync } from 'node:fs';
const R = '/Users/zhanyi/Code/EvoDesign/packages/render-engine/';
const J = await import(R + 'src/py/json.ts');
const N = await import(R + 'src/py/number.ts');
const S = await import(R + 'src/py/str.ts');
const pf = (t: string) => t === 'nan' ? NaN : t === 'inf' ? Infinity : t === '-inf' ? -Infinity : Number(t);
const dec = (v: any): any => {
  if (Array.isArray(v)) return v.map(dec);
  if (v && typeof v === 'object') {
    if ('__f' in v) return new N.PyFloat(pf(v.__f));
    if ('__d' in v) return Object.fromEntries(v.__d.map(([k, x]: any) => [k, dec(x)]));
  }
  return v;
};
const decPlain = (v: any): any => { // floats as plain numbers (what the engine actually holds)
  if (Array.isArray(v)) return v.map(decPlain);
  if (v && typeof v === 'object') {
    if ('__f' in v) return pf(v.__f);
    if ('__d' in v) return Object.fromEntries(v.__d.map(([k, x]: any) => [k, decPlain(x)]));
  }
  return v;
};
const opts = [{ sortKeys: true, ensureAscii: false, default: S.pyStr }, {}, { ensureAscii: false, separators: [',', ':'] }, { sortKeys: true, indent: 2 }];
const data = JSON.parse(readFileSync(process.argv[2], 'utf-8'));
const fails: any[] = []; let pass = 0; let plainDiff: any[] = [];
for (const c of data.dumps) {
  let out: any; try { out = J.pyJsonDumps(dec(c.value), opts[c.opt]); } catch (e: any) { out = { raises: e.constructor.name }; }
  const ok = typeof c.out === 'string' ? out === c.out : (typeof out === 'object' && out.raises === c.out.raises);
  if (ok) pass++; else fails.push({ opt: c.opt, value: JSON.stringify(c.value).slice(0, 120), py: c.out, ts: out });
  if (typeof c.out === 'string') { try { const o2 = J.pyJsonDumps(decPlain(c.value), opts[c.opt]); if (o2 !== c.out) plainDiff.push({ py: c.out.slice(0, 80), ts: o2.slice(0, 80) }); } catch {} }
}
console.log('dumps', { total: data.dumps.length, pass, fails: fails.slice(0, 20) });
console.log('dumps with plain JS numbers (int/float ambiguity): differing', plainDiff.length, plainDiff.slice(0, 6));
let sp = 0; const sf: any[] = [];
for (const s of data.strs) {
  const v = dec(s.value); const a = S.pyStr(v), b = S.pyRepr(v);
  if (a === s.str && b === s.repr) sp++; else sf.push({ py: [s.str, s.repr], ts: [a, b] });
}
console.log('str/repr', { total: data.strs.length, pass: sp, fails: sf });
let rp = 0; const rf: any[] = [];
for (const r of data.round) {
  const x = pf(r.x); let got: string;
  try { const v = N.pyRound(x, r.n); got = r.isint ? String(v) : S.floatRepr(v); } catch (e: any) { got = 'threw ' + e; }
  if (got === r.r) rp++; else rf.push({ x: r.x, n: r.n, py: r.r, ts: got });
}
console.log('round', { total: data.round.length, pass: rp, fails: rf.slice(0, 10) });
