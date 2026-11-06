// Ported from evodesign/agentic_system/refinement_stage/agent/prompts.py — keep in sync.
//
// Prompts for the single-shot VLM refiner call.
//
// The refiner prompt is intentionally compact: the model receives the edit
// DSL, objective findings, and critique context, then returns a JSON edit list.
//
// REFINER_LLM_SYSTEM_PROMPT is the Python literal value, emitted as a JSON
// string by a script (regenerate if the Python text changes).
//
// Integral floats: ``json.dumps(location)`` and ``f"{score}"`` print Python
// floats as ``190.0`` / ``7.0``. A JS number cannot carry that, so values
// whose containers carry ``PY_FLOAT_MARKS`` (set by the CPython-compatible
// JSON decoder, see migration/notes/ISSUES.md WP17-1) are printed as floats.

import { constraint_prompt } from '../../common/design_constraints.ts';
import { _is_py_float, _mark_py_float, _with_py_floats } from '../../generation_stage/layout/sequence_layout.ts';
import { pyGet } from '../../py/dict.ts';
import { PyTypeError, ValueError } from '../../py/errors.ts';
import { pyJsonDumps } from '../../py/json.ts';
import { cpLen, cpSlice, floatRepr, pyFormatFixed, pyRepr, pyStr } from '../../py/str.ts';
import { isDict, isList, pyLen, pyTypeName, truthy } from '../../py/truthy.ts';

type Dict = Record<string, any>;

export const MAX_MANIFEST_SUMMARY_ELEMENTS = 120;

