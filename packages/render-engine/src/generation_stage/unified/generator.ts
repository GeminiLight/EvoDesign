// Ported from evodesign/agentic_system/generation_stage/unified/generator.py — keep in sync.
// server-only (BaseAgent / LangChain.js; transport journal writes files)
//
// UnifiedGenerator — single LLM call that emits a full Excalidraw scene.
//
// Context: the 3-stage pipeline has a strong methodology but pays 3x input
// tokens (each stage re-reads the 50K skill system prompt) and is vulnerable to
// format drift between stages. This agent is the experimental alternative: one
// LLM call, the same skill system prompt, but a single task prompt asking for
// the final Excalidraw clipboard JSON directly.
//
// The LLM still performs the three-phase diagnostic internally; we just skip
// the serialisation round-trip between stages. Deterministic post-processors
// (group fitter, validator) still run afterwards — they work on the native
// Excalidraw schema so they don't care which stage produced the elements.
//
// TS notes
// --------
// * ``UNIFIED_TASK_PROMPT`` is emitted from the Python f-string's AST (the
//   ``{{``/``}}`` escapes already resolved); its sha256 equals Python's
//   (da52b17d…, see migration/notes/WP18.md).
// * ``model.model_copy(update={"callbacks": ...})`` → ``_model_copy`` (a
//   shallow clone of the chat model instance with ``callbacks`` replaced).
// * ``str(self._last_raw_output)`` is Python's ``repr`` of the agent state
//   dict, including LangChain message reprs → ``_py_str_raw_output``.
// * ``deepcopy`` of model output keeps the integral-float marks
//   (ISSUES.md WP17-1) so the repair turn's ``json.dumps`` prints ``64.0``.

import { dirname, join } from 'node:path';
import type { BaseChatModel } from '@langchain/core/language_models/chat_models';
import { BaseMessage } from '@langchain/core/messages';
import { EVODESIGN_SKILL_SYSTEM_PROMPT } from '../../common/skill_loader.ts';
import {
  build_diagram_context,
  build_stage_knowledge,
  get_selected_palette,
} from '../../common/domain_knowledge_loader.ts';
import {
  CANVAS_DEFAULT_VIEWPORT_HEIGHT,
  CANVAS_DEFAULT_VIEWPORT_WIDTH,
} from '../../canvas_runtime.ts';
import { BaseAgent, type ChatMessageDict, type PromptDict } from '../../core/base_agent.ts';
import { preprocess_response } from '../../utils/llm_output.ts';
import { _deepcopy_with_py_floats, _with_py_floats } from '../layout/sequence_layout.ts';
import { ValueError } from '../../py/errors.ts';
import { PyJSONDecodeError } from '../../py/json_decoder.ts';
import { pyJsonDumps } from '../../py/json.ts';
import { getLogger } from '../../py/logging.ts';
import { pySorted } from '../../py/sort.ts';
import { pyRepr, pyStr, pyStrip } from '../../py/str.ts';
import { isDict, isList, pyTypeName, truthy } from '../../py/truthy.ts';
import { validate_semantic_sidecar } from './sidecar.ts';
import type { UnifiedWorkflowState } from './state.ts';
import { NativeStreamJournal } from './transport_journal.ts';
import { invoke_native_scene } from './continuation.ts';

type Dict = Record<string, unknown>;

export const _REQUIRED_TOP_LEVEL_KEYS = new Set(['type', 'elements', 'files', 'appState', '_meta']);

const logger = getLogger('evodesign.agentic_system.generation_stage.unified.generator');

export const _CANVAS_VIEWPORT_LABEL = (
  `${CANVAS_DEFAULT_VIEWPORT_WIDTH}x${CANVAS_DEFAULT_VIEWPORT_HEIGHT}`
);

