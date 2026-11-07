// Ported from evodesign/agentic_system/generation_stage/styling/colorful.py — keep in sync.
//
// Color palette catalog for the EvoDesign styling agent.
//
// Catalog data is loaded from ``palette_catalog/*.md`` under
// ``agentic_system/system_prompt/`` through ``py/assets.ts`` (paths are
// relative to ``evodesign/agentic_system``). Loading + validation runs at
// import time, as in Python.

import { assetIsDir, globAssets, pathStem, readAssetText } from '../../py/assets.ts';
import { KeyError, ValueError } from '../../py/errors.ts';
import { cpLen, cpSlice, pyRepr, pyStrip } from '../../py/str.ts';
import { isDict, isList } from '../../py/truthy.ts';
import { cpCompare } from '../../py/sort.ts';

// ---------------------------------------------------------------------------
// Source paths
// ---------------------------------------------------------------------------

export const _SYSTEM_PROMPT_DIR = 'system_prompt';
export const _CATALOG_DIR = `${_SYSTEM_PROMPT_DIR}/palette_catalog`;

export class FileNotFoundError extends Error {
  constructor(message = '') {
    super(message);
    this.name = 'FileNotFoundError';
  }
}

// ---------------------------------------------------------------------------
// Validators
// ---------------------------------------------------------------------------

export const _HEX_RE = /^#[0-9A-Fa-f]{6}$/;
export const _KEY_RE = /^[a-z][a-z0-9_]*$/;

export const _REQUIRED_PALETTE_FIELDS = [
  'display_name',
  'mood',
  'use_when',
  'avoid_when',
  'reference_anchors',
  'balance_guidance',
  'common_mistakes',
  'digest',
  'canvas',
  'border_default',
  'accent_edge',
  'fill_families',
] as const;

export const _REQUIRED_FAMILY_FIELDS = ['name', 'fill', 'stroke', 'voice'] as const;

export type PaletteFamily = Record<string, string>;
export type Palette = Record<string, any>;

function has(obj: Record<string, unknown>, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(obj, key);
}

export function _validate_hex(value: unknown, where: string): void {
  if (!(typeof value === 'string' && _HEX_RE.test(value))) {
    throw new ValueError(
      `palette_catalog: invalid hex at ${where}: ${pyRepr(value)} `
      + "(expected '#RRGGBB')",
    );
  }
}

export function _validate_palette(key: string, p: Palette): void {
  if (!_KEY_RE.test(key)) {
    throw new ValueError(
      `palette_catalog: invalid palette key ${pyRepr(key)} `
      + '(must be snake_case, ^[a-z][a-z0-9_]*$)',
    );
  }

  for (const field of _REQUIRED_PALETTE_FIELDS) {
    if (!has(p, field)) {
      throw new ValueError(
        `palette_catalog: palette ${pyRepr(key)} missing field `
        + `${pyRepr(field)}`,
      );
    }
  }

  if (typeof p.display_name !== 'string' || !pyStrip(p.display_name)) {
    throw new ValueError(
      `palette_catalog: palette ${pyRepr(key)} has empty/non-string display_name`,
    );
  }

  _validate_hex(p.canvas, `${key}.canvas`);
  _validate_hex(p.border_default, `${key}.border_default`);
  _validate_hex(p.accent_edge, `${key}.accent_edge`);

  const families = p.fill_families;
  if (!isList(families) || families.length < 4) {
    throw new ValueError(
      `palette_catalog: palette ${pyRepr(key)} must have >=4 `
      + `fill_families (got ${isList(families) ? families.length : '?'})`,
    );
  }

  const seen_names = new Set<string>();
  families.forEach((fam, i) => {
    if (!isDict(fam)) {
      throw new ValueError(
        `palette_catalog: ${key}.fill_families[${i}] is not a dict`,
      );
    }
    for (const field of _REQUIRED_FAMILY_FIELDS) {
      if (!has(fam, field)) {
        throw new ValueError(
          `palette_catalog: ${key}.fill_families[${i}] `
          + `missing field ${pyRepr(field)}`,
        );
      }
    }
    _validate_hex(fam.fill, `${key}.fill_families[${i}].fill`);
    _validate_hex(fam.stroke, `${key}.fill_families[${i}].stroke`);
    if (seen_names.has(fam.name as string)) {
      throw new ValueError(
        `palette_catalog: ${key} has duplicate family name `
        + `${pyRepr(fam.name)}`,
      );
    }
    seen_names.add(fam.name as string);
  });
}

