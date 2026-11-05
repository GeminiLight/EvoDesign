// Ported from evodesign/agentic_system/generation_stage/structure/schemas.py — keep in sync.
//
// Notes on the port:
// * The pydantic models (GraphNode, GraphEdge, GraphGroup, ElementStructure)
//   are validated by hand-written ``model_validate`` functions that reproduce
//   pydantic v2's lax-mode checks for these field types, its alias handling
//   (``AliasChoices``: the first alias present wins; a missing value is
//   reported at the first alias) and its error order (fields in declaration
//   order, list items in order). Only the first error reaches the
//   StructureValidationError text, which is fed back into the correction
//   prompt, so ``loc`` and ``msg`` are pydantic's exact wording.
// * ``collections.Counter`` over string tuples → ``_Counter`` below (insertion
//   ordered; ``-``, ``==`` and ``elements()`` follow CPython 3.10+).
// * Python sets whose iteration order reaches an error message (group parent
//   conflicts, the group-cycle path) iterate in insertion order here; Python
//   iterates in hash order. Only the wording of those two error messages can
//   differ, never whether an error is raised.

import { DiagramTypeValidationError, normalize_supported_diagram_type } from '../../common/diagram_types.ts';
import { is_integer_like_id } from '../../common/semantic_ids.ts';
import { ValueError } from '../../py/errors.ts';
import { pyNe } from '../../py/eq.ts';
import { ValidationError } from '../../py/pydantic.ts';
import { cpCompare, pySorted } from '../../py/sort.ts';
import { cpLen, cpSlice, pyIsdigit, pyLower, pyRepr, pySplit, pyStr, pyStrip } from '../../py/str.ts';
import { isBool, isDict, isInt, isNumber, isStr, pyTypeName, truthy } from '../../py/truthy.ts';

type Dict = Record<string, unknown>;

const has = (obj: Dict, key: string): boolean => Object.prototype.hasOwnProperty.call(obj, key);
/** ``d.get(key, default)`` */
const get = (obj: Dict, key: string, defaultValue: unknown = null): unknown => (has(obj, key) ? obj[key] : defaultValue);
/** ``value or fallback`` */
const or = (value: unknown, fallback: unknown): unknown => (truthy(value) ? value : fallback);
/** ``" ".join(text.split())`` */
const joinWords = (text: string): string => pySplit(text).join(' ');
/** ``str.title()`` for the single-word categories used here. */
const title = (text: string): string => text.charAt(0).toUpperCase() + pyLower(text.slice(1));
/** Iterate a Python iterable (TypeError on None like ``for x in None``). */
const iter = (value: unknown): unknown[] => {
  if (Array.isArray(value)) return value;
  if (isDict(value)) return Object.keys(value);
  if (isStr(value)) return [...value];
  throw new TypeError(`'${pyTypeName(value)}' object is not iterable`);
};
/** Hashable key for tuples of JSON scalars (dicts and lists are unhashable). */
const tupleKey = (parts: readonly unknown[]): string => {
  for (const part of parts) {
    if (part !== null && typeof part === 'object') throw new TypeError(`unhashable type: '${pyTypeName(part)}'`);
  }
  return JSON.stringify(parts);
};
/** ``dict(value)`` of a JSON value (a shallow copy for dicts). */
const dictCopy = (value: unknown): Dict => {
  if (isDict(value)) return { ...value };
  if (!Array.isArray(value) && !isStr(value)) throw new TypeError(`'${pyTypeName(value)}' object is not iterable`);
  const out: Dict = {};
  [...value].forEach((item, index) => {
    const pair = isStr(item) ? [...item] : item;
    if (!Array.isArray(pair)) throw new TypeError(`cannot convert dictionary update sequence element #${index} to a sequence`);
    if (pair.length !== 2) throw new ValueError(`dictionary update sequence element #${index} has length ${pair.length}; 2 is required`);
    tupleKey([pair[0]]); // TypeError for an unhashable key
    out[pyStr(pair[0])] = pair[1];
  });
  return out;
};
/** ``repr(tuple)`` */
const tupleRepr = (parts: readonly unknown[]): string => `(${parts.map(pyRepr).join(', ')}${parts.length === 1 ? ',' : ''})`;

// ---------------------------------------------------------------------------
// collections.Counter over tuples
// ---------------------------------------------------------------------------

export class _Counter<K extends readonly unknown[] = readonly unknown[]> {
  readonly _items = new Map<string, [K, number]>();

  constructor(iterable: Iterable<K> = []) {
    for (const key of iterable) this.add(key, 1);
  }

  add(key: K, count = 1): void {
    const slot = this._items.get(tupleKey(key));
    if (slot) slot[1] += count;
    else this._items.set(tupleKey(key), [key, count]);
  }

  /** ``counter[key]`` (0 when absent, without inserting). */
  get(key: K): number {
    return this._items.get(tupleKey(key))?.[1] ?? 0;
  }

  set(key: K, count: number): void {
    const slot = this._items.get(tupleKey(key));
    if (slot) slot[1] = count;
    else this._items.set(tupleKey(key), [key, count]);
  }

  items(): [K, number][] {
    return [...this._items.values()].map(([key, count]) => [key, count]);
  }

  get size(): number {
    return this._items.size;
  }

  /** ``self - other``: keep positive differences, in self's order. */
  minus(other: _Counter<K>): _Counter<K> {
    const result = new _Counter<K>();
    for (const [key, count] of this._items.values()) {
      const remaining = count - other.get(key);
      if (remaining > 0) result.set(key, remaining);
    }
    return result;
  }

  /** ``self == other`` (Python 3.10+: missing elements count as zero). */
  equals(other: _Counter<K>): boolean {
    for (const [key, count] of this._items.values()) if (other.get(key) !== count) return false;
    for (const [key, count] of other._items.values()) if (this.get(key) !== count) return false;
    return true;
  }

  /** ``list(self.elements())`` */
  elements(): K[] {
    const out: K[] = [];
    for (const [key, count] of this._items.values()) for (let i = 0; i < count; i += 1) out.push(key);
    return out;
  }

  /** Fixture shape: Counter is a dict; tuple keys only appear when non-empty. */
  toFixture(): unknown {
    return this._items.size ? new Map(this.items().map(([key, count]) => [key, count])) : {};
  }
}

// ---------------------------------------------------------------------------
// pydantic models
// ---------------------------------------------------------------------------

type FieldCheck = 'str' | 'optional_str' | 'list_of_str';
interface ModelField { name: string; aliases: string[]; type: FieldCheck; required: boolean }
type ErrorLoc = (string | number)[];
type FirstError = { loc: ErrorLoc; msg: string } | null;

function _check_value(type: FieldCheck, value: unknown, loc: ErrorLoc): FirstError {
  if (type === 'optional_str' && value === null) return null;
  if (type === 'str' || type === 'optional_str') {
    return isStr(value) ? null : { loc, msg: 'Input should be a valid string' };
  }
  if (!Array.isArray(value)) return { loc, msg: 'Input should be a valid list' };
  for (let index = 0; index < value.length; index += 1) {
    if (!isStr(value[index])) return { loc: [...loc, index], msg: 'Input should be a valid string' };
  }
  return null;
}

function _model_first_error(fields: readonly ModelField[], data: Dict, loc: ErrorLoc): FirstError {
  for (const spec of fields) {
    const alias = spec.aliases.find((name) => has(data, name));
    if (alias === undefined) {
      if (spec.required) return { loc: [...loc, spec.aliases[0]], msg: 'Field required' };
      continue;
    }
    const error = _check_value(spec.type, data[alias], [...loc, alias]);
    if (error) return error;
  }
  return null;
}

