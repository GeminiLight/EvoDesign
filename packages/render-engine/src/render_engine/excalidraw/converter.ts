// Ported from evodesign/agentic_system/render_engine/excalidraw/converter.py — keep in sync.
//
// Excalidraw Converter - Convert layout_instantiation to Excalidraw scene format.
// Pure logic implementation (no LLM calls).

import { sequential_index } from '../shared/order_keys.ts';
import { icon_filename, require_icon_svg_path } from '../../common/icon_assets.ts';
import { ICON_SIZE, ICON_KEY, bundled_icons, icon_file, sync_node_icons } from '../../common/node_icons.ts';
import { validate_layout_instantiation } from '../../common/layout_contract.ts';
import {
  BACKGROUND_SUFFIX,
  ICON_SUFFIX,
  TITLE_SUFFIX,
  companion_base_id,
  companion_id,
} from '../../common/semantic_ids.ts';
import { is_layout_edge_entry } from '../shared/edge_routing.ts';
import { LAYER_GROUP_FRAME, base_id, is_group_frame, layer_for } from '../shared/normalization.ts';
import { readAssetText } from '../../py/assets.ts';
import { pyGet, pyGetItem } from '../../py/dict.ts';
import { md5Hex, sha256Hex, utf8Encode } from '../../py/hash.ts';
import { pyStableJsonDumps } from '../../py/json.ts';
import { pyMod } from '../../py/number.ts';
import { pyMax, pyMaxN, pyMinN, pySorted } from '../../py/sort.ts';
import { copyF, markF, orF, pyDictCopy } from '../../py/float_marks.ts';
import { cpLen, pyLstrip, pyRepr, pyStr, pyStrip } from '../../py/str.ts';
import { isDict, isNumberOrBool, isStr, pyOr, truthy } from '../../py/truthy.ts';

type Dict = Record<string, unknown>;

// Size mapping (same as TLDraw converter)
export const SIZE_DICT: Readonly<Record<string, number>> = {
  s: 36,
  m: 48,
  l: 58,
  xl: 65.2,
};

// Approximate character width per font size unit (for estimating text dimensions)
export const _CHAR_WIDTH_FACTOR = 0.6;
export const _STABLE_EXCALIDRAW_UPDATED_MS = 1;
export const _DEFAULT_NODE_STROKE = '#64748B';
export const _DEFAULT_NODE_FILL = '#F8FAFC';
export const _DEFAULT_TEXT_COLOR = '#1F2937';
export const _DEFAULT_NODE_FONT_SIZE = 18;
export const _DEFAULT_ANNOTATION_FONT_SIZE = 16;
export const _DEFAULT_GROUP_TITLE_FONT_SIZE = 18;
export const _DEFAULT_LINE_HEIGHT = 1.2;

function hasKey(obj: unknown, key: string): boolean {
  return isDict(obj) && Object.prototype.hasOwnProperty.call(obj, key);
}

/** ``base64.b64encode(raw).decode("ascii")`` */
function b64encode(bytes: Uint8Array): string {
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
  let out = '';
  let i = 0;
  for (; i + 2 < bytes.length; i += 3) {
    const n = (bytes[i] << 16) | (bytes[i + 1] << 8) | bytes[i + 2];
    out += alphabet[(n >> 18) & 63] + alphabet[(n >> 12) & 63] + alphabet[(n >> 6) & 63] + alphabet[n & 63];
  }
  const rest = bytes.length - i;
  if (rest === 1) {
    const n = bytes[i] << 16;
    out += `${alphabet[(n >> 18) & 63]}${alphabet[(n >> 12) & 63]}==`;
  } else if (rest === 2) {
    const n = (bytes[i] << 16) | (bytes[i + 1] << 8);
    out += `${alphabet[(n >> 18) & 63]}${alphabet[(n >> 12) & 63]}${alphabet[(n >> 6) & 63]}=`;
  }
  return out;
}

/** Serialize a value for deterministic hashes. */
export function _stable_payload(value: unknown): string {
  try {
    return pyStableJsonDumps(value);
  } catch {
    // Python: ``except TypeError: return repr(value)``
    return pyRepr(value);
  }
}

