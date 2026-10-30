export type AnchorPoint = { x: number; y: number };
export type AnchorViewport = { width: number; height: number; top: number };
export function clampFloatingAnchor(point: AnchorPoint, viewport: AnchorViewport): AnchorPoint {
  return { x: Math.max(12, Math.min(point.x, viewport.width - 60)),
    y: Math.max(viewport.top + 12, Math.min(point.y, Math.max(viewport.top + 12, viewport.height - 84))) };
}
export function defaultFloatingAnchor(viewport: AnchorViewport): AnchorPoint {
  return clampFloatingAnchor({ x: viewport.width - 96, y: viewport.height - 140 }, viewport);
}
export function isAnchorDrag(start: AnchorPoint, current: AnchorPoint): boolean {
  return Math.hypot(current.x - start.x, current.y - start.y) >= 6;
}
export function floatingPanelPosition(anchor: AnchorPoint, viewport: AnchorViewport) {
  const width = Math.min(350, Math.max(0, viewport.width - 24));
  const height = Math.min(440, Math.max(0, viewport.height - viewport.top - 32));
  const above = anchor.y - height - 14;
  const top = above >= viewport.top + 12 ? above : Math.min(viewport.height - height - 12, anchor.y + 62);
  return { left: Math.max(12, Math.min(anchor.x + 48 - width, viewport.width - width - 12)),
    top: Math.max(viewport.top + 12, top), width, height };
}
