/// <reference lib="dom" />
/// <reference lib="dom.iterable" />
// WP28 renderer parity (PHASE3_PLAN.md WP28): the in-browser renderer
// (frontend/src/services/browser/pipelineRenderer.ts) against the renderer
// service page (http://127.0.0.1:3001/renderers/excalidraw driven by playwright).
//
// For every fixtures/stages/<case>.json the final manifest (last snapshot) is
// rendered through the pipeline's own entry point, ExcalidrawRender.render:
//   * service:  no PngRenderer installed -> platform default (playwright page);
//   * browser:  a PngRenderer that forwards to the frontend test page
//               frontend/test-pages/pipeline-renderer.html (served by Vite),
//               where pipelineRenderer.render runs exportToBlob.
// Two modes per case: product (default scale, margin 40, crop=False so the raw
// export is compared, then smart_crop padding 60 is applied to both files) and
// analysis (render_scale 1.0, crop=False).
//
// Threshold (migration/notes/WP28.md): sizes equal and the share of pixels
// whose largest channel difference exceeds 16 is <= 0.5%. smart_crop must
// return the same message (same crop box and size) on both files, and the
// cropped images must meet the same threshold.
//
// Usage: npm run parity:render [-- --case <substring>] [--modes product,analysis]
//        [--concurrency 4] [--frontend-url http://127.0.0.1:5179] [--keep]
// Output: reports/wp28/<case>/<mode>.{service,browser}.png (+ .crop.png),
//         reports/wp28/summary.json
import { spawn, type ChildProcess } from 'node:child_process';
import { copyFileSync, existsSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { chromium, type Page } from 'playwright';
import { PNG } from 'pngjs';
import { FIXTURES, PACKAGE_ROOT } from '../../test/harness/fixtures.ts';
import { ExcalidrawRender } from '../../src/render_engine/canvas_render.ts';
import { smart_crop } from '../../src/render_engine/shared/image_cropper.ts';
import { pngSize, withPngRenderer, type PngRenderRequest, type PngRenderer, type PngRenderResult } from '../../src/render_engine/png_renderer.ts';

const REPO = resolve(PACKAGE_ROOT, '../..');
const FRONTEND = join(REPO, 'frontend');
const OUT = join(PACKAGE_ROOT, 'reports/wp28');
const RENDER_URL = process.env.EXCALIDRAW_RENDER_URL ?? 'http://127.0.0.1:3001/renderers/excalidraw';
const PIXEL_DIFF = 16;
const MAX_RATIO = 0.005;

const argv = process.argv.slice(2);
const option = (name: string) => {
  const index = argv.indexOf(`--${name}`);
  return index >= 0 ? argv[index + 1] : undefined;
};
const caseFilter = option('case');
const modes = (option('modes') ?? 'product,analysis').split(',') as Mode[];
const concurrency = Number(option('concurrency') ?? 4);
let frontendUrl = option('frontend-url');

type Mode = 'product' | 'analysis';
interface PixelDiff { sameSize: boolean; sizeA: [number, number]; sizeB: [number, number]; identicalBytes: boolean; identicalPixels: boolean; over: number; ratio: number; maxDiff: number; pass: boolean }
interface CaseResult {
  case: string; mode: Mode; error?: string;
  raw?: PixelDiff; crop?: { serviceMessage: string; browserMessage: string; agree: boolean; diff: PixelDiff | null };
  warnings?: { service: string[]; browser: string[] };
}

function diffPng(a: Uint8Array, b: Uint8Array): PixelDiff {
  const pa = PNG.sync.read(Buffer.from(a));
  const pb = PNG.sync.read(Buffer.from(b));
  const sizeA: [number, number] = [pa.width, pa.height];
  const sizeB: [number, number] = [pb.width, pb.height];
  const identicalBytes = Buffer.compare(Buffer.from(a), Buffer.from(b)) === 0;
  if (pa.width !== pb.width || pa.height !== pb.height) {
    return { sameSize: false, sizeA, sizeB, identicalBytes, identicalPixels: false, over: -1, ratio: 1, maxDiff: 255, pass: false };
  }
  let over = 0;
  let maxDiff = 0;
  let identicalPixels = true;
  for (let i = 0; i < pa.data.length; i += 4) {
    let d = 0;
    for (let c = 0; c < 4; c += 1) d = Math.max(d, Math.abs(pa.data[i + c] - pb.data[i + c]));
    if (d > 0) identicalPixels = false;
    if (d > maxDiff) maxDiff = d;
    if (d > PIXEL_DIFF) over += 1;
  }
  const ratio = over / (pa.width * pa.height);
  return { sameSize: true, sizeA, sizeB, identicalBytes, identicalPixels, over, ratio, maxDiff, pass: ratio <= MAX_RATIO };
}

/** PngRenderer that runs pipelineRenderer inside the frontend test page. */
class FrontendPageRenderer implements PngRenderer {
  readonly name = 'browser-export (frontend test page)';
  lastWarnings: string[] = [];
  constructor(private readonly page: Page) {}
  async render(request: PngRenderRequest): Promise<PngRenderResult> {
    const out = await this.page.evaluate(
      ({ scene, options }) => window.__pipelineRender(scene, options),
      { scene: request.scene, options: request.options },
    );
    const png = new Uint8Array(Buffer.from(out.base64, 'base64'));
    const size = pngSize(png);
    if (size.width !== out.width || size.height !== out.height) throw new Error('size metadata mismatch');
    this.lastWarnings = out.warnings;
    return { png, width: out.width, height: out.height, warnings: out.warnings, renderer: out.renderer };
  }
}

declare global {
  interface Window {
    __pipelineRender: (scene: unknown, options: unknown) => Promise<{ base64: string; width: number; height: number; warnings: string[]; renderer: string }>;
    __pipelineRendererReady: boolean;
  }
}

function renderArgs(mode: Mode): [number | null, boolean] {
  // [render_scale, crop]; crop is applied separately below.
  return mode === 'analysis' ? [1.0, false] : [null, false];
}

async function renderVia(manifest: Record<string, unknown>, output: string, mode: Mode): Promise<string[]> {
  const [renderScale, crop] = renderArgs(mode);
  const result = await new ExcalidrawRender().render(manifest, output, null, null, RENDER_URL, null, null, null, null, renderScale, crop, null, false, true);
  const stderr = result.stderr ?? '';
  return stderr ? stderr.split('\n').filter((line) => line.startsWith('  ')).map((line) => line.slice(2)) : [];
}

async function pool<T>(items: T[], size: number, fn: (item: T) => Promise<void>): Promise<void> {
  let next = 0;
  await Promise.all(Array.from({ length: Math.max(1, size) }, async () => {
    while (next < items.length) {
      const item = items[next++];
      await fn(item);
    }
  }));
}

async function startVite(): Promise<{ url: string; child: ChildProcess }> {
  const port = 5179;
  const child = spawn('npx', ['vite', '--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: FRONTEND, stdio: ['ignore', 'pipe', 'pipe'] });
  const url = `http://127.0.0.1:${port}`;
  let log = '';
  child.stdout?.on('data', (d) => { log += String(d); });
  child.stderr?.on('data', (d) => { log += String(d); });
  for (let i = 0; i < 120; i += 1) {
    try {
      const res = await fetch(`${url}/test-pages/pipeline-renderer.html`);
      if (res.ok) return { url, child };
    } catch { /* not up yet */ }
    if (child.exitCode !== null) break;
    await new Promise((r) => setTimeout(r, 500));
  }
  child.kill();
  throw new Error(`vite did not start:\n${log}`);
}

// ---------------------------------------------------------------------------

const stageDir = join(FIXTURES, 'stages');
const files = readdirSync(stageDir)
  .filter((name) => name.endsWith('.json') && !name.startsWith('_') && (!caseFilter || name.includes(caseFilter)))
  .sort();
const manifests = new Map<string, Record<string, unknown>>();
for (const file of files) {
  const fixture = JSON.parse(readFileSync(join(stageDir, file), 'utf-8')) as { case: string; snapshots: { diagram_manifest: Record<string, unknown> | null }[] };
  const manifest = fixture.snapshots[fixture.snapshots.length - 1]?.diagram_manifest;
  if (manifest) manifests.set(fixture.case, manifest);
}
if (!argv.includes('--keep')) rmSync(OUT, { recursive: true, force: true });
mkdirSync(OUT, { recursive: true });

const jobs = [...manifests.keys()].flatMap((c) => modes.map((mode) => ({ case: c, mode })));
const errors = new Map<string, string>();
const warnings = new Map<string, { service: string[]; browser: string[] }>();
const key = (j: { case: string; mode: Mode }) => `${j.case}/${j.mode}`;
const pathOf = (j: { case: string; mode: Mode }, side: 'service' | 'browser', suffix = '') => join(OUT, j.case, `${j.mode}.${side}${suffix}.png`);

const t0 = Date.now();
// 1. Renderer service (default platform renderer: playwright + port 3001).
await pool(jobs, concurrency, async (job) => {
  mkdirSync(join(OUT, job.case), { recursive: true });
  try {
    const w = await renderVia(manifests.get(job.case)!, pathOf(job, 'service'), job.mode);
    warnings.set(key(job), { service: w, browser: [] });
  } catch (error) {
    errors.set(key(job), `service: ${String((error as Error).message).slice(0, 400)}`);
  }
});
const tService = Date.now() - t0;
console.log(`service renders: ${jobs.length} in ${(tService / 1000).toFixed(1)}s`);

// 2. In-browser renderer (frontend test page), installed as the PngRenderer.
let vite: ChildProcess | null = null;
if (!frontendUrl) {
  const started = await startVite();
  frontendUrl = started.url;
  vite = started.child;
}
const browser = await chromium.launch({ headless: true });
const t1 = Date.now();
try {
  const page = await (await browser.newContext()).newPage();
  const pageErrors: string[] = [];
  page.on('pageerror', (e) => pageErrors.push(e.message));
  await page.goto(`${frontendUrl}/test-pages/pipeline-renderer.html`, { waitUntil: 'load' });
  await page.waitForFunction(() => window.__pipelineRendererReady === true, null, { timeout: 60000 });
  const renderer = new FrontendPageRenderer(page);
  await withPngRenderer(renderer, async () => {
    for (const job of jobs) {
      try {
        await renderVia(manifests.get(job.case)!, pathOf(job, 'browser'), job.mode);
        const w = warnings.get(key(job)) ?? { service: [], browser: [] };
        w.browser = renderer.lastWarnings;
        warnings.set(key(job), w);
      } catch (error) {
        errors.set(key(job), `${errors.get(key(job)) ?? ''} browser: ${String((error as Error).message).slice(0, 400)}`.trim());
      }
    }
  });
  if (pageErrors.length) console.log('page errors:', pageErrors);
} finally {
  await browser.close();
  vite?.kill();
}
const tBrowser = Date.now() - t1;
console.log(`browser renders: ${jobs.length} in ${(tBrowser / 1000).toFixed(1)}s`);

// 3. Compare raw exports, then smart crop both.
const results: CaseResult[] = [];
for (const job of jobs) {
  const result: CaseResult = { case: job.case, mode: job.mode, warnings: warnings.get(key(job)) };
  results.push(result);
  if (errors.has(key(job))) {
    result.error = errors.get(key(job));
    continue;
  }
  const svc = pathOf(job, 'service');
  const brw = pathOf(job, 'browser');
  result.raw = diffPng(readFileSync(svc), readFileSync(brw));
  const svcCrop = pathOf(job, 'service', '.crop');
  const brwCrop = pathOf(job, 'browser', '.crop');
  copyFileSync(svc, svcCrop);
  copyFileSync(brw, brwCrop);
  const crop = (p: string) => smart_crop.invoke({ image_path: p, output_path: p, padding: 60, canvas_engine: 'excalidraw' }).replace(/\nSaved to: .*$/, '');
  const serviceMessage = crop(svcCrop);
  const browserMessage = crop(brwCrop);
  const diff = existsSync(svcCrop) && existsSync(brwCrop) ? diffPng(readFileSync(svcCrop), readFileSync(brwCrop)) : null;
  result.crop = { serviceMessage, browserMessage, agree: serviceMessage === browserMessage && (diff?.pass ?? false), diff };
}

const failed = results.filter((r) => r.error || !r.raw?.pass || !r.crop?.agree);
const summary = {
  renderer_url: RENDER_URL,
  frontend_url: frontendUrl,
  threshold: { pixel_channel_diff_gt: PIXEL_DIFF, max_ratio: MAX_RATIO, sizes_equal: true },
  cases: manifests.size,
  modes,
  renders_per_side: jobs.length,
  seconds: { service: tService / 1000, browser: tBrowser / 1000 },
  pass: results.length - failed.length,
  fail: failed.length,
  identical_bytes: results.filter((r) => r.raw?.identicalBytes).length,
  identical_pixels: results.filter((r) => r.raw?.identicalPixels).length,
  max_ratio: Math.max(0, ...results.map((r) => (r.raw?.sameSize ? r.raw.ratio : 0))),
  max_channel_diff: Math.max(0, ...results.map((r) => r.raw?.maxDiff ?? 0)),
  crop_agree: results.filter((r) => r.crop?.agree).length,
  with_warnings: results.filter((r) => (r.warnings?.service.length ?? 0) + (r.warnings?.browser.length ?? 0) > 0).length,
  failed: failed.map((r) => ({ case: r.case, mode: r.mode, error: r.error, raw: r.raw, crop: r.crop })),
  results,
};
writeFileSync(join(OUT, 'summary.json'), JSON.stringify(summary, null, 1));
console.log(JSON.stringify({ ...summary, results: undefined, failed: summary.failed.map((f) => `${f.case}/${f.mode}: ${f.error ?? `ratio=${f.raw?.ratio} size=${f.raw?.sizeA}/${f.raw?.sizeB} crop=${f.crop?.serviceMessage} | ${f.crop?.browserMessage}`}`) }, null, 1));
console.log(`${results.length - failed.length}/${results.length} within threshold; report: ${join(OUT, 'summary.json')}`);
process.exit(failed.length === 0 ? 0 : 1);
