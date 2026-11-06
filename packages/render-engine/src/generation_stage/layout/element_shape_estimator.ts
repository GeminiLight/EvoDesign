// Ported from evodesign/agentic_system/generation_stage/layout/element_shape_estimator.py — keep in sync.
//
// Element Shape Estimator
//
// Estimates min_width and min_height for node elements based on their label text
// and font size. This provides size hints to the Layout LLM so it can produce
// more accurate coordinate assignments.
//
// Padding (20px each side horizontally, 15px each side vertically) is NOT added
// here — it is handled exclusively by the shape_size_fitter post-processor. This
// avoids double-padding (estimator + fitter each adding their own) and keeps all
// padding logic in one place.
//
// IMPORTANT:
// - Only estimates elements (nodes), NOT groups, edges, or icon entries.
// - Does NOT enforce any positions or sizes — only provides hints.
// - Compatible with both Excalidraw and TLDraw styling formats.

import { markF, pyDeepcopy } from '../../py/float_marks.ts';
import { pyGet, pyGetItem, pyItems, type PyMapping } from '../../py/dict.ts';
import { pyIn } from '../../py/eq.ts';
import { PyTypeError } from '../../py/errors.ts';
import { ceil } from '../../py/math.ts';
import { pyFloatParse, pyInt } from '../../py/number.ts';
import { pyMax, pyMaxN, pyMin } from '../../py/sort.ts';
import { cpChars, cpLen } from '../../py/str.ts';
import { isDict, isList, isMapping, isNumberOrBool, isSet, isStr, truthy } from '../../py/truthy.ts';
import { ICON_SUFFIX, companion_id } from '../../common/semantic_ids.ts';
import { ICON_GAP, ICON_PADDING, ICON_SIZE } from '../../common/node_icons.ts';

type Dict = Record<string, any>;

// Line height multiplier
export const _LINE_HEIGHT_FACTOR = 1.25;
// Padding constants — kept here for reference only. All padding is handled
// by shape_size_fitter. Do NOT add these to min_width/min_height output.
export const _PADDING_W = 40;
export const _PADDING_H = 30;
// Icon layout constants. Icons are rendered inside the node on the left, so
// their footprint must be reflected in the text-width hint sent to the layout
// model. Boundary padding is still owned by shape_size_fitter.
export const _ICON_LEFT_PAD = ICON_PADDING;
export const _ICON_TEXT_GAP = ICON_GAP;
export const _ICON_DEFAULT_DIM = ICON_SIZE;
export const _ICON_SIZE_TO_PX: Readonly<Record<string, number>> = { s: 36, m: 48, l: 58, xl: 65.2 };

/**
 * Character width factor per script.
 *
 * Latin baseline is ~0.6× font size. CJK glyphs render near 1.0×, so a
 * single CJK code point in the label bumps the whole line to the wider
 * factor — matching how a single wide glyph determines line width in
 * practice and avoiding Chinese/Japanese labels being estimated too small.
 */
export function _char_width_factor(text: string): number {
  if (cpChars(text).some((c) => c.codePointAt(0)! > 0x2E80)) { // CJK range
    return 1.0;
  }
  return 0.6;
}

// TLDraw size token to pixel mapping (used when styling is in TLDraw format)
export const _TLDRAW_SIZE_TO_PX: Readonly<Record<string, number>> = { s: 24, m: 32, l: 48, xl: 60 };

/** ``value in {str-keyed dict}`` — unhashable values raise like Python. */
function _inTable(value: unknown, table: Readonly<Record<string, number>>): boolean {
  if (isList(value) || isDict(value) || value instanceof Map || isSet(value)) {
    throw new PyTypeError('unhashable type');
  }
  return isStr(value) && Object.prototype.hasOwnProperty.call(table, value);
}

/**
 * Estimate min_width and min_height for node elements based on their label text.
 *
 * Processes semantic node ids from Structure. Groups, edges, icons, and
 * metadata keys are left untouched.
 *
 * Writes 'min_width' and 'min_height' as integer pixel values into each
 * qualifying node entry. Returns a new dict; the input is NOT mutated.
 */
export function estimate_element_sizes(
  styling_instantiation: PyMapping,
  structure_instantiation: Dict | null = null,
): PyMapping {
  const result = pyDeepcopy(styling_instantiation);
  const node_ids = _structure_node_ids(structure_instantiation);
  for (const [key, value] of pyItems(result)) {
    // --- Only estimate nodes ---
    if (!_is_node_key(key, node_ids)) {
      continue;
    }
    if ((key as string).endsWith(ICON_SUFFIX)) {
      continue;
    }
    if (!isMapping(value)) {
      continue;
    }

    const text = _extract_text(value as Dict);
    if (!truthy(text)) {
      continue;
    }

    const font_size = _extract_font_size(value as Dict);
    const dims = _estimate_text_dimensions(text, font_size);

    let icon_extra_width = 0.0;
    if (_has_icon_for_node(result, key as string)) {
      icon_extra_width = _estimate_icon_extra_width(result, key as string);
    }

    _setItem(value, 'min_width', pyInt(ceil(dims.width + icon_extra_width)));
    _setItem(value, 'min_height', pyInt(ceil(dims.height)));
  }

  return result;
}