function _list_of_models_first_error(model: { name: string; fields: readonly ModelField[] }, value: unknown, loc: ErrorLoc): FirstError {
  if (!Array.isArray(value)) return { loc, msg: 'Input should be a valid list' };
  for (let index = 0; index < value.length; index += 1) {
    const item = value[index];
    if (!isDict(item)) return { loc: [...loc, index], msg: `Input should be a valid dictionary or instance of ${model.name}` };
    const error = _model_first_error(model.fields, item, [...loc, index]);
    if (error) return error;
  }
  return null;
}

function _raise_first(model: string, error: FirstError): void {
  if (error) throw new ValidationError(model, [{ loc: error.loc.map(String).join('.'), msg: error.msg }]);
}

const f = (name: string, type: FieldCheck, required: boolean, aliases: string[] = [name]): ModelField => ({ name, aliases, type, required });

/**
 * A node in the final Semantic Topology.
 *
 * Validation accepts a small alias set at the LLM boundary; downstream code
 * receives the canonical field names from ``model_dump(by_alias=False)``.
 */
export class GraphNode {
  static readonly fields: readonly ModelField[] = [
    f('id', 'str', true),
    f('label', 'str', true),
    f('semantic_class', 'str', true, ['class', 'type']),
    f('branch_id', 'optional_str', false),
  ];

  static model_validate(obj: unknown): Dict {
    if (!isDict(obj)) _raise_first('GraphNode', { loc: [], msg: 'Input should be a valid dictionary or instance of GraphNode' });
    _raise_first('GraphNode', _model_first_error(GraphNode.fields, obj as Dict, []));
    return obj as Dict;
  }
}

/**
 * A relation between nodes with explicit semantic directionality.
 *
 * ``from``/``to`` are tolerated only as LLM-boundary aliases for
 * ``source``/``target``.
 */
export class GraphEdge {
  static readonly fields: readonly ModelField[] = [
    f('id', 'str', true),
    f('source', 'str', true, ['source', 'from']),
    f('target', 'str', true, ['target', 'to']),
    f('relation', 'optional_str', false),
    f('label', 'optional_str', false), // Optional label for the edge if different from relation
    f('relation_type', 'optional_str', false),
    f('evidence_basis', 'optional_str', false),
    f('directionality', 'optional_str', false),
    f('evidence', 'optional_str', false),
  ];

  static model_validate(obj: unknown): Dict {
    if (!isDict(obj)) _raise_first('GraphEdge', { loc: [], msg: 'Input should be a valid dictionary or instance of GraphEdge' });
    _raise_first('GraphEdge', _model_first_error(GraphEdge.fields, obj as Dict, []));
    return obj as Dict;
  }
}

/** A logical grouping of nodes (hierarchy). */
export class GraphGroup {
  static readonly fields: readonly ModelField[] = [
    f('id', 'str', true),
    f('label', 'optional_str', false),
    f('parent_group_id', 'optional_str', false),
    // List of member node ids or sub-group ids
    f('members', 'list_of_str', false),
    // List of edge ids that connect members
    f('relations', 'list_of_str', false),
    // Relation among members: parallel, progression, causal, contrast, conditional, temporal, hierarchical, compositional, exemplification
    f('group_member_relation', 'optional_str', false),
  ];

  static model_validate(obj: unknown): Dict {
    if (!isDict(obj)) _raise_first('GraphGroup', { loc: [], msg: 'Input should be a valid dictionary or instance of GraphGroup' });
    _raise_first('GraphGroup', _model_first_error(GraphGroup.fields, obj as Dict, []));
    return obj as Dict;
  }
}

/** The final structured output optimized for diagramming. */
export class ElementStructure {
  // Type of chart: flow chart, mind map, org chart, etc.
  // LLM-boundary alias tolerance. Canonical output remains chart_type.
  static readonly chart_type_aliases = ['chart_type', 'diagram_type'];

  static model_validate(obj: unknown): Dict {
    if (!isDict(obj)) _raise_first('ElementStructure', { loc: [], msg: 'Input should be a valid dictionary or instance of ElementStructure' });
    const data = obj as Dict;
    _raise_first('ElementStructure', ElementStructure._first_error(data));
    return data;
  }

  static _first_error(data: Dict): FirstError {
    const chartAlias = ElementStructure.chart_type_aliases.find((name) => has(data, name));
    if (chartAlias === undefined) return { loc: ['chart_type'], msg: 'Field required' };
    const chartError = _check_value('str', data[chartAlias], [chartAlias]);
    if (chartError) return chartError;
    if (!has(data, 'nodes')) return { loc: ['nodes'], msg: 'Field required' };
    const nodes = _list_of_models_first_error({ name: 'GraphNode', fields: GraphNode.fields }, data.nodes, ['nodes']);
    if (nodes) return nodes;
    if (has(data, 'edges')) {
      const edges = _list_of_models_first_error({ name: 'GraphEdge', fields: GraphEdge.fields }, data.edges, ['edges']);
      if (edges) return edges;
    }
    if (has(data, 'groups')) {
      const groups = _list_of_models_first_error({ name: 'GraphGroup', fields: GraphGroup.fields }, data.groups, ['groups']);
      if (groups) return groups;
    }
    return null;
  }
}

// ---------------------------------------------------------------------------
// Errors
// ---------------------------------------------------------------------------

/** Raised when Structure output violates the graph contract. */
export class StructureValidationError extends ValueError {
  constructor(message?: string) {
    super(message);
    this.name = 'StructureValidationError';
  }
}

/**
 * Ledger entries have no edge, and no edge is missing from the ledger.
 *
 * The diagram omits claims it listed but asserts nothing false, so callers
 * may drop the unrealized entries instead of discarding the whole output.
 */
export class StructureLedgerOmission extends StructureValidationError {
  ledger_name: string;
  missing: [string, string, string][];

  constructor(message: string, ledger_name: string, missing: [string, string, string][]) {
    super(message);
    this.name = 'StructureLedgerOmission';
    this.ledger_name = ledger_name;
    this.missing = missing;
  }
}

export const _LEDGER_FIELDS: Readonly<Record<string, readonly [string, string, string]>> = {
  fact_ledger: ['subject_id', 'predicate', 'object_id'],
  organizer_ledger: ['source_id', 'label', 'target_id'],
};

/** Return ``specification`` without the ledger entries ``omission`` names. */
export function drop_unrealized_ledger_entries(
  specification: Dict, omission: StructureLedgerOmission,
): Dict {
  const typology: Dict = { ...(or(get(specification, 'semantic_typology'), {}) as Dict) };
  const [source_field, label_field, target_field] = _LEDGER_FIELDS[omission.ledger_name];
  const pending = new _Counter<readonly [string, string, string]>(omission.missing);
  const kept: unknown[] = [];
  for (const entry of iter(or(get(typology, omission.ledger_name), []))) {
    const key: readonly [string, string, string] | null = isDict(entry)
      ? [
        pyStr(get(entry, source_field)),
        joinWords(pyLower(pyStrip(pyStr(or(get(entry, label_field), ''))))),
        pyStr(get(entry, target_field)),
      ]
      : null;
    if (key !== null && pending.get(key) > 0) {
      pending.set(key, pending.get(key) - 1);
      continue;
    }
    kept.push(entry);
  }
  typology[omission.ledger_name] = kept;
  return { ...specification, semantic_typology: typology };
}

