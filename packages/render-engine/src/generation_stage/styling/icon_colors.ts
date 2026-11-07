// Ported from evodesign/agentic_system/generation_stage/styling/icon_colors.py — keep in sync.
//
// Map a styling colour onto the Material icon asset colour directory.
//
// Icon entries carry ``props.color``, but that value is a *directory key*
// (``/icons/material-design-icons/{color}/{icon}.svg``), never a render
// colour. A hex is mapped to the nearest icon directory name (hue-first, in
// HLS) before it is written to ``props.color``.

import { TLDrawColorValidator } from '../../common/tldraw_utils.ts';
import { pyInt, pyMod } from '../../py/number.ts';
import { cpLen, pyLstrip, pyStrip } from '../../py/str.ts';
import { pyMin } from '../../py/sort.ts';

export const _HEX_RE = /^#(?:[0-9A-Fa-f]{3}|[0-9A-Fa-f]{6})$/;

// Colour directories that actually exist under
// ``tool_services/public/icons/material-design-icons/`` (see manifest.json).
// This is the TLDraw enum minus ``white``, which has no icon directory.
export const ICON_COLOR_NAMES: readonly string[] = TLDrawColorValidator.VALID_COLORS.filter((name) => name !== 'white');

export const DEFAULT_ICON_COLOR = 'black';

// Hue anchors (degrees) for the chromatic icon directories.
export const _HUE_ANCHORS: readonly (readonly [number, string])[] = [
  [0.0, 'red'],
  [25.0, 'orange'],
  [45.0, 'yellow'],
  [145.0, 'green'],
  [220.0, 'blue'],
  [288.0, 'violet'],
];

// Families that ship a lighter directory alongside the base one.
export const _HAS_LIGHT_VARIANT: ReadonlySet<string> = new Set(['red', 'green', 'blue', 'violet']);

// Below this saturation a colour reads as neutral, so hue is meaningless.
export const _NEUTRAL_SATURATION = 0.15;
// Below this lightness a neutral colour is black rather than grey.
export const _NEUTRAL_DARK_LIGHTNESS = 0.35;
// At or above this lightness a chromatic colour takes its ``light-`` variant.
export const _LIGHT_VARIANT_LIGHTNESS = 0.6;

/** ``re.match`` with ``$`` (also matches before one trailing newline). */
function hexMatch(value: string): boolean {
  return _HEX_RE.test(value) || (value.endsWith('\n') && _HEX_RE.test(value.slice(0, -1)));
}

export function is_hex_color(value: unknown): boolean {
  return typeof value === 'string' && hexMatch(pyStrip(value));
}

export function _hex_to_rgb(value: string): [number, number, number] {
  let digits = pyLstrip(pyStrip(value), '#');
  if (cpLen(digits) === 3) {
    digits = [...digits].map((ch) => ch + ch).join('');
  }
  return [0, 2, 4].map((i) => pyInt([...digits].slice(i, i + 2).join(''), 16) / 255.0) as [number, number, number];
}

export function _hue_distance(left: number, right: number): number {
  const delta = pyMod(Math.abs(left - right), 360.0);
  return Math.min(delta, 360.0 - delta);
}

/** ``colorsys.rgb_to_hls`` (CPython 3.11+). */
function rgb_to_hls(r: number, g: number, b: number): [number, number, number] {
  const maxc = Math.max(r, g, b);
  const minc = Math.min(r, g, b);
  const sumc = maxc + minc;
  const rangec = maxc - minc;
  const l = sumc / 2.0;
  if (minc === maxc) {
    return [0.0, l, 0.0];
  }
  let s: number;
  if (l <= 0.5) {
    s = rangec / sumc;
  } else {
    s = rangec / (2.0 - maxc - minc);
  }
  const rc = (maxc - r) / rangec;
  const gc = (maxc - g) / rangec;
  const bc = (maxc - b) / rangec;
  let h: number;
  if (r === maxc) {
    h = bc - gc;
  } else if (g === maxc) {
    h = 2.0 + rc - bc;
  } else {
    h = 4.0 + gc - rc;
  }
  h = pyMod(h / 6.0, 1.0);
  return [h, l, s];
}

/** Return the icon directory name closest to a ``#RRGGBB`` colour. */
export function hex_to_icon_color_name(value: string): string {
  const [red, green, blue] = _hex_to_rgb(value);
  const [hue, lightness, saturation] = rgb_to_hls(red, green, blue);
  const hue_degrees = hue * 360.0;

  if (saturation < _NEUTRAL_SATURATION) {
    return lightness < _NEUTRAL_DARK_LIGHTNESS ? 'black' : 'grey';
  }

  const [, family] = pyMin(
    _HUE_ANCHORS.map(([anchor, name]) => [_hue_distance(hue_degrees, anchor), name] as const),
    (item) => item[0],
  );
  if (_HAS_LIGHT_VARIANT.has(family) && lightness >= _LIGHT_VARIANT_LIGHTNESS) {
    return `light-${family}`;
  }
  return family;
}

/**
 * Normalise any styling colour into an icon asset directory name.
 *
 * Hex values are matched to the nearest directory; colour names keep going
 * through the TLDraw enum so TLDraw-canvas behaviour is unchanged.
 */
export function resolve_icon_color_name(value: string | null): string {
  if (typeof value !== 'string' || !pyStrip(value)) {
    return DEFAULT_ICON_COLOR;
  }
  if (is_hex_color(value)) {
    return hex_to_icon_color_name(value);
  }
  return TLDrawColorValidator.normalize_color(value);
}

export const __all__ = [
  'DEFAULT_ICON_COLOR',
  'ICON_COLOR_NAMES',
  'hex_to_icon_color_name',
  'is_hex_color',
  'resolve_icon_color_name',
];