function _setItem(mapping: PyMapping, key: string, value: unknown): void {
  if (mapping instanceof Map) mapping.set(key, value);
  else mapping[key] = value;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

export function _structure_node_ids(structure_instantiation: Dict | null): Set<string> {
  if (!isMapping(structure_instantiation)) {
    return new Set();
  }
  const nodes = pyGet(structure_instantiation, 'nodes');
  if (!isList(nodes)) {
    return new Set();
  }
  const ids = new Set<string>();
  for (const node of nodes) {
    if (isMapping(node) && isStr(pyGet(node, 'id')) && truthy(pyGet(node, 'id'))) {
      ids.add(pyGetItem(node, 'id') as string);
    }
  }
  return ids;
}

export function _is_node_key(key: unknown, node_ids: ReadonlySet<string>): boolean {
  if (!isStr(key)) {
    return false;
  }
  if (key.endsWith(ICON_SUFFIX)) {
    return false;
  }
  return node_ids.has(key);
}

/** Extract display text from an element, supporting multiple formats. */
export function _extract_text(element_data: Dict): string {
  // Excalidraw: label.text
  const label = pyGet(element_data, 'label', {});
  if (isMapping(label) && truthy(pyGet(label, 'text'))) {
    return pyGetItem(label, 'text') as string;
  }
  // Standalone text element
  if (truthy(pyGet(element_data, 'text'))) {
    return pyGetItem(element_data, 'text') as string;
  }
  // TLDraw: props.text
  const props = pyGet(element_data, 'props', {});
  if (isMapping(props) && truthy(pyGet(props, 'text'))) {
    return pyGetItem(props, 'text') as string;
  }
  return '';
}

/** Extract font size in pixels from an element, supporting multiple formats. */
export function _extract_font_size(element_data: Dict): number {
  // Excalidraw: label.fontSize
  const label = pyGet(element_data, 'label', {});
  if (isMapping(label) && pyIn('fontSize', label)) {
    return pyGetItem(label, 'fontSize') as number;
  }
  // Top-level fontSize
  if (pyIn('fontSize', element_data)) {
    return pyGetItem(element_data, 'fontSize') as number;
  }
  // TLDraw: derive from props.size token
  const props = pyGet(element_data, 'props', {});
  if (isMapping(props)) {
    if (pyIn('fontSize', props)) {
      return pyGetItem(props, 'fontSize') as number;
    }
    const size_token = pyGet(props, 'size');
    if (_inTable(size_token, _TLDRAW_SIZE_TO_PX)) {
      return _TLDRAW_SIZE_TO_PX[size_token as string];
    }
  }
  return 16; // sensible default
}

/** Return True when a node has a canonical companion icon definition. */
export function _has_icon_for_node(styling_instantiation: PyMapping, key: string): boolean {
  return pyIn(companion_id(key, ICON_SUFFIX), styling_instantiation);
}

/** Estimate the horizontal node budget consumed by a left-aligned icon. */
export function _estimate_icon_extra_width(styling_instantiation: PyMapping, key: string): number {
  let icon_data = pyGet(styling_instantiation, companion_id(key, ICON_SUFFIX));
  if (!isMapping(icon_data)) {
    icon_data = {};
  }

  const icon_dim = _extract_icon_dimension(icon_data as Dict);
  return _ICON_LEFT_PAD + icon_dim + _ICON_TEXT_GAP;
}

/** Resolve an icon dimension from styling data, matching converter defaults. */
export function _extract_icon_dimension(icon_data: Dict): number {
  let icon_size = pyGet(icon_data, 'size');
  if (_inTable(icon_size, _ICON_SIZE_TO_PX)) {
    return _ICON_SIZE_TO_PX[icon_size as string];
  }

  const props = pyGet(icon_data, 'props', {});
  if (isMapping(props)) {
    icon_size = pyGet(props, 'size');
    if (_inTable(icon_size, _ICON_SIZE_TO_PX)) {
      return _ICON_SIZE_TO_PX[icon_size as string];
    }
    const w = pyGet(props, 'w');
    const h = pyGet(props, 'h');
    if (isNumberOrBool(w) && isNumberOrBool(h)) {
      return pyMin([w, h]) as number;
    }
    if (isNumberOrBool(w)) {
      return pyFloatParse(w);
    }
    if (isNumberOrBool(h)) {
      return pyFloatParse(h);
    }
  }

  return _ICON_DEFAULT_DIM;
}

/**
 * Estimate the rendered width and height of a text string.
 *
 * Uses a simple character-count heuristic. This is intentionally approximate —
 * the Layout LLM can adjust sizes based on its own judgement.
 */
export function _estimate_text_dimensions(text: string, font_size: number): { width: number; height: number } {
  const lines = text ? text.split('\n') : [''];
  const max_line_len = pyMax(lines.map((line) => cpLen(line))) as number;
  const width = max_line_len * font_size * _char_width_factor(text);
  const height = lines.length * font_size * _LINE_HEIGHT_FACTOR;
  const dims = {
    width: pyMaxN(width, 10),
    height: pyMaxN(height, font_size * _LINE_HEIGHT_FACTOR),
  };
  // Python: ``* _char_width_factor`` / ``* 1.25`` give floats; max(width, 10) may keep the int 10.
  markF(dims, 'width', !(10 > width));
  markF(dims, 'height', true);
  return dims;
}
