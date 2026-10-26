// Benchmark for getSnapshotDocSignature (frontend/src/utils/app.ts).
//
// Bundles the real module with esbuild and times it against the legacy
// full-JSON.stringify implementation (kept inline here verbatim as the
// "before" reference) on synthetic 500/1000-element Excalidraw scenes.
//
// Run: node scripts/bench-signature.mjs
import { execFileSync } from 'node:child_process';
import { performance } from 'node:perf_hooks';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const repoFrontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const esbuild = path.join(repoFrontend, 'node_modules', '.bin', 'esbuild');
const bundlePath = '/tmp/evo-app-utils-bundle.mjs';

execFileSync(
  esbuild,
  [
    path.join(repoFrontend, 'src', 'utils', 'app.ts'),
    '--bundle', '--format=esm', '--platform=neutral',
    `--outfile=${bundlePath}`, '--log-level=error',
    '--define:import.meta.env.DEV=false',
  ],
  { stdio: 'inherit' },
);
const { getSnapshotDocSignature } = await import(`${bundlePath}?t=${Date.now()}`);

// --- timing ------------------------------------------------------------------

// --- legacy implementation (verbatim copy of the pre-change behaviour) ------
const isObjectRecord = (value) => Boolean(value) && typeof value === 'object' && !Array.isArray(value);
const legacySignature = (snapshotLike) => {
  if (!snapshotLike || typeof snapshotLike !== 'object') return null;
  const payload = snapshotLike;
  if (Array.isArray(payload.elements)) {
    const appState = isObjectRecord(payload.appState) ? payload.appState : {};
    const files = isObjectRecord(payload.files) ? payload.files : {};
    const documentPart = {
      elements: payload.elements,
      files,
      appState: { viewBackgroundColor: appState.viewBackgroundColor ?? null },
    };
    try { return JSON.stringify(documentPart); } catch { return null; }
  }
  const document = isObjectRecord(payload.document) ? payload.document : null;
  const documentPart = (
    document && isObjectRecord(document.store)
      ? document.store
      : isObjectRecord(payload.store)
        ? payload.store
        : document && isObjectRecord(document.records)
          ? document.records
          : isObjectRecord(payload.records)
            ? payload.records
            : payload.document ?? payload
  );
  try { return JSON.stringify(documentPart); } catch { return null; }
};

// --- fixtures ---------------------------------------------------------------
const TEXT = 'The quick brown fox jumps over the lazy dog. '.repeat(3);
const makeElement = (i, version = 3) => ({
  id: `elem_${i.toString(36)}_${(i * 7919).toString(36)}`,
  type: i % 5 === 0 ? 'text' : 'rectangle',
  x: 40 + (i % 20) * 180, y: 40 + Math.floor(i / 20) * 120,
  width: 160, height: 90, angle: 0,
  strokeColor: '#1e293b', backgroundColor: i % 2 ? '#e0f2fe' : 'transparent',
  fillStyle: 'solid', strokeWidth: 2, strokeStyle: 'solid', roughness: 1, opacity: 100,
  groupIds: [], frameId: null, roundness: { type: 3 },
  seed: 100000 + i, version, versionNonce: (i * 2654435761) % 2147483647,
  index: `a${i.toString(36).padStart(4, '0')}`,
  isDeleted: false, boundElements: null, updated: 1757500000000 + i,
  link: null, locked: false,
  ...(i % 5 === 0
    ? { text: TEXT, fontSize: 16, fontFamily: 1, textAlign: 'left', verticalAlign: 'top', containerId: null, originalText: TEXT, lineHeight: 1.25 }
    : {}),
});
const makeScene = (n, fileCount = 10, fileKb = 1) => ({
  elements: Array.from({ length: n }, (_, i) => makeElement(i)),
  appState: { viewBackgroundColor: '#f5fbff', gridSize: null, selectedElementIds: {} },
  files: Object.fromEntries(Array.from({ length: fileCount }, (_, i) => [
    `file_${i}`,
    { mimeType: 'image/png', id: `file_${i}`, dataURL: `data:image/png;base64,${'QUJD'.repeat(Math.ceil(fileKb * 1024 / 4))}`, created: 1757500000000, lastRetrieved: 1757500000000 },
  ])),
});

// --- timing ------------------------------------------------------------------
const bench = (label, fn, scene, iterations) => {
  for (let i = 0; i < 20; i += 1) fn(scene); // warmup
  const samples = [];
  for (let i = 0; i < iterations; i += 1) {
    // Simulate the hot path: one element touched between computations.
    const el = scene.elements[i % scene.elements.length];
    el.version += 1; el.versionNonce = (el.versionNonce + 1) % 2147483647; el.updated += 1;
    const t0 = performance.now();
    fn(scene);
    samples.push(performance.now() - t0);
  }
  samples.sort((a, b) => a - b);
  const avg = samples.reduce((s, v) => s + v, 0) / samples.length;
  const p50 = samples[Math.floor(samples.length * 0.5)];
  const p95 = samples[Math.floor(samples.length * 0.95)];
  const max = samples[samples.length - 1];
  console.log(`${label.padEnd(46)} avg=${avg.toFixed(3)}ms p50=${p50.toFixed(3)}ms p95=${p95.toFixed(3)}ms max=${max.toFixed(3)}ms`);
  return { avg, p50, p95, max };
};