export const UNIFIED_TASK_PROMPT = pyStrip(`
### CURRENT TASK: One-shot Diagram Generation (Unified mode) ###

Apply ALL three phases from the methodology in your system prompt as internal
thinking before writing JSON:
  Phase 1 — Structural Diagnosis (family, organizer, entities, edges w/ Visual
             Necessity Filter, calibration anchor)
  Phase 2 — Visual System Design (recognition anchor, shape language, colour
             system, typography, role hierarchy)
  Phase 3 — Layout Composition (${_CANVAS_VIEWPORT_LABEL} hard canvas limit,
             profile-first composition, organizer-first placement, derive
             group bounds from children, self-audit)

Then output a single Excalidraw clipboard JSON object plus a semantic sidecar.
Do NOT emit any "specification" / "instantiation" wrapper — go straight to
the scene envelope below.

### OUTPUT FORMAT (strict) ###
Return EXACTLY this top-level shape, with keys in the shown order and no extra keys:
{
  "type": "excalidraw/clipboard",
  "elements": [ ... ],
  "files": {},
  "appState": {"viewBackgroundColor": "<canvas hex from PALETTE>", "gridSize": null},
  "_meta": {
    "structure_instantiation": {
      "chart_type": "<canonical diagram_type>",
      "nodes": [
        {"id": "n_semantic_id", "label": "Node label", "class": "semantic role"}
      ],
      "edges": [
        {"id": "edge:n_source2n_target", "source": "n_source", "target": "n_target"}
      ],
      "groups": []
    },
    "id_map": {
      "n_semantic_id": "<matching Excalidraw element id>",
      "edge:n_source2n_target": "<matching arrow element id>"
    }
  }
}

### ELEMENT CONTRACT ###
Author the visual decisions only. Every element MUST include:
  id (unique string), type, x, y, width, height, strokeColor, backgroundColor.
Include groupIds for related elements, and style overrides where meaningful.
The runtime supplies these omitted defaults: angle=0, fillStyle=solid,
strokeWidth=1.5, strokeStyle=solid, roughness=0, opacity=100, groupIds=[],
roundness=null, plus stable seed/version/versionNonce, index, isDeleted=false,
frameId=null, link=null, locked=false, updated, and reciprocal boundElements.
OMIT that repeated metadata from your output. Explicit visual overrides are
preserved. Never omit actual geometry, semantic IDs, or relation endpoints.

Type-specific additions:
- rectangle / ellipse / diamond: use \`roundness: {"type": 3}\` for rounded rects,
  \`null\` for sharp corners.
- text: text, fontSize (16-24 typical),
  textAlign ("left"|"center"|"right"),
  verticalAlign ("top"|"middle"|"bottom"), containerId (string or null),
  fontFamily only when different from Helvetica (2). Runtime supplies
  originalText=text, autoResize=true, lineHeight=1.25.
- arrow: points (array of \`[dx, dy]\` relative to x/y; first point is [0,0]),
  startBinding ({"elementId":"...","focus":0,"gap":5} or null),
  endBinding (same shape or null),
  startArrowhead (null|"arrow"|"triangle"|"dot"),
  endArrowhead (null|"arrow"|"triangle"|"dot"),
  elbowed (bool).
- arrow elements MUST include \`meta.semantic_edge_id\` matching an edge id from
  \`_meta.structure_instantiation.edges[*].id\`.

### SEMANTIC SIDECAR CONTRACT ###
\`_meta.structure_instantiation\` uses the exact same semantic graph contract as
the multiagent Structure stage:
- canonical \`chart_type\` from the supported diagram type registry
- every node has \`id\`, \`label\`, and \`class\`
- every edge has \`id\`, \`source\`, and \`target\`, with id format
  \`edge:{source_id}2{target_id}\`
- every edge endpoint references an existing node
- type-specific fields are mandatory when applicable (for example
  \`parent_id\` for mindmap/tree/orgchart, \`row\`/\`col\` for matrix,
  \`actor_id\`/\`sequence_idx\` for sequence diagrams, \`start_ts\`/\`end_ts\` for gantt)

For \`concept_map\`, include the complete contract on the first response:
- Every node has \`branch_id\`: the \`core_concept\` uses null, each
  \`branch_anchor\` uses its own id, and other nodes use their owning anchor id.
  Ownership describes the source grouping; a cross-group fact never changes it.
- Every edge has a readable \`label\`, \`relation_type\`, \`directionality\`, and
  \`evidence_basis\`. The ONLY relation types are \`hierarchy\`, \`composition\`,
  \`exemplification\`, \`dependency\`, \`causal\`, and \`association\`. Use \`causal\`
  for enabling/improvement predicates; retain the precise meaning in \`label\`.
  Do not invent compound enum values.
- \`directionality\` is exactly \`directed\` or \`undirected\`; choose it from the
  source predicate. A weak or symmetric association is not automatically causal.
- \`evidence_basis\` is exactly \`explicit\` or \`structural\`. EVERY explicit edge
  also requires \`evidence\`: a short source phrase supporting that specific
  subject, predicate, and object. Preserve source qualifiers and collective
  subjects. Structural organizer edges may omit evidence.
- An explicit hierarchy, composition, or exemplification is still a source
  fact. Preserve it along with dependency and causal facts; never reclassify
  facts as structural merely to simplify the drawing.

\`_meta.id_map\` maps every semantic node id and edge id to its Excalidraw
element id. Semantic groups may map either the group id itself or the
\`<group_id>:background\` companion id to the rendered group frame. Additional
companion keys are allowed only for real semantic bases:
\`<node_or_group_or_edge_id>:title\`, \`:label\`, \`:icon\`, or \`:background\`.
If a semantic edge is rendered as an arrow, the arrow's \`meta.semantic_edge_id\`
MUST equal that semantic edge id. This sidecar is not optional: verifier and
render audit use it to prove semantic coverage.
Map every visible relation label with \`<edge_id>:label\`. A standalone relation
label may use containerId=null; the runtime derives its semantic ownership from
this explicit mapping so later geometry edits preserve the label and its style.

### BINDING / GROUP INVARIANTS ###
1. Every element's \`id\` MUST be unique across the scene.
2. Stable seed, versionNonce, and editor bookkeeping are supplied by code.
3. Arrow bindings and text containerId MUST reference real element IDs.
   The runtime derives reciprocal boundElements; do not repeat them.
4. Set containerId on bound text to its owning element. Standalone group
   titles use \`containerId: null\` and live outside their group's bounds so
   they render above the container.
5. Related elements (lane background + title + children) share the same
   \`groupIds\` array (e.g. \`["group-marketing"]\`). Group membership implies
   belonging — do NOT draw arrows just to signal containment.
6. Use ONLY colours from the injected PALETTE card. Set \`viewBackgroundColor\`
   to its \`canvas\` value, use \`border_default\` for neutral structure, and pair
   every fill with the matching stroke from the same family. Do not import the
   legacy Excalidraw default palette or raw primary colours.

### COMPOSITION BUDGET ###
\`${_CANVAS_VIEWPORT_LABEL}\` is a safety boundary, NOT a target size. Before
placing elements, choose the smallest profile that fits readable labels:
- compact \`1200x800\`: up to 8 ordinary nodes
- wide \`1600x900\`: 9-16 nodes, architecture layers, timelines, or swimlanes
- large \`2400x1600\`: more than 16 nodes or genuinely long labels
Use 70-90% of the chosen profile in the dominant direction. Keep outer margins
40-80 px, ordinary node gaps 40-80 px, and group padding 32-64 px. Upgrade one
profile only when the content cannot fit at readable sizes; never spread a
small diagram across the full hard limit.

For architecture diagrams, use draw.io-like compact components: Helvetica 18,
ordinary rectangles approximately 180-300 px wide and 56-72 px high, sized to
their labels rather than forced to one oversized width. Use a white canvas,
light role fill plus darker matching border, and visually quiet group surfaces.
Primary dependency flow uses neutral solid 2 px connectors with a filled
triangle end; dashed coloured connectors are reserved for cross-cutting,
feedback, or other secondary relations. Prefer orthogonal paths with at most
2-3 bends and never use double-headed arrows unless the relation is genuinely
bidirectional.

### COLOUR HIERARCHY ###
- Keep one resting family on at least half of ordinary nodes.
- Reserve the strongest family for one or two primary anchors, not every node.
- Use at most two supporting families unless distinct categories require more.
- Group surfaces must be lighter and quieter than their child nodes.
- Connector colours encode meaning; routine edges use \`border_default\` or
  \`accent_edge\` consistently rather than inheriting arbitrary node colours.

### ZERO-BLOAT DISCIPLINE ###
- Apply the Visual Necessity Filter to every edge before adding it.
- Relationships implied by group membership, layer containment, or spatial
  proximity MUST NOT become arrows.
- No ghost nodes, no empty containers, no redundant edges.

### DIAGRAM CONTEXT ###
{{diagram_context}}

### DOMAIN KNOWLEDGE (all stages) ###
{{stage_knowledge}}

### PALETTE ###
{{palette_card}}

### DESIGN EXPERTISE ###
{{design_expertise}}

### RUNTIME DIRECTIVES ###
{{runtime_directives}}

### INPUTS ###
text_content:
{{text_content}}

user_query:
{{user_query}}

Return ONLY the JSON object. No markdown fences, no prose, no specification
wrapper.
`);

