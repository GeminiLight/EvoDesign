// Ported from evodesign/agentic_system/verification_stage/critic/critic_agent.py — keep in sync.
// server-only (reads the PNG, calls the chat model)
//
// Single-shot VLM critic agent.
//
// This module deliberately stays small: build one multimodal HumanMessage,
// invoke the model once, parse the JSON, return a Critique. No tool-calling,
// no iteration — that's what refinement_stage is for.
//
// The PNG is read as raw bytes and base64-encoded for the API's
// ``image_url`` payload. We do NOT use any image-display tool here — only the
// remote VLM sees the image.
//
// Async: ``VerifierCriticAgent(model=None)`` creates its model with
// ``LLMFactory.create_for_role("verifier")``, which is async in TS. A TS
// constructor cannot await, so the ``model is None`` path lives in the static
// ``VerifierCriticAgent.create(...)`` (same parameters, same order: capability
// check first, then model creation). ``new VerifierCriticAgent(model, ...)``
// requires a model. ``critique()`` is async.

import { readUInt32BE } from '../../py/bytes.ts';
import { readFileSync } from '../../py/fs.ts';
import type { BaseChatModel } from '@langchain/core/language_models/chat_models';
import { HumanMessage, SystemMessage, type BaseMessage } from '@langchain/core/messages';
import { VERIFIER_CRITIC_SYSTEM_PROMPT, build_user_prompt } from './prompts.ts';
import { _is_permanent_http_error, _sleep, charge_llm_run_budget } from '../../core/base_agent.ts';
import { LLMFactory } from '../../core/llm_factory.ts';
import { ModelConfig } from '../../config/model_loader.ts';
import { image_to_data_url } from '../../utils/io_utils.ts';
import { convert_json_output } from '../../utils/llm_output.ts';
import { JSONDecodeError, KeyError, PyTypeError, ValueError, ZeroDivisionError } from '../../py/errors.ts';
import { PyJSONDecodeError } from '../../py/json_decoder.ts';
import { getLogger } from '../../py/logging.ts';
import { pyGet } from '../../py/dict.ts';
import { pyFloatParse } from '../../py/number.ts';
import { pyRepr, pyStr, pyStrip } from '../../py/str.ts';
import { isDict, truthy } from '../../py/truthy.ts';
import { Critique, DimensionCritique } from '../state.ts';

const logger = getLogger('evodesign.agentic_system.verification_stage.critic.critic_agent');

type Dict = Record<string, any>;

/** ``Image.open(path).size`` for the PNGs the renderer writes (IHDR width/height). */
function _image_size(image_path: string): [number, number] {
  const bytes = readFileSync(image_path);
  if (bytes.length < 24 || ![0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a].every((b, i) => bytes[i] === b)) {
    // PIL.UnidentifiedImageError (an OSError)
    throw new Error(`cannot identify image file '${image_path}'`);
  }
  return [readUInt32BE(bytes, 16), readUInt32BE(bytes, 20)];
}

/** ``e[key]`` on a dict (KeyError when missing). */
function _item(e: Dict, key: string): unknown {
  if (!Object.prototype.hasOwnProperty.call(e, key)) throw new KeyError(pyRepr(key));
  return e[key];
}

/** ``float(x)``: TypeError for non-numbers, ValueError for bad strings. */
function _float(value: unknown): number {
  if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'string') return pyFloatParse(value);
  throw new PyTypeError(`float() argument must be a string or a real number, not '${value === null ? 'NoneType' : Array.isArray(value) ? 'list' : typeof value === 'object' ? 'dict' : typeof value}'`);
}

/** ``a / b`` with Python's ZeroDivisionError. */
function _div(a: number, b: number): number {
  if (b === 0) throw new ZeroDivisionError('float division by zero');
  return a / b;
}

/** ``a > b`` for the opacity filter (``None > 0`` raises TypeError). */
function _gt0(value: unknown): boolean {
  if (typeof value === 'number') return value > 0;
  if (typeof value === 'boolean') return value;
  throw new PyTypeError(`'>' not supported between instances of '${value === null ? 'NoneType' : typeof value}' and 'int'`);
}

/**
 * Reduce oversampled exports, keeping the smallest visible text >=16px.
 *
 * Dense or imported scenes with unknown text geometry keep full resolution.
 * This policy changes only qualitative critic input, never refiner coordinates.
 */
