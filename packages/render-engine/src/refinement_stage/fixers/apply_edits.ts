// Ported from evodesign/agentic_system/refinement_stage/fixers/apply_edits.py — keep in sync.
//
// Apply a list of EditOps to a manifest, recording per-op outcomes.
//
// This is the single point of mutation: deterministic fixers and the LLM
// agent both produce ``List[EditOp]``, and both go through ``apply_edits``.
// That guarantees the iteration log is uniform, and a single bug fix in the
// dispatcher fixes both paths.
//
// ``EditOp`` / ``EditApplyOutcome`` live in ``refinement_stage/state`` (WP22).
// They are loaded from ``../state.ts`` when that file exists, otherwise from a
// local equivalent with the same fields, defaults and validation (see
// migration/notes/WP21.md).

import { color_contrast_ratio } from '../../canvas_environment/scene.ts';
import { ICON_KEY, sync_node_icons } from '../../common/node_icons.ts';
import { pyGet } from '../../py/dict.ts';
import { pyEq } from '../../py/eq.ts';
import { AttributeError, KeyError, PyTypeError } from '../../py/errors.ts';
import { getLogger } from '../../py/logging.ts';
import { pyFloatParse } from '../../py/number.ts';
import { BaseModel, field } from '../../py/pydantic.ts';
import { pyRepr, pySplit, pyStr, pyStrip } from '../../py/str.ts';
import { isList, isMapping, isStr, pyTypeName, truthy } from '../../py/truthy.ts';
import { OP_HANDLERS } from './primitives.ts';

type Dict = Record<string, unknown>;

const logger = getLogger('evodesign.agentic_system.refinement_stage.fixers.apply_edits');

// ---------------------------------------------------------------------------
// EditOp / EditApplyOutcome (refinement_stage/state.py, owned by WP22)
// ---------------------------------------------------------------------------

/** Structural view of ``state.EditOp`` used by the fixers. */
export interface EditOpLike {
  op: string;
  id: string;
  payload: Dict;
  rationale: string;
  source: string;
}

/** Structural view of ``state.EditApplyOutcome``. */
export interface EditApplyOutcomeLike {
  edit: EditOpLike | null;
  applied: boolean;
  error: string | null;
  raw: Dict | null;
}

type EditOpClass = new (data: Record<string, unknown>) => EditOpLike;
type EditApplyOutcomeClass = new (data: Record<string, unknown>) => EditApplyOutcomeLike;

const _EDIT_OP_NAMES = [
  'set_icon', 'set_position', 'set_size', 'set_style', 'set_text', 'delete_element',
  'clear_arrow_binding', 'clear_container_binding', 'append_bound_element',
  'remove_bound_element', 'set_index',
];

function _literal(allowed: string[]): (value: unknown) => unknown {
  return (value: unknown) => {
    if (typeof value === 'string' && allowed.includes(value)) return value;
    throw new Error(`Input should be ${allowed.map((v) => `'${v}'`).join(', ')}`);
  };
}

/** Local equivalent of ``state.EditOp`` (used only while WP22's state.ts is absent). */
class _LocalEditOp extends BaseModel {
  static override pythonName = 'evodesign.agentic_system.refinement_stage.state.EditOp';
  static override model_fields = {
    op: field({ before: _literal(_EDIT_OP_NAMES), required: true }),
    id: field({ type: 'str', required: true }),
    payload: field({ type: 'dict', default_factory: () => ({}) }),
    rationale: field({ type: 'str', default: '' }),
    source: field({ before: _literal(['deterministic', 'llm']), default: 'deterministic' }),
  };
  declare op: string;
  declare id: string;
  declare payload: Dict;
  declare rationale: string;
  declare source: string;
}

/** Local equivalent of ``state.EditApplyOutcome``. */
class _LocalEditApplyOutcome extends BaseModel {
  static override pythonName = 'evodesign.agentic_system.refinement_stage.state.EditApplyOutcome';
  static override model_fields = {
    edit: field({ type: 'any', default: null }),
    applied: field({ type: 'bool', required: true }),
    error: field({ type: 'optional_str', default: null }),
    raw: field({ type: 'optional_dict', default: null }),
  };
  declare edit: EditOpLike | null;
  declare applied: boolean;
  declare error: string | null;
  declare raw: Dict | null;
}

