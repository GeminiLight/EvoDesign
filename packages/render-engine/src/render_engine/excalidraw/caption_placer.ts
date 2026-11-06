// Ported from evodesign/agentic_system/render_engine/excalidraw/caption_placer.py — keep in sync.
//
// Anchor figure captions (axis names, stated rules) to the figure they describe.
//
// Quadrant axis names and layer-stack rule captions are ``class: "axis"`` nodes.
// The layout agent places them by eye, so they drift away from the figure and
// keep whatever small font it guessed. Once the group frames are final, this
// pass sizes each caption like the items it describes and places it where the
// type pattern says: the horizontal axis centred below the quadrant block, the
// vertical axis left of it, and rule captions right of the layer stack.
//
// TS-specific (see migration/notes/WP09.md):
// - ``textwrap.wrap(text, width)`` (default TextWrapper options, CPython 3.11)
//   and ``statistics.median`` have no runtime helper in src/py, so faithful
//   private ports (``_textwrapWrap``, ``_median``) live at the bottom of this file.
// - ``by_eid`` is a ``Map`` keyed by the raw ``e.get("id")`` (``null`` when absent).

import { assignF, copyF, markF } from '../../py/float_marks.ts';
import { pyGet, pyGetItem, type PyMapping } from '../../py/dict.ts';
import { ValueError } from '../../py/errors.ts';
import { ceil } from '../../py/math.ts';
import { pyFloatParse, pyInt, pySum } from '../../py/number.ts';
import { pyMaxN, pyMinN, pySorted } from '../../py/sort.ts';
import { cpChars, cpLen, cpSlice, pyLower, pyStr, pyStrip } from '../../py/str.ts';
import { isDict, pyOr, truthy } from '../../py/truthy.ts';
import { group_frame_render_id } from '../../common/semantic_ids.ts';
import { _estimate_text_dimensions } from '../../generation_stage/layout/element_shape_estimator.ts';

type Dict = Record<string, unknown>;

export const CAPTION_TYPES = new Set(['quadrant', 'layer_stack']);
export const _GAP = 24.0;
export const _STACK_GAP = 32.0;
export const _MIN_FONT = 16;
export const _PAD_X = 8.0;
export const _PAD_Y = 4.0;
export const _WRAP = 28;
export const _HORIZONTAL = new Set(cpChars('→←↔⟶⟵'));
export const _VERTICAL = new Set(cpChars('↑↓↕'));

function _float(value: unknown): number {
  return pyFloatParse(value as number | string | boolean);
}

export function is_caption(node: PyMapping): boolean {
  return pyLower(pyStrip(pyStr(pyOr(pyGet(node, 'class'), '')))) === 'axis';
}

export function _bound_text(elements: Dict[], host: PyMapping): Dict | null {
  const hostId = pyGet(host, 'id');
  for (const e of elements) {
    if (pyGet(e, 'type') === 'text' && pyGet(e, 'containerId') === hostId) return e;
  }
  return null;
}

export function _box(elements: PyMapping[]): Record<string, number> | null {
  if (!truthy(elements)) {
    return null;
  }
  const xs = [
    ...elements.map((e) => _float(pyGetItem(e, 'x'))),
    ...elements.map((e) => _float(pyGetItem(e, 'x')) + _float(pyGetItem(e, 'width'))),
  ];
  const ys = [
    ...elements.map((e) => _float(pyGetItem(e, 'y'))),
    ...elements.map((e) => _float(pyGetItem(e, 'y')) + _float(pyGetItem(e, 'height'))),
  ];
  return { left: pyMinN(...xs), top: pyMinN(...ys), right: pyMaxN(...xs), bottom: pyMaxN(...ys) };
}

/** Wrap into as few lines as the limit allows, with lines of similar length. */
export function _balanced_lines(raw: string): string[] {
  const count = ceil(cpLen(raw) / _WRAP);
  for (let width = ceil(cpLen(raw) / count); width < _WRAP + 1; width++) {
    const lines = _textwrapWrap(raw, width);
    if (lines.length <= count) {
      return lines;
    }
  }
  return _textwrapWrap(raw, _WRAP);
}

export function _resize(host: Dict, text: Dict, font: number, wrap: boolean): null {
  const raw = pyStr(pyOr(pyOr(pyGet(text, 'originalText'), pyGet(text, 'text')), ''));
  let shown = raw;
  if (wrap && cpLen(raw) > _WRAP) {
    shown = _balanced_lines(raw).join('\n');
  }
  const size = _estimate_text_dimensions(shown, font);
  Object.assign(text, {
    fontSize: font, text: shown, originalText: raw,
    width: size.width, height: size.height,
  });
  markF(text, 'fontSize', false); // int font
  copyF(size, 'width', text, 'width');
  copyF(size, 'height', text, 'height');
  // ``+ 2 * _PAD_X`` (8.0 / 4.0): floats.
  assignF(host, { width: size.width + 2 * _PAD_X, height: size.height + 2 * _PAD_Y }, ['width', 'height']);
  return null;
}

