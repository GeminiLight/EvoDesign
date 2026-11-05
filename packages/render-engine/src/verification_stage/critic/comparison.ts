// Ported from evodesign/agentic_system/verification_stage/critic/comparison.py — keep in sync.
// server-only (reads the rendered PNGs, calls the chat model)
//
// Compare two verified renders without relying on independent score scales.
//
// Async: the model call (and, when `model` is null, the default critic model
// creation) is awaited. COMPARISON_PROMPT is the Python literal value.

import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import type { BaseChatModel } from '@langchain/core/language_models/chat_models';
import { HumanMessage, SystemMessage } from '@langchain/core/messages';
import { image_to_data_url } from '../../utils/io_utils.ts';
import { convert_json_output } from '../../utils/llm_output.ts';
import { PyTypeError, ValueError } from '../../py/errors.ts';
import { pyGet } from '../../py/dict.ts';
import { pySorted } from '../../py/sort.ts';
import { cpSlice, pyStr, pyStrip } from '../../py/str.ts';
import { isDict } from '../../py/truthy.ts';

type Dict = Record<string, any>;

// prettier-ignore
export const COMPARISON_PROMPT: string = "Compare two diagrams of the same source, shown as Image 1 and\nImage 2. Both have already passed the same objective checks. Choose the one that\ncommunicates the source more clearly, considering readable relationship labels,\nunambiguous endpoints, balanced spacing, alignment, typography and coherent color.\nJudge visible results, not the number of edits or a guessed production order.\n\nPreserve source meaning. Section containment can express membership; a collective\nsubject can have one outcome arrow. Navigation headings may be plain text while\nheadings that are relationship endpoints need a visible boundary. Longer routes\nare acceptable when they avoid crossings. A shorter edge does not compensate for\npushing a balanced section against its border. Do not reward hidden facts.\n\nUse tie when there is no clear overall improvement or the tradeoffs cancel out.\nGive one concrete visible reason. Return only JSON:\n{\"preference\": \"1\" | \"2\" | \"tie\", \"reason\": \"...\"}\n";

/** ``x in {"1", "2", "tie"}`` (unhashable values raise TypeError, as in Python). */
function _valid_preference(value: unknown): boolean {
  if (Array.isArray(value)) throw new PyTypeError("unhashable type: 'list'");
  if (isDict(value)) throw new PyTypeError("unhashable type: 'dict'");
  return value === '1' || value === '2' || value === 'tie';
}

/** Return an auditable preference; raise if comparison is unavailable. */
export async function compare_rendered_diagrams(
  original_path: string,
  candidate_path: string,
  source_text: string,
  model: BaseChatModel | null = null,
): Promise<Dict> {
  const paths: Record<string, string> = { original: original_path, candidate: candidate_path };
  const hashes: Record<string, string> = Object.fromEntries(
    Object.entries(paths).map(([name, path]) => [name, createHash('sha256').update(readFileSync(path)).digest('hex')]),
  );
  if (hashes.original === hashes.candidate) {
    return {
      winner: 'tie', reason: 'The rendered files are identical.',
      image_hashes: hashes, display_order: [],
    };
  }
  // Keep the presentation order independent of which image is the revision.
  const order = pySorted(Object.keys(paths), (name: string) => hashes[name]) as string[];
  const content: Dict[] = [
    { type: 'text', text: 'Source content:\n' + cpSlice(source_text, null, 12000) },
  ];
  order.forEach((name, i) => {
    const index = i + 1;
    content.push(
      { type: 'text', text: `Image ${index}:` },
      {
        type: 'image_url', image_url: {
          url: image_to_data_url(paths[name]), detail: 'high',
        },
      },
    );
  });
  if (model === null || model === undefined) {
    const { VerifierCriticAgent } = await import('./critic_agent.ts');

    model = (await VerifierCriticAgent.create()).model;
  }
  const response = await model.invoke([
    new SystemMessage({ content: COMPARISON_PROMPT }), new HumanMessage({ content: content as never }),
  ]);
  let raw: unknown = (response as { content?: unknown } | null)?.content ?? null;
  if (Array.isArray(raw)) {
    raw = raw.filter((part) => isDict(part)).map((part) => pyStr(pyGet(part as Dict, 'text', ''))).join('');
  }
  if (typeof raw !== 'string' || !pyStrip(raw)) {
    throw new ValueError('Diagram comparison returned no text');
  }
  const parsed = convert_json_output(raw);
  if (!isDict(parsed) || !_valid_preference(pyGet(parsed, 'preference'))) {
    throw new ValueError('Diagram comparison returned an invalid preference');
  }
  const reason = pyGet(parsed, 'reason');
  if (typeof reason !== 'string' || !pyStrip(reason)) {
    throw new ValueError('Diagram comparison omitted its visible evidence');
  }
  const preference = parsed.preference as string;
  return {
    winner: preference === 'tie' ? 'tie' : order[Number(preference) - 1],
    reason: pyStrip(reason), display_order: order,
    image_hashes: hashes, raw_response: raw,
  };
}
