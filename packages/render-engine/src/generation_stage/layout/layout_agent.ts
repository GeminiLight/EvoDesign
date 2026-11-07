// Ported from evodesign/agentic_system/generation_stage/layout/layout_agent.py — keep in sync.
// server-only (BaseAgent / LangChain.js)
//
// LayoutAgent Implementation (Combined One-Shot)
//
// Stage 3 of the pipeline. Uses the shared skill system prompt and the layout
// task with complete, validated Structure + Styling artifacts from workflow state.
//
// Input:
//     - structure_instantiation / styling_instantiation and their specifications:
//       canonical upstream context, also used by the geometry merge.
//     - user_query: User's intent
//     - text_content: Original text
//
// Output:
//     - layout_instantiation: Final merged layout with coordinates
//
// ``run`` is async (``invoke_with_history`` is); the call order is unchanged.
// Python floats in the produced geometry (flow-grid centres, deterministic
// sequence geometry) are tracked with the marks of ``sequence_layout.ts`` so
// the conversation-history JSON prints ``360.0`` like Python.

import type { BaseChatModel } from '@langchain/core/language_models/chat_models';
import { EVODESIGN_SKILL_SYSTEM_PROMPT } from '../../common/skill_loader.ts';
import {
  build_assistant_content,
  build_stage_messages,
  parse_stage_output,
  unwrap_structure_instantiation,
} from '../../common/spec_utils.ts';
import { is_layout_edge_entry, validate_layout_instantiation } from '../../common/layout_contract.ts';
import { ICON_SUFFIX, drop_canvas_decorations } from '../../common/semantic_ids.ts';
import { COMPACT_FLOW_LAYOUT_TASK_PROMPT, FLOW_GRID_LAYOUT_TASK_PROMPT, LAYOUT_TASK_PROMPT } from './prompts.ts';
import { choose_layout_viewport } from './viewport_profile.ts';
import { BaseAgent, _render_template } from '../../core/base_agent.ts';
import type { WorkflowState } from './state.ts';
import { expand_layout_output, use_compact_decisions } from '../compact_decisions.ts';
import { expand_flow_grid, supports_flow_grid } from './flow_grid.ts';
import { _PY_FLOAT_FIELDS, _deepcopy_with_py_floats, _is_py_float, _mark_py_float, _with_py_floats } from './sequence_layout.ts';
import { pySetItem } from '../../py/dict.ts';
import { pyUpdate } from '../../py/float_marks.ts';
import { KeyError, PyTypeError, ValueError } from '../../py/errors.ts';
import { pyJsonDumps } from '../../py/json.ts';
import { getLogger } from '../../py/logging.ts';
import { pyRepr, pyStrip } from '../../py/str.ts';
import { isDict, isInt, pyOr, pyTypeName, truthy } from '../../py/truthy.ts';

const logger = getLogger('evodesign.agentic_system.generation_stage.layout.layout_agent');

type Dict = Record<string, unknown>;

function has(d: Dict, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(d, key);
}

function get(d: Dict, key: string, defaultValue: unknown = null): unknown {
  return has(d, key) ? d[key] : defaultValue;
}

/** ``for x in value`` over a JSON value. */
function iterate(value: unknown): unknown[] {
  if (Array.isArray(value)) return value;
  if (typeof value === 'string') return [...value];
  if (isDict(value)) return Object.keys(value);
  throw new PyTypeError(`'${pyTypeName(value)}' object is not iterable`);
}

/** ``key in container`` for a dict / None (TypeError like Python). */
function contains(container: unknown, key: string): boolean {
  if (isDict(container)) return has(container, key);
  throw new PyTypeError(`argument of type '${pyTypeName(container)}' is not iterable`);
}

const _LAYOUT_OWNED_FIELDS = ['x', 'y', 'w', 'h', 'width', 'height', 'min_width', 'min_height'];

/**
 * TS-only: carry Python-float marks from ``src`` (decoded model output) to the
 * equivalent values of ``dst`` (its expansion by ``expand_layout_output``,
 * which deep-copies). Compact ``[x,y,w,h]`` boxes map to ``{x,y,w,h}``.
 */
function _transfer_py_floats(src: unknown, dst: unknown): void {
  if (Array.isArray(src) && isDict(dst)) {
    const marks = _PY_FLOAT_FIELDS.get(src);
    if (src.length === 4 && marks) {
      ['x', 'y', 'w', 'h'].forEach((field, i) => {
        if (marks.has(String(i)) && dst[field] === src[i]) _mark_py_float(dst, field);
      });
    }
    return;
  }
  if (Array.isArray(src) && Array.isArray(dst)) {
    src.forEach((item, i) => {
      if (_is_py_float(src, String(i)) && dst[i] === item) _mark_py_float(dst, String(i));
      _transfer_py_floats(item, dst[i]);
    });
    return;
  }
  if (!isDict(src) || !isDict(dst)) return;
  for (const [key, item] of Object.entries(src)) {
    if (!has(dst, key)) continue;
    if (_is_py_float(src, key) && dst[key] === item) _mark_py_float(dst, key);
    _transfer_py_floats(item, dst[key]);
  }
}