const _LEDGER_SPECS: readonly (readonly [string, string, string, string, string])[] = [
  ['explicit', 'fact_ledger', 'subject_id', 'object_id', 'predicate'],
  ['structural', 'organizer_ledger', 'source_id', 'target_id', 'label'],
];

const _complete_entry = (entry: unknown, keys: readonly string[]): entry is Dict =>
  isDict(entry) && keys.every((key) => isStr(get(entry, key)) && truthy(pyStrip(entry[key] as string)));

/**
 * Recover an omitted predicate only from an unambiguous emitted ledger.
 *
 * Architecture/flow outputs may omit visual edge labels. Their source and
 * target still identify a ledger claim when there is exactly one edge and
 * one claim for that directed pair. Never guess among parallel relations,
 * create an edge, or overwrite an authored predicate.
 */
export function restore_structure_ledger_relations(
  specification: unknown, instantiation: Dict,
): Dict {
  const typology = isDict(specification) ? get(specification, 'semantic_typology') : null;
  if (!isDict(typology)) {
    return instantiation;
  }
  const edges: Dict[] = iter(get(instantiation, 'edges', [])).map(dictCopy);
  // Evidence metadata is optional in the legacy graph schema. Recover only
  // an exact, unambiguous predicate match from the emitted ledger; never
  // relabel an authored edge or infer a relationship from its endpoints alone.
  const ledger_claims = new Map<string, string[]>();
  for (const [basis, name, source, target, predicate] of _LEDGER_SPECS) {
    const ledger = get(typology, name);
    if (!Array.isArray(ledger)) {
      continue;
    }
    for (const entry of ledger) {
      if (_complete_entry(entry, [source, target, predicate])) {
        const key = tupleKey([get(entry, source), get(entry, target),
          joinWords(pyLower(pyStr(or(get(entry, predicate), ''))))]);
        if (!ledger_claims.has(key)) ledger_claims.set(key, []);
        ledger_claims.get(key)!.push(basis);
      }
    }
  }
  for (const edge of edges) {
    const relationText = joinWords(pyLower(pyStr(or(or(get(edge, 'relation'), get(edge, 'label')), ''))));
    const key = tupleKey([get(edge, 'source'), get(edge, 'target'), relationText]);
    const matches = ledger_claims.get(key) ?? [];
    if (!truthy(get(edge, 'evidence_basis')) && truthy(relationText) && matches.length === 1) {
      edge.evidence_basis = matches[0];
    }
  }
  // An edge emitted with neither evidence_basis nor relation is still the
  // drawing of a claim when its directed pair is unique on both sides: one
  // edge for the pair, one claim for the pair across both ledgers.
  const claims_by_pair = new Map<string, [string, unknown][]>();
  for (const [basis, name, source, target, predicate] of _LEDGER_SPECS) {
    const ledger = get(typology, name);
    for (const entry of Array.isArray(ledger) ? ledger : []) {
      if (_complete_entry(entry, [source, target, predicate])) {
        const key = tupleKey([entry[source], entry[target]]);
        if (!claims_by_pair.has(key)) claims_by_pair.set(key, []);
        claims_by_pair.get(key)!.push([basis, entry[predicate]]);
      }
    }
  }
  const pairOf = (edge: Dict): readonly [unknown, unknown] => [get(edge, 'source'), get(edge, 'target')];
  const edges_by_pair = new _Counter(edges.map(pairOf));
  const tagged_pairs = new Set(edges.filter((edge) => truthy(get(edge, 'evidence_basis'))).map((edge) => tupleKey(pairOf(edge))));
  for (const edge of edges) {
    const pair = pairOf(edge);
    const matches = claims_by_pair.get(tupleKey(pair)) ?? [];
    if (!truthy(get(edge, 'evidence_basis')) && !truthy(get(edge, 'relation'))
        && edges_by_pair.get(pair) === 1 && !tagged_pairs.has(tupleKey(pair))
        && matches.length === 1) {
      [edge.evidence_basis, edge.relation] = matches[0];
    }
  }
  for (const [basis, name, source, target, predicate] of _LEDGER_SPECS) {
    const ledger = get(typology, name);
    if (!Array.isArray(ledger)) {
      continue;
    }
    const claims = new Map<string, unknown[]>();
    for (const entry of ledger) {
      if (!_complete_entry(entry, [source, target, predicate])) {
        continue;
      }
      const key = tupleKey([entry[source], entry[target]]);
      if (!claims.has(key)) claims.set(key, []);
      claims.get(key)!.push(entry[predicate]);
    }
    const counts = new _Counter(edges.filter((edge) => get(edge, 'evidence_basis') === basis).map(pairOf));
    for (const edge of edges) {
      const pair = pairOf(edge);
      const matches = claims.get(tupleKey(pair)) ?? [];
      if (get(edge, 'evidence_basis') === basis && !truthy(get(edge, 'relation'))
          && !truthy(get(edge, 'label')) && counts.get(pair) === 1 && matches.length === 1) {
        edge.relation = matches[0];
      }
    }
  }
  return { ...instantiation, edges };
}

/**
 * Verify an emitted fact ledger against the concrete relation graph.
 *
 * The ledger is optional for legacy outputs. Once either ledger is emitted,
 * it becomes an auditable contract: source facts must map one-to-one to
 * explicit edges and organizer entries must map one-to-one to structural
 * edges. Counters preserve legitimate parallel relations with the same
 * endpoints but different predicates.
 */
export function validate_structure_semantic_ledger(
  specification: unknown,
  instantiation: Dict,
): void {
  if (!isDict(specification)) {
    return;
  }
  const semantic_typology = get(specification, 'semantic_typology');
  if (!isDict(semantic_typology)) {
    return;
  }
  const has_fact_ledger = has(semantic_typology, 'fact_ledger');
  const has_organizer_ledger = has(semantic_typology, 'organizer_ledger');
  if (!has_fact_ledger && !has_organizer_ledger) {
    return;
  }

  const fact_ledger = get(semantic_typology, 'fact_ledger');
  const organizer_ledger = get(semantic_typology, 'organizer_ledger');
  if (!Array.isArray(fact_ledger) || !Array.isArray(organizer_ledger)) {
    throw new StructureValidationError(
      'Structure semantic_typology must provide fact_ledger and '
      + 'organizer_ledger as lists once ledger validation is enabled.',
    );
  }

  const normalized = (value: unknown): string => joinWords(pyLower(pyStrip(pyStr(or(value, '')))));

  const ledger_key = (
    entry: unknown,
    source_field: string,
    label_field: string,
    target_field: string,
    ledger_name: string,
  ): readonly [string, string, string] => {
    if (!isDict(entry)) {
      throw new StructureValidationError(
        `Structure ${ledger_name} entries must be objects.`,
      );
    }
    const source = get(entry, source_field);
    const label = normalized(get(entry, label_field));
    const target = get(entry, target_field);
    if (![source, target].every((value) => isStr(value) && truthy(pyStrip(value)))) {
      throw new StructureValidationError(
        `Structure ${ledger_name} entry must include non-empty `
        + `${source_field} and ${target_field}.`,
      );
    }
    if (!label) {
      throw new StructureValidationError(
        `Structure ${ledger_name} entry must include non-empty ${label_field}.`,
      );
    }
    return [pyStr(source), label, pyStr(target)];
  };

  const fact_keys = new _Counter(fact_ledger.map((entry) => ledger_key(
    entry,
    'subject_id',
    'predicate',
    'object_id',
    'fact_ledger',
  )));
  const organizer_keys = new _Counter(organizer_ledger.map((entry) => ledger_key(
    entry,
    'source_id',
    'label',
    'target_id',
    'organizer_ledger',
  )));

  const explicit_edges = new _Counter<readonly [string, string, string]>();
  const structural_edges = new _Counter<readonly [string, string, string]>();
  for (const edge of iter(or(get(instantiation, 'edges', []), []))) {
    if (!isDict(edge)) {
      continue;
    }
    const key: readonly [string, string, string] = [
      pyStr(get(edge, 'source', '')),
      // A display label (e.g. "Yes") may abbreviate the predicate.
      normalized(or(get(edge, 'relation'), get(edge, 'label'))),
      pyStr(get(edge, 'target', '')),
    ];
    if (get(edge, 'evidence_basis') === 'explicit') {
      explicit_edges.add(key);
    } else if (get(edge, 'evidence_basis') === 'structural') {
      structural_edges.add(key);
    }
  }

  const compare = (
    ledger: _Counter<readonly [string, string, string]>,
    edges: _Counter<readonly [string, string, string]>,
    ledger_name: string,
  ): void => {
    if (ledger.equals(edges)) {
      return;
    }
    const missing = ledger.minus(edges).elements().map((key) => [...key] as [string, string, string]);
    const unledgered = edges.minus(ledger).elements();
    const details: string[] = [];
    if (missing.length) {
      details.push(`missing edges for [${missing.map(tupleRepr).join(', ')}]`);
    }
    if (unledgered.length) {
      details.push(`unledgered edges [${unledgered.map(tupleRepr).join(', ')}]`);
    }
    const message = (
      `Structure ${ledger_name} does not match the relation graph: `
      + details.join('; ')
      + '.'
    );
    if (!unledgered.length) {
      throw new StructureLedgerOmission(message, ledger_name, missing);
    }
    throw new StructureValidationError(message);
  };

  compare(fact_keys, explicit_edges, 'fact_ledger');
  compare(
    organizer_keys.minus(_organizer_claims_realized_by_groups(
      organizer_keys.minus(structural_edges), get(instantiation, 'groups'),
    )),
    structural_edges,
    'organizer_ledger',
  );
}