async function _load_state(): Promise<{ EditOp?: EditOpClass; EditApplyOutcome?: EditApplyOutcomeClass } | null> {
  try {
    return (await import(/* @vite-ignore */ new URL('../state.ts', import.meta.url).href)) as {
      EditOp?: EditOpClass;
      EditApplyOutcome?: EditApplyOutcomeClass;
    };
  } catch {
    return null;
  }
}

const _state = await _load_state();

/** ``state.EditOp`` (WP22's class when available). */
export const EditOp: EditOpClass = _state?.EditOp ?? (_LocalEditOp as unknown as EditOpClass);
/** ``state.EditApplyOutcome`` (WP22's class when available). */
export const EditApplyOutcome: EditApplyOutcomeClass = _state?.EditApplyOutcome
  ?? (_LocalEditApplyOutcome as unknown as EditApplyOutcomeClass);

// ---------------------------------------------------------------------------
// Python helpers
// ---------------------------------------------------------------------------

/** ``obj.get(key, default)`` that raises AttributeError for non-mappings, like Python. */
function _get(obj: unknown, key: string, default_: unknown = null): unknown {
  if (!isMapping(obj)) {
    throw new AttributeError(`'${pyTypeName(obj)}' object has no attribute 'get'`);
  }
  return pyGet(obj, key, default_);
}

function _float(value: unknown): number {
  if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'string') return pyFloatParse(value);
  throw new PyTypeError(`float() argument must be a string or a real number, not '${pyTypeName(value)}'`);
}

/** ``value in {"transparent", "none"}`` (unhashable values raise TypeError). */
function _in_hidden_colors(value: unknown): boolean {
  if (isList(value) || isMapping(value)) {
    throw new PyTypeError(`unhashable type: '${pyTypeName(value)}'`);
  }
  return value === 'transparent' || value === 'none';
}

/** ``f"{type(exc).__name__}: {exc}"`` */
function _exc_text(exc: unknown): string {
  if (exc instanceof KeyError) return `KeyError: ${exc.message}`;
  if (exc instanceof Error) return `${exc.name}: ${exc.message}`;
  return `Exception: ${String(exc)}`;
}

// ---------------------------------------------------------------------------
// Port
// ---------------------------------------------------------------------------

export function _collapse_whitespace(text: string): string {
  return pySplit(text).join(' ');
}

/**
 * True when *new_text* only re-wraps the label (whitespace/line breaks).
 *
 * Visual refinement may re-flow a semantic label to fix overflow, but must
 * not reword, abbreviate or translate it: the words are source facts.
 */
export function _same_label_content(element: Dict, new_text: string): boolean {
  const candidate = _collapse_whitespace(new_text);
  return [pyGet(element, 'originalText'), pyGet(element, 'text')].some(
    (current) => isStr(current) && _collapse_whitespace(current) === candidate,
  );
}