// ── TS-only helpers ──────────────────────────────────────────────────────

/** ``model.model_copy(update={"callbacks": callbacks})`` (shallow, like pydantic). */
export function _model_copy(model: BaseChatModel, callbacks: unknown): BaseChatModel {
  const copy = Object.create(Object.getPrototypeOf(model)) as BaseChatModel;
  Object.assign(copy, model);
  (copy as unknown as { callbacks: unknown }).callbacks = callbacks;
  return copy;
}

// Fields of langchain_core message models in declaration order. Serializable
// ``__repr_args__`` omits values equal to a field default; fields built by a
// ``default_factory`` (additional_kwargs, response_metadata, tool_calls,
// invalid_tool_calls) are always shown.
const _MESSAGE_REPR_FIELDS: Record<string, [string, 'always' | 'non_null'][]> = {
  HumanMessage: [],
  SystemMessage: [],
  AIMessage: [['tool_calls', 'always'], ['invalid_tool_calls', 'always'], ['usage_metadata', 'non_null']],
};

const _JS_AGENT_MODEL_NODE_NAME = 'model';

function _message_repr(message: BaseMessage): string {
  const type = message.getType();
  const cls = ({ human: 'HumanMessage', ai: 'AIMessage', system: 'SystemMessage' } as Record<string, string>)[type]
    ?? message.constructor.name;
  const record = message as unknown as Dict;
  const args: string[] = [`content=${_py_str_raw_output(message.content)}`];
  args.push(`additional_kwargs=${_py_str_raw_output(record.additional_kwargs ?? {})}`);
  args.push(`response_metadata=${_py_str_raw_output(record.response_metadata ?? {})}`);
  for (const name of ['name', 'id']) {
    const value = record[name];
    // LangChain.js ``createAgent`` stamps ``name: 'model'`` on the AIMessage
    // its model node returns; Python ``create_agent`` leaves ``name=None``.
    if (name === 'name' && cls === 'AIMessage' && value === _JS_AGENT_MODEL_NODE_NAME) continue;
    if (value !== null && value !== undefined) args.push(`${name}=${_py_str_raw_output(value)}`);
  }
  for (const [name, mode] of _MESSAGE_REPR_FIELDS[cls] ?? []) {
    const value = record[name];
    if (mode === 'always') args.push(`${name}=${_py_str_raw_output(value ?? [])}`);
    else if (value !== null && value !== undefined) args.push(`${name}=${_py_str_raw_output(value)}`);
  }
  return `${cls}(${args.join(', ')})`;
}