/** Copy ``src[field]`` into ``dst[field]`` keeping the Python-float mark. */
function copyField(dst: Dict, dst_field: string, src: Dict, src_field: string): void {
  pySetItem(dst, dst_field, src[src_field]);
  _mark_py_float(dst, dst_field, _is_py_float(src, src_field));
}

/**
 * One-shot layout agent that directly generates coordinates from the
 * Structure + Styling conversation context.
 *
 * Input: conversation_history, structure_instantiation, styling_instantiation, user_query
 * Output: layout_instantiation (merged coordinates JSON)
 */
export class LayoutAgent extends BaseAgent {
  constructor(
    model: BaseChatModel,
    tools: unknown[] | null = null,
    kwargs: Dict = {},
  ) {
    kwargs = { ...kwargs };
    const exclude_think = has(kwargs, 'exclude_think') ? kwargs.exclude_think : false;
    delete kwargs.exclude_think;
    const json_retry_attempts = has(kwargs, 'json_retry_attempts') ? kwargs.json_retry_attempts : 5;
    delete kwargs.json_retry_attempts;
    if (!has(kwargs, 'strict_json_output')) kwargs.strict_json_output = true;
    super(
      model,
      EVODESIGN_SKILL_SYSTEM_PROMPT,
      LAYOUT_TASK_PROMPT,
      tools,
      { exclude_think, json_retry_attempts, ...kwargs },
    );
  }

  /**
   * Run the combined layout agent to generate layout coordinates.
   *
   * Generates directly from canonical Structure + Styling context in one
   * LLM call, without replaying their earlier task instructions.
   */
  async run(state: WorkflowState): Promise<WorkflowState> {
    const input_dict = {
      text_content: pyOr(state.text_content, ''),
      user_query: pyOr(state.user_query, 'N/A'),
      content_area: pyOr(state.content_area, 'N/A'),
      stage_knowledge: pyOr(state.stage_knowledge, ''),
      design_expertise: pyOr(state.design_expertise, ''),
      runtime_directives: pyOr(state.runtime_directives, ''),
      size_hints: _build_size_hints_prompt(state.styling_instantiation),
      viewport_plan: choose_layout_viewport(
        state.structure_instantiation,
      ).to_prompt(),
    };

    // Render task prompt
    const compact = use_compact_decisions(state.structure_instantiation, state.canvas_library);
    let task = compact ? COMPACT_FLOW_LAYOUT_TASK_PROMPT : LAYOUT_TASK_PROMPT;
    const grid = compact && supports_flow_grid(
      unwrap_structure_instantiation(state.structure_instantiation),
      state.styling_instantiation, pyOr(state.runtime_directives, '') as string,
    );
    if (grid) {
      task = FLOW_GRID_LAYOUT_TASK_PROMPT;
    }
    const rendered_task = _render_template(task, input_dict);

    const messages: Record<string, string>[] = build_stage_messages(this._system_prompt as string, rendered_task, [
      ['Structure', state.structure_specification, state.structure_instantiation],
      ['Styling', state.styling_specification, state.styling_instantiation],
    ]);

    logger.info('[LayoutAgent] Invoking LLM...');
    let raw_output = await this.invoke_with_history(messages);

    if (compact) {
      let grid_node_ids: string[] = [];
      if (grid) {
        const before = raw_output;
        raw_output = expand_flow_grid(raw_output, state.structure_instantiation, state.styling_instantiation);
        if (raw_output !== before) {
          grid_node_ids = Object.keys(((before as Dict).instantiation as Dict).nodes as Dict);
        }
      }
      const before_expand = raw_output;
      raw_output = expand_layout_output(raw_output, state.structure_instantiation);
      _transfer_py_floats(before_expand, raw_output);
      // TS-only: flow-grid boxes are ``[float x, float y, int w, int h]`` in Python.
      for (const node_id of grid_node_ids) {
        const entry = ((raw_output as Dict).instantiation as Dict)[node_id];
        if (isDict(entry)) {
          _mark_py_float(entry, 'x');
          _mark_py_float(entry, 'y');
        }
      }
    }

    const parsed = parse_stage_output(
      raw_output,
      'Layout',
      true,
      true,
      true,
    );
    const specification = parsed.specification;
    const layout_instantiation = parsed.instantiation as Dict;

    if (truthy(specification)) {
      state.update_stage('layout_specification', specification);
    }

    // Merge LLM-produced geometry onto the styled element map. The merge
    // has to run after the LLM call because styling owns colours while
    // layout owns x/y/w/h + edge routing — we reconcile both here.
    const merged_instantiation = this._merge_layout_with_styling(
      layout_instantiation,
      state.styling_instantiation,
      state.canvas_library,
      state.structure_instantiation,
    );

    state.update_stage('layout_instantiation', merged_instantiation);

    // Save conversation history
    const assistant_content = build_assistant_content(
      'Layout Design Specification',
      specification,
      _with_py_floats(merged_instantiation),
    );
    messages.push({ role: 'assistant', content: assistant_content });
    state.conversation_history = messages;

    logger.info('[LayoutAgent] Layout generation completed');
    return state;
  }

