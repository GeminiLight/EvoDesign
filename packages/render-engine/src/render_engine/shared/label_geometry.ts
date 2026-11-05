// Ported from evodesign/agentic_system/render_engine/shared/label_geometry.py — keep in sync.
//
// Shared distance calculation for a label box clear of a connector segment.

import { hypot } from '../../py/math.ts';
import { pyMax, pyMin } from '../../py/sort.ts';
import { truthy } from '../../py/truthy.ts';

type Point = readonly [number, number] | readonly number[];

/** Return the exact gap after the caller has ruled out an intersection. */
export function disjoint_segment_box_distance(start: Point, end: Point, box: readonly number[]): number {
  const [left, top, width, height] = box;
  const [right, bottom] = [left + width, top + height];
  const distances = [start, end].map(([x, y]) =>
    hypot(pyMax([left - x, x - right, 0]), pyMax([top - y, y - bottom, 0])));
  const [dx, dy] = [end[0] - start[0], end[1] - start[1]];
  const squared_length = dx * dx + dy * dy;
  if (truthy(squared_length)) {
    for (const [x, y] of [[left, top], [right, top], [left, bottom], [right, bottom]]) {
      const fraction = pyMax([0.0, pyMin([1.0, ((x - start[0]) * dx + (y - start[1]) * dy) / squared_length])]);
      distances.push(hypot(x - start[0] - fraction * dx, y - start[1] - fraction * dy));
    }
  }
  return pyMin(distances);
}
