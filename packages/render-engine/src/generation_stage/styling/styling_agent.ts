// Ported from evodesign/agentic_system/generation_stage/styling/styling_agent.py — keep in sync.
// server-only (BaseAgent / LangChain.js)
//
// StylingAgent Implementation (Unified One-Shot)
//
// Generates styling and icon decisions in a single LLM call.
// ``run`` is async (``invoke_with_history`` is); the call order is unchanged.

import type { BaseChatModel } from '@langchain/core/language_models/chat_models';
import { EVODESIGN_SKILL_SYSTEM_PROMPT } from '../../common/skill_loader.ts';
import {
  build_assistant_content,
  build_stage_messages,
  parse_stage_output,
  unwrap_structure_instantiation,
} from '../../common/spec_utils.ts';
import { ICON_FALLBACK_NAME, icon_name_exists } from '../../common/icon_assets.ts';
import { ICON_SUFFIX, TITLE_SUFFIX, companion_id } from '../../common/semantic_ids.ts';
import { build_styling_task_prompt } from './prompts.ts';
import { DEFAULT_PALETTE_KEY } from '../router/agent.ts';
import { TLDrawColorValidator } from '../../common/tldraw_utils.ts';
import { BaseAgent, _render_template, type ChatMessageDict } from '../../core/base_agent.ts';
import { DEFAULT_ICON_COLOR, resolve_icon_color_name } from './icon_colors.ts';
import { StylingValidationError, validate_styling_instantiation } from './schemas.ts';
import type { WorkflowState } from './state.ts';
import { expand_styling_output, use_compact_decisions } from '../compact_decisions.ts';
import { bundled_icons } from '../../common/node_icons.ts';
import { AttributeError, KeyError, PyTypeError, ValueError } from '../../py/errors.ts';
import { getLogger } from '../../py/logging.ts';
import { pyLower, pyRepr, pyStrip } from '../../py/str.ts';
import { isDict, pyOr, pyTypeName, truthy } from '../../py/truthy.ts';

const logger = getLogger('evodesign.agentic_system.generation_stage.styling.styling_agent');

type Dict = Record<string, unknown>;

// Icon configuration
export const ICON_NAME_PATTERN = /[^a-z0-9_]/g;

/** ``dict.get(key, default)`` */
function get(d: Dict, key: string, defaultValue: unknown = null): unknown {
  return Object.prototype.hasOwnProperty.call(d, key) ? d[key] : defaultValue;
}

/** ``key in dict`` */
function has(d: Dict, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(d, key);
}

/** ``for item in value`` over a JSON value. */
function iterate(value: unknown): unknown[] {
  if (Array.isArray(value)) return value;
  if (typeof value === 'string') return [...value];
  if (isDict(value)) return Object.keys(value);
  throw new PyTypeError(`'${pyTypeName(value)}' object is not iterable`);
}

/** ``value.get(key)`` on an arbitrary value (AttributeError unless it is a dict). */
function attrGet(value: unknown, key: string): unknown {
  if (!isDict(value)) {
    throw new AttributeError(`'${pyTypeName(value)}' object has no attribute 'get'`);
  }
  return get(value, key);
}

/**
 * Combined Styling Agent: Directly generates styling from semantic topology.
 *
 * Input: conversation_history (with Structure messages), structure_instantiation, text_content, user_query
 * Output: styling_instantiation (styling JSON + normalized :icon entries)
 *
 * Note: Icon URLs are added later by render_engine/shared/icon_url_adder.py
 */
export class StylingAgent extends BaseAgent {
  use_icons: boolean;

  constructor(
    model: BaseChatModel,
    tools: unknown[] | null = null,
    use_icons = false,
    kwargs: Dict = {},
  ) {
    kwargs = { ...kwargs };
    if (!has(kwargs, 'strict_json_output')) kwargs.strict_json_output = true;
    super(
      model,
      EVODESIGN_SKILL_SYSTEM_PROMPT,
      build_styling_task_prompt(
        use_icons,
        DEFAULT_PALETTE_KEY,
      ),
      tools,
      kwargs,
    );
    this.use_icons = use_icons;
  }

  /** Normalize icon name and ensure the icon file exists; fallback when invalid. */
  _normalize_icon_name(icon_name: unknown): string {
    if (typeof icon_name !== 'string') {
      return ICON_FALLBACK_NAME;
    }

    let normalized = pyLower(pyStrip(icon_name)).replaceAll('-', '_').replaceAll(' ', '_');
    normalized = normalized.replace(ICON_NAME_PATTERN, '');
    if (!normalized) {
      return ICON_FALLBACK_NAME;
    }

    if (has(bundled_icons(), normalized) || icon_name_exists(normalized)) {
      return normalized;
    }
    return ICON_FALLBACK_NAME;
  }

