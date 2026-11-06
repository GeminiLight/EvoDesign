// In-browser PNG renderer for the TS pipeline (PHASE3_PLAN.md WP28).
//
// The pipeline (packages/render-engine) renders Excalidraw scenes through a
// ``PngRenderer`` (src/render_engine/png_renderer.ts). On the server that is
// the renderer page evodesign/agentic_system/tool_services/src/app/renderers/
// excalidraw/page.tsx driven by playwright; here the same export runs in the
// user's page. Every export parameter mirrors that page's
// ``loadExcalidrawScene``:
//
//   * appState = { viewModeEnabled, zenModeEnabled, gridSize: undefined,
//     viewBackgroundColor: '#ffffff' } overlaid with the scene's appState,
//     then exportWithDarkMode: false (never dark, whatever the UI theme),
//     exportBackground: true and the export scale;
//   * elements = restoreElements(scene.elements, null), files = scene.files;
//   * mimeType image/png, exportPadding = margin;
//   * scale: the requested one if finite and > 0 (else 4), capped at 4, then
//     clamped by getDimensions to 4000*4000*4 pixels and 16384 px per side,
//     canvas size floor(extent * scale) (renderDefaults.ts);
//   * fonts: exportToBlob loads the scene's fonts itself
//     (Fonts.loadElementsFonts); like the page we also wait for
//     document.fonts.ready. Font files come from the same place as the page's
//     (EXCALIDRAW_ASSET_PATH if the host sets one, else Excalidraw's CDN
//     fallback) and @excalidraw/excalidraw is the same version (0.18.1 in
//     both lock files).
//
// The page also mounts an editor and scrolls it to the content before
// exporting; nothing of that reaches the exported image (the export uses the
// submitted elements, not the editor's), so it is not reproduced. Pixel
// parity with the page is checked by packages/render-engine
// tools/wp28/compare-renderers.ts over all stage fixtures (migration/notes/WP28.md).
//
// The types below are structurally identical to png_renderer.ts; WP31 swaps
// them for imports once the package is a frontend dependency.

export interface PngRenderOptions {
  url: string;
  viewportWidth: number;
  viewportHeight: number;
  timeoutMs: number;
  exportScale: number;
  margin: number;
}

export interface PngRenderRequest {
  scene: Record<string, unknown>;
  options: PngRenderOptions;
  signal?: AbortSignal;
}

export interface PngRenderResult {
  png: Uint8Array;
  width: number;
  height: number;
  warnings: string[];
  renderer: string;
}

export interface PngRenderer {
  readonly name: string;
  render(request: PngRenderRequest): Promise<PngRenderResult>;
}

// tool_services/src/lib/renderDefaults.ts
const DEFAULT_EXCALIDRAW_EXPORT_SCALE = 4;
const DEFAULT_RENDER_MARGIN = 40;
const MAX_EXCALIDRAW_EXPORT_SCALE = 4;
const MAX_EXCALIDRAW_EXPORT_PIXELS = 4000 * 4000 * 4;
const MAX_EXCALIDRAW_EXPORT_SIDE = 16384;
const DEFAULT_RENDER_TIMEOUT_MS = 15000;

function clampExcalidrawExportScale(width: number, height: number, requested: number): number {
  if (!(width > 0) || !(height > 0)) return requested;
  return Math.min(
    requested,
    Math.sqrt(MAX_EXCALIDRAW_EXPORT_PIXELS / (width * height)),
    MAX_EXCALIDRAW_EXPORT_SIDE / width,
    MAX_EXCALIDRAW_EXPORT_SIDE / height,
  );
}

// page.tsx defaultAppState
const DEFAULT_APP_STATE = {
  viewModeEnabled: true,
  zenModeEnabled: true,
  gridSize: undefined,
  viewBackgroundColor: '#ffffff',
};

function pngSize(png: Uint8Array): { width: number; height: number } {
  const signature = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a];
  if (png.length < 24 || signature.some((byte, i) => png[i] !== byte)) {
    throw new Error('Excalidraw export did not produce a PNG file.');
  }
  const u32 = (offset: number) => ((png[offset] << 24) | (png[offset + 1] << 16) | (png[offset + 2] << 8) | png[offset + 3]) >>> 0;
  return { width: u32(16), height: u32(20) };
}

function abortError(signal: AbortSignal): unknown {
  return signal.reason ?? new DOMException('The render was aborted.', 'AbortError');
}