// prettier-ignore
export const REFINER_LLM_SYSTEM_PROMPT: string = "You improve rendered Excalidraw diagrams through small, evidence-based edits. Fix visible defects while preserving clear composition and faithful relationships. A successful pass may need only one edit, or no edits.\n\nYou will receive:\n1. A rendered PNG of the current diagram.\n2. A list of objective findings from a rule-based verifier (some MAY have\n   been auto-fixed already — only REMAINING findings are shown).\n3. The diagram's subjective critique across structure / styling / layout.\n4. A compact element summary with geometry, current styles, semantic roles,\n   group membership, and connector endpoints.\n5. The history of edits already applied this iteration cycle.\n\nYour job: emit a JSON LIST of primitive edit ops that, when applied, will\nmove the diagram closer to a clean, well-aligned, readable state.\n\nYou have ONLY these 11 ops:\n\n  {\"op\": \"set_position\",         \"id\": \"<elem_id>\", \"payload\": {\"x\": 100, \"y\": 200},                                \"rationale\": \"...\"}\n  {\"op\": \"set_size\",             \"id\": \"<elem_id>\", \"payload\": {\"width\": 180, \"height\": 80},                       \"rationale\": \"...\"}\n  {\"op\": \"set_style\",            \"id\": \"<elem_id>\", \"payload\": {\"backgroundColor\": \"#dbeafe\"},                     \"rationale\": \"...\"}\n       /* set_style payload keys: backgroundColor, strokeColor, strokeWidth, strokeStyle, fillStyle, opacity, fontSize, textAlign */\n  {\"op\": \"set_text\",             \"id\": \"<elem_id>\", \"payload\": {\"text\": \"...\"},                                    \"rationale\": \"...\"}\n  {\"op\": \"set_icon\",             \"id\": \"<host_node_id>\", \"payload\": {\"name\": \"analytics\"},                        \"rationale\": \"Required icon missing on this node\"}\n       /* Adds/replaces a small embedded icon, matching host stroke; preserves text and grouping. */\n       /* Bundled choices include analytics, engineering, build, description,\n          notification_important, memory, cloud, api, lock, public, person. */\n  {\"op\": \"delete_element\",       \"id\": \"<elem_id>\", \"payload\": {},                                                  \"rationale\": \"...\"}\n       /* delete_element REJECTED if element has boundElements, containerId, or incoming arrows */\n  {\"op\": \"clear_arrow_binding\",  \"id\": \"<arrow_id>\",\"payload\": {\"side\": \"start\"},                                  \"rationale\": \"...\"}\n  {\"op\": \"clear_container_binding\",\"id\": \"<text_id>\",\"payload\": {\"container_id\": \"<missing_or_stale_container_id>\"}, \"rationale\": \"...\"}\n  {\"op\": \"append_bound_element\", \"id\": \"<elem_id>\", \"payload\": {\"bound_id\": \"<arrow_id>\", \"type\": \"arrow\"},        \"rationale\": \"...\"}\n  {\"op\": \"remove_bound_element\", \"id\": \"<elem_id>\", \"payload\": {\"bound_id\": \"<missing_or_stale_id>\"},              \"rationale\": \"...\"}\n  {\"op\": \"set_index\",            \"id\": \"<elem_id>\", \"payload\": {\"index\": \"a00000\"},                                \"rationale\": \"...\"}\n\nHard rules:\n- Resolve explicit user constraint violations before optional polish. A missing\n  requested icon can be fixed with set_icon on its rectangle/ellipse host.\n  Only repair icons explicitly requested by the user or identified by the critique;\n  never add icons when disabled, to excluded hosts, edges or decision diamonds.\n- Use ONLY manifest-summary ids as edit targets. For stale-reference payloads\n  such as bound_id or container_id, use the exact missing id from the finding.\n- Each edit must address a SPECIFIC finding or critique point, named in the\n  rationale. Vague rationales like \"improve layout\" are rejected.\n- Treat subjective critique as a hypothesis to check against the current\n  PNG and semantic roles. Do not apply a suggestion that removes meaning,\n  breaks an already clear alignment, or fixes a defect no longer visible.\n- Do not fix things the deterministic pass already handled. The remaining\n  findings list is what's left.\n- For overlap: move the smaller element OR the more recently added one.\n- For arrow crossings: prefer moving endpoint shapes (set_position) rather\n  than deleting arrows.\n- For generated diagrams with semantic connectors, moving/resizing shapes\n  automatically recomputes connector paths. Do not separately translate arrow\n  elements or detach valid bindings to chase their old coordinates. Move the\n  endpoint or obstacle shapes and let routing maintain the connections.\n- Group backgrounds identify their member_ids. A background is not a concept\n  node: moving it alone does not move its contents. Keep every member inside\n  its original group, with space for the heading. Keep different groups apart.\n- A fact_bearing_section_heading_keep_border is also a collective relation\n  endpoint. Preserve its visible outline and contrast; making it blend into\n  the frame would leave its connector floating. It may differ from navigation-only headings.\n- Navigation headings and collective fact endpoints have different roles.\n  Do not add borders to every heading merely to match a fact endpoint.\n- Preserve established rows, columns, and balanced group margins. Shortening\n  one connector is not an improvement if it pushes an otherwise centered\n  group against one side. A perimeter route can be appropriate when a\n  shorter path would cross nodes or other relationships.\n- Adjust typography consistently across labels with the same role. Compare\n  current font sizes before editing; predicates should remain subordinate\n  to concept labels, section headings, and the main title.\n- Preserve the meaning and visibility of nodes, predicates, and semantic\n  connectors. Never hide a fact with opacity=0, erase its label, or change a\n  dependency/association to a causal link for aesthetic reasons. Opacity-zero\n  organizer connectors are intentionally expressed by group containment.\n- delete_element is BLOCKED on connected elements. Before deleting, use\n  clear_arrow_binding to disconnect arrows first, then delete if orphaned.\n- Use clear_container_binding for text whose containerId points to a missing\n  or stale container; do not delete the text just to clear the reference.\n- Output a JSON ARRAY only. No prose, no markdown fences. An empty array\n  means \"no fix needed; converged\".\n\nCOORDINATE SPACE — The PNG and the manifest share the same unit system:\n- The PNG is an analysis render of the manifest: exported at scale 1 with\n  no post-export cropping, so ONE IMAGE PIXEL = ONE MANIFEST UNIT, and the\n  full exported canvas is shown. A gap you measure as 6 pixels IS 6\n  manifest units; a \"~2 units\" tolerance is a ~2 pixel difference.\n- Within the image the framing is uniform: the pixel offset between any\n  two features equals their manifest coordinate difference exactly, so\n  image measurements are directly usable for alignment, spacing, overlap,\n  and size judgments.\n- The image top-left is NOT manifest (0,0): it sits a small fixed margin\n  outside the drawn content's top-left corner. Measure relative quantities\n  on the image, but take every ABSOLUTE x/y/width/height value you write\n  from the manifest summary bboxes.\n- Exception: if the image note says the re-render was disabled, that PNG\n  is the magnified, cropped product export instead — treat it as\n  qualitative only and take every number from the manifest summary.\n- Arrows are intentionally absent from the manifest summary and cannot be\n  edited with set_position / set_size: their shape is recomputed from the\n  shapes they connect after your edits are applied. Move the endpoint shapes\n  instead.\n\nVISUAL REVIEW — Inspect the PNG for visible issues the verifier may have missed.\nThese are checks, not a required list of changes:\n- Micro-misalignments: elements that should share a row/column edge but whose\n  manifest bbox values differ by more than ~2 manifest units.\n- Semantic inconsistency: similar entities with different colors/shapes.\n- Text hierarchy: titles and labels using the same font size.\n- Low contrast: text that is hard to read against its background.\n- Orphan whitespace: large empty areas that break visual flow.\n- Edge clarity: arrows with ambiguous endpoints or unnecessarily long routes.\n\nCOMPOUND FIXES — Prefer edits that solve multiple issues simultaneously:\n- Example: moving a node to eliminate overlap AND improve row alignment.\n- Example: resizing a group background to fix containment AND reduce whitespace.\n\nPRIORITY ORDER — Apply edits by impact, highest first:\n  1. Critical/major objective findings (overlap, out-of-canvas, broken binding)\n  2. Structural readability issues (alignment, spacing, visual hierarchy)\n  3. Styling improvements (contrast, semantic color, font size hierarchy)\n  4. Minor polish (micro-adjustments, consistency nits)\nDo NOT apply a minor cosmetic edit if a major layout issue remains unfixed.\n\nIf you can't fix something with these ops, leave it alone.\n";