  /** Resolve icon name and color from flexible payload formats. */
  _resolve_icon_name_and_color(
    icon_payload: unknown,
    fallback_color: unknown = null,
  ): [string, string] {
    let icon_name: unknown = null;
    let icon_color: unknown = null;

    if (typeof icon_payload === 'string') {
      icon_name = icon_payload;
    } else if (isDict(icon_payload)) {
      const payload = icon_payload;
      const props = (isDict(get(payload, 'props')) ? get(payload, 'props') : payload) as Dict;

      icon_name = pyOr(pyOr(
        get(props, 'icon'),
        get(props, 'icon_name')),
      get(props, 'name'));
      icon_color = pyOr(get(props, 'color'), get(props, 'icon_color'));
    }

    const normalized_name = this._normalize_icon_name(icon_name);
    const normalized_color = resolve_icon_color_name(
      (truthy(icon_color) ? icon_color : pyOr(fallback_color, DEFAULT_ICON_COLOR)) as string | null,
    );
    return [normalized_name, normalized_color];
  }

  /**
   * Build normalized :icon entry with icon name and color.
   *
   * ``props.color`` is an icon *asset directory* key, never a render colour.
   */
  _build_icon_entry(icon_payload: unknown, host_element: unknown): Dict {
    // Prefer the host element's strokeColor as icon color — the LLM
    // often emits generic "black" instead of the actual palette color.
    let host_color: unknown = null;
    if (isDict(host_element)) {
      host_color = get(host_element, 'strokeColor');
      if (!truthy(host_color)) {
        const props = get(host_element, 'props');
        if (isDict(props)) {
          host_color = get(props, 'color');
        }
      }
    }

    let [icon_name, icon_color] = this._resolve_icon_name_and_color(
      icon_payload, host_color,
    );

    // If the LLM provided a generic/default color but the host has a
    // palette color, prefer the host's color for visual coherence.
    if (truthy(host_color) && icon_color === DEFAULT_ICON_COLOR) {
      icon_color = resolve_icon_color_name(host_color as string);
    }

    return {
      type: 'icon',
      props: {
        icon: icon_name,
        color: icon_color,
      },
    };
  }

  _is_icon_key(key: string): boolean {
    return key.endsWith(ICON_SUFFIX);
  }

  /**
   * Normalize icon payloads into dedicated `<element_id>:icon` entries.
   *
   * Supports:
   * 1) Nested `props.icon` on element nodes.
   * 2) Top-level `icon` on element nodes.
   * 3) Direct canonical icon entries (`<id>:icon`).
   */
  _postprocess_styling_json(styling_json: Dict): Dict {
    const processed: Dict = Object.create(null);
    let extracted_icons = 0;
    let normalized_icons = 0;

    // Pass 1: extract inline icons; the existing props format takes priority.
    for (const [element_id, element_data] of Object.entries(styling_json)) {
      if (this._is_icon_key(element_id)) {
        continue;
      }

      const copied = structuredClone(element_data);
      processed[element_id] = copied;

      if (!isDict(copied)) {
        continue;
      }

      const props = get(copied, 'props');
      const nested_icon = isDict(props) && has(props, 'icon');
      if (!nested_icon && !has(copied, 'icon')) {
        continue;
      }

      const raw_icon = nested_icon ? (props as Dict).icon : copied.icon;
      if (isDict(props)) delete props.icon;
      delete copied.icon;
      const icon_entry_key = companion_id(element_id, ICON_SUFFIX);
      processed[icon_entry_key] = this._build_icon_entry(raw_icon, copied);
      extracted_icons += 1;
    }

    // Pass 2: normalize direct icon keys; direct icon output takes priority
    for (const [element_id, element_data] of Object.entries(styling_json)) {
      if (!this._is_icon_key(element_id)) {
        continue;
      }

      const base_key = element_id.slice(0, -ICON_SUFFIX.length);
      processed[element_id] = this._build_icon_entry(element_data, get(processed, base_key));
      normalized_icons += 1;
    }

    if (extracted_icons || normalized_icons) {
      logger.info(
        '[StylingAgent] Post-processing: '
        + `extracted ${extracted_icons} nested icons, `
        + `normalized ${normalized_icons} direct icon entries`,
      );
    }

    return processed;
  }

