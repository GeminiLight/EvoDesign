// Ported from evodesign/agentic_system/generation_stage/structure/structure_agent.py — keep in sync.
// server-only (BaseAgent / LangChain.js)
//
// Structure agent — Stage 1 of the EvoDesign pipeline.
//
// Uses the shared ``EVODESIGN_SKILL_SYSTEM_PROMPT`` as its system message and
// the minimal ``STRUCTURE_TASK_PROMPT`` as its task message. After a successful
// run it stores a conversation thread on the workflow state so downstream agents
// can inherit the Structure task and output without serialising prompt blocks.
//
// Self-consistency (optional)
// ---------------------------
// When the env var ``STRUCTURE_SELF_CONSISTENCY_N`` is set to an integer >= 2,
// this agent draws that many independent samples concurrently and majority-votes
// on the ``chart_type`` field via ``common.self_consistency.sample_and_vote``.
// Non-voted fields come from a single winning sample so ids/coords stay
// internally consistent. When the env var is unset or <= 1, behaviour is
// identical to single-shot (the default).
//
// ``run`` is async (``invoke_with_history`` is); the call order is unchanged.

import type { BaseChatModel } from '@langchain/core/language_models/chat_models';
import { sample_and_vote } from '../../common/self_consistency.ts';
import { EVODESIGN_SKILL_SYSTEM_PROMPT } from '../../common/skill_loader.ts';
import { build_assistant_content, parse_stage_output } from '../../common/spec_utils.ts';
import { AppSettings } from '../../config/settings.ts';
import { BaseAgent, _render_template, type ChatMessageDict } from '../../core/base_agent.ts';
import { pyJsonDumps } from '../../py/json.ts';
import { getLogger } from '../../py/logging.ts';
import { isDict, truthy } from '../../py/truthy.ts';
import { STRUCTURE_TASK_PROMPT } from './prompts.ts';
import {
  StructureLedgerOmission,
  StructureValidationError,
  drop_unrealized_ledger_entries,
  restore_structure_ledger_relations,
  validate_structure_instantiation,
  validate_structure_semantic_ledger,
} from './schemas.ts';
import type { WorkflowState } from './state.ts';

const logger = getLogger('evodesign.agentic_system.generation_stage.structure.structure_agent');

type Dict = Record<string, unknown>;

/** Unwrap and canonicalize one Structure sample before self-consistency voting. */
export function _unwrap_and_validate_structure_sample(raw_output: unknown): [Dict | null, Dict] {
  const parsed = parse_stage_output(
    raw_output,
    'StructureAgent',
    true,
  );
  return [parsed.specification, validate_structure_instantiation(parsed.instantiation)];
}

/**
 * Generate the semantic topology directly from text.
 *
 * Input: text_content, user_query, design_expertise, runtime_directives.
 * Output: structure_specification (Phase-1 diagnosis) + structure_instantiation (concrete graph).
 */
export class StructureAgent extends BaseAgent {
  constructor(
    model: BaseChatModel,
    tools: unknown[] | null = null,
    kwargs: Record<string, unknown> = {},
  ) {
    const options = { ...kwargs };
    if (!Object.prototype.hasOwnProperty.call(options, 'strict_json_output')) options.strict_json_output = true;
    super(
      model,
      EVODESIGN_SKILL_SYSTEM_PROMPT,
      STRUCTURE_TASK_PROMPT,
      tools,
      options,
    );
  }

  /**
   * Keep a corrected structure that only omits listed claims.
   *
   * After the correction turn, a ledger entry that still has no edge is a
   * claim the diagram leaves out. Dropping the entry keeps the ledger an
   * honest record of what is drawn. An edge outside the ledger is a claim
   * the source may not support, so that case still fails.
   * Returns the pruned specification, or None when it cannot be kept.
   */
  static _drop_omitted_claims(
    specification: unknown, instantiation: Dict, exc: StructureValidationError,
  ): Dict | null {
    for (let i = 0; i < ['fact_ledger', 'organizer_ledger'].length; i += 1) {
      if (!(exc instanceof StructureLedgerOmission) || !isDict(specification)) {
        return null;
      }
      logger.warning(
        '[StructureAgent] Diagram omits %d %s claim(s); dropping them from the ledger: %s',
        exc.missing.length, exc.ledger_name, exc.missing,
      );
      specification = drop_unrealized_ledger_entries(specification, exc);
      try {
        validate_structure_semantic_ledger(specification, instantiation);
        return specification as Dict;
      } catch (next_exc) {
        if (!(next_exc instanceof StructureValidationError)) throw next_exc;
        exc = next_exc;
      }
    }
    return null;
  }

