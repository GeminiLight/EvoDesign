import { useCallback, useEffect, useRef, useState, type RefObject } from 'react';

/** Embedded browsers may deny native fullscreen; the viewport layout still works. */
export async function requestCanvasFullscreen(element: HTMLElement): Promise<boolean> {
  if (!element.ownerDocument.fullscreenEnabled || !element.requestFullscreen) return false;
  try {
    await element.requestFullscreen({ navigationUI: 'hide' });
    return element.ownerDocument.fullscreenElement === element;
  } catch {
    return false;
  }
}

export function useCanvasFullscreen(targetRef: RefObject<HTMLDivElement | null>) {
  const [native, setNative] = useState(false);
  const [viewport, setViewport] = useState(false);
  const pendingRef = useRef(false);
  const mountedRef = useRef(true);
  const openerRef = useRef<HTMLElement | null>(null);
  const wasFullscreenRef = useRef(false);
  const isFullscreen = native || viewport;

  useEffect(() => {
    mountedRef.current = true;
    const target = targetRef.current;
    const sync = () => setNative(Boolean(target && document.fullscreenElement === target));
    document.addEventListener('fullscreenchange', sync);
    sync();
    return () => {
      mountedRef.current = false;
      document.removeEventListener('fullscreenchange', sync);
      if (target && document.fullscreenElement === target) void document.exitFullscreen().catch(() => {});
    };
  }, [targetRef]);

  useEffect(() => {
    if (!isFullscreen && wasFullscreenRef.current) {
      const opener = openerRef.current;
      requestAnimationFrame(() => { if (opener?.isConnected) opener.focus({ preventScroll: true }); });
    }
    wasFullscreenRef.current = isFullscreen;
  }, [isFullscreen]);

  useEffect(() => {
    if (!viewport) return;
    const escape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape' || event.isComposing) return;
      event.preventDefault(); event.stopPropagation(); setViewport(false);
    };
    document.addEventListener('keydown', escape, true);
    return () => document.removeEventListener('keydown', escape, true);
  }, [viewport]);

  const toggleFullscreen = useCallback(async () => {
    const target = targetRef.current;
    if (!target || pendingRef.current) return;
    pendingRef.current = true;
    try {
      if (document.fullscreenElement === target) await document.exitFullscreen();
      else if (viewport) setViewport(false);
      else {
        openerRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
        const enteredNative = await requestCanvasFullscreen(target);
        if (!mountedRef.current) return;
        setNative(enteredNative);
        setViewport(!enteredNative);
        requestAnimationFrame(() => target.querySelector<HTMLElement>('.excalidraw, .tl-container')?.focus({ preventScroll: true }));
      }
    } finally { pendingRef.current = false; }
  }, [targetRef, viewport]);

  return { isFullscreen, toggleFullscreen };
}
