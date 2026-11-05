// Ported from evodesign/agentic_system/refinement_stage/agent/llm_agent.py — keep in sync.
// server-only (reads the PNG, calls the chat model)
//
// Single-shot VLM refiner agent.
//
// One model call per refinement iteration. Receives:
// - the current PNG (base64 — never visually inspected by Claude)
// - the **remaining** findings (after deterministic pass)
// - the original verifier subjective critique (loaded once at start)
// - a compact manifest summary
// - previous-iteration edit log (so the model doesn't loop)
//
// Returns a List[EditOp]. Schema-violating items are dropped rather than
// raising, but never silently: they land in ``last_rejected_edits`` so the
// workflow can record them in the iteration log.
//
// Async: ``RefinerLLMAgent(model=None)`` creates its model with
// ``LLMFactory.create_for_role("refiner")``, which is async in TS. A TS
// constructor cannot await, so the ``model is None`` path lives in the static
// ``RefinerLLMAgent.create(...)`` (same parameters, same order: capability
// check first, then model creation). ``new RefinerLLMAgent(model, ...)``
// requires a model. ``propose_edits()`` and ``refine_with_llm()`` are async.

import type { BaseChatModel } from '@langchain/core/language_models/chat_models';
import { HumanMessage, SystemMessage } from '@langchain/core/messages';
import { ModelConfig } from '../../config/model_loader.ts';
import { LLMBudgetExceeded, _is_permanent_http_error, _sleep, charge_llm_run_budget } from '../../core/base_agent.ts';
import { LLMFactory } from '../../core/llm_factory.ts';
import { _is_py_float, _mark_py_float } from '../../generation_stage/layout/sequence_layout.ts';
import { pyGet } from '../../py/dict.ts';
import { AttributeError, JSONDecodeError, PyTypeError, ValueError } from '../../py/errors.ts';
import { PyJSONDecodeError } from '../../py/json_decoder.ts';
import { getLogger } from '../../py/logging.ts';
import { pyFloatParse } from '../../py/number.ts';
import { cpSlice, pyRepr, pySlice, pyStr } from '../../py/str.ts';
import { isDict, isList, pyTypeName, truthy } from '../../py/truthy.ts';
import { image_to_data_url } from '../../utils/io_utils.ts';
import { convert_json_output } from '../../utils/llm_output.ts';
import { EditOp } from '../state.ts';
import { MAX_MANIFEST_SUMMARY_ELEMENTS, REFINER_LLM_SYSTEM_PROMPT, build_refiner_user_prompt } from './prompts.ts';

const logger = getLogger('evodesign.agentic_system.refinement_stage.agent.llm_agent');

type Dict = Record<string, any>;

// ---------------------------------------------------------------- Python helpers

/** ``str.splitlines()`` */
function _splitlines(text: string): string[] {
  const parts = text.split(/\r\n|[\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029]/);
  if (parts.length && parts[parts.length - 1] === '') parts.pop();
  return parts;
}

/** ``type(exc).__name__`` */
function _exc_type_name(exc: unknown): string {
  if (exc instanceof Error) {
    const name = exc.name || exc.constructor?.name || 'Exception';
    return name === 'PyTypeError' ? 'TypeError' : name;
  }
  return pyTypeName(exc);
}

/** ``str(exc)`` */
function _exc_str(exc: unknown): string {
  if (exc instanceof Error) return exc.message;
  return pyStr(exc);
}

/** ``mapping.get(key, default)`` that raises AttributeError for non-mappings. */
function _get(mapping: unknown, key: string, default_: unknown = null): unknown {
  if (!isDict(mapping)) throw new AttributeError(`'${pyTypeName(mapping)}' object has no attribute 'get'`);
  return pyGet(mapping, key, default_);
}

/** ``float(x)``: TypeError for non-numbers, ValueError for bad strings. */
function _float(value: unknown): number {
  if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'string') return pyFloatParse(value);
  throw new PyTypeError(`float() argument must be a string or a real number, not '${pyTypeName(value)}'`);
}

/** ``isinstance(exc, json.JSONDecodeError)`` */
function _is_json_decode_error(error: unknown): boolean {
  return error instanceof PyJSONDecodeError || error instanceof JSONDecodeError;
}

// ---------------------------------------------------------------- coercion

/**
 * Validate each item with the EditOp pydantic model.
 *
 * Returns ``(edits, rejections)``. ``EditOp`` is ``extra="forbid"``, so one
 * drifted field name (``reason`` instead of ``rationale``) invalidates a whole
 * item — and when every item drifts the caller used to receive a bare ``[]``,
 * identical to "the model had nothing to propose". Rejections are handed back
 * so the workflow can record them in the iteration log instead.
 */
