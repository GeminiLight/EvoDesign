// Ported from evodesign/agentic_system/common/tldraw_utils.py — keep in sync.
//
// Common TLDraw Utilities. The Excalidraw pipeline only needs
// ``json_dumps_stable``; the TLDraw helpers are ported as well (small, pure)
// so every top-level Python name has a TS counterpart. The ``__main__`` demo
// block is not ported.

import { pyGet } from '../py/dict.ts';
import { PyTypeError, ValueError } from '../py/errors.ts';
import { md5Hex, sha256Hex } from '../py/hash.ts';
import { pyJsonDumps } from '../py/json.ts';
import { cpLen, pyRepr, pyStr, pyStrip } from '../py/str.ts';
import { truthy } from '../py/truthy.ts';

export function json_dumps_stable(value: unknown): string {
  try {
    return pyJsonDumps(value, { sortKeys: true, ensureAscii: false, default: pyStr });
  } catch (error) {
    if (error instanceof PyTypeError) return pyRepr(value);
    throw error;
  }
}

/** Generator for TLDraw-compatible IDs */
export class TLDrawIDGenerator {
  static _stable_suffix(seed: unknown): string {
    const payload = json_dumps_stable(seed);
    return sha256Hex(payload).slice(0, 20);
  }

  /** Generate a deterministic TLDraw-compatible shape ID ("prefix:suffix"). */
  static generate_shape_id(prefix = 'shape', seed: unknown = null): string {
    if (seed === null || seed === undefined) {
      throw new ValueError('TLDraw shape ids require a semantic seed.');
    }
    return `${prefix}:${TLDrawIDGenerator._stable_suffix([prefix, seed])}`;
  }

  /** Generate unique asset ID from icon URL ("asset:hash"). */
  static generate_asset_id(icon_url: string): string {
    const hash_hex = md5Hex(icon_url).slice(0, 20);
    return `asset:${hash_hex}`;
  }

  /** Generate a deterministic binding ID ("binding:suffix"). */
  static generate_binding_id(seed: unknown = null): string {
    return TLDrawIDGenerator.generate_shape_id('binding', seed);
  }

  /** Generate TLDraw index (e.g., "a1", "a2"). */
  static get_next_index(counter: number): string {
    return `a${pyStr(counter)}`;
  }

  /** Generate a deterministic TLDraw index (e.g., "b123xy"). */
  static generate_stable_index(prefix = 'b', seed: unknown = null): string {
    if (seed === null || seed === undefined) {
      throw new ValueError('TLDraw generated indexes require a semantic seed.');
    }
    return `${prefix}${TLDrawIDGenerator._stable_suffix([prefix, seed]).slice(0, 5)}`;
  }
}

/** Mapper for TLDraw size enums to pixel values */
export class TLDrawSizeMapper {
  static readonly ICON_SIZE_MAP: Readonly<Record<string, number>> = {
    xs: 24,
    s: 36,
    m: 48,
    l: 58,
    xl: 65.2,
  };

  /** Get icon pixel size from size enum. */
  static get_icon_size(size: string): number {
    return pyGet(TLDrawSizeMapper.ICON_SIZE_MAP, size, 48);
  }

  /** Calculate text box dimensions based on text content -> [width, height]. */
  static calculate_text_dimensions(text: string, size = 'm', padding_x = 20): [number, number] {
    const size_to_height: Record<string, number> = { xs: 40.0, s: 50.0, m: 60.0, l: 80.0, xl: 100.0 };
    const size_multiplier: Record<string, number> = { xs: 1.0, s: 1.1, m: 1.2, l: 1.4, xl: 1.6 };

    // Calculate base width based on text length
    const char_width = 8.0;
    const base_width = cpLen(text) * char_width + padding_x * 2;

    // Get height based on size
    const height = pyGet(size_to_height, size, 60.0) * pyGet(size_multiplier, size, 1.2);

    return [base_width, height];
  }
}

/** Validator for TLDraw color enums */
export class TLDrawColorValidator {
  static readonly VALID_COLORS: readonly string[] = [
    'black', 'grey', 'light-violet', 'violet', 'blue', 'light-blue',
    'yellow', 'orange', 'green', 'light-green', 'light-red', 'red', 'white',
  ];

  /** Normalize color to valid TLDraw color enum. */
  static normalize_color(color: string): string {
    if (!truthy(color)) {
      return 'black';
    }

    color = pyStrip(color.toLowerCase());

    // Common color mappings
    const color_map: Record<string, string> = {
      'light-grey': 'grey',
      lightgrey: 'grey',
      gray: 'grey',
      'light-gray': 'grey',
      lightgray: 'grey',
      purple: 'violet',
      'light-violet': 'light-violet', // identity
      'light-purple': 'light-violet',
      pink: 'light-red',
      'light-pink': 'light-red',
      cyan: 'light-blue',
      teal: 'light-blue',
      lime: 'light-green',
      navy: 'blue',
      maroon: 'red',
      brown: 'orange',
      gold: 'yellow',
      silver: 'grey',
      'dark-grey': 'black',
      'dark-gray': 'black',
      'dark-blue': 'blue',
      'dark-green': 'green',
      'dark-red': 'red',
    };

    const mapped = pyGet(color_map, color, null);
    if (mapped !== null) {
      return mapped;
    }

    // Return original if already valid
    if (TLDrawColorValidator.VALID_COLORS.includes(color)) {
      return color;
    }

    // Default to black for unknown colors
    return 'black';
  }
}