  /** Read self-consistency sample count from settings; default 1 (single-shot). */
  _read_self_consistency_n(): number {
    return AppSettings.get_default().structure_self_consistency_n;
  }

  async run(state: WorkflowState): Promise<WorkflowState> {
    const input_dict: Dict = {
      text_content: state.text_content || '',
      user_query: state.user_query || '',
      content_area: state.content_area || 'N/A',
      stage_knowledge: state.stage_knowledge || 'N/A',
      design_expertise: state.design_expertise || 'N/A',
      runtime_directives: state.runtime_directives || 'N/A',
    };

    // Render task prompt
    const rendered_task = _render_template(STRUCTURE_TASK_PROMPT, input_dict);

    // Build conversation: system + user task
    // Use type-specific system prompt when diagram_type is available
    const system_prompt = this._system_prompt;
    const messages: ChatMessageDict[] = [
      { role: 'system', content: system_prompt },
      { role: 'user', content: rendered_task },
    ];

    let specification: Dict | null;
    let instantiation: unknown;
    const n_samples = this._read_self_consistency_n();
    if (n_samples >= 2) {
      logger.info(
        `[StructureAgent] Invoking LLM (self-consistency N=${n_samples}, `
        + "vote_key='chart_type')...",
      );

      const _invoke_sc = (_input_dict: Dict) => this.invoke_with_history(messages);

      [specification, instantiation] = await sample_and_vote(
        _invoke_sc,
        input_dict,
        n_samples,
        'chart_type',
        _unwrap_and_validate_structure_sample,
      );
    } else {
      logger.info('[StructureAgent] Invoking LLM...');
      const raw_output = await this.invoke_with_history(messages);
      const parsed = parse_stage_output(
        raw_output,
        'StructureAgent',
        true,
      );
      specification = parsed.specification;
      instantiation = parsed.instantiation;
    }

    for (let attempt = 0; attempt < 2; attempt += 1) {
      try {
        instantiation = validate_structure_instantiation(instantiation);
        instantiation = restore_structure_ledger_relations(specification, instantiation as Dict);
        validate_structure_semantic_ledger(specification, instantiation as Dict);
        break;
      } catch (exc) {
        if (!(exc instanceof StructureValidationError)) throw exc;
        if (attempt === 1) {
          specification = StructureAgent._drop_omitted_claims(specification, instantiation as Dict, exc);
          if (specification !== null) {
            break;
          }
          state.add_error(exc.message);
          throw exc;
        }
        logger.warning('Structure contract failed; requesting one correction: %s', exc.message);
        messages.push(
          {
            role: 'assistant',
            content: pyJsonDumps({
              specification, instantiation,
            }, { ensureAscii: false }),
          },
          {
            role: 'user',
            content: (
              'The structure failed validation: ' + exc.message
              + '\nReturn a corrected complete specification/instantiation JSON object. '
              + 'Keep the source facts and their direction. Repair the reported contract '
              + 'violation without deleting facts or inventing relations.'
            ),
          },
        );
        const parsed = parse_stage_output(
          await this.invoke_with_history(messages), 'StructureAgent',
          true,
        );
        [specification, instantiation] = [parsed.specification, parsed.instantiation];
      }
    }

    if (truthy(specification)) {
      state.update_stage('structure_specification', specification);
    }
    state.update_stage('structure_instantiation', instantiation);

    // Save conversation history for downstream agents
    const assistant_content = build_assistant_content(
      'Structure Design Specification',
      specification,
      instantiation,
    );
    messages.push({ role: 'assistant', content: assistant_content });
    state.conversation_history = messages as Record<string, string>[];

    return state;
  }
}