  /** Merge validated geometry with styling, resolving exact group aliases. */
  _merge_layout_with_styling(
    layout_instantiation: unknown,
    styling_instantiation: Dict,
    canvas_library = 'excalidraw',
    structure_instantiation: Dict | null = null,
  ): Dict {
    const merged_instantiation = _deepcopy_with_py_floats(styling_instantiation);

    if (!isDict(layout_instantiation)) {
      throw new ValueError(
        'LayoutAgent expected layout instantiation to be a JSON object; '
        + `got ${pyTypeName(layout_instantiation)}`,
      );
    }

    // A logical group and its :background identify the same container.
    // Models sometimes position the logical ID even when Styling emitted
    // only the background. Reconcile that exact alias before strict ID and
    // geometry validation; do not invent geometry or accept unknown IDs.
    let layout = _deepcopy_with_py_floats(layout_instantiation);
    const structure = unwrap_structure_instantiation(structure_instantiation);
    for (const group of iterate(pyOr(get(structure, 'groups', []), []))) {
      if (!isDict(group)) throw new PyTypeError(`'${pyTypeName(group)}' object is not subscriptable`);
      if (!has(group, 'id')) throw new KeyError("'id'");
      const group_id = group.id as string;
      if (typeof group_id !== 'string') {
        throw new PyTypeError(`unsupported operand type(s) for +: '${pyTypeName(group_id)}' and 'str'`);
      }
      const background_id = group_id + ':background';
      if (!contains(styling_instantiation, group_id) && contains(styling_instantiation, background_id)
        && has(layout, group_id)) {
        const geometry = layout[group_id];
        delete layout[group_id];
        if (!has(layout, background_id)) layout[background_id] = geometry;
      }
    }
    // A canvas caption Styling never declared has nothing to place.
    let decorations: string[];
    [layout, decorations] = drop_canvas_decorations(
      layout, new Set(Object.keys(pyOr(styling_instantiation, {}) as Dict)));
    if (decorations.length) {
      logger.warning(`Layout added undeclared canvas captions ${pyRepr(decorations)}; dropping them.`);
    }

    validate_layout_instantiation(
      layout,
      structure_instantiation,
      styling_instantiation,
    );

    const structure_edge_ids = new Set<string>();
    for (const edge of iterate(pyOr(get((pyOr(structure_instantiation, {}) as Dict), 'edges', []), []))) {
      if (isDict(edge) && typeof get(edge, 'id') === 'string') {
        structure_edge_ids.add(edge.id as string);
      }
    }

    for (const [key, value] of Object.entries(layout)) {
      if (key.endsWith(ICON_SUFFIX)) {
        // Icon placement is handled by renderer-side logic.
        continue;
      }

      if (is_layout_edge_entry(key, value, structure_edge_ids)) {
        const existing_edge = get(merged_instantiation, key);
        const edge_value = this._extract_edge_color_only_base(
          isDict(existing_edge) ? existing_edge : {},
          canvas_library,
        );
        pySetItem(merged_instantiation, key, edge_value);

        if (isDict(value)) {
          if (isDict(get(value, 'props'))) {
            if (!has(edge_value, 'props') || !isDict(edge_value.props)) {
              edge_value.props = {};
            }
            pyUpdate(edge_value.props as Dict, value.props as Dict);
          }

          for (const [edge_key, edge_field] of Object.entries(value)) {
            if (edge_key === 'props') {
              continue;
            }
            copyField(edge_value, edge_key, value, edge_key);
            void edge_field;
          }
        } else {
          edge_value.value = value;
        }
        continue;
      }

      if (!has(merged_instantiation, key) || !isDict(merged_instantiation[key])) {
        pySetItem(merged_instantiation, key, {});
      }

      if (!isDict(value)) {
        (merged_instantiation[key] as Dict).value = value;
        continue;
      }

      const node_value = merged_instantiation[key] as Dict;

      LayoutAgent._strip_layout_owned_fields(node_value);

      if (has(value, 'x')) {
        copyField(node_value, 'x', value, 'x');
      }
      if (has(value, 'y')) {
        copyField(node_value, 'y', value, 'y');
      }

      if (canvas_library === 'excalidraw') {
        if (has(value, 'w')) {
          copyField(node_value, 'w', value, 'w');
        }
        if (has(value, 'h')) {
          copyField(node_value, 'h', value, 'h');
        }
      } else {
        if (has(value, 'w') || has(value, 'h')) {
          if (!has(node_value, 'props') || !isDict(node_value.props)) {
            node_value.props = {};
          }
          if (has(value, 'w')) {
            copyField(node_value.props as Dict, 'w', value, 'w');
          }
          if (has(value, 'h')) {
            copyField(node_value.props as Dict, 'h', value, 'h');
          }
        }
      }

      if (isDict(get(value, 'props'))) {
        if (!has(node_value, 'props') || !isDict(node_value.props)) {
          node_value.props = {};
        }
        const value_props = value.props as Dict;
        for (const prop_key of ['w', 'h']) {
          if (has(value_props, prop_key)) {
            copyField(node_value.props as Dict, prop_key, value_props, prop_key);
          }
        }
      }
    }

    LayoutAgent._inject_edge_labels_from_structure(
      merged_instantiation,
      structure_instantiation,
    );

    return merged_instantiation;
  }