/** Place the caption; the text hugs the side that faces the figure. */
export function _move(host: Dict, text: Dict, x: number, y: number, align = 'center'): null {
  assignF(host, { x, y }, ['x', 'y']); // block coordinates come from float(...)
  const width = _float(pyGetItem(host, 'width'));
  const text_w = _float(pyGetItem(text, 'width'));
  const offsets: Record<string, number> = { left: _PAD_X, right: width - text_w - _PAD_X };
  const fallback = (width - text_w) / 2;
  const offset = align === 'left' || align === 'right' ? offsets[align] : fallback;
  Object.assign(text, {
    x: x + offset, y: y + (_float(pyGetItem(host, 'height')) - _float(pyGetItem(text, 'height'))) / 2,
    textAlign: align, verticalAlign: 'middle',
  });
  markF(text, 'x', true);
  markF(text, 'y', true);
  return null;
}

export function _is_horizontal(label: string, host: PyMapping, block: Record<string, number>, index: number): boolean {
  const chars = cpChars(label);
  if (chars.some((ch) => _HORIZONTAL.has(ch))) {
    return true;
  }
  if (chars.some((ch) => _VERTICAL.has(ch))) {
    return false;
  }
  const cx = _float(pyGetItem(host, 'x')) + _float(pyGetItem(host, 'width')) / 2;
  const cy = _float(pyGetItem(host, 'y')) + _float(pyGetItem(host, 'height')) / 2;
  if (cy > block.bottom) {
    return true;
  }
  if (cx < block.left) {
    return false;
  }
  return index === 0;
}

/** Size and anchor caption nodes in place; return how many were placed. */
export function place_captions(chart_type: string, structure: PyMapping,
  elements: Dict[], id_map: PyMapping): number {
  if (!CAPTION_TYPES.has(chart_type)) {
    return 0;
  }
  const by_eid = new Map<unknown, Dict>();
  for (const e of elements) by_eid.set(pyGet(e, 'id'), e);
  const frames: (Dict | null)[] = [];
  for (const g of (pyOr(pyGet(structure, 'groups'), []) as unknown[])) {
    if (!isDict(g)) continue;
    const key = pyOr(group_frame_render_id(id_map, pyGet(g, 'id')), '');
    frames.push(by_eid.has(key) ? by_eid.get(key)! : null);
  }
  const block = _box(frames.filter((f): f is Dict => truthy(f)));
  if (block === null) {
    return 0;
  }

  const captions: [string, Dict, Dict][] = [];
  const item_fonts: number[] = [];
  for (const node of (pyOr(pyGet(structure, 'nodes'), []) as unknown[])) {
    if (!isDict(node)) {
      continue;
    }
    const hostKey = pyGet(id_map, pyStr(pyGet(node, 'id')), '');
    const host = by_eid.has(hostKey) ? by_eid.get(hostKey)! : null;
    const text = truthy(host) ? _bound_text(elements, host!) : null;
    if (!truthy(host) || !truthy(text)) {
      continue;
    }
    if (is_caption(node)) {
      captions.push([pyStr(pyOr(pyOr(pyGet(node, 'label'), pyGet(text!, 'text')), '')), host!, text!]);
    } else if (truthy(pyGet(text!, 'fontSize'))) {
      item_fonts.push(_float(pyGetItem(text!, 'fontSize')));
    }
  }
  if (!captions.length) {
    return 0;
  }
  const font = Math.max(_MIN_FONT, item_fonts.length ? pyInt(_median(item_fonts)) : _MIN_FONT);

  if (chart_type === 'quadrant') {
    captions.forEach(([label, host, text], index) => {
      const horizontal = _is_horizontal(label, host, block, index);
      _resize(host, text, font, false);
      if (horizontal) {
        const x = (block.left + block.right - _float(host.width)) / 2;
        _move(host, text, x, block.bottom + _GAP);
      } else {
        const y = (block.top + block.bottom - _float(host.height)) / 2;
        _move(host, text, block.left - _GAP - _float(host.width), y, 'right');
      }
    });
    return captions.length;
  }

  // layer_stack: rule captions stacked right of the bands, centred on them.
  for (const [, host, text] of captions) {
    _resize(host, text, font, true);
  }
  const total = pySum(captions.map(([, h]) => _float(h.height))) + _GAP * (captions.length - 1);
  let y = (block.top + block.bottom - total) / 2;
  for (const [, host, text] of captions) {
    _move(host, text, block.right + _STACK_GAP, y, 'left');
    y += _float(host.height) + _GAP;
  }
  return captions.length;
}