export function review_image_edge_limit(image_path: string, manifest: Dict | null): number | null {
  const [width, height] = _image_size(image_path);
  if (Math.max(width, height) <= 3072) {
    return 3072;
  }
  const source = (truthy(manifest) ? manifest : {}) as Dict;
  const elements = (pyGet(source, 'elements', []) as Dict[]).filter(
    (e) => !truthy(pyGet(e, 'isDeleted')) && _gt0(pyGet(e, 'opacity', 100)),
  );
  const labels = elements.filter((e) => pyGet(e, 'type') === 'text' && truthy(pyStrip(pyGet(e, 'text', '') as string)));
  if (!labels.length) {
    return null;
  }
  try {
    const min_font = Math.min(...labels.map((e) => _float(_item(e, 'fontSize'))));
    const left = Math.min(...elements.map((e) => _float(_item(e, 'x'))));
    const top = Math.min(...elements.map((e) => _float(_item(e, 'y'))));
    const right = Math.max(...elements.map((e) => _float(_item(e, 'x')) + Math.abs(_float(_item(e, 'width')))));
    const bottom = Math.max(...elements.map((e) => _float(_item(e, 'y')) + Math.abs(_float(_item(e, 'height')))));
    const scale = Math.min(_div(width, right - left), _div(height, bottom - top));
    const font_pixels = min_font * scale;
    if (!Number.isFinite(font_pixels) || font_pixels <= 0) {
      return null;
    }
    return Math.max(3072, Math.ceil(_div(Math.max(width, height) * 16, font_pixels)));
  } catch (error) {
    if (error instanceof KeyError || error instanceof PyTypeError || error instanceof ValueError || error instanceof ZeroDivisionError) {
      return null;
    }
    throw error;
  }
}

/**
 * The VLM response lacks a required score.
 *
 * A missing score is a critic failure, never an implicit 0: a fabricated low
 * "before" score would let ``quality_policy.verified_learning_gain`` credit a
 * fake improvement and write it into design memory.
 */
export class IncompleteCritiqueError extends ValueError {}

export function _required_score(payload: Dict, key: string, label: string): number {
  const raw = pyGet(payload, key);
  if (typeof raw === 'boolean' || raw === null || raw === undefined) {
    throw new IncompleteCritiqueError(`VLM critique is missing ${label}`);
  }
  let score: number;
  try {
    score = _float(raw);
  } catch (error) {
    if (error instanceof PyTypeError || error instanceof ValueError) {
      throw new IncompleteCritiqueError(`VLM critique has a non-numeric ${label}: ${pyRepr(raw)}`);
    }
    throw error;
  }
  if (!Number.isFinite(score)) {
    throw new IncompleteCritiqueError(`VLM critique has a non-finite ${label}: ${pyRepr(raw)}`);
  }
  // max(0.0, min(10.0, score))
  const low = score < 10.0 ? score : 10.0;
  return 0.0 < low ? low : 0.0;
}

/** Require a numeric score; clamp it and default missing arrays to []. */
export function _coerce_dimension(payload: unknown, name: string): DimensionCritique {
  if (!isDict(payload)) {
    throw new IncompleteCritiqueError(`VLM critique is missing the ${name} dimension`);
  }
  const score = _required_score(payload, 'score', `${name}.score`);

  const _as_str_list = (key: string): string[] => {
    const raw = pyGet(payload, key);
    if (Array.isArray(raw)) {
      return raw.filter((x) => x !== null && x !== undefined).map((x) => pyStr(x));
    }
    if (typeof raw === 'string') {
      return [raw];
    }
    return [];
  };

  return new DimensionCritique({
    score,
    strengths: _as_str_list('strengths'),
    weaknesses: _as_str_list('weaknesses'),
    suggestions: _as_str_list('suggestions'),
  });
}

/**
 * Turn the parsed dict into a strict Critique pydantic model.
 *
 * Raises ``IncompleteCritiqueError`` when ``overall_score`` or any dimension
 * score is missing or non-numeric.
 */
export function _coerce_critique(data: Dict, raw: string | null): Critique {
  const structure = _coerce_dimension(pyGet(data, 'structure'), 'structure');
  const styling = _coerce_dimension(pyGet(data, 'styling'), 'styling');
  const layout = _coerce_dimension(pyGet(data, 'layout'), 'layout');
  const overall = _required_score(data, 'overall_score', 'overall_score');

  let summary: unknown = pyGet(data, 'summary', '');
  if (!truthy(summary)) summary = '';
  if (typeof summary !== 'string') {
    summary = pyStr(summary);
  }

  const violations = pyGet(data, 'constraint_violations', []);
  return new Critique({
    structure,
    styling,
    layout,
    overall_score: overall,
    summary,
    constraint_violations: Array.isArray(violations)
      ? violations.filter((value) => truthy(value)).map((value) => pyStr(value))
      : [pyStr(_item(data, 'constraint_violations'))],
    raw_response: raw,
  });
}

