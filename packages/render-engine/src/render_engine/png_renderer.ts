// PNG renderer contract (PHASE3_PLAN.md WP28).
//
// ``canvas_render`` renders an Excalidraw scene by running
// ``tool_services/scripts/render-excalidraw.ts``: that script opens the
// renderer page (``/renderers/excalidraw``), injects the scene and reads back
// the PNG the page exported with ``exportToBlob``. A ``PngRenderer`` is that
// "scene in, PNG out" step on its own, so the host can supply it:
//
//   * Node (default): playwright drives the renderer page on port 3001
//     (``src/node/png_renderer.ts``, same code as before);
//   * browser: ``frontend/src/services/browser/pipelineRenderer.ts`` calls
//     ``exportToBlob`` in the user's page with the renderer page's export
//     parameters.
//
// Input and output follow what ``canvas_render`` exchanges with the page:
// the scene (already normalized to ``{ elements, ... }``), export scale,
// margin, viewport, timeout and page URL in; PNG bytes plus metadata out.
// ``warnings`` are the page's console errors; ``canvas_render`` writes them to
// the script's stderr exactly like the page driver does.
//
// No renderer is installed by default: ``canvas_render`` then keeps using the
// platform hook (``getPlatform().renderExcalidrawPage``), so Node behaviour and
// every recorded fixture stay unchanged. A host installs one with
// ``setPngRenderer`` (the browser bundle must, it has no other renderer).

/** Options of one render; the same fields the render-excalidraw.ts CLI accepts. */
export interface PngRenderOptions {
  /** Renderer page URL (only used by page-driving renderers). */
  url: string;
  viewportWidth: number;
  viewportHeight: number;
  timeoutMs: number;
  /** Image pixels per scene unit; the renderer page clamps it to 4 and to the export pixel caps. */
  exportScale: number;
  /** Export padding in scene units (``exportPadding``). */
  margin: number;
}

export interface PngRenderRequest {
  /** Normalized scene: ``{ elements, appState?, files?, ... }`` (``_cli_normalize_scene`` output). */
  scene: Record<string, unknown>;
  options: PngRenderOptions;
  signal?: AbortSignal;
}

export interface PngRenderResult {
  /** The exported PNG file. */
  png: Uint8Array;
  /** PNG pixel size (from IHDR). */
  width: number;
  height: number;
  /** Console errors the renderer saw while rendering (written to stderr). */
  warnings: string[];
  /** Implementation name, e.g. ``playwright-page`` or ``browser-export``. */
  renderer: string;
}

export interface PngRenderer {
  readonly name: string;
  render(request: PngRenderRequest): Promise<PngRenderResult>;
}

let _active: PngRenderer | null = null;

/** Install (or with null, remove) the renderer ``canvas_render`` uses for Excalidraw scenes. */
export function setPngRenderer(renderer: PngRenderer | null): void {
  _active = renderer;
}

/** The installed renderer, or null when ``canvas_render`` uses the platform default. */
export function getPngRenderer(): PngRenderer | null {
  return _active;
}

/** Run ``fn`` with ``renderer`` installed, restoring the previous one afterwards. */
export async function withPngRenderer<T>(renderer: PngRenderer | null, fn: () => Promise<T>): Promise<T> {
  const previous = _active;
  _active = renderer;
  try {
    return await fn();
  } finally {
    _active = previous;
  }
}

/** Width and height from a PNG's IHDR chunk; throws when ``png`` is not a PNG. */
export function pngSize(png: Uint8Array): { width: number; height: number } {
  const signature = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a];
  if (png.length < 24 || signature.some((byte, i) => png[i] !== byte)) {
    throw new Error('Renderer output is not a PNG file.');
  }
  const u32 = (offset: number) => ((png[offset] << 24) | (png[offset + 1] << 16) | (png[offset + 2] << 8) | png[offset + 3]) >>> 0;
  return { width: u32(16), height: u32(20) };
}