/**
 * Return organizer claims already drawn as group containment.
 *
 * An organizer entry such as ``(api, "grouped in", g_online)`` is presentation
 * structure. When ``api`` sits inside ``g_online`` (directly or through nested
 * groups) the container already draws that claim, and adding an edge would
 * duplicate it. Only claims with no matching structural edge are considered,
 * and only for the organizer ledger: source facts must always be edges.
 */
export function _organizer_claims_realized_by_groups(
  unmatched: _Counter<readonly [string, string, string]>,
  groups: unknown,
): _Counter<readonly [string, string, string]> {
  const parents = new Map<string, string>();
  const group_ids = new Set<string>();
  for (const group of iter(or(groups, []))) {
    if (!isDict(group) || !isStr(get(group, 'id'))) {
      continue;
    }
    const group_id = group.id as string;
    group_ids.add(group_id);
    if (isStr(get(group, 'parent_group_id'))) {
      if (!parents.has(group_id)) parents.set(group_id, group.parent_group_id as string);
    }
    for (const member of iter(or(get(group, 'members'), []))) {
      if (isStr(member)) {
        if (!parents.has(member)) parents.set(member, group_id);
      }
    }
  }

  const inside = (member: string, group_id: string): boolean => {
    const seen = new Set<string>();
    let current = parents.get(member);
    while (current !== undefined && !seen.has(current)) {
      if (current === group_id) {
        return true;
      }
      seen.add(current);
      current = parents.get(current);
    }
    return false;
  };

  const realized = new _Counter<readonly [string, string, string]>();
  for (const [[source, label, target], count] of unmatched.items()) {
    if ((group_ids.has(target) && inside(source, target)) || (
      group_ids.has(source) && inside(target, source)
    )) {
      realized.set([source, label, target], count);
    }
  }
  return realized;
}

export const _RELATION_TYPE_ALIASES: Readonly<Record<string, string>> = {
  hierarchical: 'hierarchy',
  subtype: 'hierarchy',
  compositional: 'composition',
  containment: 'composition',
  membership: 'composition',
  example: 'exemplification',
  dependency: 'dependency',
  enabling: 'causal',
  cause: 'causal',
  associative: 'association',
  link: 'association',
};
export const _STRUCTURAL_RELATION_TYPES: ReadonlySet<string> = new Set([
  'hierarchy',
  'composition',
  'exemplification',
]);
export const _CONCEPT_RELATION_TYPES: ReadonlySet<string> = new Set([
  ..._STRUCTURAL_RELATION_TYPES,
  'dependency',
  'causal',
  'association',
]);
export const _EVIDENCE_BASES: ReadonlySet<string> = new Set(['explicit', 'structural']);
export const _DIRECTIONALITIES: ReadonlySet<string> = new Set(['directed', 'undirected']);
export const _STRUCTURAL_RELATION_LABELS: ReadonlySet<string> = new Set([
  'organized into',
  'has subtype',
  'includes',
  'contains',
  'has example',
]);
export const _RELATION_LABEL_TYPES: Readonly<Record<string, ReadonlySet<string>>> = {
  hierarchy: new Set(['organized into', 'has subtype', 'is subtype of']),
  composition: new Set(['includes', 'contains', 'has part', 'part of']),
  exemplification: new Set(['has example', 'exemplifies', 'is example of']),
  dependency: new Set(['depends on', 'requires', 'relies on']),
  causal: new Set([
    'causes',
    'drives',
    'enables',
    'improves',
    'raises',
    'transforms',
  ]),
  association: new Set(['associated with', 'linked to', 'relates to']),
};

/** ``x in some_set`` for a set of strings (non-strings are never members). */
const inSet = (set: ReadonlySet<string>, value: unknown): boolean => isStr(value) && set.has(value);

/**
 * Validate and canonicalize a Structure stage instantiation.
 *
 * The Structure stage is the foreign-key root for Styling, Layout, Render,
 * and Refiner.  This guard catches hard graph-contract failures immediately
 * instead of letting dangling ids become missing arrows or misleading
 * verifier findings downstream. The returned artifact uses canonical fields:
 * ``chart_type``, node ``class``, and edge ``source`` / ``target``.
 */
