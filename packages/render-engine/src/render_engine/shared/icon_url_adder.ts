// Ported from evodesign/agentic_system/render_engine/shared/icon_url_adder.py — keep in sync.
//
// Icon URL Adder Tool
//
// Adds HTTP URLs to icon entries in styling JSON for rendering via tool_services.
//
// Not ported 1:1 (see migration/notes/WP02.md):
// - ``AppSettings.get_default().icon_base_url`` -> ``_default_icon_base_url``:
//   the ``ICON_BASE_URL`` env override (non-blank), else the value shipped in
//   evodesign/config/defaults/settings.yaml (identical to the property default).
// - ``make_icon_url_adder_tool`` returns a dependency-free StructuredTool-like
//   object (name/description/args_schema/func/invoke) instead of LangChain.
// - ``main`` (argparse CLI with file IO) is not available in the browser-safe
//   port and raises ``NotImplementedError``.

import { pyDeepcopy } from '../../py/float_marks.ts';
import { pyGet, pyItems, type PyMapping } from '../../py/dict.ts';
import { pyIn } from '../../py/eq.ts';
import { AttributeError, NotImplementedError, ValueError } from '../../py/errors.ts';
import { getEnv } from '../../py/env.ts';
import { getLogger } from '../../py/logging.ts';
import { pyRepr, pyStr, pyStrip } from '../../py/str.ts';
import { isMapping, isStr, truthy } from '../../py/truthy.ts';
import { format_icon_url, is_local_material_icon_url, require_icon_svg_path } from '../../common/icon_assets.ts';
import { ICON_SUFFIX } from '../../common/semantic_ids.ts';
import { bundled_icons } from '../../common/node_icons.ts';

const logger = getLogger('evodesign.agentic_system.render_engine.shared.icon_url_adder');

// Icons are served from tool_services at: http://localhost:3000/icons/material-design-icons/
// Pattern: http://localhost:3000/icons/material-design-icons/{color}/{icon}.svg

const _SETTINGS_YAML_ICON_BASE_URL = 'http://localhost:3000/icons/material-design-icons/{color}/{icon}.svg';

/** ``AppSettings.get_default().icon_base_url`` (``render.icon_base_url`` / ``ICON_BASE_URL``). */
export function _default_icon_base_url(): string {
  const env_val = getEnv('ICON_BASE_URL');
  if (env_val !== null && pyStrip(env_val)) {
    return env_val;
  }
  return _SETTINGS_YAML_ICON_BASE_URL;
}

/** Check if an entry is an icon entry. */
export function _is_icon_entry(key: unknown): boolean {
  if (!isStr(key)) {
    return false;
  }
  return key.endsWith(ICON_SUFFIX);
}

/**
 * Add bundled Material icon URLs to icon entries in styling JSON.
 *
 * @param styling_json The styling JSON dictionary with icon entries
 * @param base_url Optional Material icon route template (defaults to
 *   render.icon_base_url in settings.yaml)
 * @returns Updated styling JSON with URLs added to icon entries
 */
export function add_icon_urls(styling_json: PyMapping, base_url: string | null = null): PyMapping {
  if (base_url === null || base_url === undefined) {
    base_url = _default_icon_base_url();
  }

  const updated = pyDeepcopy(styling_json);
  let added_count = 0;

  for (const [key, value] of pyItems(updated)) {
    if (!_is_icon_entry(key)) {
      continue;
    }

    if (!isMapping(value)) {
      continue;
    }

    const props = pyGet(value, 'props', {});
    if (!isMapping(props)) {
      continue;
    }

    // Get icon name and color
    const icon_name = pyGet(props, 'icon');
    const icon_color = pyGet(props, 'color', 'black');

    if (!truthy(icon_name)) {
      continue;
    }

    // Add or update URL
    const url = format_icon_url(icon_name as string, icon_color as string, base_url);
    if (!is_local_material_icon_url(url)) {
      throw new ValueError(
        'Icon URL template must target the bundled Material icon route '
        + `(${pyRepr(url)}). Use a template containing `
        + "'/icons/material-design-icons/{color}/{icon}.svg'.",
      );
    }
    if (!pyIn(icon_name, bundled_icons())) {
      require_icon_svg_path(pyStr(icon_name), pyStr(icon_color), url, key as string);
    }
    if (props instanceof Map) props.set('url', url);
    else props.url = url;
    added_count += 1;
  }

  logger.info('[IconUrlAdder] Added URLs to %d icon entries', added_count);
  return updated;
}

export class IconUrlAdderInput {
  /** Styling JSON with icon entries */
  styling_json: Record<string, unknown>;
  /** Optional Material icon route template */
  base_url: string | null;

  constructor(styling_json: Record<string, unknown>, base_url: string | null = null) {
    this.styling_json = styling_json;
    this.base_url = base_url;
  }
}

/** Add icon URLs to styling JSON entries. */
export function _icon_url_adder_impl(styling_json: PyMapping, base_url: string | null = null): PyMapping {
  return add_icon_urls(styling_json, base_url);
}

export interface IconUrlAdderTool {
  name: string;
  description: string;
  args_schema: typeof IconUrlAdderInput;
  func: typeof _icon_url_adder_impl;
  invoke(input: { styling_json: PyMapping; base_url?: string | null }): PyMapping;
}

/** Create an instance of the icon URL adder tool (LangChain-free stand-in). */
export function make_icon_url_adder_tool(): IconUrlAdderTool {
  return {
    name: 'icon_url_adder',
    description: 'Add HTTP URLs to icon entries in styling JSON for rendering via tool_services',
    args_schema: IconUrlAdderInput,
    func: _icon_url_adder_impl,
    invoke: (input) => _icon_url_adder_impl(input.styling_json, input.base_url ?? null),
  };
}

let _icon_url_adder: IconUrlAdderTool | null = null;

/** Module ``__getattr__``: ``icon_url_adder`` is built on first use. */
export function __getattr__(name: string): unknown {
  // ``icon_url_adder`` stays importable for agent tooling, built on first use.
  if (name === 'icon_url_adder') {
    _icon_url_adder ??= make_icon_url_adder_tool();
    return _icon_url_adder;
  }
  throw new AttributeError(
    `module 'evodesign.agentic_system.render_engine.shared.icon_url_adder' has no attribute ${pyRepr(name)}`,
  );
}

/** CLI entry point for testing the tool (Python only: argparse + file IO). */
export function main(): never {
  throw new NotImplementedError(
    'icon_url_adder.main is a Python CLI (argparse + file IO); use add_icon_urls from TS.',
  );
}