export function _stable_digest(namespace: string, value: unknown): string {
  const payload = `${namespace}:${_stable_payload(value)}`;
  return sha256Hex(payload);
}

/** Generate a stable Excalidraw-compatible ID from semantic input. */
export function _generate_excalidraw_id(seed: unknown): string {
  return _stable_digest('excalidraw-id', seed).slice(0, 20);
}

export function _stable_seed(seed: unknown): number {
  // 12 hex digits = 48 bits, exact in a double.
  const value = parseInt(_stable_digest('excalidraw-seed', seed).slice(0, 12), 16);
  return pyMod(value, 2_000_000_000) + 1;
}

/** Return the standard boilerplate fields every Excalidraw element needs. */
export function _excalidraw_defaults(seed: unknown): Dict {
  return {
    angle: 0,
    strokeColor: '#1e1e1e',
    backgroundColor: 'transparent',
    fillStyle: 'solid',
    strokeWidth: 2,
    strokeStyle: 'solid',
    roughness: 1,
    opacity: 100,
    groupIds: [],
    frameId: null,
    index: 'a0',
    roundness: null,
    seed: _stable_seed(['seed', seed]),
    version: 2,
    versionNonce: _stable_seed(['versionNonce', seed]),
    isDeleted: false,
    boundElements: [],
    updated: _STABLE_EXCALIDRAW_UPDATED_MS,
    link: null,
    locked: false,
  };
}

/** Estimate text width/height based on character count and font size. */
export function _estimate_text_dimensions(text: string, font_size: number): { width: number; height: number } {
  const lines = truthy(text) ? text.split('\n') : [''];
  const max_line_len = pyMax(lines.map((line) => cpLen(line))) as number;
  const width = max_line_len * font_size * _CHAR_WIDTH_FACTOR;
  const height = lines.length * font_size * 1.25; // lineHeight = 1.25
  const dims = { width: pyMaxN(width, 10), height: pyMaxN(height, font_size * 1.25) };
  // Python: width/height are floats (``* 0.6`` / ``* 1.25``); ``max(width, 10)`` may pick the int 10.
  markF(dims, 'width', !(10 > width));
  markF(dims, 'height', true);
  return dims;
}

/**
 * Return the first positive numeric dimension value, otherwise the default.
 *
 * Python signature is ``(*values, default)``; per MIGRATION_PLAN §2.3 the
 * keyword-only ``default`` follows the spread values, so it is the LAST
 * positional argument here.
 */
export function _resolve_numeric_dimension(...args: unknown[]): number {
  const values = args.slice(0, -1);
  const default_ = args[args.length - 1] as number;
  for (const value of values) {
    if (isNumberOrBool(value) && Number(value) > 0) {
      return Number(value);
    }
  }
  return Number(default_);
}

/** Resolve width/height from Excalidraw or layout-style w/h fields. */
export function _resolve_element_dimensions(
  element_data: Dict,
  default_width: number,
  default_height: number,
): [number, number] {
  let props = pyGet(element_data, 'props', {});
  if (!isDict(props)) {
    props = {};
  }

  const width = _resolve_numeric_dimension(
    pyGet(element_data, 'width'),
    pyGet(element_data, 'w'),
    pyGet(props, 'w'),
    default_width,
  );
  const height = _resolve_numeric_dimension(
    pyGet(element_data, 'height'),
    pyGet(element_data, 'h'),
    pyGet(props, 'h'),
    default_height,
  );
  return [width, height];
}

/** Extract icon URL from current and persisted icon asset shapes. */
export function _extract_icon_url(icon_data: Dict): string {
  const icon_url = pyGet(icon_data, 'src', '');
  if (truthy(icon_url)) {
    return icon_url as string;
  }
  const props = pyGet(icon_data, 'props', {});
  if (isDict(props)) {
    return pyOr(pyGet(props, 'url', ''), pyGet(props, 'src', '')) as string;
  }
  return '';
}

