// Ported from evodesign/agentic_system/generation_stage/router/agent.py — keep in sync.
// server-only (BaseAgent / LangChain.js)
//
// RouterAgent — lightweight classifier for diagram_type + palette_key.
//
// Uses a small system prompt (~300 tokens) and task prompt (~200 tokens) to
// classify the input text into two routing variables before the main pipeline
// runs. This replaces the full EvoDesign system prompt with a focused
// classifier prompt, keeping cost low (~500-1500 tokens total per call).
//
// ``run`` is async (``BaseAgent.invoke`` is); the call order is unchanged.
// ``evodesign/agentic_system/generation_stage/router/__init__.py`` only
// re-exports this module's names.

import type { BaseChatModel } from '@langchain/core/language_models/chat_models';
import { DiagramTypeValidationError, normalize_supported_diagram_type } from '../../common/diagram_types.ts';
import { BaseAgent } from '../../core/base_agent.ts';
import { RuntimeError } from '../../py/errors.ts';
import { getLogger } from '../../py/logging.ts';
import { pyRepr, pyStr, pyStrip } from '../../py/str.ts';
import { isDict, pyTypeName, truthy } from '../../py/truthy.ts';
import { get_router_system_prompt, get_router_task_prompt } from './prompts.ts';

const logger = getLogger('evodesign.agentic_system.generation_stage.router.agent');

// Default palette used when the router is intentionally disabled.
export const DEFAULT_PALETTE_KEY = 'blush_sage';

/** Raised when an enabled router cannot produce a valid routing result. */
export class RouterClassificationError extends RuntimeError {
  constructor(message?: string, cause?: unknown) {
    super(message);
    this.name = 'RouterClassificationError';
    if (cause !== undefined) (this as { cause?: unknown }).cause = cause;
  }
}

/** ``str(d.get(key) or "")`` */
const textField = (result: Record<string, unknown>, key: string): string => {
  const value = Object.prototype.hasOwnProperty.call(result, key) ? result[key] : null;
  return pyStr(truthy(value) ? value : '');
};

/**
 * Classify input text into diagram_type, palette_key, and retrieval_query.
 *
 * Input: text_content + user_query
 * Output: dict with diagram_type, palette_key, reasoning, retrieval_query
 *
 * This agent intentionally does NOT use the full EvoDesign system prompt.
 * It has its own small system prompt focused on classification.
 */
export class RouterAgent extends BaseAgent {
  constructor(
    model: BaseChatModel,
    kwargs: Record<string, unknown> = {},
  ) {
    super(
      model,
      get_router_system_prompt(),
      get_router_task_prompt(),
      [],
      {
        exclude_think: Object.prototype.hasOwnProperty.call(kwargs, 'exclude_think') ? kwargs.exclude_think : true,
        jsonalize_output: true,
        json_retry_attempts: 3,
        strict_json_output: true,
      },
    );
  }

  /**
   * Run the router classifier.
   *
   * @param text_content The source text being diagrammed.
   * @param user_query The user's intent string.
   * @returns Dict with keys: diagram_type, palette_key, reasoning, retrieval_query.
   * @throws RouterClassificationError If the model call fails or returns an
   *   invalid routing payload. Router failures are quality-critical and
   *   should not be converted into plausible diagram defaults.
   */
  // ``user_query`` is optional only so the signature stays assignable to
  // ``BaseAgent.run(state)``; Python requires both arguments.
  async run(text_content: string, user_query?: string | null): Promise<Record<string, string>> {
    const { PALETTE_KEYS } = await import('../styling/colorful.ts');

    let result: unknown;
    try {
      result = await this.invoke({
        text_content: text_content || '',
        user_query: user_query || 'N/A',
      });
    } catch (exc) {
      throw new RouterClassificationError('Router classification failed', exc);
    }

    if (!isDict(result)) {
      throw new RouterClassificationError(
        `Router returned ${pyTypeName(result)}; expected a JSON object`,
      );
    }

    let diagram_type = pyStrip(textField(result, 'diagram_type'));
    try {
      diagram_type = normalize_supported_diagram_type(diagram_type);
    } catch (exc) {
      if (!(exc instanceof DiagramTypeValidationError)) throw exc;
      if (!diagram_type) {
        throw new RouterClassificationError('Router output missing diagram_type', exc);
      }
      throw new RouterClassificationError(exc.message, exc);
    }

    const palette_key = pyStrip(textField(result, 'palette_key'));
    if (!PALETTE_KEYS.includes(palette_key)) {
      throw new RouterClassificationError(
        `Router output palette_key=${pyRepr(palette_key)} is not in the palette catalog`,
      );
    }

    const reasoning = textField(result, 'reasoning');
    const retrieval_query = textField(result, 'retrieval_query');

    logger.info(
      '[RouterAgent] Classified: diagram_type=%s, palette_key=%s',
      diagram_type, palette_key,
    );

    return {
      diagram_type,
      palette_key,
      reasoning,
      retrieval_query,
    };
  }
}

export const __all__ = ['RouterAgent', 'RouterClassificationError', 'DEFAULT_PALETTE_KEY'];