// ---------------------------------------------------------------------------
// Markdown parser
// ---------------------------------------------------------------------------

// Python ``\w`` (Unicode word chars) and ``\s`` (``str.isspace`` set).
const PY_WS = '\\t\\n\\v\\f\\r \\x1c-\\x1f\\x85\\xa0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000';
export const _FIELD_RE = new RegExp(`^\\*\\*([\\p{L}\\p{N}_\\p{Mn}\\p{Mc}\\p{Pc}]+):\\*\\*[${PY_WS}]*(.*)$`, 'u');

/** ``str.splitlines()`` (no keepends). */
function splitlines(text: string): string[] {
  const lines: string[] = [];
  const re = /\r\n|[\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029]/g;
  let start = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    lines.push(text.slice(start, m.index));
    start = m.index + m[0].length;
  }
  if (start < text.length) lines.push(text.slice(start));
  return lines;
}

/** Parse a single ``palette_catalog/*.md`` file into a structured dict. */
export function _parse_palette_markdown(text: string): Palette {
  const lines = splitlines(text);

  // Extract key from first line: ## key
  let key = '';
  if (lines.length && lines[0].startsWith('## ')) {
    key = pyStrip(lines[0].slice(3));
  }

  // Extract **field:** value pairs (support multi-line values)
  const fields: Record<string, string> = {};
  let current_field: string | null = null;
  let current_value: string[] = [];
  let fill_families_start: number | null = null;

  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];
    if (line.startsWith('### Fill Families')) {
      if (current_field !== null) {
        fields[current_field] = pyStrip(current_value.join('\n'));
        current_field = null;
      }
      fill_families_start = i;
      break;
    }

    const m = _FIELD_RE.exec(line);
    if (m) {
      if (current_field !== null) {
        fields[current_field] = pyStrip(current_value.join('\n'));
      }
      current_field = m[1];
      current_value = [m[2]];
    } else if (current_field !== null) {
      current_value.push(line);
    }
  }

  if (current_field !== null) {
    fields[current_field] = pyStrip(current_value.join('\n'));
  }

  // Strip backticks from hex values
  for (const hex_field of ['canvas', 'border_default', 'accent_edge']) {
    if (has(fields, hex_field)) {
      fields[hex_field] = pyStrip(pyStrip(fields[hex_field]), '`');
    }
  }

  // Parse Fill Families table
  const fill_families: PaletteFamily[] = [];
  if (fill_families_start !== null) {
    const table_lines: string[] = [];
    for (const line of lines.slice(fill_families_start + 1)) {
      const stripped = pyStrip(line);
      if (stripped.startsWith('|')) {
        table_lines.push(stripped);
      } else if (stripped === '') {
        continue;
      } else {
        break;
      }
    }

    // Skip header and separator rows
    for (const row_line of table_lines.slice(2)) {
      const cells = pyStrip(row_line, '|').split('|').map((c) => pyStrip(c));
      if (cells.length === 4) {
        fill_families.push({
          name: cells[0],
          fill: pyStrip(cells[1], '`'),
          stroke: pyStrip(cells[2], '`'),
          voice: cells[3],
        });
      }
    }
  }

  const get = (name: string): string => (has(fields, name) ? fields[name] : '');
  return {
    key,
    display_name: get('display_name'),
    mood: get('mood'),
    use_when: get('use_when'),
    avoid_when: get('avoid_when'),
    reference_anchors: get('reference_anchors'),
    balance_guidance: get('balance_guidance'),
    common_mistakes: get('common_mistakes'),
    digest: get('digest'),
    canvas: get('canvas'),
    border_default: get('border_default'),
    accent_edge: get('accent_edge'),
    fill_families,
  };
}

// ---------------------------------------------------------------------------
// Digest table builder
// ---------------------------------------------------------------------------