/** Prevent visual cleanup from erasing source facts. */
export function _semantic_edit_error(manifest: Dict, edit: EditOpLike): string | null {
  if (edit.source !== 'llm') {
    return null;
  }
  const elements = new Map<unknown, Dict>();
  for (const element of _get(manifest, 'elements', []) as Dict[]) {
    elements.set(_get(element, 'id'), element);
  }
  const element = (elements.has(edit.id) ? elements.get(edit.id) : {}) as Dict;
  const customData = _get(element, 'customData');
  const is_node_icon = truthy(_get(truthy(customData) ? customData : {}, ICON_KEY));
  if (is_node_icon && ['set_position', 'set_size', 'delete_element'].includes(edit.op)) {
    return 'generated icons follow their host node; edit the host geometry instead of detaching its icon';
  }
  const id_map = _get(_get(manifest, '_meta', {}), 'id_map', {});
  const semantic_ids = new Set<unknown>(id_map instanceof Map ? [...id_map.values()] : Object.values(id_map as Dict));
  const meta = _get(element, 'meta');
  const metadata = (truthy(meta) ? meta : {}) as Dict;
  const semantic = (
    semantic_ids.has(edit.id)
    || semantic_ids.has(_get(element, 'containerId'))
    || truthy(_get(metadata, 'semantic_edge_id'))
  ) && !truthy(_get(element, 'is_group'));
  if (!semantic) {
    return null;
  }
  if (pyEq(_get(element, 'opacity', 100), 0)) {
    if (_get(element, 'type') === 'arrow' && edit.op === 'set_style' && _float(_get(edit.payload, 'opacity', 0)) > 0) {
      return 'organizer connectors already encoded by containment must remain hidden';
    }
    return null;
  }
  if (edit.op === 'delete_element') {
    return 'semantic content cannot be deleted during visual refinement';
  }
  if (edit.op === 'set_text') {
    const new_text = _get(edit.payload, 'text', '');
    if (!pyStrip(pyStr(new_text))) {
      return 'semantic labels cannot be erased during visual refinement';
    }
    if (!_same_label_content(element, pyStr(new_text))) {
      return (
        'semantic label content is fixed during visual refinement; '
        + 'set_text may only re-wrap it (whitespace/line breaks)'
      );
    }
  }
  if (edit.op === 'set_style') {
    if (truthy(_get(metadata, 'conceptFactAnchor')) && (
      _float(_get(edit.payload, 'strokeWidth', 1)) <= 0
      || _in_hidden_colors(_get(edit.payload, 'strokeColor'))
    )) {
      return 'fact-bearing section headings need a visible connector boundary';
    }
    if (truthy(_get(metadata, 'conceptFactAnchor'))) {
      const stroke = _get(edit.payload, 'strokeColor', _get(element, 'strokeColor'));
      const fill = _get(edit.payload, 'backgroundColor', _get(element, 'backgroundColor'));
      const contrast = color_contrast_ratio(stroke as string, fill as string);
      if (contrast !== null && contrast < 1.5) {
        return 'fact-bearing heading border must remain distinguishable from its fill';
      }
    }
    if (_float(_get(edit.payload, 'opacity', 100)) < 25) {
      return 'semantic content must remain visible';
    }
    if (_get(element, 'type') === 'arrow' && (
      _float(_get(edit.payload, 'strokeWidth', 1)) <= 0
      || _in_hidden_colors(_get(edit.payload, 'strokeColor'))
    )) {
      return 'semantic connectors must remain visible';
    }
  }
  return null;
}

/**
 * Apply ``edits`` in order, mutating ``manifest`` in place.
 *
 * Returns the same manifest reference (for chaining) plus a per-edit
 * outcome list. Unknown ids / invalid payloads / unknown ops never raise:
 * they record a failed outcome and the loop continues.
 */
export function apply_edits(
  manifest: Dict,
  edits: EditOpLike[],
  allow_icons = true,
): [Dict, EditApplyOutcomeLike[]] {
  const outcomes: EditApplyOutcomeLike[] = [];

  for (const edit of edits) {
    if (edit.op === 'set_icon' && !allow_icons) {
      outcomes.push(new EditApplyOutcome({ edit, applied: false, error: 'Icons are disabled by the user.' }));
      continue;
    }
    const handler = Object.prototype.hasOwnProperty.call(OP_HANDLERS, edit.op) ? OP_HANDLERS[edit.op] : undefined;
    if (handler === undefined) {
      outcomes.push(new EditApplyOutcome({ edit, applied: false, error: `unknown op ${pyRepr(edit.op)}` }));
      continue;
    }

    let applied: boolean;
    let error: string | null;
    try {
      error = _semantic_edit_error(manifest, edit);
      applied = false;
      if (error === null) {
        [applied, error] = handler(manifest, edit.id, edit.payload);
      }
    } catch (exc) {
      // defensive: never let a fixer crash the workflow
      logger.exception('EditOp handler raised', { op: edit.op, id: edit.id });
      outcomes.push(new EditApplyOutcome({ edit, applied: false, error: `handler raised ${_exc_text(exc)}` }));
      continue;
    }

    outcomes.push(new EditApplyOutcome({ edit, applied, error }));
  }

  sync_node_icons(manifest);
  return [manifest, outcomes];
}

export const __all__ = ['apply_edits'];