export function validate_structure_instantiation(instantiation: unknown): Dict {
  if (!isDict(instantiation)) {
    throw new StructureValidationError(
      'Structure instantiation must be a JSON object; '
      + `got ${pyTypeName(instantiation)}.`,
    );
  }

  const normalized: Dict = { ...instantiation };
  const chart_type = get(normalized, 'chart_type', get(normalized, 'diagram_type'));
  try {
    normalized.chart_type = normalize_supported_diagram_type(
      chart_type as string | null,
      'chart_type',
    );
  } catch (exc) {
    if (exc instanceof DiagramTypeValidationError) {
      const error = new StructureValidationError(exc.message);
      (error as { cause?: unknown }).cause = exc;
      throw error;
    }
    throw exc;
  }
  delete normalized.diagram_type;

  normalized.nodes = _canonicalize_nodes(get(normalized, 'nodes'));
  normalized.edges = _canonicalize_edges(get(normalized, 'edges', []));
  if (!has(normalized, 'groups')) normalized.groups = [];

  try {
    ElementStructure.model_validate(normalized);
  } catch (exc) {
    if (exc instanceof ValidationError) {
      const first = exc.errors.length ? exc.errors[0] : null;
      const loc = (first ? first.loc : '') || 'structure';
      const msg = first ? first.msg : exc.message;
      const error = new StructureValidationError(
        `Invalid Structure instantiation schema at ${loc}: ${msg}`,
      );
      (error as { cause?: unknown }).cause = exc;
      throw error;
    }
    throw exc;
  }

  if (normalized.chart_type === 'concept_map') {
    normalized.edges = _normalize_concept_map_relation_metadata(
      normalized.nodes as Dict[],
      normalized.edges as Dict[],
    );
    normalized.edges = _reduce_concept_map_hierarchy_edges(
      normalized.nodes as Dict[],
      normalized.edges as Dict[],
    );
    _validate_concept_map_semantic_metadata(
      normalized.nodes as Dict[],
      normalized.edges as Dict[],
    );
  }

  const nodes = _as_sequence(get(normalized, 'nodes'), 'nodes');
  const edges = _as_sequence(get(normalized, 'edges'), 'edges');
  const groups = _as_sequence(get(normalized, 'groups'), 'groups');

  // A node-less graph is the failure signature of a truncated / refused LLM
  // response. Every downstream guard (styling coverage, layout id checks)
  // passes vacuously on empty id sets, so without this the pipeline renders a
  // blank canvas and reports success.
  if (!nodes.length) {
    throw new StructureValidationError(
      'Structure instantiation must contain at least one node; '
      + "got an empty 'nodes' list, which renders a blank canvas.",
    );
  }

  const node_ids = _collect_unique_ids(nodes, 'node');
  const edge_ids = _collect_unique_ids(edges, 'edge');
  const group_ids = _collect_unique_ids(groups, 'group');
  _ensure_disjoint_ids(node_ids, edge_ids, group_ids);
  if (normalized.chart_type === 'concept_map') {
    _validate_concept_map_branch_ids(nodes);
  }

  const valid_member_ids = new Set([...node_ids, ...group_ids]);
  for (const edge of edges) {
    const edge_id = get(edge, 'id');
    const source = get(edge, 'source');
    const target = get(edge, 'target');
    if (!inSet(node_ids, source)) {
      throw new StructureValidationError(
        `Edge ${pyRepr(edge_id)} source ${pyRepr(source)} does not reference an existing node.`,
      );
    }
    if (!inSet(node_ids, target)) {
      throw new StructureValidationError(
        `Edge ${pyRepr(edge_id)} target ${pyRepr(target)} does not reference an existing node.`,
      );
    }
    _validate_edge_id(edge_id, source, target);
  }

  const memberships = new Map<unknown, unknown>();
  for (const group of groups) {
    const group_id = get(group, 'id');
    if (get(group, 'parent_group_id') !== null && !inSet(group_ids, group.parent_group_id)) {
      throw new StructureValidationError(
        `Group ${pyRepr(group_id)} parent_group_id ${pyRepr(group.parent_group_id)} `
        + 'does not reference an existing group.',
      );
    }
    for (const member_id of iter(or(get(group, 'members', []), []))) {
      if (member_id === group_id) {
        throw new StructureValidationError(`Group ${pyRepr(group_id)} cannot include itself as a member.`);
      }
      if (!inSet(valid_member_ids, member_id)) {
        throw new StructureValidationError(
          `Group ${pyRepr(group_id)} member ${pyRepr(member_id)} does not reference an existing node or group.`,
        );
      }
      const previous_group = memberships.has(member_id) ? memberships.get(member_id) : null;
      if (truthy(previous_group) && previous_group !== group_id) {
        throw new StructureValidationError(
          `Member ${pyRepr(member_id)} belongs to multiple groups: `
          + `${pyRepr(previous_group)} and ${pyRepr(group_id)}.`,
        );
      }
      memberships.set(member_id, group_id);
    }
    for (const edge_id of iter(or(get(group, 'relations', []), []))) {
      if (!inSet(edge_ids, edge_id)) {
        throw new StructureValidationError(
          `Group ${pyRepr(group_id)} relation ${pyRepr(edge_id)} does not reference an existing edge.`,
        );
      }
    }
  }

  _ensure_group_graph_acyclic(groups);
  _validate_type_specific_fields(normalized.chart_type as string, nodes, edges, node_ids);
  return normalized;
}

export function _canonicalize_nodes(value: unknown): unknown {
  if (!Array.isArray(value)) {
    return value;
  }
  const normalized_nodes: unknown[] = [];
  for (const node of value) {
    if (!isDict(node)) {
      normalized_nodes.push(node);
      continue;
    }
    const normalized: Dict = { ...node };
    const class_values = [
      get(normalized, 'class'),
      get(normalized, 'semantic_class'),
      get(normalized, 'type'),
    ].filter((item) => item !== null);
    if (class_values.length && class_values.slice(1).some((item) => pyNe(item, class_values[0]))) {
      throw new StructureValidationError(
        `Node ${pyRepr(get(normalized, 'id'))} has conflicting class/type values: `
        + `${pyRepr(class_values)}.`,
      );
    }
    let canonical_class: unknown = class_values.length ? class_values[0] : null;
    if (canonical_class === null) {
      // Some models name the semantic class `role` or `kind`; the
      // renderer already reads both. Keep the original field as well.
      const key = ['role', 'kind'].find((name) => isStr(get(normalized, name)) && truthy(pyStrip(normalized[name] as string)));
      canonical_class = key !== undefined ? normalized[key] : null;
    }
    if (canonical_class !== null) {
      normalized.class = canonical_class;
    }
    delete normalized.type;
    delete normalized.semantic_class;
    normalized_nodes.push(normalized);
  }
  return normalized_nodes;
}

export function _canonicalize_edges(value: unknown): unknown {
  if (!Array.isArray(value)) {
    return value;
  }
  const normalized_edges: unknown[] = [];
  for (const edge of value) {
    if (!isDict(edge)) {
      normalized_edges.push(edge);
      continue;
    }
    const normalized: Dict = { ...edge };
    if (
      has(normalized, 'source')
      && has(normalized, 'from')
      && pyNe(normalized.source, normalized.from)
    ) {
      throw new StructureValidationError(
        `Edge ${pyRepr(get(normalized, 'id'))} has conflicting source/from values: `
        + `${pyRepr(normalized.source)} vs ${pyRepr(normalized.from)}.`,
      );
    }
    if (
      has(normalized, 'target')
      && has(normalized, 'to')
      && pyNe(normalized.target, normalized.to)
    ) {
      throw new StructureValidationError(
        `Edge ${pyRepr(get(normalized, 'id'))} has conflicting target/to values: `
        + `${pyRepr(normalized.target)} vs ${pyRepr(normalized.to)}.`,
      );
    }
    if (!has(normalized, 'source') && has(normalized, 'from')) {
      normalized.source = normalized.from;
    }
    if (!has(normalized, 'target') && has(normalized, 'to')) {
      normalized.target = normalized.to;
    }
    delete normalized.from;
    delete normalized.to;
    let relation_type = get(normalized, 'relation_type');
    if (isStr(relation_type) && truthy(pyStrip(relation_type))) {
      relation_type = pyLower(pyStrip(relation_type)).split('-').join('_').split(' ').join('_');
      normalized.relation_type = get(_RELATION_TYPE_ALIASES, relation_type as string, relation_type);
    }
    const evidence_basis = get(normalized, 'evidence_basis');
    if (isStr(evidence_basis) && truthy(pyStrip(evidence_basis))) {
      normalized.evidence_basis = pyLower(pyStrip(evidence_basis));
    }
    const directionality = get(normalized, 'directionality');
    if (isStr(directionality) && truthy(pyStrip(directionality))) {
      normalized.directionality = pyLower(pyStrip(directionality));
    }
    normalized_edges.push(normalized);
  }
  return normalized_edges;
}