// ---------------------------------------------------------------- Python formatting helpers

/** ``value[:n]`` for a ``str`` (code points) or a list. */
function _head<T>(value: unknown, n: number): T[] | string {
  if (typeof value === 'string') return cpSlice(value, 0, n);
  if (Array.isArray(value)) return value.slice(0, n) as T[];
  throw new PyTypeError(`'${pyTypeName(value)}' object is not subscriptable`);
}

/** ``text[:n]`` where Python requires ``text`` to be a str (or list). */
function _str_head(value: unknown, n: number): string {
  const head = _head(value, n);
  return typeof head === 'string' ? head : pyStr(head);
}

/** Items of ``value[:n]`` for iteration (a str iterates its characters). */
function _iter_head(value: unknown, n: number): unknown[] {
  const head = _head(value, n);
  return typeof head === 'string' ? [...head] : head;
}

/** ``f"{value:{width}s}"`` */
function _format_s(value: unknown, width: number): string {
  if (typeof value !== 'string') {
    if (value === null || value === undefined) throw new PyTypeError('unsupported format string passed to NoneType.__format__');
    throw new ValueError(`Unknown format code 's' for object of type '${pyTypeName(value)}'`);
  }
  const pad = width - cpLen(value);
  return pad > 0 ? value + ' '.repeat(pad) : value;
}

/** ``f"{value:>{width}.0f}"`` */
function _format_f(value: unknown, width: number): string {
  if (typeof value !== 'number' && typeof value !== 'boolean') {
    if (value === null || value === undefined) throw new PyTypeError('unsupported format string passed to NoneType.__format__');
    throw new ValueError(`Unknown format code 'f' for object of type '${pyTypeName(value)}'`);
  }
  return pyFormatFixed(Number(value), 0).padStart(width, ' ');
}