/** Validator for TLDraw shape enums */
export class TLDrawShapeValidator {
  static readonly VALID_SHAPES: readonly string[] = [
    'cloud', 'rectangle', 'ellipse', 'triangle', 'diamond',
    'pentagon', 'hexagon', 'octagon', 'star', 'rhombus',
    'rhombus-2', 'oval', 'trapezoid', 'arrow-right', 'arrow-left',
    'arrow-up', 'arrow-down', 'x-box', 'check-box', 'heart',
  ];

  /** Normalize shape to valid TLDraw shape enum. */
  static normalize_shape(shape: string): string {
    shape = pyStrip(shape.toLowerCase());

    // Common shape mappings
    const shape_map: Record<string, string> = {
      circle: 'ellipse',
      square: 'rectangle',
      box: 'rectangle',
    };

    const mapped = pyGet(shape_map, shape, null);
    if (mapped !== null) {
      return mapped;
    }

    // Return original if already valid
    if (TLDrawShapeValidator.VALID_SHAPES.includes(shape)) {
      return shape;
    }

    // Default to rectangle for unknown shapes
    return 'rectangle';
  }
}

/** Validator for TLDraw fill enums */
export class TLDrawFillValidator {
  static readonly VALID_FILLS: readonly string[] = ['none', 'semi', 'solid', 'pattern'];

  /** Normalize fill to valid TLDraw fill enum. */
  static normalize_fill(fill: string): string {
    fill = pyStrip(fill.toLowerCase());

    // Common fill mappings
    const fill_map: Record<string, string> = {
      transparent: 'none',
      empty: 'none',
      'empty-fill': 'none',
      outline: 'none',
    };

    const mapped = pyGet(fill_map, fill, null);
    if (mapped !== null) {
      return mapped;
    }

    // Return original if already valid
    if (TLDrawFillValidator.VALID_FILLS.includes(fill)) {
      return fill;
    }

    // Default to none for unknown fills
    return 'none';
  }
}

/** Convenience class combining all TLDraw utilities */
export class TLDrawUtils {
  /** Create a TLDraw asset entry for an icon. */
  static create_asset_entry(icon_url: string, icon_size = 'm', icon_name: string | null = null): Record<string, unknown> {
    if (icon_name === null || icon_name === undefined) {
      const parts = icon_url.split('/');
      icon_name = parts[parts.length - 1];
    }

    const dimension = TLDrawSizeMapper.get_icon_size(icon_size);
    const asset_id = TLDrawIDGenerator.generate_asset_id(icon_url);

    return {
      id: asset_id,
      type: 'image',
      typeName: 'asset',
      props: {
        name: icon_name,
        src: icon_url,
        w: dimension,
        h: dimension,
        mimeType: 'image/svg+xml',
        isAnimated: false,
      },
      meta: {},
    };
  }

  /** Create a TLDraw geo shape (text box). */
  static create_geo_shape(
    element_id: string,
    text = '',
    x = 500,
    y = 200,
    color = 'black',
    shape = 'rectangle',
    fill = 'none',
    size = 'm',
    parent_id = 'page:page',
    index = 'a1',
  ): Record<string, unknown> {
    // Normalize enums
    color = TLDrawColorValidator.normalize_color(color);
    shape = TLDrawShapeValidator.normalize_shape(shape);
    fill = TLDrawFillValidator.normalize_fill(fill);

    // Calculate dimensions
    const [w, h] = TLDrawSizeMapper.calculate_text_dimensions(text, size);

    return {
      x,
      y,
      rotation: 0,
      isLocked: false,
      opacity: 1,
      meta: {},
      id: `shape:${element_id}`,
      type: 'geo',
      props: {
        w,
        h,
        geo: shape,
        color,
        labelColor: color,
        fill,
        dash: 'draw',
        size,
        font: 'draw',
        text,
        align: 'middle',
        verticalAlign: 'middle',
        growY: 0,
        url: '',
        scale: 1,
      },
      parentId: parent_id,
      index,
      typeName: 'shape',
    };
  }

  /** Create a TLDraw image shape (icon). */
  static create_image_shape(
    element_id: string,
    asset_id: string,
    x = 500,
    y = 200,
    icon_size = 'm',
    parent_id = 'page:page',
    index = 'a2',
  ): Record<string, unknown> {
    const dimension = TLDrawSizeMapper.get_icon_size(icon_size);

    return {
      x,
      y,
      rotation: 0,
      isLocked: false,
      opacity: 1,
      meta: {},
      id: `shape:${element_id}`,
      type: 'image',
      props: {
        w: dimension,
        h: dimension,
        assetId: asset_id,
        playing: true,
        url: '',
        crop: null,
        flipX: false,
        flipY: false,
        altText: element_id,
      },
      parentId: parent_id,
      index,
      typeName: 'shape',
    };
  }

  /** Create a TLDraw binding. */
  static create_binding(
    from_id: string,
    to_id: string,
    terminal = 'start',
    anchor: Record<string, number> | null = null,
  ): Record<string, unknown> {
    if (anchor === null || anchor === undefined) {
      anchor = { x: 0.5, y: 0.5 };
    }

    return {
      meta: {},
      id: TLDrawIDGenerator.generate_binding_id([from_id, to_id, terminal, anchor]),
      type: 'arrow',
      fromId: from_id,
      toId: to_id,
      props: {
        isPrecise: true,
        isExact: true,
        normalizedAnchor: anchor,
        terminal,
      },
      typeName: 'binding',
    };
  }
}