export function _extract_icon_filename(icon_data: Dict, icon_url: string): string {
  let filename = '';
  if (truthy(icon_url)) {
    const parts = icon_url.split('/');
    filename = parts[parts.length - 1];
  }
  if (filename.endsWith('.svg')) {
    return filename;
  }

  const props = pyGet(icon_data, 'props', {});
  if (isDict(props)) {
    const icon_name = pyGet(props, 'icon');
    if (isStr(icon_name) && truthy(pyStrip(icon_name))) {
      return icon_filename(pyStrip(icon_name));
    }
  }
  return '';
}

/** Resolve icon dimension from size or explicit width/height. */
export function _extract_icon_dimension(icon_data: Dict): number {
  const icon_size = pyGet(icon_data, 'size');
  if (isStr(icon_size) && hasKey(SIZE_DICT, icon_size)) {
    return SIZE_DICT[icon_size];
  }
  const props = pyGet(icon_data, 'props', {});
  if (isDict(props)) {
    const w = pyGet(props, 'w');
    const h = pyGet(props, 'h');
    // Python returns the raw value (a bool stays a bool), like min(w, h).
    if (isNumberOrBool(w) && isNumberOrBool(h)) {
      return (Number(h) < Number(w) ? h : w) as number;
    }
    if (isNumberOrBool(w)) {
      return w as number;
    }
    if (isNumberOrBool(h)) {
      return h as number;
    }
  }
  return 48;
}

/** Read an SVG file and return it as a data URI string. */
export function _read_svg_as_data_uri(svg_path: string): string {
  // Python reads raw bytes; asset files are UTF-8 text, so reading text and
  // re-encoding yields the same bytes.
  const raw = utf8Encode(readAssetText(svg_path));
  const b64 = b64encode(raw);
  return `data:image/svg+xml;base64,${b64}`;
}

/** Convert inline SVG text into a base64 data URI string. */
export function _svg_text_to_data_uri(svg_text: string): string {
  const b64 = b64encode(utf8Encode(svg_text));
  return `data:image/svg+xml;base64,${b64}`;
}

/** Resolve icon data into a base64 data URL string. */
export function _icon_to_data_url(icon_data: Dict, element_id: string | null = null): string {
  const icon_url = _extract_icon_url(icon_data);

  if (icon_url.startsWith('data:image/')) {
    return icon_url;
  }

  if (pyLstrip(icon_url).startsWith('<svg')) {
    return _svg_text_to_data_uri(icon_url);
  }

  const props = pyGet(icon_data, 'props', {});
  const icon_color = isDict(props) ? (pyGet(props, 'color') as string | null) : null;
  const filename = _extract_icon_filename(icon_data, icon_url);
  const svg_path = require_icon_svg_path(filename, icon_color, icon_url, element_id);
  return _read_svg_as_data_uri(svg_path);
}

const GEO_TO_EXCALIDRAW: Readonly<Record<string, string>> = {
  rectangle: 'rectangle',
  ellipse: 'ellipse',
  diamond: 'diamond',
  triangle: 'triangle',
  // All others → rectangle (Excalidraw's actual behavior)
  pentagon: 'rectangle',
  hexagon: 'rectangle',
  octagon: 'rectangle',
  star: 'rectangle',
  cloud: 'rectangle',
  arrowLeft: 'rectangle',
  arrowRight: 'rectangle',
  arrowUp: 'rectangle',
  arrowDown: 'rectangle',
};

const FILL_MAP: Readonly<Record<string, string>> = { none: 'solid', solid: 'solid', pattern: 'cross-hatch' };

/** Convert layout_instantiation (with positions) to Excalidraw scene format. */
export class InstantiationToExcalidrawConverter {
  layout_instantiation: Dict;
  structure_instantiation: Dict;
  id_map: Record<string, string>;
  _index_counter: number;
  _structure_labels: Record<string, unknown>;

  constructor(layout_instantiation: Dict, structure_instantiation: Dict | null = null) {
    this.layout_instantiation = layout_instantiation;
    this.structure_instantiation = pyOr(structure_instantiation, {}) as Dict;
    this.id_map = {}; // semantic ID -> excalidraw ID
    this._index_counter = 0;
    // Pre-build a label lookup from structure for O(1) fallback.
    this._structure_labels = {};
    for (const field of ['nodes', 'groups', 'edges']) {
      for (const item of (pyOr(pyGet(this.structure_instantiation, field), []) as unknown[])) {
        if (isDict(item) && truthy(pyGet(item, 'id')) && truthy(pyGet(item, 'label'))) {
          this._structure_labels[pyStr(item.id)] = item.label;
        }
      }
    }
  }

