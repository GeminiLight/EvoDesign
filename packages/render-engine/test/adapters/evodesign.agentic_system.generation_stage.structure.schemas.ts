import type { Adapter } from '../parity/functions.test.ts';
import { _Counter } from '../../src/generation_stage/structure/schemas.ts';

// Functions returning None are ``void`` in TS.
const none: Adapter = { result: (actual) => (actual === undefined ? null : actual) };

// collections.Counter → _Counter. The recorded Counters are all empty, so the
// fixture encodes them as {} (a non-empty one would carry tuple keys).
const toCounter = (value: unknown): unknown => (value instanceof _Counter ? value : new _Counter(
  value instanceof Map ? [...value].flatMap(([key, count]) => Array.from({ length: count as number }, () => key as unknown[])) : [],
));

export default {
  _ensure_disjoint_ids: none,
  _ensure_group_graph_acyclic: none,
  _validate_concept_map_branch_ids: none,
  _validate_concept_map_semantic_metadata: none,
  _validate_edge_id: none,
  _validate_gantt_fields: none,
  _validate_matrix_fields: none,
  _validate_parent_id_fields: none,
  _validate_sequence_fields: none,
  _validate_type_specific_fields: none,
  validate_structure_semantic_ledger: none,
  _organizer_claims_realized_by_groups: {
    args: (bound) => [toCounter(bound[0]), ...bound.slice(1)],
    result: (actual) => (actual as _Counter).toFixture(),
    // The Counter argument is never mutated; its representation differs from the fixture's {}.
    checkMutation: false,
  },
} satisfies Record<string, Adapter>;
