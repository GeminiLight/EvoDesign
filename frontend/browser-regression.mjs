#!/usr/bin/env node
/**
 * Browser regression for the EvoDiagram frontend (playwright + chromium headless shell).
 *
 * (a) storage disabled: `/` and `/workspace` must render their main structure
 *     with zero uncaught pageerrors when localStorage/sessionStorage methods
 *     throw SecurityError.
 * (b) OAuth error toast: `/?error=invalid_state` must show the
 *     auth.oauthInvalidState toast and strip `?error=` from the URL. This flow
 *     is pure frontend (no backend exchange involved).
 * (c) big-canvas throttle: a 500-element excalidraw scene is injected through
 *     the workspace recovery draft (backend fully mocked via route
 *     interception), synthetic drag/keys/wheel interactions run against the
 *     canvas, and the DEV signature instrumentation
 *     (window.__evoSnapshotSignatureStats) verifies signature computations
 *     stay within the 100ms throttle budget with no long-task freeze.
 *
 * Starts its own `npm run dev` server on :5175 (reuses one if already up) and
 * kills it on exit. Never starts a backend; all /api/v1 traffic is intercepted.
 * Exit code 0 = no FAIL (SKIPPED allowed, reason printed).
 *
 * Run: node browser-regression.mjs   (REGRESSION_VERBOSE=1 to echo vite logs)
 */
import { chromium } from 'playwright';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const EXE = process.env.CHROME_EXECUTABLE_PATH;
const PORT = 5175;
const BASE = `http://localhost:${PORT}`;
const FRONTEND_DIR = path.dirname(fileURLToPath(import.meta.url));
const VERBOSE = Boolean(process.env.REGRESSION_VERBOSE);

const results = [];
const record = (name, status, detail = '') => {
  results.push({ name, status, detail });
  console.log(`[${status}] ${name}${detail ? ` — ${detail}` : ''}`);
};

// ---------------------------------------------------------------------------
// dev server lifecycle
// ---------------------------------------------------------------------------
const portServing = async () => {
  try {
    const res = await fetch(`${BASE}/`, { method: 'GET' });
    return res.status < 500;
  } catch {
    return false;
  }
};

let devProc = null;
let startedByUs = false;

