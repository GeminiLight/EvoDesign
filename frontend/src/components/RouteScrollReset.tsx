import { useLayoutEffect } from 'react';
import { useLocation } from 'react-router-dom';

/** A page change must not carry the previous page's scroll into the editor. */
export function RouteScrollReset() {
  const { pathname } = useLocation();
  useLayoutEffect(() => {
    window.scrollTo({ top: 0, left: 0, behavior: 'instant' });
  }, [pathname]);
  return null;
}
