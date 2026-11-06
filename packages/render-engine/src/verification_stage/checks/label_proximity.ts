// Ported from evodesign/agentic_system/verification_stage/checks/label_proximity.py — keep in sync.
//
// Check that independent relationship labels remain near their connectors.

import { pyGet, pyGetItem } from '../../py/dict.ts';
import { PyTypeError } from '../../py/errors.ts';
import { pyFloatParse, pyRound } from '../../py/number.ts';
import { pyMin } from '../../py/sort.ts';
import { pyFormatFixed } from '../../py/str.ts';
import { isDict, truthy } from '../../py/truthy.ts';
import { disjoint_segment_box_distance } from '../../canvas_environment/scene.ts';
import { _arrow_segments, _bbox, _segment_intersects_rect_interior } from './collision_detection.ts';
import { Finding, Severity } from './finding.ts';

type Dict = Record<string, any>;

/** Python ``float(value)``. */
function _float(value: unknown): number {
  if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'string') return pyFloatParse(value);
  throw new PyTypeError('float() argument must be a string or a real number');
}

export function _segment_box_distance(start: readonly number[], end: readonly number[], box: readonly number[]): number {
  if (_segment_intersects_rect_interior(start, end, box)) {
    return 0.0;
  }
  return disjoint_segment_box_distance(start, end, box);
}

/** Report detached predicates too far from the edge they describe. */
export function check_edge_label_proximity(manifest: Dict): Finding[] {
  const elements = (pyGet(manifest, 'elements', []) as unknown[]).filter(
    (element) => isDict(element) && !truthy(pyGet(element, 'isDeleted'))
      && _float(pyGet(element, 'opacity', 100)) > 0,
  ) as Dict[];
  const arrows = new Map<unknown, Dict>();
  for (const element of elements) {
    if (pyGet(element, 'type') === 'arrow') arrows.set(pyGetItem(element, 'id'), element);
  }
  const semantic_arrows = new Map<unknown, Dict>();
  for (const arrow of arrows.values()) {
    const meta = truthy(pyGet(arrow, 'meta')) ? pyGet(arrow, 'meta') : {};
    semantic_arrows.set(pyGet(meta, 'semantic_edge_id'), arrow);
  }
  const findings: Finding[] = [];
  for (const label of elements) {
    // Native bound text is positioned by the renderer, not its saved x/y.
    if (pyGet(label, 'type') !== 'text' || truthy(pyGet(label, 'containerId'))) {
      continue;
    }
    const metadata = truthy(pyGet(label, 'meta')) ? pyGet(label, 'meta') : {};
    const edge_id = pyGet(metadata, 'semantic_edge_id');
    const arrowKey = pyGet(metadata, 'semantic_arrow_id');
    let arrow: Dict | null = arrows.has(arrowKey) ? arrows.get(arrowKey)! : null;
    if (arrow === null && truthy(edge_id)) {
      arrow = semantic_arrows.has(edge_id) ? semantic_arrows.get(edge_id)! : null;
    }
    const box = _bbox(label);
    if (arrow === null || box === null) {
      continue;
    }
    const segments = _arrow_segments(arrow);
    if (!segments.length) {
      continue;
    }
    const distance = pyMin(segments.map(([start, end]) => _segment_box_distance(start, end, box)));
    const font_size = _float(pyGet(label, 'fontSize', 16));
    const limit = Math.max(24.0, 1.5 * font_size);
    const major_limit = Math.max(48.0, 3.0 * font_size);
    if (distance > limit) {
      findings.push(new Finding({
        category: 'binding/edge_label_distance',
        severity: distance > major_limit ? Severity.MAJOR : Severity.MINOR,
        element_id: pyGet(label, 'id') as string | null,
        message: `Relationship label is ${pyFormatFixed(distance, 1)}px from its connector; keep it within ${pyFormatFixed(limit, 0)}px of that edge.`,
        location: { arrow_id: pyGetItem(arrow, 'id'), distance: pyRound(distance, 1), limit },
      }));
    }
  }
  return findings;
}