  /** Record failures on states that expose Structure-style error hooks. */
  _record_error(state: WorkflowState, message: string): void {
    const add_error = (state as unknown as Dict).add_error;
    if (typeof add_error === 'function') {
      (add_error as (m: string) => unknown).call(state, message);
    }
  }

  _collect_structure_edge_ids(
    structure_instantiation: Dict | null,
  ): Set<string> {
    const structure = unwrap_structure_instantiation(structure_instantiation);

    const edge_ids = new Set<string>();
    for (const edge of iterate(pyOr(get(structure, 'edges'), []))) {
      if (isDict(edge) && typeof get(edge, 'id') === 'string') {
        edge_ids.add(edge.id as string);
      }
    }
    return edge_ids;
  }

  /** Keep only edge color in styling output; layout owns all other edge fields. */
  _sanitize_edge_styling(
    styling_json: Dict,
    canvas_library: string,
    structure_instantiation: Dict | null = null,
  ): Dict {
    const sanitized: Dict = Object.create(null);
    let sanitized_edge_count = 0;
    const structure_edge_ids = this._collect_structure_edge_ids(structure_instantiation);

    for (const [element_id, element_data] of Object.entries(styling_json)) {
      const is_structure_edge = typeof element_id === 'string' && structure_edge_ids.has(element_id);
      const is_edge_like = typeof element_id === 'string' && element_id.startsWith('edge:');
      if (!((is_structure_edge || is_edge_like) && isDict(element_data))) {
        sanitized[element_id] = element_data;
        continue;
      }

      let edge_entry: Dict;
      if (canvas_library === 'excalidraw') {
        edge_entry = {};
        if (typeof get(element_data, 'strokeColor') === 'string') {
          edge_entry.strokeColor = element_data.strokeColor;
        }
      } else {
        edge_entry = {};
        const props = get(element_data, 'props');
        if (isDict(props) && typeof get(props, 'color') === 'string') {
          edge_entry.props = {
            color: TLDrawColorValidator.normalize_color(props.color as string),
          };
        }
      }

      sanitized[element_id] = edge_entry;
      const removed_fields = Object.keys(element_data).length - Object.keys(edge_entry).length;
      if (removed_fields > 0) {
        sanitized_edge_count += 1;
      }
    }

    if (sanitized_edge_count) {
      logger.info(
        '[StylingAgent] Edge sanitization: '
        + `reduced ${sanitized_edge_count} edge entries to color-only styling`,
      );
    }

    return sanitized;
  }

  /**
   * Copy label strings from Structure output into matching styling entries.
   *
   * Edge labels are deliberately NOT seeded here (see the Python docstring).
   */
  _inject_labels_from_structure(
    styling_json: Dict,
    structure_instantiation: Dict | null,
  ): Dict {
    if (!isDict(styling_json) || !isDict(structure_instantiation)) {
      return styling_json;
    }

    structure_instantiation = unwrap_structure_instantiation(structure_instantiation);

    const _set_label = (entry: Dict, label_text: unknown): void => {
      if (!truthy(label_text)) {
        return;
      }
      const existing = get(entry, 'label');
      if (isDict(existing) && truthy(get(existing, 'text'))) {
        return; // Respect anything the LLM already set.
      }
      entry.label = { ...(isDict(existing) ? existing : {}), text: label_text };
    };

    // Nodes
    for (const node of iterate(pyOr(get(structure_instantiation, 'nodes', []), []))) {
      if (!isDict(node)) {
        continue;
      }
      const node_id = get(node, 'id');
      if (typeof node_id !== 'string') {
        continue;
      }
      const entry = get(styling_json, node_id);
      if (isDict(entry)) {
        _set_label(entry, get(node, 'label', ''));
      }
    }

    // Groups: label attaches to the :title entry
    for (const group of iterate(pyOr(get(structure_instantiation, 'groups', []), []))) {
      if (!isDict(group)) {
        continue;
      }
      const group_id = get(group, 'id');
      if (typeof group_id !== 'string') {
        continue;
      }
      const label_text = get(group, 'label', '');
      for (const candidate of [companion_id(group_id, TITLE_SUFFIX), group_id]) {
        const entry = get(styling_json, candidate);
        if (isDict(entry) && (get(entry, 'type') === 'text' || get(entry, 'shape') === 'text')) {
          _set_label(entry, label_text);
          break;
        }
      }
    }

    // Edges: intentionally skipped — see the docstring. Layout owns the edge
    // entry the renderer reads, so the fallback belongs there.

    return styling_json;
  }