/** ``str(value)`` for the agent output (state dict with LangChain messages). */
export function _py_str_raw_output(value: unknown): string {
  if (value instanceof BaseMessage) return _message_repr(value);
  if (isList(value)) return `[${value.map((item) => _py_str_raw_output(item)).join(', ')}]`;
  if (isDict(value)) {
    return `{${Object.entries(value)
      .filter(([, item]) => item !== undefined)
      .map(([key, item]) => `${pyRepr(key)}: ${_py_str_raw_output(item)}`)
      .join(', ')}}`;
  }
  return pyRepr(value);
}

// ── agent ────────────────────────────────────────────────────────────────

/**
 * One-shot Excalidraw generator. Skips the structure/styling/layout split.
 *
 * Inputs: ``text_content``, ``user_query``, optional ``design_expertise`` and
 * ``runtime_directives``.
 * Output: a complete Excalidraw clipboard dict assigned to
 * ``state.diagram_manifest``.
 */
export class UnifiedGenerator extends BaseAgent {
  stream_journal: NativeStreamJournal;
  full_domain_knowledge: boolean;

  constructor(
    model: BaseChatModel,
    tools: unknown[] | null = null,
    full_domain_knowledge = true,
    kwargs: Dict = {},
  ) {
    kwargs = { ...kwargs };
    if (!Object.prototype.hasOwnProperty.call(kwargs, 'strict_json_output')) kwargs.strict_json_output = true;
    const stream_journal = new NativeStreamJournal();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const existing: any = model.callbacks;
    let callbacks: unknown;
    if (existing !== null && existing !== undefined && !Array.isArray(existing)) {
      // BaseCallbackManager
      callbacks = existing.copy();
      (callbacks as { addHandler: (h: unknown) => void }).addHandler(stream_journal);
    } else {
      callbacks = [...(existing ?? []), stream_journal];
    }
    super(
      _model_copy(model, callbacks),
      EVODESIGN_SKILL_SYSTEM_PROMPT,
      UNIFIED_TASK_PROMPT,
      tools,
      kwargs,
    );
    this.stream_journal = stream_journal;
    this.full_domain_knowledge = full_domain_knowledge;
  }

