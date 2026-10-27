import type { ExcalidrawImperativeAPI } from '@excalidraw/excalidraw/types';
import type { ExcalidrawElement } from '@excalidraw/excalidraw/element/types';

/** Native fitting rounds down in 10% steps, leaving large diagrams unnecessarily small. */
export async function fitExcalidraw(api: ExcalidrawImperativeAPI, elements: readonly ExcalidrawElement[], duration = 240) {
  const visible = elements.filter(element => !element.isDeleted);
  if (!visible.length) return;
  const { getCommonBounds } = await import('@excalidraw/excalidraw');
  const [left, top, right, bottom] = getCommonBounds(visible);
  const { width, height } = api.getAppState();
  const offsets = { top: 80, bottom: 64, left: 24, right: 24 };
  const zoom = Math.max(0.1, Math.min(1,
    (width - offsets.left - offsets.right) / Math.max(1, right - left),
    (height - offsets.top - offsets.bottom) / Math.max(1, bottom - top),
  ) * 0.96);
  api.scrollToContent(visible, {
    fitToContent: true, minZoom: zoom, maxZoom: zoom, canvasOffsets: offsets,
    animate: !window.matchMedia('(prefers-reduced-motion: reduce)').matches, duration,
  });
}