/** ``f"{container[key]}"`` honouring integral-float marks (``7.0``). */
function _format_value(container: unknown, key: string, value: unknown): string {
  if (typeof value === 'number' && _is_py_float(container, key)) return floatRepr(value);
  return pyStr(value);
}

/** ``json.dumps(value, ensure_ascii=False, sort_keys=True)`` honouring integral-float marks. */
function _dumps_sorted(value: unknown): string {
  return pyJsonDumps(_with_py_floats(value), { ensureAscii: false, sortKeys: true });
}

/** ``mapping.get(key, default)`` — AttributeError-like failure for non-dicts. */
function _get(mapping: unknown, key: string, default_: unknown = null): unknown {
  if (!isDict(mapping)) throw new PyTypeError(`'${pyTypeName(mapping)}' object has no attribute 'get'`);
  return pyGet(mapping, key, default_);
}

/** ``x, y, w, h = value`` */
function _unpack4(value: unknown): [unknown, unknown, unknown, unknown] {
  if (!isList(value)) throw new PyTypeError(`cannot unpack non-iterable ${pyTypeName(value)} object`);
  if (value.length > 4) throw new ValueError('too many values to unpack (expected 4)');
  if (value.length < 4) throw new ValueError(`not enough values to unpack (expected 4, got ${value.length})`);
  return [value[0], value[1], value[2], value[3]];
}

/** ``str.title()`` for the fixed dimension names. */
function _title(text: string): string {
  return text.replace(/[A-Za-z]+/g, (word) => word[0].toUpperCase() + word.slice(1).toLowerCase());
}

/**
 * Assemble the text part of the multimodal user message.
 *
 * ``image_note`` states how the attached PNG relates to the manifest summary
 * (rendered after this round's deterministic fixes, or still showing the
 * state before them). Without it the model re-proposes fixes for problems the
 * deterministic pass already solved, doubling every displacement.
 */