export function _coerce_to_edits(raw_list: unknown[]): [EditOp[], Dict[]] {
  const edits: EditOp[] = [];
  const rejections: Dict[] = [];
  raw_list.forEach((item, i) => {
    if (!isDict(item)) {
      logger.warning(`LLM edit ${i} is not a dict; skip`);
      rejections.push({
        raw: { value: cpSlice(pyRepr(item), 0, 200) },
        error: `schema: item ${i} is ${pyTypeName(item)}, not an object`,
      });
      return;
    }
    // Inject source so audit trail tags it correctly.
    if (!Object.prototype.hasOwnProperty.call(item, 'source')) item.source = 'llm';
    let edit: EditOp;
    try {
      edit = EditOp.model_validate(item);
    } catch (exc) {
      // pydantic ValidationError
      logger.warning(`LLM edit ${i} failed validation: ${_exc_str(exc)}; payload=${pyRepr(item)}`);
      rejections.push({
        raw: item,
        error: `schema: ${cpSlice(_splitlines(_exc_str(exc))[0], 0, 200)}`,
      });
      return;
    }
    edits.push(edit);
  });
  return [edits, rejections];
}

/**
 * Produce a compact element list for the LLM prompt.
 *
 * Includes semantic IDs, container membership, and connector endpoints so
 * visually similar background frames cannot be confused with nodes.
 * ``pinned_ids`` are emitted first so elements tied
 * to active verifier findings are not lost when the prompt is capped.
 *
 * The arrow exclusion is enforced here, not merely documented: an arrow's
 * bbox in the prompt is an invitation to translate it, and translating an
 * arrow moves the whole baked polyline away from both shapes it connects.
 * ``op_set_position`` / ``op_set_size`` also refuse arrow targets, so the two
 * layers agree.
 */
export function build_manifest_summary(
  manifest: Dict,
  cap: number = MAX_MANIFEST_SUMMARY_ELEMENTS,
  pinned_ids: Iterable<unknown> | null = null,
): Dict[] {
  const pinned: Dict[] = [];
  const regular: Dict[] = [];
  const pinned_set = new Set<string>();
  for (const value of (truthy(pinned_ids) ? pinned_ids! : [])) {
    if (typeof value === 'string') pinned_set.add(value);
  }
  const seen_ids = new Set<string>();
  const elements = _get(manifest, 'elements', []);
  if (!isList(elements)) {
    return [];
  }
  // render id -> semantic id (Map: ids may look like integers)
  const semantic_ids = new Map<unknown, unknown>();
  const id_map = _get(_get(manifest, '_meta', {}), 'id_map', {});
  if (!isDict(id_map)) throw new AttributeError(`'${pyTypeName(id_map)}' object has no attribute 'items'`);
  for (const [semantic_id, render_id] of Object.entries(id_map)) {
    semantic_ids.set(render_id, semantic_id);
  }
  const bound_texts = new Map<unknown, unknown>();
  for (const elem of elements) {
    if (isDict(elem) && pyGet(elem, 'type') === 'text' && truthy(pyGet(elem, 'containerId'))) {
      const text = pyGet(elem, 'text');
      bound_texts.set(pyGet(elem, 'containerId'), truthy(text) ? text : pyGet(elem, 'originalText'));
    }
  }
  for (const elem of elements) {
    if (!isDict(elem) || truthy(pyGet(elem, 'isDeleted'))) {
      continue;
    }
    if (pyGet(elem, 'type') === 'arrow') {
      continue;
    }
    let x: number;
    let y: number;
    let w: number;
    let h: number;
    try {
      x = _float(_or0(pyGet(elem, 'x', 0)));
      y = _float(_or0(pyGet(elem, 'y', 0)));
      w = _float(_or0(pyGet(elem, 'width', 0)));
      h = _float(_or0(pyGet(elem, 'height', 0)));
    } catch (error) {
      if (error instanceof PyTypeError || error instanceof ValueError) continue;
      throw error;
    }
    const bbox = [x, y, w, h];
    // float(...) values: all four are Python floats.
    for (let i = 0; i < 4; i++) _mark_py_float(bbox, String(i));
    const entry: Dict = {
      id: pyGet(elem, 'id'),
      type: pyGet(elem, 'type'),
      bbox,
    };
    const element_id = pyGet(entry, 'id');
    if (typeof element_id !== 'string' || !element_id || seen_ids.has(element_id)) {
      continue;
    }
    let text: unknown = pyGet(elem, 'text');
    if (!truthy(text)) text = pyGet(elem, 'originalText');
    if (!truthy(text)) text = bound_texts.has(element_id) ? bound_texts.get(element_id) : null;
    if (truthy(text)) {
      entry.text = cpSlice(pyStr(text), 0, 60);
    }
    if (semantic_ids.has(element_id)) {
      entry.semantic_id = semantic_ids.get(element_id);
    }
    if (truthy(pyGet(elem, 'containerId'))) {
      entry.container_id = elem.containerId;
    }
    const metadata = truthy(pyGet(elem, 'meta')) ? pyGet(elem, 'meta') : {};
    for (const key of ['semantic_edge_id', 'semantic_arrow_id']) {
      if (truthy(_get(metadata, key))) {
        entry[key] = (metadata as Dict)[key];
      }
    }
    const style: Dict = {};
    for (const key of ['fontSize', 'fontFamily', 'strokeColor', 'backgroundColor', 'strokeWidth', 'strokeStyle']) {
      if (Object.prototype.hasOwnProperty.call(elem, key)) {
        style[key] = elem[key];
        if (_is_py_float(elem, key)) _mark_py_float(style, key);
      }
    }
    if (truthy(style)) {
      entry.style = style;
    }
    if (truthy(_get(metadata, 'conceptFactAnchor'))) {
      entry.role = 'fact_bearing_section_heading_keep_border';
    }
    if (truthy(pyGet(elem, 'is_group'))) {
      entry.role = 'group_background';
      if (truthy(_get(metadata, 'memberIds'))) {
        entry.member_ids = (metadata as Dict).memberIds;
      }
    }
    if (pyGet(elem, 'type') === 'arrow') {
      entry.source = _get(metadata, 'source');
      entry.target = _get(metadata, 'target');
    }
    entry.opacity = pyGet(elem, 'opacity', 100);
    if (_is_py_float(elem, 'opacity')) _mark_py_float(entry, 'opacity');
    if (pinned_set.has(element_id)) {
      pinned.push(entry);
    } else {
      regular.push(entry);
    }
    seen_ids.add(element_id);
  }
  // regular.sort(key=lambda entry: entry.get("opacity", 100) == 0) — stable
  const sorted = regular
    .map((entry, index) => ({ entry, index, key: _eq0(pyGet(entry, 'opacity', 100)) ? 1 : 0 }))
    .sort((a, b) => a.key - b.key || a.index - b.index)
    .map((item) => item.entry);
  return pySlice([...pinned, ...sorted], null, cap);
}

