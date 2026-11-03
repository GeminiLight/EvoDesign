import {
  MAX_EXCALIDRAW_EXPORT_SCALE,
  MAX_RENDER_MARGIN,
  MAX_RENDER_TIMEOUT_MS,
  MAX_RENDERER_VIEWPORT,
} from './renderDefaults';

const LOCAL_RENDERER_HOSTS = new Set([
  'localhost',
  '127.0.0.1',
  '::1',
  '[::1]',
  '0.0.0.0',
]);

function normalizePathname(pathname: string): string {
  if (pathname === '/') return pathname;
  return pathname.replace(/\/+$/, '');
}

export function assertBoundedNumber(
  value: number,
  field: string,
  min: number,
  max: number,
): number {
  if (!Number.isFinite(value)) {
    throw new Error(`${field} must be a finite number`);
  }
  if (value < min || value > max) {
    throw new Error(`${field} must be between ${min} and ${max}`);
  }
  return value;
}

export function validateRendererUrl(url: string, expectedPathname: string): string {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    throw new Error('Renderer URL is invalid');
  }

  if (!['http:', 'https:'].includes(parsed.protocol)) {
    throw new Error('Renderer URL must use http or https');
  }
  if (!LOCAL_RENDERER_HOSTS.has(parsed.hostname)) {
    throw new Error('Renderer URL must point to a local host');
  }
  if (normalizePathname(parsed.pathname) !== normalizePathname(expectedPathname)) {
    throw new Error(`Renderer URL must point to ${expectedPathname}`);
  }

  return parsed.toString();
}

export function validateRenderDimensions(width: number, height: number): void {
  assertBoundedNumber(width, 'viewport width', 1, MAX_RENDERER_VIEWPORT.width);
  assertBoundedNumber(height, 'viewport height', 1, MAX_RENDERER_VIEWPORT.height);
}

export function validateRenderTimeout(timeoutMs: number): void {
  assertBoundedNumber(timeoutMs, 'timeout', 1, MAX_RENDER_TIMEOUT_MS);
}

export function validateRenderMargin(margin: number): void {
  assertBoundedNumber(margin, 'margin', 0, MAX_RENDER_MARGIN);
}

export function validateExcalidrawExportScale(scale: number): void {
  assertBoundedNumber(scale, 'scale', 0.01, MAX_EXCALIDRAW_EXPORT_SCALE);
}
