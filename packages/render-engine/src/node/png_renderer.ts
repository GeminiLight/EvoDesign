// Node ``PngRenderer`` (PHASE3_PLAN.md WP28): playwright opens the renderer
// page and returns the PNG it exported. It is the same driver
// ``canvas_render`` uses by default (``excalidraw_page.ts``); installing it
// with ``setPngRenderer`` only routes the call through the renderer interface.

import { pngSize, type PngRenderRequest, type PngRenderResult, type PngRenderer } from '../render_engine/png_renderer.ts';
import { renderExcalidrawPage } from './excalidraw_page.ts';

const CONSOLE_HEADER = '[render-excalidraw] Browser console emitted errors:\n';

export class PlaywrightPngRenderer implements PngRenderer {
  readonly name = 'playwright-page';

  async render(request: PngRenderRequest): Promise<PngRenderResult> {
    request.signal?.throwIfAborted();
    const stderr: string[] = [];
    const png = await renderExcalidrawPage(request.options, request.scene, (scene) => scene as Record<string, unknown>, stderr);
    // excalidraw_page.ts writes console errors as a header line + "  <entry>\n" lines.
    const warnings = stderr[0] === CONSOLE_HEADER
      ? stderr.slice(1).map((line) => line.replace(/^ {2}/, '').replace(/\n$/, ''))
      : stderr.map((line) => line.replace(/\n$/, ''));
    return { png, ...pngSize(png), warnings, renderer: this.name };
  }
}

export const playwrightPngRenderer = new PlaywrightPngRenderer();