  _next_index(): string {
    // Zero-padded so lexicographic comparison matches numeric intent.
    const idx = sequential_index(this._index_counter);
    this._index_counter += 1;
    return idx;
  }

  /** Create or retrieve an Excalidraw ID for a semantic ID. */
  _make_id(semantic_id: string): string {
    if (!hasKey(this.id_map, semantic_id)) {
      this.id_map[semantic_id] = _generate_excalidraw_id(['semantic', semantic_id]);
    }
    return this.id_map[semantic_id];
  }

  /** Resolve label text: layout_instantiation first, structure fallback. */
  _lookup_label(semantic_id: string, element_data: Dict): string {
    // 1. Check layout_instantiation (label.text / props.text / top-level text)
    const label_data = pyGet(element_data, 'label', {});
    if (isDict(label_data) && truthy(pyGet(label_data, 'text'))) {
      return label_data.text as string;
    }
    const props = pyGet(element_data, 'props', {});
    if (isDict(props) && truthy(pyGet(props, 'text'))) {
      return props.text as string;
    }
    if (truthy(pyGet(element_data, 'text'))) {
      return element_data.text as string;
    }
    // 2. Fallback to structure_instantiation
    return pyGet(this._structure_labels, semantic_id, '') as string;
  }

  /** Compute icon position inside a node, left-aligned and vertically centered. */
  _position_icon_in_node(icon_data: Dict, node_data: Dict): { x: number; y: number; dim: number } {
    void icon_data;
    const node_x = pyGet(node_data, 'x', 0) as number;
    const node_y = pyGet(node_data, 'y', 0) as number;
    const [, node_h] = _resolve_element_dimensions(node_data, 186, 62);

    const icon_dim = pyMinN(ICON_SIZE, pyMaxN(12, node_h - 16));

    const padding = 16;
    const icon_x = node_x + padding;
    const icon_y = node_y + pyMaxN(0, (node_h - icon_dim) / 2);

    const position = { x: icon_x, y: icon_y, dim: icon_dim };
    // node_h is a float (``_resolve_numeric_dimension``); ``(...) / 2`` is a float.
    const max_dim_f = !(12 >= node_h - 16); // max(12, node_h - 16) keeps 12 (int) unless the float is larger
    copyF(node_data, 'x', position, 'x');
    markF(position, 'y', true);
    markF(position, 'dim', ICON_SIZE > pyMaxN(12, node_h - 16) ? max_dim_f : false);
    return position;
  }