export function build_refiner_user_prompt(
  chart_type: string | null,
  remaining_findings: Dict[],
  critique: Dict | null,
  manifest_summary: Dict[],
  previous_attempts: Dict[] | null = null,
  iteration: number = 1,
  max_iterations: number = 3,
  image_note: string | null = null,
  design_constraints: string = '',
): string {
  const lines: string[] = [
    `Iteration ${pyStr(iteration)}/${pyStr(max_iterations)}.`,
  ];
  lines.push(constraint_prompt(design_constraints));
  if (truthy(chart_type)) {
    lines.push(`Declared chart_type: ${pyStr(chart_type)}`);
  }
  if (truthy(image_note)) {
    lines.push(`Image: ${pyStr(image_note)}`);
  }

  lines.push('');
  lines.push(`Remaining objective findings (${pyLen(remaining_findings)}):`);
  if (truthy(remaining_findings)) {
    for (const f of remaining_findings) {
      const sev = _get(f, 'severity', '?');
      const cat = _get(f, 'category', '?');
      const eid = truthy(_get(f, 'element_id')) ? _get(f, 'element_id') : '-';
      const message = _get(f, 'message');
      const msg = _str_head(truthy(message) ? message : '', 160);
      lines.push(`  [${pyStr(sev)}] ${pyStr(cat)} (${pyStr(eid)}): ${msg}`);
      const location = _get(f, 'location');
      if (truthy(location)) {
        const loc_json = cpSlice(_dumps_sorted(location), 0, 240);
        lines.push(`      location=${loc_json}`);
      }
    }
  } else {
    lines.push('  (none — no objective issues remain)');
  }

  lines.push('');
  if (truthy(critique)) {
    const violations = truthy(_get(critique, 'constraint_violations')) ? _get(critique, 'constraint_violations') : [];
    if (truthy(violations)) {
      lines.push('USER CONSTRAINT VIOLATIONS — resolve before optional polish:');
      for (const violation of _iter_head(violations, Number.MAX_SAFE_INTEGER)) lines.push(`  - ${pyStr(violation)}`);
    }
    for (const dim of ['structure', 'styling', 'layout']) {
      const d = truthy(_get(critique, dim)) ? _get(critique, dim) : {};
      const score = _get(d, 'score', '?');
      const weaknesses = truthy(_get(d, 'weaknesses')) ? _get(d, 'weaknesses') : [];
      if (truthy(weaknesses)) {
        lines.push(`${_title(dim)} (score=${_format_value(d, 'score', score)}):`);
        for (const w of _iter_head(weaknesses, 3)) {
          lines.push(`  - ${pyStr(w)}`);
        }
      }
    }
    if (truthy(_get(critique, 'summary'))) {
      lines.push(`Overall: ${pyStr(critique!.summary)}`);
    }
  } else {
    lines.push('(no subjective critique provided this run)');
  }

  lines.push('');
  lines.push('Manifest summary:');
  // Use the same budget as build_manifest_summary; a second smaller cap
  // silently hid the final relationship labels of ordinary overview diagrams.
  for (const entry of manifest_summary.slice(0, MAX_MANIFEST_SUMMARY_ELEMENTS)) {
    const eid = _get(entry, 'id', '?');
    const etype = _get(entry, 'type', '?');
    const [x, y, w, h] = _unpack4(_get(entry, 'bbox', [0, 0, 0, 0]));
    const rawText = truthy(_get(entry, 'text')) ? _get(entry, 'text') : '';
    if (typeof rawText !== 'string') throw new PyTypeError(`'${pyTypeName(rawText)}' object has no attribute 'replace'`);
    const shown = cpSlice(rawText.split('\n').join(' '), 0, 60);
    lines.push(
      `  ${_format_s(eid, 24)} ${_format_s(etype, 9)} x=${_format_f(x, 5)} y=${_format_f(y, 5)} w=${_format_f(w, 5)} h=${_format_f(h, 5)}  text=${pyRepr(shown)}`,
    );
    const context: Dict = {};
    for (const [key, value] of Object.entries(entry)) {
      if (!['id', 'type', 'bbox', 'text'].includes(key)) context[key] = value;
    }
    _copy_float_marks(entry, context);
    if (truthy(context)) {
      lines.push('    ' + _dumps_sorted(context));
    }
  }
  if (manifest_summary.length > MAX_MANIFEST_SUMMARY_ELEMENTS) {
    lines.push(`  … (${manifest_summary.length - MAX_MANIFEST_SUMMARY_ELEMENTS} more elements omitted)`);
  }

  if (truthy(previous_attempts)) {
    lines.push('');
    lines.push('Edits already applied this cycle (do NOT re-apply identical edits):');
    for (const log of previous_attempts!) {
      const it = _get(log, 'iteration', '?');
      for (const outcome_kind of ['deterministic_edits', 'llm_edits']) {
        const outs = _get(log, outcome_kind, []);
        for (const o of _iter_head(outs, 6)) {
          const edit = truthy(_get(o, 'edit')) ? _get(o, 'edit') : {};
          const applied = truthy(_get(o, 'applied')) ? '✓' : '✗';
          if (!truthy(edit)) {
            const error = truthy(_get(o, 'error')) ? _get(o, 'error') : 'invalid edit';
            lines.push(
              `  iter${pyStr(it)} ${outcome_kind.slice(0, 4)} ✗ REJECTED → `
              + `${_str_head(error, 70)}`,
            );
            continue;
          }
          lines.push(
            `  iter${pyStr(it)} ${outcome_kind.slice(0, 4)} ${applied} `
            + `${pyStr(_get(edit, 'op'))}(${pyStr(_get(edit, 'id'))}) → ${_str_head(_get(edit, 'rationale', ''), 60)}`,
          );
        }
      }
    }
  }

  lines.push('');
  lines.push('Return ONLY a JSON array of edit ops. No markdown fences, no prose.');
  return lines.join('\n');
}

/** ``{k: v for k, v in entry.items() if ...}`` keeps the values: carry their float marks. */
function _copy_float_marks(source: object, target: Dict): void {
  for (const key of Object.keys(target)) {
    if (_is_py_float(source, key)) _mark_py_float(target, key);
  }
}

export const __all__ = [
  'REFINER_LLM_SYSTEM_PROMPT',
  'build_refiner_user_prompt',
];
