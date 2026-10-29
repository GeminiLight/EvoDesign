import { useLayoutEffect } from 'react';
import type { RefObject } from 'react';

/** The native top layer avoids clipping inside scrolling settings dialogs. */
export function useAnchoredPopover(open: boolean, anchorRef: RefObject<HTMLElement | null>, panelRef: RefObject<HTMLElement | null>, width: number | 'anchor' = 232, placement: 'auto' | 'below' = 'auto', align: 'start' | 'end' = 'start') {
  useLayoutEffect(() => {
    if (!open) return;
    const position = () => {
      const anchor = anchorRef.current?.getBoundingClientRect();
      const panel = panelRef.current;
      if (!anchor || !panel) return;
      if (typeof panel.showPopover === 'function' && !panel.matches(':popover-open')) panel.showPopover();
      const viewport = window.visualViewport;
      const bottom = viewport ? Math.min(window.innerHeight, viewport.height + viewport.offsetTop) : window.innerHeight;
      const panelWidth = Math.min(width === 'anchor' ? anchor.width : width, window.innerWidth - 24);
      panel.style.width = `${panelWidth}px`;
      panel.style.left = `${Math.max(12, Math.min(align === 'end' ? anchor.right - panelWidth : anchor.left, window.innerWidth - panelWidth - 12))}px`;
      const headerBottom = document.querySelector('.studio-header')?.getBoundingClientRect().bottom ?? 0;
      const above = Math.max(0, anchor.top - Math.max(12, headerBottom + 8) - 8);
      const below = Math.max(0, bottom - anchor.bottom - 20);
      panel.style.maxHeight = '300px';
      const height = Math.min(panel.scrollHeight, 300);
      const side = placement === 'below' && below >= height ? 'below' : above >= height || above >= below ? 'above' : 'below';
      const available = Math.min(300, side === 'above' ? above : below);
      panel.style.maxHeight = `${available}px`;
      panel.style.top = `${side === 'above' ? anchor.top - Math.min(height, available) - 8 : anchor.bottom + 8}px`;
    };
    const observer = new ResizeObserver(position);
    if (panelRef.current) observer.observe(panelRef.current);
    position();
    const onScroll = (event: Event) => { if (!(event.target instanceof Node) || !panelRef.current?.contains(event.target)) position(); };
    window.addEventListener('resize', position);
    window.addEventListener('scroll', onScroll, true);
    window.visualViewport?.addEventListener('resize', position);
    return () => {
      observer.disconnect();
      window.removeEventListener('resize', position);
      window.removeEventListener('scroll', onScroll, true);
      window.visualViewport?.removeEventListener('resize', position);
    };
  }, [open, anchorRef, panelRef, width, placement, align]);
}