  /**
   * Create an Excalidraw shape element.
   *
   * Excalidraw natively supports only: rectangle, ellipse, diamond, triangle.
   * All other geo values are rendered as rectangle.
   */
  _create_shape_element(semantic_id: string, element_data: Dict): Dict {
    const eid = this._make_id(semantic_id);

    let elem_type = pyOr(pyOr(pyGet(element_data, 'type'), pyGet(element_data, 'shape')), 'rectangle') as unknown;

    // Handle TLDraw-style geo field
    if (elem_type === 'geo') {
      const props = pyGet(element_data, 'props', {});
      const geo = pyGet(props, 'geo', 'rectangle');
      elem_type = isStr(geo) && hasKey(GEO_TO_EXCALIDRAW, geo) ? GEO_TO_EXCALIDRAW[geo] : 'rectangle';
    }

    const x = pyGet(element_data, 'x', 0);
    const y = pyGet(element_data, 'y', 0);
    const [width, height] = _resolve_element_dimensions(element_data, 186, 62);

    const shape: Dict = {
      ..._excalidraw_defaults(['shape', semantic_id]),
      id: eid,
      type: elem_type,
      x,
      y,
      width,
      height,
      index: this._next_index(),
    };
    copyF(element_data, 'x', shape, 'x');
    copyF(element_data, 'y', shape, 'y');
    markF(shape, 'width', true); // _resolve_numeric_dimension returns float(...)
    markF(shape, 'height', true);

    // Keep the renderer fallback visually usable even when an upstream
    // styling stage omits shape details. Group frames retain their
    // transparent defaults.
    if (!is_group_frame(semantic_id, element_data)) {
      Object.assign(shape, {
        strokeColor: _DEFAULT_NODE_STROKE,
        backgroundColor: _DEFAULT_NODE_FILL,
        strokeWidth: 1.5,
        roughness: 0,
      });
      markF(shape, 'roughness', false);
      if (elem_type === 'rectangle') {
        shape.roundness = { type: 3 };
      }
    }

    // Apply Excalidraw-native styling if present
    for (const key of ['strokeColor', 'backgroundColor', 'fillStyle', 'strokeWidth',
      'strokeStyle', 'roughness', 'opacity', 'roundness']) {
      if (hasKey(element_data, key)) {
        shape[key] = element_data[key];
        copyF(element_data, key, shape, key);
      }
    }

    // Accept TLDraw-style props at this renderer boundary.
    const props = pyGet(element_data, 'props', {});
    if (isDict(props)) {
      if (hasKey(props, 'color') && !hasKey(element_data, 'strokeColor')) {
        shape.strokeColor = props.color;
      }
      if (hasKey(props, 'fill') && !hasKey(element_data, 'fillStyle')) {
        const fill = props.fill;
        shape.fillStyle = isStr(fill) && hasKey(FILL_MAP, fill) ? FILL_MAP[fill] : 'solid';
        if (fill === 'none') {
          shape.backgroundColor = 'transparent';
        } else if (fill === 'semi') {
          // TLDraw "semi" = semi-transparent solid fill.
          shape.fillStyle = 'solid';
          shape.opacity = 60;
          markF(shape, 'opacity', false);
        }
      }
    }

    // Safety cap: group frame / lane backgrounds should never be fully opaque.
    if (is_group_frame(semantic_id, element_data)) {
      const current_opacity = pyGet(shape, 'opacity', 100) as number;
      if (current_opacity >= 40) {
        shape.opacity = 40;
        markF(shape, 'opacity', false);
      }
    }

    return shape;
  }

  /**
   * Create a standalone Excalidraw text element (not bound to any container).
   * Resolves text and font attributes via label.* > props.* > top-level.
   */
  _create_standalone_text_element(semantic_id: string, element_data: Dict): Dict {
    const eid = this._make_id(semantic_id);

    let label_data = pyGet(element_data, 'label', {});
    if (!isDict(label_data)) {
      label_data = {};
    }
    let props = pyGet(element_data, 'props', {});
    if (!isDict(props)) {
      props = {};
    }

    const text = this._lookup_label(semantic_id, element_data);
    const is_group_title = semantic_id.endsWith(TITLE_SUFFIX);
    const font_size = pyOr(pyOr(pyOr(
      pyGet(label_data, 'fontSize'),
      pyGet(props, 'fontSize')),
    pyGet(element_data, 'fontSize')),
    is_group_title ? _DEFAULT_GROUP_TITLE_FONT_SIZE : _DEFAULT_ANNOTATION_FONT_SIZE) as number;
    const font_family = pyOr(pyOr(
      pyGet(label_data, 'fontFamily'),
      pyGet(props, 'fontFamily')),
    pyGet(element_data, 'fontFamily', 2));
    const text_align = pyOr(pyOr(
      pyGet(label_data, 'textAlign'),
      pyGet(props, 'textAlign')),
    pyGet(element_data, 'textAlign', 'left'));
    const vertical_align = pyOr(pyOr(
      pyGet(label_data, 'verticalAlign'),
      pyGet(props, 'verticalAlign')),
    pyGet(element_data, 'verticalAlign', 'top'));
    const font_style = pyOr(pyOr(pyOr(
      pyGet(label_data, 'fontStyle'),
      pyGet(props, 'fontStyle')),
    pyGet(element_data, 'fontStyle')),
    is_group_title ? 1 : 0);
    const line_height = pyOr(pyOr(pyOr(
      pyGet(label_data, 'lineHeight'),
      pyGet(props, 'lineHeight')),
    pyGet(element_data, 'lineHeight')),
    _DEFAULT_LINE_HEIGHT);

    const x = pyGet(element_data, 'x', 0);
    const y = pyGet(element_data, 'y', 0);

    // Estimate text dimensions if not explicitly provided
    const dims = _estimate_text_dimensions(text, font_size);
    const [width, height] = _resolve_element_dimensions(element_data, dims.width, dims.height);

    const text_elem: Dict = {
      ..._excalidraw_defaults(['standalone_text', semantic_id]),
      id: eid,
      type: 'text',
      x,
      y,
      width,
      height,
      index: this._next_index(),
      text,
      fontSize: font_size,
      fontFamily: font_family,
      fontStyle: font_style,
      textAlign: text_align,
      verticalAlign: vertical_align,
      containerId: null,
      originalText: text,
      autoResize: true,
      lineHeight: line_height,
      strokeColor: _DEFAULT_TEXT_COLOR,
    };
    copyF(element_data, 'x', text_elem, 'x');
    copyF(element_data, 'y', text_elem, 'y');
    markF(text_elem, 'width', true); // _resolve_numeric_dimension returns float(...)
    markF(text_elem, 'height', true);
    for (const [key, field, last] of [['fontSize', 'fontSize', false], ['fontFamily', 'fontFamily', true],
      ['fontStyle', 'fontStyle', false], ['lineHeight', 'lineHeight', false]] as [string, string, boolean][]) {
      markF(text_elem, key, orF([[label_data, field], [props, field], [element_data, field]], last));
    }

    // Text color: label.strokeColor > strokeColor > color > props.color.
    const resolved_color = pyOr(pyOr(pyOr(
      pyGet(label_data, 'strokeColor'),
      pyGet(element_data, 'strokeColor')),
    pyGet(element_data, 'color')),
    pyGet(props, 'color'));
    if (truthy(resolved_color)) {
      text_elem.strokeColor = resolved_color;
    }

    return text_elem;
  }

