import { useEffect, useRef, useState } from 'react';
import type { CSSProperties, KeyboardEvent, PointerEvent } from 'react';
import { clampFloatingAnchor, defaultFloatingAnchor, floatingPanelPosition, isAnchorDrag } from '../utils/floatingAnchor';
import type { AnchorPoint } from '../utils/floatingAnchor';

const storageKey = 'evodesign.assistant-anchor.v1';
const viewport = () => ({ width: window.innerWidth, height: window.innerHeight,
  top: document.querySelector('.studio-header')?.getBoundingClientRect().bottom ?? 64 });
function initialAnchor() {
  const bounds = viewport();
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey) ?? 'null');
    if (saved && Number.isFinite(saved.x) && Number.isFinite(saved.y)) return clampFloatingAnchor(saved, bounds);
  } catch { /* Device preferences can be unavailable in private browsing. */ }
  return defaultFloatingAnchor(bounds);
}
export function useFloatingAssistant() {
  const [point, setPoint] = useState<AnchorPoint>(initialAnchor);
  const [dragging, setDragging] = useState(false);
  const drag = useRef<{ pointerId: number; start: AnchorPoint; origin: AnchorPoint; moved: boolean } | null>(null);
  const suppressClick = useRef(false);
  const lastPoint = useRef(point);
  const move = (next: AnchorPoint) => { const bounded = clampFloatingAnchor(next, viewport()); lastPoint.current = bounded; setPoint(bounded); };
  const persist = () => { try { localStorage.setItem(storageKey, JSON.stringify(lastPoint.current)); } catch { /* Position remains available for this visit. */ } };
  useEffect(() => {
    const resize = () => setPoint(current => { const next = clampFloatingAnchor(current, viewport()); lastPoint.current = next; return next; });
    window.addEventListener('resize', resize);
    return () => window.removeEventListener('resize', resize);
  }, []);
  const onPointerDown = (event: PointerEvent<HTMLButtonElement>) => {
    if (event.button !== 0) return;
    suppressClick.current = false;
    drag.current = { pointerId: event.pointerId, start: { x: event.clientX, y: event.clientY }, origin: point, moved: false };
    event.currentTarget.setPointerCapture(event.pointerId);
  };
  const onPointerMove = (event: PointerEvent<HTMLButtonElement>) => {
    const active = drag.current;
    if (!active || active.pointerId !== event.pointerId) return;
    const current = { x: event.clientX, y: event.clientY };
    active.moved ||= isAnchorDrag(active.start, current);
    if (!active.moved) return;
    event.preventDefault(); setDragging(true); suppressClick.current = true;
    move({ x: active.origin.x + current.x - active.start.x, y: active.origin.y + current.y - active.start.y });
  };
  const onPointerUp = (event: PointerEvent<HTMLButtonElement>) => {
    if (drag.current?.pointerId !== event.pointerId) return;
    if (drag.current.moved) persist();
    drag.current = null; setDragging(false);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
  };
  const onPointerCancel = (event: PointerEvent<HTMLButtonElement>) => {
    suppressClick.current = true; onPointerUp(event);
  };
  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    const offsets: Record<string, AnchorPoint> = { ArrowLeft: { x: -16, y: 0 }, ArrowRight: { x: 16, y: 0 }, ArrowUp: { x: 0, y: -16 }, ArrowDown: { x: 0, y: 16 } };
    const delta = offsets[event.key];
    if (!delta) { suppressClick.current = false; return; }
    event.preventDefault(); event.stopPropagation();
    move({ x: point.x + delta.x, y: point.y + delta.y }); persist();
  };
  const panel = floatingPanelPosition(point, viewport());
  return { dragging, launcherStyle: { left: point.x, top: point.y, right: 'auto', bottom: 'auto' } as CSSProperties,
    panelBelow: panel.top > point.y,
    panelStyle: { ...panel, right: 'auto', bottom: 'auto', '--assistant-tail-right': `${Math.max(14, Math.min(panel.width - 24, panel.left + panel.width - point.x - 29))}px` } as CSSProperties,
    handlers: { onPointerDown, onPointerMove, onPointerUp, onPointerCancel, onKeyDown },
    consumeDragClick: () => { const suppressed = suppressClick.current; suppressClick.current = false; return suppressed; } };
}