  /**
   * Backfill Structure edge labels onto layout edge entries in place.
   *
   * The renderer reads edge labels from the layout entry only (see
   * ``relations_from_edge_data``), and Styling edge entries are colour-only
   * by contract, so this is the single place a Structure edge label can
   * survive into the render. Only fills gaps: an explicit Layout label always
   * wins, and an edge that Structure left unlabelled stays unlabelled.
   */
  static _inject_edge_labels_from_structure(
    merged_instantiation: Dict,
    structure_instantiation: Dict | null,
  ): void {
    const structure = unwrap_structure_instantiation(structure_instantiation);

    for (const edge of iterate(pyOr(get(structure, 'edges'), []))) {
      if (!isDict(edge)) {
        continue;
      }
      const edge_id = get(edge, 'id');
      const label_text = get(edge, 'label');
      if (typeof edge_id !== 'string' || !edge_id) {
        continue;
      }
      if (typeof label_text !== 'string' || !pyStrip(label_text)) {
        continue;
      }

      const entry = get(merged_instantiation, edge_id);
      if (!isDict(entry)) {
        continue;
      }

      const existing = get(entry, 'label');
      if (isDict(existing)) {
        const text = get(existing, 'text');
        if (typeof text === 'string' && pyStrip(text)) {
          continue;
        }
      } else if (typeof existing === 'string' && pyStrip(existing)) {
        continue;
      }

      entry.label = { ...(isDict(existing) ? existing : {}), text: label_text };
    }
  }

  /** Remove transient size hints and stale geometry from styling data. */
  static _strip_layout_owned_fields(element_value: Dict): void {
    for (const field of _LAYOUT_OWNED_FIELDS) {
      delete element_value[field];
    }

    const props = get(element_value, 'props');
    if (isDict(props)) {
      for (const field of _LAYOUT_OWNED_FIELDS) {
        delete props[field];
      }
    }
  }

  /** Preserve only styling-owned edge color before layout overwrites geometry. */
  _extract_edge_color_only_base(
    edge_value: Dict,
    canvas_library: string,
  ): Dict {
    if (canvas_library === 'excalidraw') {
      if (typeof get(edge_value, 'strokeColor') === 'string') {
        return { strokeColor: edge_value.strokeColor };
      }
      return {};
    }

    const props = get(edge_value, 'props');
    if (isDict(props) && typeof get(props, 'color') === 'string') {
      return { props: { color: props.color } };
    }
    return { props: {} };
  }
}

export function _build_size_hints_prompt(styling_instantiation: unknown): string {
  if (!isDict(styling_instantiation)) {
    return '(none)';
  }

  const hints: Record<string, Record<string, unknown>> = Object.create(null);
  for (const [element_id, element_data] of Object.entries(styling_instantiation)) {
    if (typeof element_id !== 'string' || element_id.endsWith(ICON_SUFFIX)) {
      continue;
    }
    if (!isDict(element_data)) {
      continue;
    }
    const min_width = get(element_data, 'min_width');
    const min_height = get(element_data, 'min_height');
    // ``isinstance(x, int)`` — bool is an int too.
    if (!isInt(min_width, true) || !isInt(min_height, true)) {
      continue;
    }
    hints[element_id] = {
      min_width,
      min_height,
    };
  }

  if (!Object.keys(hints).length) {
    return '(none)';
  }
  return pyJsonDumps(hints, { ensureAscii: false, sortKeys: true });
}