  /** Create a text element bound to a container shape (rectangle/diamond/arrow). */
  _create_bound_text_element(text: string, container_id: string, container_data: Dict): Dict {
    const text_id = _generate_excalidraw_id(['bound_text', container_id, text]);

    const x = pyGet(container_data, 'x', 0) as number;
    const y = pyGet(container_data, 'y', 0) as number;
    const [container_w, container_h] = _resolve_element_dimensions(container_data, 186, 62);

    // Get font properties from label or props
    let label_data = pyGet(container_data, 'label', {});
    if (!isDict(label_data)) {
      label_data = {};
    }
    let props = pyGet(container_data, 'props', {});
    if (!isDict(props)) {
      props = {};
    }

    const font_size = pyOr(pyOr(pyOr(
      pyGet(label_data, 'fontSize'),
      pyGet(props, 'fontSize')),
    pyGet(container_data, 'fontSize')),
    _DEFAULT_NODE_FONT_SIZE) as number;
    const font_family = pyOr(pyOr(
      pyGet(label_data, 'fontFamily'),
      pyGet(props, 'fontFamily')),
    pyGet(container_data, 'fontFamily', 2));
    const text_align = pyOr(pyOr(
      pyGet(label_data, 'textAlign'),
      pyGet(props, 'textAlign')),
    pyGet(container_data, 'textAlign', 'center'));
    const vertical_align = pyOr(pyOr(
      pyGet(label_data, 'verticalAlign'),
      pyGet(props, 'verticalAlign')),
    pyGet(container_data, 'verticalAlign', 'middle'));
    const font_style = pyOr(pyOr(pyOr(
      pyGet(label_data, 'fontStyle'),
      pyGet(props, 'fontStyle')),
    pyGet(container_data, 'fontStyle')),
    0);
    const line_height = pyOr(pyOr(pyOr(
      pyGet(label_data, 'lineHeight'),
      pyGet(props, 'lineHeight')),
    pyGet(container_data, 'lineHeight')),
    _DEFAULT_LINE_HEIGHT);

    // Estimate actual text dimensions (not container dimensions)
    const dims = _estimate_text_dimensions(text, font_size);

    const text_elem: Dict = {
      ..._excalidraw_defaults(['bound_text', container_id, text]),
      id: text_id,
      type: 'text',
      x: x + (container_w - dims.width) / 2,
      y: y + (container_h - dims.height) / 2,
      width: dims.width,
      height: dims.height,
      index: this._next_index(),
      text,
      fontSize: font_size,
      fontFamily: font_family,
      fontStyle: font_style,
      textAlign: text_align,
      verticalAlign: vertical_align,
      containerId: container_id,
      originalText: text,
      autoResize: true,
      lineHeight: line_height,
      strokeColor: _DEFAULT_TEXT_COLOR,
    };
    markF(text_elem, 'x', true); // ``... / 2``
    markF(text_elem, 'y', true);
    copyF(dims, 'width', text_elem, 'width');
    copyF(dims, 'height', text_elem, 'height');
    for (const [key, field, last] of [['fontSize', 'fontSize', false], ['fontFamily', 'fontFamily', true],
      ['fontStyle', 'fontStyle', false], ['lineHeight', 'lineHeight', false]] as [string, string, boolean][]) {
      markF(text_elem, key, orF([[label_data, field], [props, field], [container_data, field]], last));
    }

    // Apply text color from label or container
    const label_color = pyOr(pyOr(
      pyGet(label_data, 'strokeColor'),
      pyGet(container_data, 'labelColor')),
    pyGet(props, 'labelColor'));
    if (truthy(label_color)) {
      text_elem.strokeColor = label_color;
    }

    return text_elem;
  }

