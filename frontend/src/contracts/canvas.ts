import type { CanvasLibrary } from '../types/api';

export const DEFAULT_CANVAS_LIBRARY: CanvasLibrary = 'excalidraw';
export const CANVAS_LIBRARIES = ['excalidraw', 'tldraw'] as const satisfies readonly CanvasLibrary[];

const CANVAS_LIBRARY_SET = new Set<string>(CANVAS_LIBRARIES);

export function isCanvasLibrary(value: unknown): value is CanvasLibrary {
  return typeof value === 'string' && CANVAS_LIBRARY_SET.has(value);
}

export function normalizeCanvasLibraryOrNull(value: unknown): CanvasLibrary | null {
  if (value == null || value === '') {
    return null;
  }

  const canvasLibrary = String(value).trim().toLowerCase();
  return isCanvasLibrary(canvasLibrary) ? canvasLibrary : null;
}

export function normalizeCanvasLibraryOrDefault(value: unknown): CanvasLibrary {
  if (value == null || value === '') {
    return DEFAULT_CANVAS_LIBRARY;
  }

  const canvasLibrary = normalizeCanvasLibraryOrNull(value);
  if (canvasLibrary) {
    return canvasLibrary;
  }

  throw new Error(`Unsupported canvas library: ${String(value)}`);
}
