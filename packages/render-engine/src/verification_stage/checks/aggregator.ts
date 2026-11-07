// Ported from evodesign/agentic_system/verification_stage/checks/aggregator.py — keep in sync.
//
// Aggregator: run every objective check and return a flat List[Finding].

import { normalize_canvas_library } from '../../canvas_runtime.ts';
import { getLogger } from '../../py/logging.ts';
import { KeyError } from '../../py/errors.ts';
import { pyRepr, pyStr } from '../../py/str.ts';
import { truthy } from '../../py/truthy.ts';
import { check_arrow_endpoint_geometry, check_arrow_shape_binding } from './binding_consistency.ts';
import {
  check_edge_crossings,
  check_edge_node_clearance,
  check_edge_node_intersections,
  check_node_overlap,
  check_out_of_canvas,
} from './collision_detection.ts';
import { check_group_bbox_contains_children, check_swimlane_lane_membership } from './containment.ts';
import { Finding, summarize_findings } from './finding.ts';
import { check_edge_label_proximity } from './label_proximity.ts';
import { check_node_icons } from './node_icons.ts';
import { build_objective_manifest } from './objective_manifest.ts';
import { check_layout_audit, check_render_audit, check_schema } from './render_validation.ts';
import { check_sequence } from './sequence.ts';

type Dict = Record<string, any>;

const logger = getLogger('evodesign.agentic_system.verification_stage.checks.aggregator');

export type _CheckSpec = [string, (...args: any[]) => Finding[], unknown[]];

export function _is_skipped(skip_key: string, skip_prefixes: Set<string> | Iterable<string>): boolean {
  for (const prefix of skip_prefixes) {
    if (skip_key === prefix || skip_key.startsWith(`${prefix}/`)) return true;
  }
  return false;
}

export function _check_specs(
  manifest: Dict,
  structure: Dict | null,
  layout_instantiation: Dict | null,
  canvas_library: string,
): _CheckSpec[] {
  const objective_manifest = build_objective_manifest(manifest, canvas_library, structure);
  return [
    ['schema', check_schema, [manifest, canvas_library]],
    ['icon', check_node_icons, [manifest, canvas_library]],
    ['sequence', check_sequence, [objective_manifest, canvas_library === 'excalidraw' ? structure : null]],
    ['render_audit', check_render_audit, [manifest, structure, canvas_library]],
    ['layout_audit', check_layout_audit, [layout_instantiation, structure]],
    ['binding', check_arrow_shape_binding, [objective_manifest]],
    ['binding/arrow_endpoint_drift', check_arrow_endpoint_geometry, [objective_manifest]],
    ['binding/edge_label_distance', check_edge_label_proximity, [objective_manifest]],
    ['containment/group_bbox', check_group_bbox_contains_children, [objective_manifest, structure]],
    ['containment/swimlane_lane', check_swimlane_lane_membership, [objective_manifest, structure]],
    ['collision/node_overlap', check_node_overlap, [objective_manifest]],
    ['collision/edge_crossing', check_edge_crossings, [objective_manifest]],
    ['collision/edge_node_intersection', check_edge_node_intersections, [objective_manifest]],
    ['collision/edge_node_clearance', check_edge_node_clearance, [objective_manifest]],
    ['collision/out_of_canvas', check_out_of_canvas, [objective_manifest]],
  ];
}

/** Python ``str(exc)``: a KeyError prints the repr of its key. */
function _exceptionText(error: unknown): string {
  if (error instanceof KeyError) return pyRepr(error.message);
  return error instanceof Error ? error.message : pyStr(error);
}

/** Python ``type(exc).__name__`` for an error raised by a check. */
function _exceptionName(error: unknown): string {
  if (error instanceof Error) return error.name || error.constructor.name;
  return typeof error;
}

/**
 * Run every objective check, concatenate results in deterministic order.
 *
 * Order matters for deterministic reports: schema → audit → layout audit →
 * binding (ids then endpoint geometry) → containment (group then swimlane) →
 * collisions (overlap → crossings → out_of_canvas).
 *
 * ``skip_categories``: list of category prefixes to skip (e.g.
 * ``["schema", "collision"]``).
 */
export function run_all_checks(
  manifest: Dict,
  structure: Dict | null = null,
  layout_instantiation: Dict | null = null,
  canvas_library = 'excalidraw',
  skip_categories: string[] | null = null,
): Finding[] {
  canvas_library = normalize_canvas_library(canvas_library);
  const skip = new Set<string>(truthy(skip_categories) ? skip_categories! : []);

  const findings: Finding[] = [];
  for (const [skip_key, check_fn, args] of _check_specs(
    manifest,
    structure,
    layout_instantiation,
    canvas_library,
  )) {
    if (_is_skipped(skip_key, skip)) {
      continue;
    }
    try {
      findings.push(...check_fn(...args));
    } catch (exc) {
      logger.exception('objective check failed: %s', skip_key);
      findings.push(
        new Finding({
          category: `verification/internal_error/${skip_key}`,
          severity: 'critical',
          message:
            `Objective check ${skip_key} failed: `
            + `${_exceptionName(exc)}: ${_exceptionText(exc)}`,
        }),
      );
    }
  }

  return findings;
}

export const __all__ = ['run_all_checks', 'summarize_findings'];
export { summarize_findings };