const startDevServer = async () => {
  if (await portServing()) {
    console.log(`dev server already listening on :${PORT}; reusing (it will NOT be killed)`);
    return;
  }
  devProc = spawn('npm', ['run', 'dev'], {
    cwd: FRONTEND_DIR,
    detached: true,
    stdio: ['ignore', 'pipe', 'pipe'],
    // Same-origin API base so mocked /api/v1 calls need no CORS; existing
    // process.env vars take priority over frontend/.env in vite.
    env: { ...process.env, VITE_API_BASE_URL: BASE },
  });
  startedByUs = true;
  devProc.stdout.on('data', (d) => VERBOSE && process.stdout.write(`[vite] ${d}`));
  devProc.stderr.on('data', (d) => VERBOSE && process.stderr.write(`[vite] ${d}`));

  const deadline = Date.now() + 120_000;
  while (Date.now() < deadline) {
    if (devProc.exitCode !== null) {
      throw new Error(`vite exited early with code ${devProc.exitCode}`);
    }
    if (await portServing()) {
      console.log('vite dev server ready on :' + PORT);
      return;
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error('vite dev server did not become ready within 120s');
};

const stopDevServer = () => {
  if (!startedByUs || !devProc || devProc.exitCode !== null) return;
  try {
    process.kill(-devProc.pid, 'SIGTERM'); // kill the process group (npm → vite)
  } catch {
    try { devProc.kill('SIGTERM'); } catch { /* already gone */ }
  }
  startedByUs = false;
  console.log('dev server stopped');
};

process.on('SIGINT', () => { stopDevServer(); process.exit(130); });
process.on('uncaughtException', (err) => {
  console.error('regression harness crashed:', err);
  stopDevServer();
  process.exit(2);
});

// ---------------------------------------------------------------------------
// (a) storage disabled
// ---------------------------------------------------------------------------
const runStorageDisabledTest = async (browser) => {
  const name = '(a) storage-disabled: main structure renders, no uncaught pageerror';
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  await ctx.addInitScript(() => {
    const thrower = () => {
      throw new DOMException('Access to storage is not allowed from this context.', 'SecurityError');
    };
    for (const method of ['getItem', 'setItem', 'removeItem', 'clear', 'key']) {
      Object.defineProperty(Storage.prototype, method, { value: thrower, writable: true, configurable: true });
    }
  });
  const page = await ctx.newPage();
  const pageErrors = [];
  page.on('pageerror', (e) => pageErrors.push(String(e?.message ?? e).slice(0, 160)));
  try {
    const checks = [];
    for (const route of ['/', '/workspace']) {
      await page.goto(`${BASE}${route}`, { waitUntil: 'domcontentloaded', timeout: 45_000 });
      await page.waitForSelector('#main-content', { state: 'visible', timeout: 30_000 });
      const rootChildren = await page.evaluate(() => document.getElementById('root')?.childElementCount ?? 0);
      if (rootChildren === 0) throw new Error(`${route}: #root empty (blank page)`);
      await page.waitForTimeout(1500); // let mount-time effects run
      checks.push(`${route}: #main-content visible, #root children=${rootChildren}`);
    }
    if (pageErrors.length > 0) {
      throw new Error(`uncaught pageerrors: ${JSON.stringify(pageErrors.slice(0, 5))}`);
    }
    record(name, 'PASS', checks.join(' | '));
  } catch (err) {
    record(name, 'FAIL', `${err.message}${pageErrors.length ? ` | pageerrors: ${JSON.stringify(pageErrors.slice(0, 5))}` : ''}`);
  } finally {
    await ctx.close();
  }
};

// ---------------------------------------------------------------------------
// (b) OAuth error toast
// ---------------------------------------------------------------------------
const runOAuthToastTest = async (browser) => {
  const name = '(b) OAuth ?error=invalid_state: toast shown and param stripped';
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await ctx.newPage();
  const pageErrors = [];
  page.on('pageerror', (e) => pageErrors.push(String(e?.message ?? e).slice(0, 160)));
  try {
    // No backend needed: BackendAuthProvider handles ?error= purely client-side
    // (the exchange path only runs for ?code=).
    await page.goto(`${BASE}/?error=invalid_state`, { waitUntil: 'domcontentloaded', timeout: 45_000 });
    await page.waitForSelector('[role="alert"]', { timeout: 25_000 });
    const texts = await page.$$eval('[role="alert"]', (els) => els.map((e) => (e.textContent || '').trim()));
    const hit = texts.find((t) => /could not be verified/i.test(t) || /安全校验/.test(t));
    if (!hit) {
      throw new Error(`oauthInvalidState toast not found; alerts on page: ${JSON.stringify(texts).slice(0, 300)}`);
    }
    await page.waitForFunction(() => !new URL(window.location.href).searchParams.has('error'), null, { timeout: 10_000 });
    record(name, 'PASS', `toast="${hit.slice(0, 90)}" finalUrl=${page.url()}`);
    if (pageErrors.length) console.log(`   note: pageerrors during (b): ${JSON.stringify(pageErrors.slice(0, 3))}`);
  } catch (err) {
    record(name, 'FAIL', `${err.message}${pageErrors.length ? ` | pageerrors: ${JSON.stringify(pageErrors.slice(0, 3))}` : ''}`);
  } finally {
    await ctx.close();
  }
};

// ---------------------------------------------------------------------------
// (c) big-canvas throttle
// ---------------------------------------------------------------------------
const SCENE_ELEMENTS = 500;

const makeElement = (i) => ({
  id: `elem_${i.toString(36)}_${(i * 7919).toString(36)}`,
  type: i % 5 === 0 ? 'text' : 'rectangle',
  x: 40 + (i % 20) * 180,
  y: 40 + Math.floor(i / 20) * 120,
  width: 160,
  height: 90,
  angle: 0,
  strokeColor: '#1e293b',
  backgroundColor: i % 2 ? '#e0f2fe' : 'transparent',
  fillStyle: 'solid',
  strokeWidth: 2,
  strokeStyle: 'solid',
  roughness: 1,
  opacity: 100,
  groupIds: [],
  frameId: null,
  roundness: { type: 3 },
  seed: 100000 + i,
  version: 3,
  versionNonce: (i * 2654435761) % 2147483647,
  index: `a${i.toString(36).padStart(4, '0')}`,
  isDeleted: false,
  boundElements: null,
  updated: 1757500000000 + i,
  link: null,
  locked: false,
  ...(i % 5 === 0
    ? { text: `Node ${i}`, fontSize: 16, fontFamily: 1, textAlign: 'left', verticalAlign: 'top', containerId: null, originalText: `Node ${i}`, lineHeight: 1.25 }
    : {}),
});

const buildRecoveryDraft = () => ({
  version: 1,
  savedAt: Date.now(),
  sourceAuthIdentity: 'u_mock',
  preview: {
    diagramId: 'diag_regression',
    requestId: 'req_regression',
    projectId: 'proj_regression',
    snapshotId: 'snap_regression',
    excalidrawPayload: '',
    summary: 'regression scene',
    previewImage: '',
    generatedAt: new Date().toISOString(),
    persistError: false,
  },
  request: {
    id: 'req_regression',
    prompt: 'regression canvas with 500 elements',
    diagramType: 'architecture',
    style: 'neutral',
    refinementLevel: 'draft',
    constraints: {},
    llmConfigId: 'provider_openai',
  },
  canvasMode: 'excalidraw',
  projectName: 'Regression Canvas',
  latestSnapshot: {
    elements: Array.from({ length: SCENE_ELEMENTS }, (_, i) => makeElement(i)),
    appState: { viewBackgroundColor: '#f5fbff' },
    files: {},
  },
  activeEditingSnapshotId: 'snap_regression',
  lastSyncedDocSignature: null,
  projectVersion: 1,
  hasUnsavedChanges: false,
});

const runCanvasThrottleTest = async (browser) => {
  const name = `(c) ${SCENE_ELEMENTS}-element canvas: signature throttle effective, no long-task freeze`;
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });

  // Mock every backend call the workspace makes (auth, projects, snapshots,
  // DNA, schema sync). The sync echo returns the patch as latest_schema so the
  // post-sync dirty check settles instead of looping.
  await ctx.route('**/api/v1/**', async (route) => {
    const req = route.request();
    const url = req.url();
    const cors = {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET,POST,PATCH,PUT,DELETE,OPTIONS',
      'Access-Control-Allow-Headers': '*',
    };
    const json = (obj, status = 200) => route.fulfill({
      status,
      contentType: 'application/json',
      headers: cors,
      body: JSON.stringify(obj),
    });
    if (req.method() === 'OPTIONS') return route.fulfill({ status: 204, headers: cors, body: '' });
    if (url.includes('/auth/me')) {
      return json({
        token: 'mock-token',
        user: { user_id: 'u_mock', email: 'mock@regression.local', username: 'mock', auth_provider: 'email', created_at: '2026-01-01T00:00:00Z' },
      });
    }
    if (url.includes('/schema/sync')) {
      let body = {};
      try { body = JSON.parse(req.postData() || '{}'); } catch { /* keep {} */ }
      return json({
        project_id: body.project_id ?? 'proj_regression',
        snapshot_id: body.base_snapshot_id ?? 'snap_regression',
        latest_schema: body.schema_patch ?? {},
        edit_source: 'HUMAN',
        version: (typeof body.version === 'number' ? body.version : 1) + 1,
      });
    }
    if (url.includes('/snapshots')) return json({ snapshots: [], page: 1, page_size: 20, total: 0 });
    if (url.includes('/dna/rules')) return json({ structure: [], style: [], layout: [] });
    if (url.includes('/projects')) return json({ projects: [], total: 0 });
    return json({});
  });

  const draftJson = JSON.stringify(buildRecoveryDraft());
  await ctx.addInitScript((draft) => {
    // Seeded session so BackendAuthProvider resolves authIdentity='u_mock'
    // synchronously and the recovery draft is applied.
    localStorage.setItem('auth_token', 'mock-token');
    localStorage.setItem('auth_user_id', 'u_mock');
    localStorage.setItem('auth_user_profile', JSON.stringify({
      user_id: 'u_mock', email: 'mock@regression.local', username: 'mock', auth_provider: 'email',
    }));
    sessionStorage.setItem('evodiagram_workspace_recovery_draft_v1', draft);

    window.__evoLongTasks = [];
    try {
      new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) {
          window.__evoLongTasks.push({ start: entry.startTime, dur: entry.duration });
        }
      }).observe({ entryTypes: ['longtask'] });
    } catch { /* longtask unsupported: count stays empty */ }

    // Sample the DEV signature instrumentation every 20ms so the harness can
    // compute per-100ms-window computation counts.
    window.__evoSigSamples = [];
    setInterval(() => {
      const stats = window.__evoSnapshotSignatureStats;
      if (stats) window.__evoSigSamples.push({ t: performance.now(), c: stats.computeCount });
    }, 20);
  }, draftJson);

  const page = await ctx.newPage();
  const pageErrors = [];
  page.on('pageerror', (e) => pageErrors.push(String(e?.message ?? e).slice(0, 160)));

  try {
    await page.goto(`${BASE}/workspace`, { waitUntil: 'domcontentloaded', timeout: 45_000 });
    await page.waitForSelector('.excalidraw canvas', { timeout: 90_000 });
    if (!await page.evaluate(() => Boolean(window.__evoSnapshotSignatureStats))) {
      record(name, 'SKIPPED', 'DEV signature instrumentation (window.__evoSnapshotSignatureStats) unavailable — dev build did not expose it');
      return;
    }
    // The restored scene must have flowed through the signature path.
    await page.waitForFunction(
      (n) => (window.__evoSnapshotSignatureStats?.lastElementCount ?? 0) >= n,
      SCENE_ELEMENTS,
      { timeout: 30_000 },
    );
    await page.waitForTimeout(1500); // let the initial auto-sync settle

    // --- interaction phase ---------------------------------------------------
    const startInfo = await page.evaluate(() => {
      window.__evoSigSamples.length = 0;
      const stats = window.__evoSnapshotSignatureStats;
      return { perfNow: performance.now(), computeCount: stats.computeCount, longTasks: window.__evoLongTasks.length };
    });
    const wallStart = Date.now();

    const canvas = await page.$('.excalidraw canvas');
    const box = await canvas.boundingBox();
    const cx = box.x + box.width / 2;
    const cy = box.y + box.height / 2;

    // 1) click + drag across the scene (selects/moves whatever is under the
    //    cursor; otherwise a marquee — both fire continuous onChange events).
    await page.mouse.click(cx, cy);
    await page.mouse.move(cx, cy);
    await page.mouse.down();
    for (let i = 1; i <= 24; i += 1) {
      await page.mouse.move(cx + i * 6, cy + Math.sin(i / 3) * 40);
    }
    await page.mouse.up();
    // 2) arrow-key nudges (move the selection when the click hit an element).
    for (let i = 0; i < 15; i += 1) await page.keyboard.press('ArrowRight');
    // 3) wheel zoom burst (appState churn at high frequency).
    await page.mouse.move(cx, cy);
    for (let i = 0; i < 24; i += 1) await page.mouse.wheel(0, i % 2 ? -240 : 240);
    // 4) pan drag near a corner.
    await page.mouse.move(box.x + 40, box.y + 40);
    await page.mouse.down();
    for (let i = 1; i <= 12; i += 1) await page.mouse.move(box.x + 40 + i * 10, box.y + 40 + i * 4);
    await page.mouse.up();

    const interactionMs = Date.now() - wallStart;
    await page.waitForTimeout(400); // let trailing throttle edges run

    const data = await page.evaluate((start) => {
      const stats = window.__evoSnapshotSignatureStats;
      return {
        computeCount: stats.computeCount,
        lastElementCount: stats.lastElementCount,
        lastAlgorithm: stats.lastAlgorithm,
        samples: window.__evoSigSamples.filter((s) => s.t >= start.perfNow - 60),
        longTasksDuringInteraction: window.__evoLongTasks.slice(start.longTasks).filter((lt) => lt.start >= start.perfNow - 60),
        totalLongTasks: window.__evoLongTasks.length,
        maxLongTaskOverall: window.__evoLongTasks.reduce((m, lt) => Math.max(m, lt.dur), 0),
      };
    }, startInfo);

    const deltaCompute = data.computeCount - startInfo.computeCount;
    // Max signature computations within any ~100ms sliding window of the
    // interaction phase. The throttle allows 1 leading + 1 trailing edge per
    // 100ms, so <= 3 with sampling slack.
    let maxPer100ms = 0;
    const samples = data.samples;
    for (let i = 0; i < samples.length; i += 1) {
      for (let j = i + 1; j < samples.length; j += 1) {
        if (samples[j].t - samples[i].t >= 100) {
          maxPer100ms = Math.max(maxPer100ms, samples[j].c - samples[i].c);
          break;
        }
      }
    }
    const throttleBudget = Math.ceil((interactionMs + 300) / 100) + 2;
    const worstLongTask = data.longTasksDuringInteraction.reduce((m, lt) => Math.max(m, lt.dur), 0);

    const detail = [
      `elements=${data.lastElementCount} algo=${data.lastAlgorithm}`,
      `interaction=${interactionMs}ms`,
      `sigComputes=${deltaCompute} (overall budget ${throttleBudget})`,
      `maxPer100msWindow=${maxPer100ms} (limit 3)`,
      `longtasks during interaction=${data.longTasksDuringInteraction.length} worst=${worstLongTask.toFixed(0)}ms`,
      `longtasks total=${data.totalLongTasks} worstOverall=${data.maxLongTaskOverall.toFixed(0)}ms`,
    ].join(' | ');

    if (deltaCompute === 0) {
      record(name, 'SKIPPED', `synthetic input produced no scene-change signature computations; throttle not exercised. ${detail}`);
      return;
    }
    const failures = [];
    if (deltaCompute > throttleBudget) failures.push(`signature computations ${deltaCompute} exceeded throttle budget ${throttleBudget}`);
    if (maxPer100ms > 3) failures.push(`max per-100ms window ${maxPer100ms} > 3`);
    if (worstLongTask > 500) failures.push(`long task ${worstLongTask.toFixed(0)}ms > 500ms during interaction`);
    if (pageErrors.length) failures.push(`pageerrors: ${JSON.stringify(pageErrors.slice(0, 3))}`);
    if (failures.length) {
      record(name, 'FAIL', `${failures.join('; ')} | ${detail}`);
    } else {
      record(name, 'PASS', detail);
    }
  } catch (err) {
    record(name, 'FAIL', `${err.message}${pageErrors.length ? ` | pageerrors: ${JSON.stringify(pageErrors.slice(0, 3))}` : ''}`);
  } finally {
    await ctx.close();
  }
};

// ---------------------------------------------------------------------------
// main
// ---------------------------------------------------------------------------
const browser = await chromium.launch({ executablePath: EXE });
try {
  await startDevServer();
  await runStorageDisabledTest(browser);
  await runOAuthToastTest(browser);
  await runCanvasThrottleTest(browser);
} finally {
  await browser.close();
  stopDevServer();
}

console.log('\n=== summary ===');
for (const r of results) console.log(`${r.status.padEnd(7)} ${r.name}`);
const failed = results.filter((r) => r.status === 'FAIL').length;
console.log(`\nPASS=${results.filter((r) => r.status === 'PASS').length} FAIL=${failed} SKIPPED=${results.filter((r) => r.status === 'SKIPPED').length}`);
process.exit(failed > 0 ? 1 : 0);
