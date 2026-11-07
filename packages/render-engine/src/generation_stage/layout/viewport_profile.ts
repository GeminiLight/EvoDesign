// Ported from evodesign/agentic_system/generation_stage/layout/viewport_profile.py — keep in sync.
//
// Choose a bounded logical viewport for the layout agent.

import { CANVAS_DEFAULT_VIEWPORT_HEIGHT, CANVAS_DEFAULT_VIEWPORT_WIDTH } from '../../canvas_runtime.ts';
import { KeyError } from '../../py/errors.ts';
import { cpLen, pyStr, pyStrip } from '../../py/str.ts';
import { isMapping, pyLen, pyOr, truthy } from '../../py/truthy.ts';

type PyMapping = Record<string, unknown> | Map<unknown, unknown>;

/** ``mapping.get(key, default)`` on a dict or ``Map``. */
function get(mapping: PyMapping, key: string, defaultValue: unknown = null): unknown {
  if (mapping instanceof Map) return mapping.has(key) ? mapping.get(key) : defaultValue;
  return Object.prototype.hasOwnProperty.call(mapping, key) ? mapping[key] : defaultValue;
}

/** ``for item in value`` over a JSON-ish value. */
function iterate(value: unknown): unknown[] {
  if (Array.isArray(value)) return value;
  if (typeof value === 'string') return [...value];
  if (value instanceof Map) return [...value.keys()];
  if (value instanceof Set) return [...value];
  if (value !== null && typeof value === 'object') return Object.keys(value);
  throw new TypeError(`'${typeof value}' object is not iterable`);
}

/** Program-selected composition budget passed to the layout model. (frozen dataclass) */
export class LayoutViewportPlan {
  readonly profile: string;
  readonly width: number;
  readonly height: number;
  readonly node_count: number;
  readonly edge_count: number;
  readonly group_count: number;
  readonly label_char_count: number;

  constructor(
    profile: string,
    width: number,
    height: number,
    node_count: number,
    edge_count: number,
    group_count: number,
    label_char_count: number,
  ) {
    this.profile = profile;
    this.width = width;
    this.height = height;
    this.node_count = node_count;
    this.edge_count = edge_count;
    this.group_count = group_count;
    this.label_char_count = label_char_count;
    Object.freeze(this);
  }

  to_prompt(): string {
    return (
      '- Program-selected profile: '
      + `${this.profile}\n`
      + `- Preferred logical viewport: ${pyStr(this.width)} x ${pyStr(this.height)}\n`
      + "- Target content occupancy: 70%-90% of the preferred viewport's "
      + 'longest axis\n'
      + `- Input load: ${pyStr(this.node_count)} nodes, ${pyStr(this.edge_count)} edges, `
      + `${pyStr(this.group_count)} groups, ${pyStr(this.label_char_count)} label characters\n`
      + `- Hard safety bounds: ${CANVAS_DEFAULT_VIEWPORT_WIDTH} x `
      + `${CANVAS_DEFAULT_VIEWPORT_HEIGHT}\n`
      + '- Treat the preferred viewport as the composition constraint. '
      + 'Exceed it only when the supplied minimum element sizes cannot fit; '
      + 'never spread elements merely to fill the hard safety bounds.'
    );
  }
}

/** Unbound method form for the parity harness: ``LayoutViewportPlan.to_prompt(self)``. */
export function LayoutViewportPlan_to_prompt(self: LayoutViewportPlan | Record<string, unknown>): string {
  const plan = self instanceof LayoutViewportPlan
    ? self
    : new LayoutViewportPlan(
      self.profile as string,
      self.width as number,
      self.height as number,
      self.node_count as number,
      self.edge_count as number,
      self.group_count as number,
      self.label_char_count as number,
    );
  return plan.to_prompt();
}

export const _PROFILES: Readonly<Record<string, readonly [number, number]>> = {
  compact: [1200, 800],
  wide: [1600, 900],
  large: [2400, 1600],
  extended: [3200, 2200],
};

export function _label_char_count(structure: PyMapping): number {
  let count = 0;
  for (const collection of ['nodes', 'groups']) {
    for (const item of iterate(pyOr(get(structure, collection, []), []))) {
      if (isMapping(item)) {
        count += cpLen(pyStrip(pyStr(pyOr(get(item, 'label'), ''))));
      }
    }
  }
  for (const edge of iterate(pyOr(get(structure, 'edges', []), []))) {
    if (isMapping(edge)) {
      count += cpLen(pyStrip(pyStr(pyOr(get(edge, 'label'), ''))));
    }
  }
  return count;
}

/**
 * Select a viewport from semantic load instead of exposing a 4000px blank page.
 *
 * Draw.io's compact single-page discipline works because the model receives a
 * real composition budget. EvoDesign keeps its 4000 x 4000 hard bounds for
 * exceptional diagrams, but ordinary inputs get a substantially smaller
 * preferred viewport chosen before coordinates are generated.
 */
export function choose_layout_viewport(
  structure_instantiation: PyMapping | null,
): LayoutViewportPlan {
  const structure = (truthy(structure_instantiation) ? structure_instantiation : {}) as PyMapping;
  const nodes = iterate(pyOr(get(structure, 'nodes', []), [])).filter((item) => isMapping(item));
  const edges = iterate(pyOr(get(structure, 'edges', []), [])).filter((item) => isMapping(item));
  const groups = iterate(pyOr(get(structure, 'groups', []), [])).filter((item) => isMapping(item));
  const label_chars = _label_char_count(structure);

  const node_count = pyLen(nodes);
  const edge_count = pyLen(edges);
  const group_count = pyLen(groups);

  // Relationships and organizers both consume routing space, while long labels
  // consume horizontal space. Keep the thresholds intentionally coarse so a
  // small semantic change does not make the whole composition jump profiles.
  const complexity = (
    node_count
    + edge_count * 0.45
    + group_count * 2.0
    + Math.max(0, label_chars - node_count * 14) / 90.0
  );
  let profile: string;
  if (node_count <= 8 && complexity <= 14) {
    profile = 'compact';
  } else if (node_count <= 16 && complexity <= 28) {
    profile = 'wide';
  } else if (node_count <= 32 && complexity <= 52) {
    profile = 'large';
  } else {
    profile = 'extended';
  }

  if (!Object.prototype.hasOwnProperty.call(_PROFILES, profile)) throw new KeyError(`'${profile}'`);
  const [width, height] = _PROFILES[profile];
  return new LayoutViewportPlan(
    profile,
    width,
    height,
    node_count,
    edge_count,
    group_count,
    label_chars,
  );
}

export const __all__ = ['LayoutViewportPlan', 'choose_layout_viewport'];