// ---------------------------------------------------------------------------
// statistics.median
// ---------------------------------------------------------------------------

function _median(data: number[]): number {
  const sorted = pySorted(data);
  const n = sorted.length;
  if (n === 0) throw new ValueError('no median for empty data');
  if (n % 2 === 1) return sorted[(n - 1) / 2];
  const i = n / 2;
  return (sorted[i - 1] + sorted[i]) / 2;
}

// ---------------------------------------------------------------------------
// textwrap.wrap(text, width) with default TextWrapper options (CPython 3.11):
// expand_tabs, replace_whitespace, drop_whitespace, break_long_words and
// break_on_hyphens all True; no indents, no max_lines. Lengths are code points.
// ---------------------------------------------------------------------------

const _TW_WS = '[\\t\\n\\x0b\\x0c\\r ]';
const _TW_NWS = '[^\\t\\n\\x0b\\x0c\\r ]';
// Python ``\w`` on str: isalnum() or '_'; ``[^\d\W]``: \w minus decimal digits.
const _TW_W = '[\\p{L}\\p{N}_]';
const _TW_WP = '[\\p{L}\\p{N}_!"\'&.,?]';
const _TW_LT = '[\\p{L}\\p{Nl}\\p{No}_]';
const _TW_WORDSEP = new RegExp(
  '(' +
    `${_TW_WS}+` +
    `|(?<=${_TW_WP})-{2,}(?=${_TW_W})` +
    `|${_TW_NWS}+?(?:` +
      `-(?:(?<=${_TW_LT}{2}-)|(?<=${_TW_LT}-${_TW_LT}-))(?=${_TW_LT}-?${_TW_LT})` +
      `|(?=${_TW_WS}|$)` +
      `|(?<=${_TW_WP})(?=-{2,}${_TW_W})` +
    ')' +
  ')',
  'u',
);

function _twExpandTabs(text: string, tabsize = 8): string {
  let out = '';
  let column = 0;
  for (const ch of text) {
    if (ch === '\t') {
      const spaces = tabsize - (column % tabsize);
      out += ' '.repeat(spaces);
      column += spaces;
    } else if (ch === '\n' || ch === '\r') {
      out += ch;
      column = 0;
    } else {
      out += ch;
      column += 1;
    }
  }
  return out;
}

function _twSplitChunks(text: string): string[] {
  const munged = _twExpandTabs(text).replace(/[\t\n\x0b\x0c\r]/g, ' ');
  return munged.split(_TW_WORDSEP).filter((c) => c !== undefined && c !== '');
}

function _twHandleLongWord(reversed_chunks: string[], cur_line: string[], cur_len: number, width: number): void {
  const space_left = width < 1 ? 1 : width - cur_len;
  let end = space_left;
  const chunk = reversed_chunks[reversed_chunks.length - 1];
  const chars = cpChars(chunk);
  if (chars.length > space_left) {
    let hyphen = -1;
    for (let i = Math.min(space_left, chars.length) - 1; i >= 0; i--) {
      if (chars[i] === '-') {
        hyphen = i;
        break;
      }
    }
    if (hyphen > 0 && chars.slice(0, hyphen).some((c) => c !== '-')) {
      end = hyphen + 1;
    }
  }
  cur_line.push(cpSlice(chunk, 0, end));
  reversed_chunks[reversed_chunks.length - 1] = cpSlice(chunk, end);
}

function _textwrapWrap(text: string, width: number): string[] {
  const chunks = _twSplitChunks(text);
  const lines: string[] = [];
  if (width <= 0) {
    throw new ValueError(`invalid width ${width} (must be > 0)`);
  }
  chunks.reverse();
  while (chunks.length) {
    const cur_line: string[] = [];
    let cur_len = 0;
    if (pyStrip(chunks[chunks.length - 1]) === '' && lines.length) {
      chunks.pop();
    }
    while (chunks.length) {
      const l = cpLen(chunks[chunks.length - 1]);
      if (cur_len + l <= width) {
        cur_line.push(chunks.pop()!);
        cur_len += l;
      } else {
        break;
      }
    }
    if (chunks.length && cpLen(chunks[chunks.length - 1]) > width) {
      _twHandleLongWord(chunks, cur_line, cur_len, width);
      cur_len = cur_line.reduce((sum, c) => sum + cpLen(c), 0);
    }
    if (cur_line.length && pyStrip(cur_line[cur_line.length - 1]) === '') {
      cur_len -= cpLen(cur_line[cur_line.length - 1]);
      cur_line.pop();
    }
    if (cur_line.length) {
      lines.push(cur_line.join(''));
    }
  }
  return lines;
}
