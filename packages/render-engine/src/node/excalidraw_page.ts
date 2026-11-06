// In-process ``render-excalidraw.ts`` for Node: drives the Excalidraw renderer
// page with playwright and returns the exported PNG bytes (PHASE3_PLAN.md WP27;
// moved verbatim from render_engine/canvas_render.ts ``_cli_render``, which now
// calls it through ``getPlatform().renderExcalidrawPage``).

import type { ExcalidrawPageOptions } from '../py/platform_types.ts';

/* eslint-disable @typescript-eslint/no-explicit-any */
export async function renderExcalidrawPage(
  options: ExcalidrawPageOptions,
  scene: unknown,
  _cli_normalize_scene: (scene: unknown) => Record<string, unknown>,
  stderr: string[],
): Promise<Uint8Array> {
  const { chromium } = await import('playwright');
  const browser = await chromium.launch({
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
  });
  const context = await browser.newContext({ deviceScaleFactor: 2 });
  const page = await context.newPage();
  try {
    // The script does not await setViewportSize; neither do we (errors surface on goto).
    page.setViewportSize({ width: options.viewportWidth, height: options.viewportHeight }).catch(() => {});
    await page.goto(options.url, { waitUntil: 'load', timeout: options.timeoutMs });
  } catch (error) {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
    await browser.close().catch(() => {});
    throw error;
  }
  const normalized = _cli_normalize_scene(scene);

  const consoleErrors: string[] = [];
  const pageErrors: string[] = [];
  const requestErrors: string[] = [];
  const handleConsole = (msg: any) => {
    if (msg.type() === 'error') consoleErrors.push(msg.text());
  };
  const handlePageError = (error: Error) => {
    pageErrors.push(error.message);
  };
  const handleCrash = () => {
    pageErrors.push('Page rendering process crashed.');
  };
  const handleRequestFailed = (request: any) => {
    const failure = request.failure?.();
    const reason = failure?.errorText ? ` (${failure.errorText})` : '';
    requestErrors.push(`${request.url()}${reason}`);
  };
  page.on('console', handleConsole);
  page.on('pageerror', handlePageError);
  page.on('crash', handleCrash);
  page.on('requestfailed', handleRequestFailed);

  try {
    if (!Number.isFinite(options.exportScale) || options.exportScale <= 0) {
      throw new Error(`Invalid export scale: ${options.exportScale}`);
    }
    if (!Number.isFinite(options.margin) || options.margin < 0) {
      throw new Error(`Invalid margin: ${options.margin}`);
    }

    await page.waitForFunction(() => typeof (globalThis as any).loadExcalidrawScene === 'function', null, { timeout: options.timeoutMs });

    const apiReady = page.waitForFunction(() => Boolean((globalThis as any).__excalidrawAPI), null, { timeout: options.timeoutMs });
    const earlyError = page.waitForFunction(() => (globalThis as any).__renderStatus === 'error', null, { timeout: options.timeoutMs });
    apiReady.catch(() => {});
    earlyError.catch(() => {});

    let apiRace: 'ready' | 'error';
    try {
      apiRace = await Promise.race([apiReady.then(() => 'ready' as const), earlyError.then(() => 'error' as const)]);
    } catch (error) {
      const combined = [...consoleErrors, ...pageErrors, ...requestErrors].join('; ');
      if (combined.length > 0) {
        throw new Error(`Client setup failed (resource errors): ${combined}`);
      }
      throw error;
    }
    if (apiRace === 'error') {
      const errorMessage = await page.evaluate(() => (globalThis as any).__renderError || 'Unknown render error');
      throw new Error(`Client setup failed: ${String(errorMessage).trim()}`);
    }

    await page.evaluate(({ exportScale, margin }) => {
      (globalThis as any).__exportScale = exportScale;
      (globalThis as any).__exportMargin = margin;
    }, { exportScale: options.exportScale, margin: options.margin });

    await page.evaluate((sceneData) => {
      const win = globalThis as unknown as { loadExcalidrawScene?: (data: unknown) => void };
      if (typeof win.loadExcalidrawScene === 'function') {
        win.loadExcalidrawScene(sceneData);
      }
    }, normalized);

    const timeoutMs = options.timeoutMs ?? 15000;
    let timeoutHandle: NodeJS.Timeout | null = null;
    const ready = page.waitForFunction(() => (globalThis as any).__renderStatus === 'ready', null, { timeout: timeoutMs }).then(() => 'success');
    const failed = page.waitForFunction(() => (globalThis as any).__renderStatus === 'error', null, { timeout: timeoutMs }).then(() => 'error');
    ready.catch(() => {});
    failed.catch(() => {});
    const raceWinner = await Promise.race([
      ready,
      failed,
      new Promise((resolveTimeout) => {
        timeoutHandle = setTimeout(() => resolveTimeout('timeout'), timeoutMs);
        timeoutHandle.unref();
      }),
    ]);
    if (timeoutHandle) clearTimeout(timeoutHandle);

    if (raceWinner === 'timeout') {
      if (consoleErrors.length > 0 || pageErrors.length > 0) {
        throw new Error(`Render failed (page errors): ${[...consoleErrors, ...pageErrors].join('; ')}`);
      }
      throw new Error('Render timeout: after injecting data the page did not render or report an error.');
    }
    if (raceWinner === 'error') {
      const errorMessage = await page.evaluate(() => (globalThis as any).__renderError || 'Unknown render error');
      throw new Error(`Client render failed: ${String(errorMessage).trim()}`);
    }
    if (raceWinner !== 'success') {
      throw raceWinner as unknown as Error;
    }

    const base64Data = await page.evaluate(() => (globalThis as any).__exportedImageData);
    if (!base64Data || typeof base64Data !== 'string') {
      throw new Error('No exported image data found after successful render.');
    }
    const base64Content = base64Data.replace(/^data:[^;]+;base64,/, '');
    const buffer = new Uint8Array(Buffer.from(base64Content, 'base64'));

    if (consoleErrors.length > 0) {
      stderr.push('[render-excalidraw] Browser console emitted errors:\n');
      for (const entry of consoleErrors) stderr.push(`  ${entry}\n`);
    }
    return buffer;
  } finally {
    page.off('console', handleConsole);
    page.off('pageerror', handlePageError);
    page.off('crash', handleCrash);
    page.off('requestfailed', handleRequestFailed);
    await page.close().catch(() => {});
    await context.close().catch(() => {});
    await browser.close().catch(() => {});
  }
}
/* eslint-enable @typescript-eslint/no-explicit-any */