/** Export one scene the way the renderer page does; errors carry the page driver's messages. */
async function exportScene(scene: Record<string, unknown>, options: PngRenderOptions): Promise<Uint8Array> {
  // excalidraw_page.ts checks these before touching the page.
  if (!Number.isFinite(options.exportScale) || options.exportScale <= 0) {
    throw new Error(`Invalid export scale: ${options.exportScale}`);
  }
  if (!Number.isFinite(options.margin) || options.margin < 0) {
    throw new Error(`Invalid margin: ${options.margin}`);
  }
  try {
    const normalized = (Array.isArray(scene) ? { elements: scene } : scene) as {
      elements?: unknown[];
      appState?: Record<string, unknown>;
      files?: Record<string, unknown>;
    };
    const appState = Object.assign({}, DEFAULT_APP_STATE, normalized.appState || {});

    await document.fonts.ready;

    const { exportToBlob, restoreElements } = await import('@excalidraw/excalidraw');
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const exportElements = restoreElements((normalized.elements || []) as any, null);
    const requestedScale = Number(options.exportScale ?? DEFAULT_EXCALIDRAW_EXPORT_SCALE);
    const exportScale = Number.isFinite(requestedScale) && requestedScale > 0
      ? Math.min(requestedScale, MAX_EXCALIDRAW_EXPORT_SCALE)
      : DEFAULT_EXCALIDRAW_EXPORT_SCALE;
    const exportMargin = Number(options.margin ?? DEFAULT_RENDER_MARGIN);
    const blob = await exportToBlob({
      elements: exportElements,
      appState: {
        ...appState,
        exportWithDarkMode: false,
        exportBackground: true,
        exportScale,
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
      } as any,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      files: (normalized.files || {}) as any,
      mimeType: 'image/png',
      exportPadding: exportMargin,
      getDimensions: (width: number, height: number) => {
        const scale = clampExcalidrawExportScale(width, height, exportScale);
        return {
          width: Math.max(1, Math.floor(width * scale)),
          height: Math.max(1, Math.floor(height * scale)),
          scale,
        };
      },
    });
    return new Uint8Array(await blob.arrayBuffer());
  } catch (error) {
    // The page reports err.message through __renderError; the driver wraps it.
    const message = error instanceof Error ? error.message : String(error);
    throw new Error(`Client render failed: ${(message || 'Unknown render error').trim()}`);
  }
}

/**
 * Renders Excalidraw scenes in this page with the renderer page's export
 * parameters. Renders run one at a time (fonts and the console hook are page
 * global). ``url`` and the viewport are accepted and ignored: the export size
 * follows the scene, not the viewport, on the page too.
 */
export class BrowserPngRenderer implements PngRenderer {
  readonly name = 'browser-export';
  private queue: Promise<unknown> = Promise.resolve();

  render(request: PngRenderRequest): Promise<PngRenderResult> {
    const run = this.queue.then(() => this.renderNow(request));
    this.queue = run.catch(() => undefined);
    return run;
  }

  private async renderNow({ scene, options, signal }: PngRenderRequest): Promise<PngRenderResult> {
    if (signal?.aborted) throw abortError(signal);
    // The page driver collects console errors and reports them on stderr.
    const warnings: string[] = [];
    const originalError = console.error;
    console.error = (...args: unknown[]) => {
      warnings.push(args.map((arg) => (arg instanceof Error ? arg.message : String(arg))).join(' '));
      originalError.apply(console, args);
    };
    let timer: ReturnType<typeof setTimeout> | undefined;
    let onAbort: (() => void) | undefined;
    try {
      const timeoutMs = options.timeoutMs ?? DEFAULT_RENDER_TIMEOUT_MS;
      const stop = new Promise<never>((_, reject) => {
        timer = setTimeout(() => reject(new Error(warnings.length > 0
          ? `Render failed (page errors): ${warnings.join('; ')}`
          : 'Render timeout: after injecting data the page did not render or report an error.')), timeoutMs);
        if (signal) {
          onAbort = () => reject(abortError(signal));
          signal.addEventListener('abort', onAbort, { once: true });
        }
      });
      const png = await Promise.race([exportScene(scene, options), stop]);
      return { png, ...pngSize(png), warnings, renderer: this.name };
    } finally {
      if (timer !== undefined) clearTimeout(timer);
      if (signal && onAbort) signal.removeEventListener('abort', onAbort);
      console.error = originalError;
    }
  }
}

export const pipelineRenderer = new BrowserPngRenderer();
