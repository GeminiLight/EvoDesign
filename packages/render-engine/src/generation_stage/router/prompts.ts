// Ported from evodesign/agentic_system/generation_stage/router/prompts.py — keep in sync.
//
// Router prompts — lightweight classifier for diagram_type + palette_key.
//
// The diagram type and palette routing tables are loaded from dedicated
// Markdown digest files under ``system_prompt/``:
//
// - ``diagram_type_digest.md`` — concise index of all 31 supported families.
// - ``palette_digest.md`` — concise index of all supported palettes.
//
// The full palette card (mood, balance guidance, per-family voices) is
// injected only into the styling agent for the selected key.
//
// Files are read through ``py/assets.ts`` (paths relative to
// ``evodesign/agentic_system``, i.e. ``Path(__file__).resolve().parents[2]``).

import { assetExists, assetIsDir, assetPath, readAssetText } from '../../py/assets.ts';
import { pyStrip } from '../../py/str.ts';

export class FileNotFoundError extends Error {
  override name = 'FileNotFoundError';
}

export const _SYSTEM_PROMPT_DIR = 'system_prompt';

/** Read a digest Markdown file from ``system_prompt/``. */
export function _load_digest(filename: string): string {
  const path = `${_SYSTEM_PROMPT_DIR}/${filename}`;
  if (assetExists(path) && !assetIsDir(path)) {
    return pyStrip(readAssetText(path));
  }
  throw new FileNotFoundError(`Router digest file missing: ${assetPath(path)}`);
}

export const _DIAGRAM_TYPE_ROUTING_TABLE = _load_digest('diagram_type_digest.md');
export const _PALETTE_ROUTING_TABLE = _load_digest('palette_digest.md');

// ---------------------------------------------------------------------------
// Router system prompt
//
// Deliberately small. The Router is a classifier, not a generator — it does
// NOT need the full EvoDesign system prompt. It only needs diagram type
// descriptions, palette routing rules, and override logic.
// ---------------------------------------------------------------------------

export const _ROUTER_SYSTEM_PROMPT_TEMPLATE = `\
You are a lightweight diagram classifier. Given a source text and user intent, determine two routing variables for the downstream pipeline. Your goal is to pick the **best-fit** diagram type and the **most aesthetically coherent** palette so the downstream agents produce a clear, professional diagram.

## Override rules (highest priority)

If the user_query explicitly specifies a diagram_type or palette_key (e.g. "make a swimlane", "use clinical_mint"), you MUST use that exact value — do not second-guess the user. Only classify the variable the user did NOT specify.

## Valid diagram_types (with descriptions)

{{diagram_type_routing_table}}

## Valid palette_keys (with selection guide)

{{palette_routing_table}}

## Selection goal

Pick the diagram_type whose **structural pattern** best matches the content's inherent organization (e.g. temporal flow → timeline, actor interactions → sequence, containment hierarchy → architecture). Pick the palette whose **selection guide** best matches the topic and desired visual voice (e.g. general refined → \`blush_sage\`, systems/pipelines → \`ocean_glass\`, healthcare / clinical → \`clinical_mint\`, engineering authority → \`slate_pro\`). When ambiguous, prefer the type that makes the diagram **instantly recognizable** to its audience and a Tier A palette from the digest.
`;

/** ``str.replace(old, new)`` (all occurrences, no ``$`` patterns). */
const replaceAll = (text: string, old: string, replacement: string): string => text.split(old).join(replacement);

export const _ROUTER_SYSTEM_PROMPT = replaceAll(
  replaceAll(_ROUTER_SYSTEM_PROMPT_TEMPLATE, '{{diagram_type_routing_table}}', _DIAGRAM_TYPE_ROUTING_TABLE),
  '{{palette_routing_table}}',
  _PALETTE_ROUTING_TABLE,
);

// ---------------------------------------------------------------------------
// Router task prompt
// ---------------------------------------------------------------------------

export const _ROUTER_TASK_PROMPT = `\
Classify the following text and user intent into routing variables.

text_content:
{{text_content}}

user_query:
{{user_query}}

---

Return ONLY a JSON object (no markdown fences, no prose):
{
  "diagram_type": "<one of the valid diagram_types>",
  "palette_key": "<one of the valid palette_keys, snake_case>",
  "reasoning": "<one sentence: why this type and palette best fit the content>",
  "retrieval_query": "<15-25 words describing the diagram's structural pattern and key design challenges, using diagram-type terminology — NOT the user's raw text>"
}
`;

/** Return the router system prompt. */
export function get_router_system_prompt(): string {
  return _ROUTER_SYSTEM_PROMPT;
}

/** Return the router task prompt template (with {{placeholders}}). */
export function get_router_task_prompt(): string {
  return _ROUTER_TASK_PROMPT;
}

export const __all__ = ['get_router_system_prompt', 'get_router_task_prompt'];