  /**
   * Run the combined styling agent to generate styling JSON and icon entries.
   *
   * Returns the updated workflow state with styling_instantiation and an
   * extended ``conversation_history``.
   */
  async run(state: WorkflowState): Promise<WorkflowState> {
    const input_dict = {
      text_content: pyOr(state.text_content, ''),
      user_query: pyOr(state.user_query, 'N/A'),
      content_area: pyOr(state.content_area, 'N/A'),
      stage_knowledge: pyOr(state.stage_knowledge, ''),
      design_expertise: pyOr(state.design_expertise, ''),
      runtime_directives: pyOr(state.runtime_directives, ''),
    };

    const compact = use_compact_decisions(state.structure_instantiation, state.canvas_library);

    // Render task prompt with the router-selected or explicit default
    // palette card. The prompt builder rejects missing/unknown palettes.
    let rendered_task = build_styling_task_prompt(
      this.use_icons,
      pyOr(state.palette_key, ''),
      state.canvas_library,
      compact,
    );
    rendered_task = _render_template(rendered_task, input_dict);

    const messages: ChatMessageDict[] = build_stage_messages(this._system_prompt as string, rendered_task, [
      ['Structure', state.structure_specification, state.structure_instantiation],
    ]);

    logger.info('[StylingAgent] Invoking LLM...');
    let raw_output = await this.invoke_with_history(messages);

    let parsed;
    try {
      if (compact) {
        raw_output = expand_styling_output(raw_output, state.structure_instantiation);
      }
      parsed = parse_stage_output(
        raw_output,
        'Styling',
        true,
        true,
        true,
      );
    } catch (exc) {
      if (exc instanceof ValueError) {
        this._record_error(state, exc.message);
        throw new StylingValidationError(exc.message);
      }
      throw exc;
    }

    const specification = parsed.specification;
    let styling_json = parsed.instantiation as Dict;

    if (truthy(specification)) {
      state.update_stage('styling_specification', specification);
    }

    styling_json = this._inject_labels_from_structure(
      styling_json,
      state.structure_instantiation,
    );
    styling_json = this._postprocess_styling_json(styling_json);
    // An unchecked option is a hard contract, even if the model or a
    // retrieved design memory happens to suggest decorative icons.
    const structure = unwrap_structure_instantiation(state.structure_instantiation);
    const node_ids = new Set<unknown>();
    for (const n of iterate(get(structure, 'nodes', []))) {
      if (!isDict(n)) {
        throw new PyTypeError(`'${pyTypeName(n)}' object is not subscriptable`);
      }
      if (!has(n, 'id')) {
        throw new KeyError(pyRepr('id'));
      }
      node_ids.add(n.id);
    }
    for (const key of Object.keys(styling_json)) {
      if (!key.endsWith(ICON_SUFFIX)) {
        continue;
      }
      const host = key.slice(0, -ICON_SUFFIX.length);
      const entry = styling_json[key] as Dict;
      const name = attrGet(pyOr(get(entry, 'props'), {}), 'icon');
      let eligible = this.use_icons && node_ids.has(host);
      if (state.canvas_library === 'excalidraw') {
        eligible = eligible
          && ['rectangle', 'ellipse'].includes(attrGet(get(styling_json, host, {}), 'shape') as string)
          && typeof name === 'string' && has(bundled_icons(), name);
      }
      // Coverage is a design preference, not a safety limit. The prompt
      // prefers sparse icons, but explicit user coverage must survive.
      if (!eligible) {
        delete styling_json[key];
      }
    }
    styling_json = this._sanitize_edge_styling(
      styling_json,
      state.canvas_library,
      state.structure_instantiation,
    );
    try {
      styling_json = validate_styling_instantiation(
        styling_json,
        state.structure_instantiation,
        state.canvas_library,
      );
    } catch (exc) {
      if (exc instanceof StylingValidationError) {
        this._record_error(state, exc.message);
      }
      throw exc;
    }

    state.update_stage('styling_instantiation', styling_json);

    // Save conversation history
    const assistant_content = build_assistant_content(
      'Styling Design Specification',
      specification,
      styling_json,
    );
    messages.push({ role: 'assistant', content: assistant_content });
    state.conversation_history = messages as Record<string, string>[];

    return state;
  }
}