// --- correctness assertions for the current implementation -------------------
const clone = (o) => structuredClone(o);
const scene = makeScene(50);
const a = getSnapshotDocSignature(scene);
const b = getSnapshotDocSignature(clone(scene));
const bumped = clone(scene); bumped.elements[7].version += 1; bumped.elements[7].versionNonce += 1;
const moved = clone(scene); moved.elements[7].x += 10; moved.elements[7].version += 1; moved.elements[7].versionNonce += 1;
const reordered = clone(scene); [reordered.elements[0], reordered.elements[1]] = [reordered.elements[1], reordered.elements[0]];
const deleted = clone(scene); deleted.elements[3].isDeleted = true;
const bgChanged = clone(scene); bgChanged.appState.viewBackgroundColor = '#ffffff';
const fileAdded = clone(scene); fileAdded.files.file_x = { mimeType: 'image/png', id: 'file_x', dataURL: 'data:,x', created: 1, lastRetrieved: 1 };
const checks = {
  'identical scenes -> equal': a === b,
  'version bump -> different': a !== getSnapshotDocSignature(bumped),
  'content move (version bump) -> different': a !== getSnapshotDocSignature(moved),
  'reorder -> different': a !== getSnapshotDocSignature(reordered),
  'delete flag -> different': a !== getSnapshotDocSignature(deleted),
  'bg color -> different': a !== getSnapshotDocSignature(bgChanged),
  'file added -> different': a !== getSnapshotDocSignature(fileAdded),
  'non-object -> null': getSnapshotDocSignature(null) === null && getSnapshotDocSignature('x') === null,
};
let failed = 0;
for (const [name, ok] of Object.entries(checks)) {
  if (!ok) failed += 1;
  console.log(`  ${ok ? 'ok  ' : 'FAIL'} ${name}`);
}

// tldraw branch must keep working (full stringify of the store)
const tldrawScene = { document: { store: { 'shape:1': { id: 'shape:1', typeName: 'shape', x: 1 }, 'page:1': { id: 'page:1', typeName: 'page' } }, id: 'doc:1', storeVersion: 5 }, session: {}, schema: {} };
const t1 = getSnapshotDocSignature(tldrawScene);
const t2 = getSnapshotDocSignature(clone(tldrawScene));
const t3 = getSnapshotDocSignature({ ...clone(tldrawScene), document: { ...tldrawScene.document, store: { ...tldrawScene.document.store, 'shape:1': { id: 'shape:1', typeName: 'shape', x: 2 } } } });
console.log(`  ${t1 === t2 && t1 !== t3 ? 'ok  ' : 'FAIL'} tldraw store signature stable and content-sensitive`);
if (!(t1 === t2 && t1 !== t3)) failed += 1;

console.log('');
const ITER = 300;
const results = {};
const configs = [
  { label: '500 elements, 10x1KB files', scene: () => makeScene(500), key: '500' },
  { label: '1000 elements, 10x1KB files', scene: () => makeScene(1000), key: '1000' },
  { label: '2000 elements, 10x1KB files', scene: () => makeScene(2000), key: '2000' },
  { label: '500 elements, 4x700KB embedded images', scene: () => makeScene(500, 4, 700), key: '500img' },
];
for (const cfg of configs) {
  const probe = cfg.scene();
  console.log(`--- ${cfg.label} | documentPart ~${(legacySignature(probe)?.length / 1024).toFixed(0)}KB, ${ITER} iterations (one element mutated between calls) ---`);
  results[`legacy_${cfg.key}`] = bench(`legacy full JSON.stringify (${cfg.key})`, legacySignature, probe, ITER);
  results[`current_${cfg.key}`] = bench(`src/utils/app.ts current impl (${cfg.key})`, getSnapshotDocSignature, cfg.scene(), ITER);
  console.log('');
}

for (const cfg of configs) {
  const speedup = results[`legacy_${cfg.key}`].avg / results[`current_${cfg.key}`].avg;
  console.log(`${cfg.key}: current is ${speedup.toFixed(1)}x legacy (avg ${results[`legacy_${cfg.key}`].avg.toFixed(3)}ms -> ${results[`current_${cfg.key}`].avg.toFixed(3)}ms)`);
}

process.exit(failed > 0 ? 1 : 0);