/** ``{str(node.get("id")): str(node.get("class", "")).lower() ...}`` */
function _node_classes(nodes: readonly Dict[], strip: boolean): Map<string, string> {
  const node_classes = new Map<string, string>();
  for (const node of nodes) {
    if (!isStr(get(node, 'id'))) continue;
    const text = pyStr(get(node, 'class', ''));
    node_classes.set(pyStr(get(node, 'id')), pyLower(strip ? pyStrip(text) : text));
  }
  return node_classes;
}

function _ids_with_class(node_classes: Map<string, string>, classes: readonly string[]): Set<string> {
  const ids = new Set<string>();
  for (const [node_id, node_class] of node_classes) if (classes.includes(node_class)) ids.add(node_id);
  return ids;
}

/**
 * Drop redundant organizer shortcuts while preserving explicit source facts.
 *
 * ``relation_type`` and ``evidence_basis`` answer different questions. An
 * explicit taxonomy fact is still a hierarchy relation, but it must not be
 * reduced through a path of layout organizers. Only edges whose evidence is
 * structural are reducible once the modern metadata contract is present.
 */
export function _reduce_concept_map_hierarchy_edges(
  nodes: readonly Dict[],
  edges: readonly Dict[],
): Dict[] {
  const node_classes = _node_classes(nodes, false);
  const core_ids = _ids_with_class(node_classes, ['core', 'core_concept']);
  const anchor_ids = _ids_with_class(node_classes, ['branch_anchor', 'category']);
  for (const edge of edges) {
    if (inSet(core_ids, get(edge, 'source')) && isStr(get(edge, 'target'))) {
      anchor_ids.add(pyStr(get(edge, 'target')));
    }
  }
  const hierarchy_sources = new Set([...core_ids, ...anchor_ids]);

  const modern_metadata = nodes.some((node) => has(node, 'branch_id'));

  const is_reducible_organizer_edge = (edge: Dict): boolean => {
    const evidence_basis = pyLower(pyStrip(pyStr(get(edge, 'evidence_basis', ''))));
    if (modern_metadata) {
      return evidence_basis === 'structural';
    }
    const relation_type = pyLower(pyStrip(pyStr(get(edge, 'relation_type', ''))));
    if (relation_type) {
      return _STRUCTURAL_RELATION_TYPES.has(relation_type);
    }
    const label = pyLower(pyStrip(pyStr(or(or(get(edge, 'label'), get(edge, 'relation')), ''))));
    if (label) {
      return _STRUCTURAL_RELATION_LABELS.has(label);
    }
    return inSet(hierarchy_sources, get(edge, 'source'));
  };

  const has_alternative_path = (source: string, target: string): boolean => {
    const adjacency = new Map<string, Set<string>>();
    for (const edge of edges) {
      const edge_source = get(edge, 'source');
      const edge_target = get(edge, 'target');
      if (!isStr(edge_source) || !isStr(edge_target)) {
        continue;
      }
      if (!is_reducible_organizer_edge(edge)) {
        continue;
      }
      // Parallel relations with the same endpoints can carry distinct
      // semantics; they do not constitute a transitive alternative.
      if (edge_source === source && edge_target === target) {
        continue;
      }
      if (!adjacency.has(edge_source)) adjacency.set(edge_source, new Set());
      adjacency.get(edge_source)!.add(edge_target);
    }
    const queue = [...(adjacency.get(source) ?? [])];
    const visited = new Set([source]);
    while (queue.length) {
      const current = queue.shift()!;
      if (current === target) {
        return true;
      }
      if (visited.has(current)) {
        continue;
      }
      visited.add(current);
      for (const next of adjacency.get(current) ?? []) if (!visited.has(next)) queue.push(next);
    }
    return false;
  };

  return edges
    .filter((edge) => !(
      isStr(get(edge, 'source'))
      && isStr(get(edge, 'target'))
      && hierarchy_sources.has(edge.source as string)
      && is_reducible_organizer_edge(edge)
      && has_alternative_path(edge.source as string, edge.target as string)
    ))
    .map((edge) => ({ ...edge }));
}

export function _infer_concept_relation_type(label: string): string | null {
  if (!isStr(label)) {
    throw new TypeError(`'${pyTypeName(label)}' object has no attribute 'strip'`);
  }
  const normalized = pyLower(pyStrip(label));
  for (const [relation_type, labels] of Object.entries(_RELATION_LABEL_TYPES)) {
    if (labels.has(normalized)) {
      return relation_type;
    }
  }
  if (normalized.includes('depend') || normalized.includes('rely')) {
    return 'dependency';
  }
  if (normalized.includes('example') || normalized.includes('exemplif')) {
    return 'exemplification';
  }
  if (normalized.includes('associat') || normalized.includes('link')) {
    return 'association';
  }
  return null;
}

/** Canonicalize relation semantics without inventing source facts. */
export function _normalize_concept_map_relation_metadata(
  nodes: readonly Dict[],
  edges: readonly Dict[],
): Dict[] {
  const node_classes = _node_classes(nodes, false);
  const core_ids = _ids_with_class(node_classes, ['core', 'core_concept']);
  const anchor_ids = _ids_with_class(node_classes, ['branch_anchor', 'category']);
  const normalized_edges: Dict[] = [];
  for (const edge of edges) {
    if (!isDict(edge)) {
      throw new TypeError(`'${pyTypeName(edge)}' object is not iterable`);
    }
    const normalized: Dict = { ...edge };
    const evidence_basis = pyLower(pyStrip(pyStr(get(normalized, 'evidence_basis', ''))));
    if (['inferred', 'world_knowledge', 'plausible'].includes(evidence_basis)) {
      continue;
    }

    const label = pyStrip(pyStr(or(or(get(normalized, 'label'), get(normalized, 'relation')), '')));
    let relation_type = pyLower(pyStrip(pyStr(get(normalized, 'relation_type', ''))));
    if (!relation_type && label) {
      const inferred_type = _infer_concept_relation_type(label);
      if (inferred_type) {
        relation_type = inferred_type;
        normalized.relation_type = inferred_type;
      }
    }

    if (inSet(core_ids, get(edge, 'source')) && inSet(anchor_ids, get(edge, 'target'))) {
      normalized.label = 'organized into';
      normalized.relation_type = 'hierarchy';
      normalized.evidence_basis = 'structural';
      if (has(normalized, 'relation')) {
        normalized.relation = 'organized into';
      }
    } else if (
      inSet(anchor_ids, get(edge, 'source'))
      && relation_type === 'exemplification'
      && ['exemplifies', 'is example of'].includes(pyLower(label))
    ) {
      normalized.label = 'has example';
      if (has(normalized, 'relation')) {
        normalized.relation = 'has example';
      }
    } else if (relation_type === 'association' && _RELATION_LABEL_TYPES.causal.has(pyLower(label))) {
      normalized.label = 'associated with';
      if (has(normalized, 'relation')) {
        normalized.relation = 'associated with';
      }
    } else if (relation_type === 'causal' && _RELATION_LABEL_TYPES.association.has(pyLower(label))) {
      normalized.relation_type = 'association';
      relation_type = 'association';
    }

    // Direction is part of the semantic contract, not a styling guess.
    // Preserve explicit model output, while upgrading older modern concept
    // maps deterministically so saved structures remain re-renderable.
    if (!pyStrip(pyStr(get(normalized, 'directionality', '')))) {
      normalized.directionality = (
        relation_type === 'association' ? 'undirected' : 'directed'
      );
    }
    normalized_edges.push(normalized);
  }
  return normalized_edges;
}

