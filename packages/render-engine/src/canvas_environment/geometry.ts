// Ported from evodesign/canvas_environment/geometry.py — keep in sync.
//
// Edge-geometry facade for canvas manifests.
//
// Arrow shape is backend-specific: an Excalidraw arrow bakes its path into an
// absolute ``x``/``y`` plus an origin-relative ``points`` polyline, so any
// consumer that moves a shape has to ask the canvas backend to redraw the arrows
// attached to it. This module exposes that one capability as a public, backend
// neutral call, keeping the routing math itself inside the render engine.

import { normalize_canvas_library } from '../canvas_runtime.ts';
import { NotImplementedError } from '../py/errors.ts';
import { pyRepr } from '../py/str.ts';
import * as _render_engine_adapter from './_render_engine_adapter.ts';
import { get_canvas_capabilities } from './capabilities.ts';

type Dict = Record<string, unknown>;

// Sides an arrow may leave from / arrive at. Anything else is treated as "no
// hint" rather than an error: a hint is advisory by definition.
export const ARROW_SIDES = ['top', 'bottom', 'left', 'right'] as const;

/**
 * Backend-neutral geometry for one re-routed arrow.
 *
 * ``points`` are relative to ``(x, y)`` — the element storage form —
 * while ``absolute_points`` are canvas coordinates, which is what a caller
 * needs to reposition anything riding along the arrow (an edge label, say).
 *
 * ``@dataclass(frozen=True)``
 */
export class ArrowRouteGeometry {
  constructor(
    readonly x: number,
    readonly y: number,
    readonly width: number,
    readonly height: number,
    readonly points: number[][],
    readonly absolute_points: number[][],
    readonly start_side: string,
    readonly end_side: string,
  ) {
    Object.freeze(this);
  }
}

export function _normalize_side(side: string | null): string | null {
  if (typeof side === 'string' && (ARROW_SIDES as readonly string[]).includes(side)) {
    return side;
  }
  return null;
}

/** ``float(x)`` */
function _float(value: unknown): number {
  return Number(value);
}

export function _as_bbox(bbox: Dict): { x: number; y: number; w: number; h: number } {
  return {
    x: _float(bbox.x),
    y: _float(bbox.y),
    w: _float(bbox.w),
    h: _float(bbox.h),
  };
}

/**
 * Recompute an arrow's geometry from the bboxes of the shapes it connects.
 *
 * Both bboxes are ``{"x", "y", "w", "h"}`` in canvas units. The optional side
 * hints name the face each end currently uses; the backend keeps a hint when
 * the new geometry still supports it and picks the face from geometry
 * otherwise.
 *
 * Only canvases whose capability matrix marks the refiner as supported can be
 * routed here.
 */
export function route_arrow_between_bboxes(
  source_bbox: Dict,
  target_bbox: Dict,
  canvas_library = 'excalidraw',
  start_side_hint: string | null = null,
  end_side_hint: string | null = null,
): ArrowRouteGeometry {
  canvas_library = normalize_canvas_library(canvas_library);
  const capabilities = get_canvas_capabilities(canvas_library);
  if (!capabilities.supports_refiner) {
    throw new NotImplementedError(
      'route_arrow_between_bboxes rewrites stored arrow geometry and is '
      + 'only available for canvases with refinement support; '
      + `canvas_library=${pyRepr(capabilities.canvas_library)} does not have it.`,
    );
  }

  const result = _render_engine_adapter.route_excalidraw_arrow(
    _as_bbox(source_bbox),
    _as_bbox(target_bbox),
    _normalize_side(start_side_hint),
    _normalize_side(end_side_hint),
  );
  return new ArrowRouteGeometry(
    _float(result.x),
    _float(result.y),
    _float(result.width),
    _float(result.height),
    (result.points as number[][]).map(([px, py]) => [_float(px), _float(py)]),
    (result.absolute_points as number[][]).map(([px, py]) => [_float(px), _float(py)]),
    String(result.start_side),
    String(result.end_side),
  );
}

export const __all__ = ['ARROW_SIDES', 'ArrowRouteGeometry', 'route_arrow_between_bboxes'];
