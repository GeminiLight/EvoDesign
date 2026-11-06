// Ported from evodesign/agentic_system/common/diagram_types.py — keep in sync.
//
// Canonical diagram-type registry shared by generation stages.

import { assetIsDir, globAssets, pathStem } from '../py/assets.ts';
import { pyGet } from '../py/dict.ts';
import { ValueError } from '../py/errors.ts';
import { pySorted } from '../py/sort.ts';
import { pyRepr, pyStr, pyStrip } from '../py/str.ts';
import { truthy } from '../py/truthy.ts';

// Python keeps absolute ``Path`` objects; the port keeps paths relative to
// ``evodesign/agentic_system`` and reads them through py/assets.ts.
export const SYSTEM_PROMPT_DIR = 'system_prompt';
export const TYPE_PATTERNS_DIR = `${SYSTEM_PROMPT_DIR}/type_patterns`;

export const DIAGRAM_TYPE_ALIASES: Readonly<Record<string, string>> = {
  architecture_diagram: 'architecture',
  class: 'class_diagram',
  class_diagram: 'class_diagram',
  concept: 'concept_map',
  concept_map: 'concept_map',
  containment_diagram: 'nested',
  customer_journey: 'user_journey',
  customer_journey_map: 'user_journey',
  cycle_diagram: 'cycle',
  data_flow: 'data_flow_diagram',
  data_flow_diagram: 'data_flow_diagram',
  dataflow: 'data_flow_diagram',
  dependency: 'dependency_graph',
  dependency_diagram: 'dependency_graph',
  dependency_graph: 'dependency_graph',
  deployment_diagram: 'deployment',
  er: 'er_diagram',
  er_diagram: 'er_diagram',
  fishbone_diagram: 'fishbone',
  flow: 'flowchart',
  flow_chart: 'flowchart',
  flow_diagram: 'flowchart',
  flywheel: 'cycle',
  funnel_chart: 'funnel',
  gantt_chart: 'gantt',
  hybrid: 'infographic',
  infographic: 'infographic',
  infrastructure_diagram: 'deployment',
  journey_map: 'user_journey',
  kanban_board: 'kanban',
  layer_diagram: 'layer_stack',
  layered_diagram: 'layer_stack',
  layers: 'layer_stack',
  loop: 'cycle',
  loop_diagram: 'cycle',
  matrix_chart: 'matrix',
  mind_map: 'mindmap',
  nested_diagram: 'nested',
  network: 'network_topology',
  network_diagram: 'network_topology',
  org_chart: 'orgchart',
  priority_quadrant: 'quadrant',
  quadrant_chart: 'quadrant',
  quadrant_diagram: 'quadrant',
  sequence: 'sequence_diagram',
  sequence_diagram: 'sequence_diagram',
  stack_diagram: 'layer_stack',
  state: 'state_diagram',
  state_diagram: 'state_diagram',
  state_machine: 'state_diagram',
  story_mapping: 'story_map',
  swimlane_diagram: 'swimlane',
  swot_analysis: 'swot',
  task_board: 'kanban',
  timeline_diagram: 'timeline',
  tree_diagram: 'tree',
  two_by_two: 'quadrant',
  uml_class_diagram: 'class_diagram',
  uml_deployment_diagram: 'deployment',
  user_journey_map: 'user_journey',
  user_story_map: 'story_map',
  venn_diagram: 'venn',
};

/** Raised when a caller supplies a diagram type outside the supported catalog. */
export class DiagramTypeValidationError extends ValueError {}

/** Normalize a free-form chart type or stage name into a stable lookup key. */
export function slugify(value: string): string {
  return pyStrip(pyStrip(value).toLowerCase().replace(/[^a-z0-9]+/gu, '_'), '_');
}

let supportedCache: readonly string[] | undefined;

/** Return the canonical diagram types backed by curated type-pattern files (``lru_cache(maxsize=1)``). */
export function get_supported_diagram_types(): readonly string[] {
  if (supportedCache === undefined) {
    supportedCache = !assetIsDir(TYPE_PATTERNS_DIR)
      ? []
      : pySorted(globAssets(TYPE_PATTERNS_DIR, '*.md').map(pathStem));
  }
  return supportedCache;
}

/** Map dataset/user chart type labels onto canonical knowledge keys. */
export function normalize_diagram_type(diagram_type: string | null | undefined): string {
  if (!truthy(diagram_type)) {
    return '';
  }
  const normalized = slugify(pyStr(diagram_type));
  return pyGet(DIAGRAM_TYPE_ALIASES, normalized, normalized);
}

/** Return whether *diagram_type* resolves to a supported canonical type. */
export function is_supported_diagram_type(diagram_type: string | null | undefined): boolean {
  const normalized = normalize_diagram_type(diagram_type);
  return Boolean(normalized) && get_supported_diagram_types().includes(normalized);
}

/** Normalize and validate a diagram type against the supported catalog. */
export function normalize_supported_diagram_type(
  diagram_type: string | null | undefined,
  field_name = 'diagram_type',
  supported_types: readonly string[] | null = null,
): string {
  const normalized = normalize_diagram_type(diagram_type);
  if (!normalized) {
    throw new DiagramTypeValidationError(`${field_name} must be a non-empty string.`);
  }

  const supported = supported_types !== null && supported_types !== undefined ? [...supported_types] : get_supported_diagram_types();
  if (!supported.includes(normalized)) {
    const supported_text = supported.length ? supported.join(', ') : '(none)';
    throw new DiagramTypeValidationError(
      `Unsupported ${field_name} ${pyRepr(diagram_type)} (normalized to ${pyRepr(normalized)}). `
      + `Supported diagram types: ${supported_text}.`,
    );
  }
  return normalized;
}

export const __all__ = [
  'DIAGRAM_TYPE_ALIASES',
  'DiagramTypeValidationError',
  'TYPE_PATTERNS_DIR',
  'get_supported_diagram_types',
  'is_supported_diagram_type',
  'normalize_diagram_type',
  'normalize_supported_diagram_type',
  'slugify',
];