/** Validate explicit branch ownership when the model emits it. */
export function _validate_concept_map_branch_ids(nodes: readonly Dict[]): void {
  const node_classes = _node_classes(nodes, true);
  const anchor_ids = _ids_with_class(node_classes, ['branch_anchor', 'category']);
  const core_ids = _ids_with_class(node_classes, ['core', 'core_concept']);
  // Flat concept networks do not have taxonomy branches. Null ownership is
  // valid there; non-null references still go through the checks below.
  if (!anchor_ids.size && nodes.every((node) => get(node, 'branch_id') === null)) {
    return;
  }
  for (const node of nodes) {
    if (!has(node, 'branch_id')) {
      continue;
    }
    const node_id = get(node, 'id');
    const branch_id = get(node, 'branch_id');
    if (inSet(core_ids, node_id)) {
      if (branch_id !== null) {
        throw new StructureValidationError(
          `Concept-map core node ${pyRepr(node_id)} must use branch_id=null.`,
        );
      }
      continue;
    }
    if (inSet(anchor_ids, node_id)) {
      if (pyNe(branch_id, node_id)) {
        throw new StructureValidationError(
          `Concept-map branch anchor ${pyRepr(node_id)} must own itself via branch_id.`,
        );
      }
      continue;
    }
    if (!inSet(anchor_ids, branch_id)) {
      throw new StructureValidationError(
        `Concept-map node ${pyRepr(node_id)} branch_id ${pyRepr(branch_id)} must reference `
        + 'a branch_anchor node.',
      );
    }
  }
}

/** Require complete semantic metadata once a concept map opts into it. */
export function _validate_concept_map_semantic_metadata(
  nodes: readonly Dict[],
  edges: readonly Dict[],
): void {
  const modern_mode = nodes.some((node) => has(node, 'branch_id'));
  if (!modern_mode) {
    return;
  }

  const missing_branch_ids = nodes
    .filter((node) => !has(node, 'branch_id'))
    .map((node) => pyStr(get(node, 'id')));
  if (missing_branch_ids.length) {
    throw new StructureValidationError(
      'Modern concept-map structures require branch_id on every node; '
      + `missing: ${missing_branch_ids.join(', ')}.`,
    );
  }

  for (const edge of edges) {
    const edge_id = pyStr(get(edge, 'id'));
    const relation_type = get(edge, 'relation_type');
    if (!inSet(_CONCEPT_RELATION_TYPES, relation_type)) {
      const allowed = pySorted(_CONCEPT_RELATION_TYPES).join(', ');
      throw new StructureValidationError(
        `Concept-map edge ${pyRepr(edge_id)} relation_type ${pyRepr(relation_type)} `
        + `must be one of: ${allowed}.`,
      );
    }
    const evidence_basis = get(edge, 'evidence_basis');
    if (!inSet(_EVIDENCE_BASES, evidence_basis)) {
      throw new StructureValidationError(
        `Concept-map edge ${pyRepr(edge_id)} evidence_basis ${pyRepr(evidence_basis)} `
        + "must be 'explicit' or 'structural'.",
      );
    }
    const directionality = get(edge, 'directionality');
    if (!inSet(_DIRECTIONALITIES, directionality)) {
      const allowed = pySorted(_DIRECTIONALITIES).join(', ');
      throw new StructureValidationError(
        `Concept-map edge ${pyRepr(edge_id)} directionality ${pyRepr(directionality)} `
        + `must be one of: ${allowed}.`,
      );
    }
    if (evidence_basis === 'explicit') {
      const evidence = get(edge, 'evidence');
      if (!isStr(evidence) || !pyStrip(evidence)) {
        throw new StructureValidationError(
          `Explicit concept-map edge ${pyRepr(edge_id)} must include evidence.`,
        );
      }
    }
  }
}

export function _as_sequence(value: unknown, field_name: string): Dict[] {
  if (!Array.isArray(value)) {
    throw new StructureValidationError(
      `Structure field ${pyRepr(field_name)} must be a list; got ${pyTypeName(value)}.`,
    );
  }
  value.forEach((item, index) => {
    if (!isDict(item)) {
      throw new StructureValidationError(
        `Structure field ${field_name}[${index}] must be an object; `
        + `got ${pyTypeName(item)}.`,
      );
    }
  });
  return value as Dict[];
}

export function _collect_unique_ids(items: readonly Dict[], category: string): Set<string> {
  const seen = new Set<string>();
  items.forEach((item, index) => {
    const item_id = get(item, 'id');
    if (!isStr(item_id) || !pyStrip(item_id)) {
      throw new StructureValidationError(`${title(category)} at index ${index} has no non-empty string id.`);
    }
    if (seen.has(item_id)) {
      throw new StructureValidationError(`Duplicate ${category} id ${pyRepr(item_id)}.`);
    }
    if (is_integer_like_id(item_id)) {
      throw new StructureValidationError(
        `${title(category)} id ${pyRepr(item_id)} must not be a bare integer; `
        + 'use a descriptive snake_case id.',
      );
    }
    seen.add(item_id);
  });
  return seen;
}

export function _ensure_disjoint_ids(node_ids: Set<string>, edge_ids: Set<string>, group_ids: Set<string>): void {
  const collisions = new Set<string>();
  for (const id of node_ids) if (edge_ids.has(id) || group_ids.has(id)) collisions.add(id);
  for (const id of edge_ids) if (group_ids.has(id)) collisions.add(id);
  if (collisions.size) {
    const formatted = pySorted(collisions).join(', ');
    throw new StructureValidationError(
      `Structure ids must be unique across nodes, edges, and groups; duplicates: ${formatted}.`,
    );
  }
}

export function _validate_edge_id(edge_id: unknown, source: unknown, target: unknown): void {
  if (![edge_id, source, target].every((value) => isStr(value) && truthy(pyStrip(value)))) {
    return;
  }
  const expected = `edge:${source as string}2${target as string}`;
  if (edge_id === expected) {
    return;
  }
  const id = edge_id as string;
  if (id.startsWith(`${expected}_`) && pyIsdigit(cpSlice(id, cpLen(expected) + 1))) {
    return;
  }
  throw new StructureValidationError(
    `Edge ${pyRepr(edge_id)} must use canonical id ${pyRepr(expected)} `
    + 'or append a numeric suffix for parallel edges.',
  );
}