/** ``value or 0`` */
function _or0(value: unknown): unknown {
  return truthy(value) ? value : 0;
}

/** ``value == 0`` (``False == 0`` and ``0.0 == 0`` are True in Python). */
function _eq0(value: unknown): boolean {
  return value === 0 || value === false;
}

// ---------------------------------------------------------------- agent

/** Single-shot VLM call wrapper that emits validated EditOps. */
export class RefinerLLMAgent {
  model: BaseChatModel;
  max_retries: number;
  retry_delay_seconds: number;
  // Set whenever a propose_edits() call exhausts retries OR exits early
  // on a permanent HTTP error. Workflow reads this to surface the failure
  // in state.errors / refiner_report.json — otherwise a silent empty list
  // looks identical to "LLM had nothing to propose".
  last_exhaustion_error: string | null;
  // Items the model proposed that failed EditOp validation. Same purpose
  // as last_exhaustion_error: an empty edit list must never be able to
  // mean two different things.
  last_rejected_edits: Dict[];

  constructor(model: BaseChatModel | null = null, max_retries = 3, retry_delay_seconds = 5.0) {
    if (model === null || model === undefined) {
      // ``model or LLMFactory.create_for_role("refiner")`` needs an await.
      throw new PyTypeError('RefinerLLMAgent(model=None): use `await RefinerLLMAgent.create(...)`');
    }
    this.model = model;
    this.max_retries = max_retries;
    this.retry_delay_seconds = retry_delay_seconds;
    this.last_exhaustion_error = null;
    this.last_rejected_edits = [];
  }

  /** ``RefinerLLMAgent(model=..., ...)`` including the ``model is None`` path. */
  static async create(model: BaseChatModel | null = null, max_retries = 3, retry_delay_seconds = 5.0): Promise<RefinerLLMAgent> {
    if (model === null || model === undefined) {
      ModelConfig.get_default().require_model_capabilities('refiner', new Set(['vision']));
    }
    const resolved = model ?? (await LLMFactory.create_for_role('refiner'));
    return new RefinerLLMAgent(resolved, max_retries, retry_delay_seconds);
  }