/** ``isinstance(exc, json.JSONDecodeError)`` */
function _is_json_decode_error(error: unknown): boolean {
  return error instanceof PyJSONDecodeError || error instanceof JSONDecodeError;
}

/** Wraps the VLM for the verifier's single subjective-critic call. */
export class VerifierCriticAgent {
  model: BaseChatModel;
  max_retries: number;
  retry_delay_seconds: number;
  max_image_edge: number | null;

  constructor(
    model: BaseChatModel | null = null,
    max_retries = 3,
    retry_delay_seconds = 5.0,
    max_image_edge: number | null = 3072,
  ) {
    if (model === null || model === undefined) {
      // ``model or LLMFactory.create_for_role("verifier")`` needs an await.
      throw new PyTypeError('VerifierCriticAgent(model=None): use `await VerifierCriticAgent.create(...)`');
    }
    this.model = model;
    this.max_retries = max_retries;
    this.retry_delay_seconds = retry_delay_seconds;
    this.max_image_edge = max_image_edge;
  }

  /** ``VerifierCriticAgent(model=..., ...)`` including the ``model is None`` path. */
  static async create(
    model: BaseChatModel | null = null,
    max_retries = 3,
    retry_delay_seconds = 5.0,
    max_image_edge: number | null = 3072,
  ): Promise<VerifierCriticAgent> {
    if (model === null || model === undefined) {
      ModelConfig.get_default().require_model_capabilities('verifier', new Set(['vision']));
    }
    const resolved = model ?? (await LLMFactory.create_for_role('verifier'));
    return new VerifierCriticAgent(resolved, max_retries, retry_delay_seconds, max_image_edge);
  }

  _build_messages(
    image_path: string,
    chart_type: string | null,
    source_text: string | null,
    objective_summary: Dict | null,
  ): BaseMessage[] {
    const data_url = image_to_data_url(image_path, this.max_image_edge);
    const user_text = build_user_prompt(chart_type, source_text, objective_summary);
    const human = new HumanMessage({
      content: [
        { type: 'image_url', image_url: { url: data_url, detail: 'high' } },
        { type: 'text', text: user_text },
      ],
    });
    return [new SystemMessage({ content: VERIFIER_CRITIC_SYSTEM_PROMPT }), human];
  }

  /** Run one VLM call → Critique. Errors raise; caller decides recovery. */
  async critique(
    image_path: string,
    chart_type: string | null = null,
    source_text: string | null = null,
    objective_summary: Dict | null = null,
  ): Promise<Critique> {
    const started = performance.now() / 1000;
    const messages = this._build_messages(image_path, chart_type, source_text, objective_summary);

    let last_error: unknown = null;
    let delay = this.retry_delay_seconds;
    for (let attempt = 1; attempt <= this.max_retries; attempt++) {
      charge_llm_run_budget(); // outside try: an exhausted run budget is final
      let answered = false;
      try {
        const response = await this.model.invoke(messages);
        if (response === null || response === undefined || !truthy((response as { content?: unknown }).content ?? null)) {
          throw new ValueError('VLM returned an empty response');
        }
        answered = true;
        let raw: unknown = response.content;
        if (Array.isArray(raw)) {
          // Some langchain backends wrap multimodal as parts list.
          raw = raw
            .filter((part) => isDict(part))
            .map((part) => pyGet(part as Dict, 'text', ''))
            .join('');
        }
        if (typeof raw !== 'string') {
          raw = pyStr(raw);
        }

        let data: unknown;
        try {
          data = convert_json_output(raw as string);
        } catch (error) {
          if (_is_json_decode_error(error)) {
            throw new ValueError('Could not extract JSON object from VLM response');
          }
          throw error;
        }
        if (!isDict(data)) {
          throw new ValueError('VLM response is not a JSON object');
        }
        const critique = _coerce_critique(data, raw as string);
        const usage = (response as { usage_metadata?: unknown }).usage_metadata;
        critique.call_metrics = {
          duration_ms: Math.trunc((performance.now() / 1000 - started) * 1000),
          attempts: attempt,
          max_image_edge: this.max_image_edge,
          usage: truthy(usage ?? null) ? usage : {},
        };
        return critique;
      } catch (exc) {
        last_error = exc;
        logger.warning(`VLM critique attempt ${attempt}/${this.max_retries} failed: ${(exc as Error)?.message ?? pyStr(exc)}`);
        // Auth / bad request / exhausted quota cannot succeed on retry.
        if (_is_permanent_http_error(exc)) {
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

    if (last_error === null) throw new Error('AssertionError');
    throw last_error;
  }
}

export const __all__ = ['VerifierCriticAgent'];