/** Build the concise palette digest table from loaded Markdown data. */
export function _build_digest_table(palettes: Record<string, Palette>): string {
  const rows = [
    '| key | display_name | use this when |',
    '|---|---|---|',
  ];
  for (const key of Object.keys(palettes).sort(cpCompare)) {
    const p = palettes[key];
    let digest: string = has(p, 'digest') ? p.digest : (has(p, 'use_when') ? p.use_when : '');
    // Truncate overly long digests
    if (cpLen(digest) > 120) {
      digest = cpSlice(digest, null, 117) + '...';
    }
    rows.push(
      `| \`${key}\` | ${p.display_name} | ${digest} |`,
    );
  }
  return rows.join('\n');
}

// ---------------------------------------------------------------------------
// Catalog loader (with validation)
// ---------------------------------------------------------------------------

export function _load_catalog(): [Record<string, Palette>, string] {
  if (!assetIsDir(_CATALOG_DIR)) {
    throw new FileNotFoundError(
      `palette_catalog directory missing: ${_CATALOG_DIR}`,
    );
  }

  const palettes: Record<string, Palette> = {};
  for (const filepath of globAssets(_CATALOG_DIR, '*.md')) {
    const text = readAssetText(filepath);
    const parsed = _parse_palette_markdown(text);
    const key: string = parsed.key || pathStem(filepath);
    parsed.key = key;
    _validate_palette(key, parsed);
    palettes[key] = parsed;
  }

  if (Object.keys(palettes).length < 12) {
    throw new ValueError(
      'palette_catalog: expected at least the baseline catalog size '
      + `(12 palettes), got ${Object.keys(palettes).length}`,
    );
  }

  const table_block = _build_digest_table(palettes);
  return [palettes, table_block];
}

export const [PALETTES, PALETTE_DIGEST_TABLE] = _load_catalog();
export const PALETTE_KEYS: string[] = Object.keys(PALETTES);

// ---------------------------------------------------------------------------
// Public utilities
// ---------------------------------------------------------------------------

/**
 * Return the lowercase set of hex codes any element in this palette
 * is allowed to emit. Used by the contrast guard and validators.
 */
export function palette_hexes(palette_key: string): Set<string> {
  const p = paletteOrKeyError(palette_key);
  const out = new Set<string>([
    String(p.canvas).toLowerCase(),
    String(p.border_default).toLowerCase(),
    String(p.accent_edge).toLowerCase(),
  ]);
  for (const fam of p.fill_families as PaletteFamily[]) {
    out.add(String(fam.fill).toLowerCase());
    out.add(String(fam.stroke).toLowerCase());
  }
  return out;
}

function paletteOrKeyError(palette_key: string): Palette {
  if (!has(PALETTES, palette_key)) {
    throw new KeyError(pyRepr(palette_key));
  }
  return PALETTES[palette_key];
}

/**
 * Render the full palette card (markdown) for one palette.
 *
 * Raises ``KeyError`` if ``palette_key`` is not a valid catalog key.
 */
export function render_palette_card(palette_key: string): string {
  const p = paletteOrKeyError(palette_key);
  const lines = [
    `#### ${p.display_name} (\`${palette_key}\`)`,
    `*${p.mood}*`,
    `- **Use when:** ${p.use_when}`,
    `- **Avoid when:** ${p.avoid_when}`,
    `- **Reference anchors:** ${p.reference_anchors}`,
    `- **Balance guidance:** ${p.balance_guidance}`,
    `- **Common mistakes:** ${p.common_mistakes}`,
    `- canvas: \`${p.canvas}\`  ·  border_default: \`${p.border_default}\`  ·  accent_edge: \`${p.accent_edge}\``,
    '- fill_families:',
  ];
  for (const fam of p.fill_families as PaletteFamily[]) {
    lines.push(
      `    - **${fam.name}** — fill \`${fam.fill}\` + stroke \`${fam.stroke}\` — ${fam.voice}`,
    );
  }
  return lines.join('\n');
}

export const __all__ = [
  'PALETTES',
  'PALETTE_KEYS',
  'PALETTE_DIGEST_TABLE',
  'render_palette_card',
  'palette_hexes',
];