  /** Run one VLM call; return validated EditOps. Empty list on parse failure. */
  async propose_edits(
    image_path: string,
    chart_type: string | null,
    remaining_findings: Dict[],
    critique: Dict | null,
    manifest_summary: Dict[],
    previous_attempts: Dict[] | null = null,
    iteration = 1,
    max_iterations = 3,
    image_note: string | null = null,
    design_constraints = '',
  ): Promise<EditOp[]> {
    // Reset for this call. Set below when retries exhaust or we exit early
    // on a permanent HTTP error.
    this.last_exhaustion_error = null;
    this.last_rejected_edits = [];

    const data_url = image_to_data_url(image_path);
    const user_text = build_refiner_user_prompt(
      chart_type,
      remaining_findings,
      critique,
      manifest_summary,
      previous_attempts,
      iteration,
      max_iterations,
      image_note,
      design_constraints,
    );
    const messages = [
      new SystemMessage({ content: REFINER_LLM_SYSTEM_PROMPT }),
      new HumanMessage({
        content: [
          { type: 'image_url', image_url: { url: data_url, detail: 'high' } },
          { type: 'text', text: user_text },
        ],
      }),
    ];

    let delay = this.retry_delay_seconds;
    let last_exc: unknown = null;
    let has_last_exc = false;
    for (let attempt = 1; attempt <= this.max_retries; attempt++) {
      try {
        charge_llm_run_budget();
      } catch (exc) {
        if (exc instanceof LLMBudgetExceeded) {
          last_exc = exc;
          has_last_exc = true;
          break;
        }
        throw exc;
      }
      let answered = false;
      try {
        const response = await this.model.invoke(messages);
        if (response === null || response === undefined || !truthy((response as { content?: unknown }).content ?? null)) {
          throw new ValueError('VLM returned empty response');
        }
        answered = true;
        let raw: unknown = response.content;
        if (Array.isArray(raw)) {
          raw = raw
            .filter((p) => isDict(p))
            .map((p) => pyStr(pyGet(p as Dict, 'text', '')))
            .join('');
        }
        if (typeof raw !== 'string') {
          raw = pyStr(raw);
        }

        let arr: unknown;
        try {
          arr = convert_json_output(raw as string);
        } catch (error) {
          if (_is_json_decode_error(error)) {
            logger.warning(
              `Could not extract JSON array from VLM response (attempt ${attempt}). Raw head: ${cpSlice(raw as string, 0, 200)}`,
            );
            throw new ValueError('no JSON array found');
          }
          throw error;
        }
        if (!isList(arr)) {
          logger.warning(
            `VLM response parsed but is not a JSON array (attempt ${attempt}). Got type: ${pyTypeName(arr)}`,
          );
          throw new ValueError('VLM response is not a JSON array');
        }

        const [edits, rejections] = _coerce_to_edits(arr);
        this.last_rejected_edits = rejections;
        logger.info(`VLM proposed ${arr.length} edits (${edits.length} valid after schema check)`);
        return edits;
      } catch (exc) {
        last_exc = exc;
        has_last_exc = true;
        logger.warning(`Refiner LLM attempt ${attempt}/${this.max_retries} failed: ${_exc_str(exc)}`);
        // Permanent provider/client errors should stop immediately.
        // Transient 408/409/429/5xx/connection failures still get the
        // outer retry budget so refiner behavior matches BaseAgent.
        if (_is_permanent_http_error(exc)) {
          logger.warning('Refiner LLM exiting retry loop early — non-retryable provider HTTP error');
          break;
        }
        // A malformed answer is resampled at once; only transport
        // failures (no answer yet) back off.
        if (attempt < this.max_retries && !answered) {
          await _sleep(delay);
          delay *= 2;
        }
      }
    }

    // All retries exhausted — return empty list rather than crashing the
    // workflow; deterministic pass result is still valuable. Surface the
    // failure via last_exhaustion_error so the workflow's state.errors
    // captures it (otherwise the empty list looks like "no proposals").
    if (has_last_exc) {
      logger.error(`Refiner LLM exhausted retries: ${_exc_str(last_exc)}`);
      this.last_exhaustion_error = `${_exc_type_name(last_exc)}: ${_exc_str(last_exc)}`;
    }
    return [];
  }
}

/** Convenience function — single LLM call, validated EditOps out. */
export async function refine_with_llm(
  image_path: string,
  chart_type: string | null = null,
  remaining_findings: Dict[] | null = null,
  critique: Dict | null = null,
  manifest_summary: Dict[] | null = null,
  previous_attempts: Dict[] | null = null,
  iteration = 1,
  max_iterations = 3,
  image_note: string | null = null,
  model: BaseChatModel | null = null,
): Promise<EditOp[]> {
  const agent = await RefinerLLMAgent.create(model);
  return agent.propose_edits(
    image_path,
    chart_type,
    truthy(remaining_findings) ? remaining_findings! : [],
    critique,
    truthy(manifest_summary) ? manifest_summary! : [],
    previous_attempts,
    iteration,
    max_iterations,
    image_note,
  );
}

export const __all__ = [
  'RefinerLLMAgent',
  'refine_with_llm',
  'build_manifest_summary',
];