export function _ensure_group_graph_acyclic(groups: readonly Dict[]): void {
  const parent_for = new Map<string, string>();
  const member_groups = new Map<string, Set<string>>();
  const group_ids = new Set<string>();
  for (const group of groups) {
    const id = get(group, 'id');
    if (isStr(id) && id) group_ids.add(id);
  }

  for (const group of groups) {
    const group_id = get(group, 'id');
    if (!isStr(group_id)) {
      continue;
    }
    const parent_group_id = get(group, 'parent_group_id');
    if (isStr(parent_group_id) && parent_group_id) {
      parent_for.set(group_id, parent_group_id);
    }
    for (const member_id of iter(or(get(group, 'members', []), []))) {
      if (isStr(member_id) && group_ids.has(member_id)) {
        if (!member_groups.has(member_id)) member_groups.set(member_id, new Set());
        member_groups.get(member_id)!.add(group_id);
      }
    }
  }

  const parent_sources = new Map<string, string>();
  const adjacency = new Map<string, Set<string>>();
  for (const group_id of group_ids) adjacency.set(group_id, new Set());
  const addChild = (parent_id: string, child_id: string) => {
    if (!adjacency.has(parent_id)) adjacency.set(parent_id, new Set());
    adjacency.get(parent_id)!.add(child_id);
  };
  for (const [child_id, parent_id] of parent_for) {
    parent_sources.set(child_id, parent_id);
    addChild(parent_id, child_id);
  }
  for (const [child_id, parents] of member_groups) {
    for (const parent_id of parents) {
      const previous_parent = parent_sources.get(child_id);
      if (previous_parent && previous_parent !== parent_id) {
        throw new StructureValidationError(
          `Group ${pyRepr(child_id)} has conflicting parents: `
          + `${pyRepr(previous_parent)} and ${pyRepr(parent_id)}.`,
        );
      }
      parent_sources.set(child_id, parent_id);
      addChild(parent_id, child_id);
    }
  }

  const visiting = new Set<string>();
  const visited = new Set<string>();

  const visit = (group_id: string, path: string[]): void => {
    if (visiting.has(group_id)) {
      const cycle = [...path, group_id].join(' -> ');
      throw new StructureValidationError(`Group hierarchy contains a cycle: ${cycle}.`);
    }
    if (visited.has(group_id)) {
      return;
    }
    visiting.add(group_id);
    for (const child_id of adjacency.get(group_id) ?? []) {
      visit(child_id, [...path, group_id]);
    }
    visiting.delete(group_id);
    visited.add(group_id);
  };

  for (const group_id of pySorted(group_ids)) {
    visit(group_id, []);
  }
}

export function _validate_type_specific_fields(
  chart_type: string,
  nodes: readonly Dict[],
  edges: readonly Dict[],
  node_ids: Set<string>,
): void {
  if (['mindmap', 'tree', 'orgchart'].includes(chart_type)) {
    _validate_parent_id_fields(chart_type, nodes, node_ids);
  } else if (chart_type === 'matrix') {
    _validate_matrix_fields(nodes);
  } else if (chart_type === 'sequence_diagram') {
    _validate_sequence_fields(nodes, edges);
  } else if (chart_type === 'gantt') {
    _validate_gantt_fields(nodes);
  }
}

export function _validate_parent_id_fields(
  chart_type: string,
  nodes: readonly Dict[],
  node_ids: Set<string>,
): void {
  const roots: string[] = [];
  const parent_for = new Map<string, string | null>();
  for (const node of nodes) {
    const node_id = get(node, 'id');
    if (!has(node, 'parent_id')) {
      throw new StructureValidationError(
        `${chart_type} node ${pyRepr(node_id)} must include parent_id.`,
      );
    }
    const parent_id = get(node, 'parent_id');
    if (parent_id === null) {
      roots.push(pyStr(node_id));
    } else if (!isStr(parent_id) || !pyStrip(parent_id)) {
      throw new StructureValidationError(
        `${chart_type} node ${pyRepr(node_id)} parent_id must be null or a non-empty node id.`,
      );
    } else if (parent_id === node_id) {
      throw new StructureValidationError(
        `${chart_type} node ${pyRepr(node_id)} cannot reference itself as parent_id.`,
      );
    } else if (!node_ids.has(parent_id)) {
      throw new StructureValidationError(
        `${chart_type} node ${pyRepr(node_id)} parent_id ${pyRepr(parent_id)} `
        + 'does not reference an existing node.',
      );
    }
    parent_for.set(pyStr(node_id), isStr(parent_id) ? parent_id : null);
  }

  if (roots.length !== 1) {
    const found = roots.length ? roots.map((root_id) => pyRepr(root_id)).join(', ') : 'none';
    throw new StructureValidationError(
      `${chart_type} must include exactly one root node with parent_id null; `
      + `found ${roots.length} (${found}). Multiple roots render as disconnected `
      + 'trees on one canvas.',
    );
  }

  const visiting = new Set<string>();
  const visited = new Set<string>();

  const visit = (node_id: string, path: string[]): void => {
    if (visiting.has(node_id)) {
      const cycle = [...path, node_id].join(' -> ');
      throw new StructureValidationError(`${chart_type} parent_id hierarchy contains a cycle: ${cycle}.`);
    }
    if (visited.has(node_id)) {
      return;
    }
    visiting.add(node_id);
    const parent_id = parent_for.get(node_id) ?? null;
    if (parent_id) {
      visit(parent_id, [...path, node_id]);
    }
    visiting.delete(node_id);
    visited.add(node_id);
  };

  for (const node_id of pySorted(parent_for.keys())) {
    visit(node_id, []);
  }
}

export function _validate_matrix_fields(nodes: readonly Dict[]): void {
  for (const node of nodes) {
    const node_id = get(node, 'id');
    if (!_is_non_negative_int(get(node, 'row'))) {
      throw new StructureValidationError(
        `matrix node ${pyRepr(node_id)} must include non-negative integer row.`,
      );
    }
    if (!_is_non_negative_int(get(node, 'col'))) {
      throw new StructureValidationError(
        `matrix node ${pyRepr(node_id)} must include non-negative integer col.`,
      );
    }
  }
}

export function _validate_sequence_fields(
  nodes: readonly Dict[],
  edges: readonly Dict[],
): void {
  for (const node of nodes) {
    const node_id = get(node, 'id');
    const actor_id = get(node, 'actor_id');
    if (!isStr(actor_id) || !pyStrip(actor_id)) {
      throw new StructureValidationError(
        `sequence_diagram node ${pyRepr(node_id)} must include non-empty actor_id.`,
      );
    }
  }
  const indices = edges.map((edge) => get(edge, 'sequence_idx'));
  if (indices.every((index) => _is_non_negative_int(index)) && new Set(indices).size !== indices.length) {
    throw new StructureValidationError('sequence_diagram messages must have unique sequence_idx values.');
  }
  for (const edge of edges) {
    const edge_id = get(edge, 'id');
    if (!_is_non_negative_int(get(edge, 'sequence_idx'))) {
      throw new StructureValidationError(
        `sequence_diagram edge ${pyRepr(edge_id)} must include non-negative integer sequence_idx.`,
      );
    }
  }
}

export function _validate_gantt_fields(nodes: readonly Dict[]): void {
  for (const node of nodes) {
    const node_id = get(node, 'id');
    const start = get(node, 'start_ts');
    const end = get(node, 'end_ts');
    if (!_is_timestamp_like(start)) {
      throw new StructureValidationError(
        `gantt node ${pyRepr(node_id)} must include non-empty start_ts.`,
      );
    }
    if (!_is_timestamp_like(end)) {
      throw new StructureValidationError(
        `gantt node ${pyRepr(node_id)} must include non-empty end_ts.`,
      );
    }
    if (isNumber(start) && isNumber(end) && start > end) {
      throw new StructureValidationError(
        `gantt node ${pyRepr(node_id)} start_ts must not be after end_ts.`,
      );
    }
    if (isStr(start) && isStr(end) && cpCompare(start, end) > 0) {
      throw new StructureValidationError(
        `gantt node ${pyRepr(node_id)} start_ts must not be after end_ts.`,
      );
    }
  }
}

export function _is_non_negative_int(value: unknown): boolean {
  return isInt(value) && !isBool(value) && value >= 0;
}

export function _is_timestamp_like(value: unknown): boolean {
  if (isBool(value)) {
    return false;
  }
  if (isNumber(value)) {
    return true;
  }
  return isStr(value) && truthy(pyStrip(value));
}