  /** Create an Excalidraw image element for an icon. */
  _create_image_element(semantic_id: string, position: { x: number; y: number; dim: number }, file_id: string): Dict {
    const eid = this._make_id(semantic_id);
    const dim = position.dim;

    const image_elem: Dict = {
      ..._excalidraw_defaults(['image', semantic_id, file_id]),
      id: eid,
      type: 'image',
      x: position.x,
      y: position.y,
      width: dim,
      height: dim,
      index: this._next_index(),
      fileId: file_id,
      status: 'saved',
      scale: [1, 1],
      crop: null,
    };
    copyF(position, 'x', image_elem, 'x');
    copyF(position, 'y', image_elem, 'y');
    copyF(position, 'dim', image_elem, 'width');
    copyF(position, 'dim', image_elem, 'height');
    return image_elem;
  }

  /** Convert layout_instantiation to Excalidraw clipboard format (type, elements, files, _meta). */
  convert(): Dict {
    if (truthy(this.structure_instantiation)) {
      validate_layout_instantiation(this.layout_instantiation, this.structure_instantiation, null, false);
    }

    const elements: Dict[] = [];
    const files: Dict = {};
    const edge_data: Dict = {};

    // Classify elements
    const icon_elements: Record<string, [string, Dict]> = {};
    const regular_elements: Record<string, Dict> = {};

    for (const [element_id, element_data] of Object.entries(this.layout_instantiation) as [string, Dict][]) {
      if (is_layout_edge_entry(element_id, element_data)) {
        edge_data[element_id] = element_data;
      } else if (element_id.endsWith(ICON_SUFFIX)) {
        const icon_base = pyOr(companion_base_id(element_id), element_id) as string;
        icon_elements[icon_base] = [element_id, element_data];
      } else {
        regular_elements[element_id] = element_data;
      }
    }

    // Group frames whose ``:title`` sibling already provides the label.
    const titled_bases = new Set<string>();
    for (const eid of Object.keys(regular_elements)) {
      if (isStr(eid) && eid.endsWith(TITLE_SUFFIX)) titled_bases.add(base_id(eid));
    }

    // Sort by z-layer so group frames never occlude their children (stable).
    const _regular_layer = (kv: [string, Dict]): number => {
      const [element_id, element_data] = kv;
      if (isStr(element_id) && !element_id.endsWith(TITLE_SUFFIX) && titled_bases.has(base_id(element_id))) {
        return LAYER_GROUP_FRAME;
      }
      return layer_for(element_id, element_data);
    };

    const sorted_regular = pySorted(Object.entries(regular_elements) as [string, Dict][], _regular_layer);

    // Process regular elements
    for (const entry of sorted_regular) {
      const element_id = entry[0];
      let element_data = entry[1];
      if (!hasKey(element_data, 'type') && !hasKey(element_data, 'shape')) {
        continue;
      }
      // Skip arrow elements - handled by arrow adder
      if (pyGet(element_data, 'type') === 'arrow' || pyGet(element_data, 'shape') === 'arrow') {
        continue;
      }

      // Skip parent group elements that have :background siblings but no
      // coordinates themselves.
      if (
        isStr(element_id)
        && !element_id.endsWith(BACKGROUND_SUFFIX)
        && !element_id.endsWith(TITLE_SUFFIX)
        && !hasKey(element_data, 'x')
        && !hasKey(element_data, 'y')
        && hasKey(regular_elements, companion_id(element_id, BACKGROUND_SUFFIX))
      ) {
        continue;
      }

      // --- Standalone text elements (e.g. group titles) ---
      if (pyGet(element_data, 'type') === 'text' || pyGet(element_data, 'shape') === 'text') {
        const text_elem = this._create_standalone_text_element(element_id, element_data);
        elements.push(text_elem);
        continue;
      }

      // --- Shape elements (rectangle, ellipse, diamond, etc.) ---
      if (isStr(element_id) && !element_id.endsWith(TITLE_SUFFIX) && titled_bases.has(base_id(element_id))) {
        element_data = pyDictCopy(element_data);
        element_data.is_group = true;
      }

      const shape = this._create_shape_element(element_id, element_data);
      const shape_eid = shape.id as string;

      // Group frames with an explicit ``:title`` sibling render as a bare backdrop.
      const frame_has_title_sibling = isStr(element_id) && titled_bases.has(base_id(element_id));

      // Extract label text: layout_instantiation first, structure fallback
      let text = '';
      if (!frame_has_title_sibling) {
        text = this._lookup_label(element_id, element_data);
      }

      let text_elem: Dict | null = null;
      if (truthy(text)) {
        text_elem = this._create_bound_text_element(text, shape_eid, element_data);
        shape.boundElements = [...(pyGet(shape, 'boundElements', []) as unknown[])];
        (shape.boundElements as unknown[]).push({ type: 'text', id: text_elem.id });
        elements.push(shape);
        elements.push(text_elem);
      } else {
        elements.push(shape);
      }

      // Handle icon for this element
      const icon_entry = hasKey(icon_elements, element_id) ? icon_elements[element_id] : null;
      if (icon_entry) {
        const [icon_element_id, icon_element_data] = icon_entry;
        const icon_name = pyGet(pyOr(pyGet(icon_element_data, 'props'), {}), 'icon', '');
        const asset = isStr(icon_name) && hasKey(bundled_icons(), icon_name)
          ? icon_file(icon_name, shape.strokeColor as string)
          : null;
        const data_url = truthy(asset)
          ? (pyGetItem(asset!, 'dataURL') as string)
          : _icon_to_data_url(icon_element_data, icon_element_id);
        const position = this._position_icon_in_node(icon_element_data, element_data);
        const file_id = truthy(asset) ? (pyGetItem(asset!, 'id') as string) : md5Hex(data_url).slice(0, 20);
        files[file_id] = {
          mimeType: 'image/svg+xml',
          id: file_id,
          dataURL: data_url,
          created: _STABLE_EXCALIDRAW_UPDATED_MS,
          lastRetrieved: _STABLE_EXCALIDRAW_UPDATED_MS,
          status: 'saved',
        };

        const image_elem = this._create_image_element(icon_element_id, position, file_id);
        const group_id = _generate_excalidraw_id(['node-icon-group', element_id]);
        shape.groupIds = [group_id];
        image_elem.groupIds = [group_id];
        image_elem.customData = { [ICON_KEY]: { hostId: shape_eid, name: icon_name } };
        if (truthy(text)) {
          text_elem!.groupIds = [group_id];
        }
        elements.push(image_elem);
      }
    }

    const manifest: Dict = {
      type: 'excalidraw/clipboard',
      elements,
      files,
      _meta: {
        id_map: { ...this.id_map },
        edge_data,
      },
    };
    sync_node_icons(manifest);
    return manifest;
  }
}
