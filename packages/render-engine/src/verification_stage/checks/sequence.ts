// Ported from evodesign/agentic_system/verification_stage/checks/sequence.py — keep in sync.
//
// Independent sequence identity and chronology checks on the rendered scene.

import { pyGet, pyGetItem } from '../../py/dict.ts';
import { pyIn } from '../../py/eq.ts';
import { pyMax, pyMin, pySorted } from '../../py/sort.ts';
import { pyLower, pyStr } from '../../py/str.ts';
import { truthy } from '../../py/truthy.ts';
import { Finding, Severity } from './finding.ts';

type Dict = Record<string, any>;

function _or(value: unknown, fallback: unknown): any {
  return truthy(value) ? value : fallback;
}

export function check_sequence(manifest: Dict, structure: Dict | null): Finding[] {
  if (!truthy(structure) || pyGet(structure, 'chart_type') !== 'sequence_diagram') {
    return [];
  }
  const s = structure!;
  const elements = new Map<unknown, Dict>();
  for (const element of pyGet(manifest, 'elements', []) as Dict[]) {
    if (!truthy(pyGet(element, 'isDeleted')) && (pyGet(element, 'opacity', 100) as number) > 0) {
      elements.set(pyGetItem(element, 'id'), element);
    }
  }
  const id_map = pyGet(pyGet(manifest, '_meta', {}), 'id_map', {}) as Dict;
  const arrows = new Map<unknown, Dict>();
  for (const element of elements.values()) {
    if (pyGet(element, 'type') === 'arrow') {
      arrows.set(pyGet(pyGet(element, 'meta', {}), 'semantic_edge_id'), element);
    }
  }
  const findings: Finding[] = [];

  const fail = (message: string, element_id: unknown = null): void => {
    findings.push(new Finding({
      category: 'sequence/chronology', severity: Severity.MAJOR,
      message, element_id: element_id as string | null,
    }));
  };

  const centers: Record<string, number> = {};
  const tops: number[] = [];
  for (const node of pyGet(s, 'nodes', []) as Dict[]) {
    const headerKey = pyGet(id_map, pyGetItem(node, 'id'));
    const header = elements.has(headerKey) ? elements.get(headerKey)! : null;
    if (!truthy(header)) {
      fail(`Missing sequence participant: ${pyStr(pyGetItem(node, 'label'))}`);
      continue;
    }
    const h = header!;
    const nodeId = pyGetItem(node, 'id') as string;
    centers[nodeId] = pyGetItem(h, 'x') + pyGetItem(h, 'width') / 2;
    tops.push(pyGetItem(h, 'y'));
    const lines = [...elements.values()].filter((element) => pyGet(element, 'type') === 'line'
      && pyGet(element, 'strokeStyle') === 'dashed'
      && Math.abs((pyGet(element, 'x', 0) as number) - centers[nodeId]) <= 2
      && Math.abs((pyGet(element, 'y', 0) as number) - pyGetItem(h, 'y') - pyGetItem(h, 'height')) <= 2
      && (pyGet(element, 'height', 0) as number) > 0 && Math.abs(pyGet(element, 'width', 0) as number) <= 2);
    if (lines.length !== 1) {
      fail(`Participant ${pyStr(pyGetItem(node, 'label'))} needs one vertical dashed lifeline`, pyGetItem(h, 'id'));
    }
  }
  if (tops.length && pyMax(tops) - pyMin(tops) > 2) {
    fail('Sequence participant headers must share the same top row');
  }
  let previous_bottom = -Infinity;
  for (const edge of pySorted(pyGet(s, 'edges', []) as Dict[], (item) => pyGet(item, 'sequence_idx', -1))) {
    const edgeKey = pyGetItem(edge, 'id');
    const arrow = arrows.has(edgeKey) ? arrows.get(edgeKey)! : null;
    if (arrow === null) {
      fail(`Missing sequence message: ${pyStr(edgeKey)}`);
      continue;
    }
    const points: [number, number][] = (pyGet(arrow, 'points', []) as number[][]).map(
      (point) => [pyGetItem(arrow, 'x') + point[0], pyGetItem(arrow, 'y') + point[1]],
    );
    if (points.length < 2) {
      fail('Sequence message has no usable geometry', pyGetItem(arrow, 'id'));
      continue;
    }
    const top = pyMin(points.map(([, y]) => y));
    const bottom = pyMax(points.map(([, y]) => y));
    if (top <= previous_bottom + 2) {
      fail('Sequence messages are not in distinct chronological rows', pyGetItem(arrow, 'id'));
    }
    previous_bottom = bottom;
    if (pyGetItem(edge, 'source') !== pyGetItem(edge, 'target') && bottom - top > 2) {
      fail('Sequence message must be horizontal between lifelines', pyGetItem(arrow, 'id'));
    }
    for (const [point, endpoint] of [[points[0], pyGetItem(edge, 'source')], [points[points.length - 1], pyGetItem(edge, 'target')]] as const) {
      if (pyIn(endpoint, centers) && Math.abs(point[0] - centers[endpoint as string]) > 2) {
        fail('Sequence message is disconnected from its participant lifeline', pyGetItem(arrow, 'id'));
      }
    }
    const kind = pyLower(pyStr(_or(_or(pyGet(edge, 'message_kind'), pyGet(edge, 'message_type')), '')));
    if (['return', 'reply', 'response'].includes(kind) && pyGet(arrow, 'strokeStyle') !== 'dashed') {
      fail('Sequence return message must use a dashed arrow', pyGetItem(arrow, 'id'));
    }
  }
  return findings;
}