  override _invoke_with_retry(input_prompt: PromptDict): Promise<unknown> {
    return invoke_native_scene(this._agent, input_prompt, this.stream_journal);
  }

  override async invoke_with_history(messages: ChatMessageDict[], tools: unknown[] | null = null): Promise<unknown> {
    if (tools !== null && tools !== undefined) {
      return super.invoke_with_history(messages, tools);
    }
    const prompt: PromptDict = {
      messages: messages.filter(
        (message) => !(message.role === 'system' && message.content === this._system_prompt),
      ),
    };
    for (let attempt = 0; attempt < this.json_retry_attempts; attempt += 1) {
      const raw_output = await this._invoke_with_retry(prompt);
      this._last_raw_output = raw_output;
      try {
        return preprocess_response(
          raw_output, true, this.exclude_think,
          this.jsonalize_output, this.strict_json_output,
        );
      } catch (error) {
        if (!(error instanceof PyJSONDecodeError)) throw error;
        if (attempt + 1 === this.json_retry_attempts) {
          throw error;
        }
      }
    }
    return null;
  }

  async run(state: UnifiedWorkflowState): Promise<UnifiedWorkflowState> {
    const journal_directory = (
      state.validation_report_path
        ? join(dirname(state.validation_report_path), 'transport')
        : null
    );
    this.stream_journal.configure(journal_directory, !truthy(state.generation_attempts));
    // Build type knowledge if diagram_type is available (Router output or
    // caller-provided).  When absent the LLM must infer from text alone.
    const diagram_type = state.diagram_type || '';
    const diagram_context = diagram_type ? build_diagram_context(diagram_type) : '';
    // Unified mode sees ALL stage rules since a single LLM call must do
    // structure + styling + layout internally. Respect the config toggle
    // so A/B experiments can compare full vs stage-specific knowledge.
    const stage_knowledge = build_stage_knowledge(
      diagram_type, null, this.full_domain_knowledge,
    );

    // Palette card
    let palette_card = '';
    if (state.palette_key) {
      palette_card = get_selected_palette(state.palette_key);
      if (!palette_card) {
        throw new ValueError(`Unknown palette_key: ${pyRepr(state.palette_key)}`);
      }
    }

    const input_dict: Dict = {
      text_content: state.text_content || '',
      user_query: state.user_query || '',
      diagram_context: diagram_context || 'N/A',
      stage_knowledge: stage_knowledge || 'N/A',
      palette_card: palette_card || 'N/A',
      design_expertise: state.design_expertise || 'N/A',
      runtime_directives: state.runtime_directives || 'N/A',
    };
    let raw_output: unknown;
    if (state.validation_error && truthy(state.generation_attempts)) {
      const previous = state.generation_attempts[state.generation_attempts.length - 1];
      const messages: ChatMessageDict[] = [
        { role: 'system', content: this._system_prompt },
        ...this._build_prompt(input_dict).messages,
        { role: 'assistant', content: pyJsonDumps(_with_py_floats(previous.output), { ensureAscii: false }) },
        {
          role: 'user',
          content: (
            'The scene failed executable validation at '
            + `${pyStr(previous.stage)}: ${state.validation_error}\n`
            + 'Correct the specific contract errors in this current scene. '
            + 'Preserve source facts, stable semantic IDs, and unaffected layout '
            + 'and styling. Return the complete corrected scene JSON, with no prose. '
            + 'Do not omit facts or weaken validation to make the scene pass.'
          ),
        },
      ];
      logger.info('[UnifiedGenerator] Repairing scene from validation feedback...');
      raw_output = await this.invoke_with_history(messages);
    } else {
      logger.info('[UnifiedGenerator] Invoking LLM (single-shot)...');
      raw_output = await this.invoke(input_dict);
    }
    state.candidate_output = _deepcopy_with_py_floats(raw_output);

    // Capture the last raw LLM output string for debugging / token audit.
    if (this._last_raw_output !== null && this._last_raw_output !== undefined) {
      state.raw_llm_output = _py_str_raw_output(this._last_raw_output);
    }

    if (!isDict(raw_output)) {
      throw new ValueError(
        `UnifiedGenerator expected a dict from LLM; got ${pyTypeName(raw_output)}`,
      );
    }

    const top_level_keys = new Set(Object.keys(raw_output));
    const missing_keys = [..._REQUIRED_TOP_LEVEL_KEYS].filter((key) => !top_level_keys.has(key));
    if (missing_keys.length) {
      const missing = pySorted(missing_keys).join(', ');
      throw new ValueError(
        `UnifiedGenerator output missing required top-level key(s): ${missing}`,
      );
    }
    const extra_keys = [...top_level_keys].filter((key) => !_REQUIRED_TOP_LEVEL_KEYS.has(key));
    if (extra_keys.length) {
      const extra = pySorted(extra_keys).join(', ');
      throw new ValueError(
        `UnifiedGenerator output has unexpected top-level key(s): ${extra}`,
      );
    }
    if (raw_output.type !== 'excalidraw/clipboard') {
      throw new ValueError(
        "UnifiedGenerator output 'type' must be 'excalidraw/clipboard'",
      );
    }
    if (!isList(raw_output.elements)) {
      throw new ValueError(
        "UnifiedGenerator output 'elements' must be a list; "
        + `got ${pyTypeName(raw_output.elements)}`,
      );
    }
    if (!isDict(raw_output.files)) {
      throw new ValueError("UnifiedGenerator output 'files' must be a dict");
    }
    if (!isDict(raw_output.appState)) {
      throw new ValueError("UnifiedGenerator output 'appState' must be a dict");
    }

    const structure_instantiation = validate_semantic_sidecar(raw_output);
    state.structure_instantiation = structure_instantiation;
    state.diagram_manifest = raw_output;
    return state;
  }
}
