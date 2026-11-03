export const DEFAULT_RENDERER_VIEWPORT = {
  width: 4000,
  height: 4000,
} as const;

export const DEFAULT_RENDER_TIMEOUT_MS = 60000;
export const DEFAULT_RENDER_MARGIN = 40;
export const DEFAULT_EXCALIDRAW_EXPORT_SCALE = 4;

export const MAX_RENDERER_VIEWPORT = {
  width: 8000,
  height: 8000,
} as const;

export const MAX_RENDER_TIMEOUT_MS = 300000;
export const MAX_RENDER_MARGIN = 1000;
export const MAX_EXCALIDRAW_EXPORT_SCALE = 4;

// Snapshot routes render at this device scale factor unless the requested
// viewport would exceed MAX_RENDER_DEVICE_PIXELS, in which case the scale is
// reduced so width * height * scale^2 stays within the cap. The default
// viewport (4000x4000 at scale 2) sits exactly at the cap.
export const DEFAULT_RENDER_DEVICE_SCALE_FACTOR = 2;
export const MAX_RENDER_DEVICE_PIXELS = 4000 * 4000 * 4;

// Excalidraw exports size their canvas from the scene extent, not the
// viewport, so the export canvas is clamped separately.
export const MAX_EXCALIDRAW_EXPORT_PIXELS = 4000 * 4000 * 4;
export const MAX_EXCALIDRAW_EXPORT_SIDE = 16384;

/** Largest device scale factor (<= preferred) that keeps the viewport under the pixel cap. */
export function clampDeviceScaleFactor(
  width: number,
  height: number,
  preferred: number = DEFAULT_RENDER_DEVICE_SCALE_FACTOR,
  maxPixels: number = MAX_RENDER_DEVICE_PIXELS,
): number {
  const area = width * height;
  if (!(area > 0)) return preferred;
  return Math.min(preferred, Math.sqrt(maxPixels / area));
}

/** Export scale (<= requested) keeping the Excalidraw export canvas within both caps. */
export function clampExcalidrawExportScale(
  width: number,
  height: number,
  requested: number,
): number {
  if (!(width > 0) || !(height > 0)) return requested;
  return Math.min(
    requested,
    Math.sqrt(MAX_EXCALIDRAW_EXPORT_PIXELS / (width * height)),
    MAX_EXCALIDRAW_EXPORT_SIDE / width,
    MAX_EXCALIDRAW_EXPORT_SIDE / height,
  );
}
