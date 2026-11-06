// Ported from evodesign/agentic_system/common/domain_knowledge_loader.py — keep in sync.
//
// Helpers for loading curated diagram domain knowledge into agent prompts.
//
// The pipeline runs three sequential agents (Structure → Styling → Layout) over
// a shared conversation history. This module separates two concerns:
//
// * ``build_diagram_context(diagram_type)`` — the **shared** block: family
//   identity, identity/usage cues, and the per-type slice extracted from the
//   ``type_patterns/`` file. Injected once, in the Structure user message.
// * ``build_stage_knowledge(diagram_type, stage)`` — only the
//   **stage-specific delta**: per-stage rules from ``type_patterns/*.md``.
//
// Files are read through ``py/assets.ts``.

import { assetExists, assetIsDir, globAssets, pathStem, readAssetText } from '../py/assets.ts';
import { pyLstrip, pyStrip } from '../py/str.ts';
import { truthy } from '../py/truthy.ts';
import { TYPE_PATTERNS_DIR, normalize_diagram_type, slugify as _slugify } from './diagram_types.ts';

export const _SYSTEM_PROMPT_DIR = 'system_prompt';

export const GROUP_CONTAINMENT_PATH = `${_SYSTEM_PROMPT_DIR}/group_containment_reference.md`;

export const STAGE_KEY_MAP: Record<string, string> = {
  structure: 'structure',
  styling: 'styling',
  layout: 'layout',
};

type Knowledge = Record<string, unknown>;

/** ``str.splitlines()`` */
function splitlines(text: string): string[] {
  const lines = text.split(/\r\n|[\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029]/);
  if (lines.length && lines[lines.length - 1] === '') lines.pop();
  return lines;
}

/**
 * Extract top-level bullet rules from a Markdown section body.
 *
 * A new rule starts with either ``- `` at the beginning of a line (indent
 * <= 2) or a ``#### `` sub-heading. Subsequent indented lines or blank lines
 * belong to the same rule until the next starter.
 */
export function _parse_rule_list(text: string): string[] {
  const rules: string[] = [];
  let current: string[] = [];
  let in_rule = false;

  for (const raw_line of splitlines(text)) {
    const stripped = pyLstrip(raw_line);
    const indent = raw_line.length - stripped.length;

    const is_subheading = stripped.startsWith('#### ');
    const is_bullet = stripped.startsWith('- ') && indent <= 2;

    if (is_subheading || is_bullet) {
      // Finish previous rule and start a new one
      if (current.length) {
        rules.push(pyStrip(current.join('\n')));
      }
      current = is_subheading ? [raw_line] : [stripped.slice(2)];
      in_rule = true;
    } else if (in_rule) {
      // Continue current rule (preserve original indentation)
      current.push(raw_line);
    }
  }

  if (current.length) {
    rules.push(pyStrip(current.join('\n')));
  }

  return rules.filter((r) => r);
}

const MAIN_SECTIONS = ['Common', 'Structure', 'Styling', 'Layout'];

/**
 * Parse a single ``type_patterns/*.md`` file into structured knowledge.
 *
 * Returns a dict with keys ``common``, ``structure``, ``styling``,
 * ``layout`` (lists of rules) plus ``common_body`` (raw Common markdown).
 */
export function _parse_type_knowledge_markdown(text: string): Knowledge {
  const sections: Knowledge = {};
  let current_heading: string | null = null;
  let current_body: string[] = [];

  const flush = () => {
    if (current_heading) {
      const body = pyStrip(current_body.join('\n'));
      if (MAIN_SECTIONS.includes(current_heading)) {
        sections[current_heading.toLowerCase()] = _parse_rule_list(body);
        if (current_heading === 'Common') {
          sections.common_body = body;
        }
      }
    }
  };

  for (const line of splitlines(text)) {
    if (line.startsWith('### ')) {
      const heading = pyStrip(line.slice(4));
      flush();
      current_heading = heading;
      current_body = [];
    } else if (line.startsWith('#### ') && current_heading !== null && MAIN_SECTIONS.includes(current_heading)) {
      // Sub-heading inside a main section — keep it in the body
      current_body.push(line);
    } else {
      current_body.push(line);
    }
  }

  // Flush the last section
  flush();

  return sections;
}

let _knowledgeCache: Record<string, Knowledge> | null = null;

/** Load curated domain knowledge from ``type_patterns/*.md`` files (``lru_cache(maxsize=1)``). */
export function load_domain_knowledge(): Record<string, Knowledge> {
  if (_knowledgeCache !== null) return _knowledgeCache;
  if (!assetIsDir(TYPE_PATTERNS_DIR)) {
    _knowledgeCache = {};
    return _knowledgeCache;
  }

  const knowledge: Record<string, Knowledge> = {};
  for (const filepath of globAssets(TYPE_PATTERNS_DIR, '*.md')) {
    const type_key = pathStem(filepath);
    let text = pyStrip(readAssetText(filepath));
    // Strip the leading ``## Title`` line — it is not part of the data
    const lines = splitlines(text);
    if (lines.length && lines[0].startsWith('## ')) {
      text = pyStrip(lines.slice(1).join('\n'));
    }

    const parsed = _parse_type_knowledge_markdown(text);
    if (truthy(parsed)) {
      knowledge[type_key] = parsed;
    }
  }

  _knowledgeCache = knowledge;
  return knowledge;
}

/** Read an optional markdown/text file if present. */
export function _read_optional_text(path: string): string {
  if (!assetExists(path) || assetIsDir(path)) {
    return '';
  }
  return pyStrip(readAssetText(path));
}

/** Extract all ``#### `` sub-sections from the Common body. */
export function _extract_visual_patterns(body: string): string {
  const lines = splitlines(body);
  const result: string[] = [];
  let collecting = false;
  for (const line of lines) {
    if (line.startsWith('#### ')) {
      collecting = true;
      result.push(line);
    } else if (collecting) {
      result.push(line);
    }
  }
  return pyStrip(result.join('\n'));
}

/**
 * Return the per-type visual-pattern section, or empty string.
 *
 * Visual patterns are embedded inside the ``Common`` section as ``#### ``
 * sub-headings; they are extracted from ``common_body``.
 */
export function get_diagram_pattern_slice(diagram_type: string | null): string {
  const normalized = normalize_diagram_type(diagram_type);
  if (!normalized) {
    return '';
  }
  const knowledge = load_domain_knowledge();
  const entry = Object.prototype.hasOwnProperty.call(knowledge, normalized) ? knowledge[normalized] : null;
  if (!truthy(entry)) {
    return '';
  }
  const body = (Object.prototype.hasOwnProperty.call(entry, 'common_body') ? entry!.common_body : '') as string;
  if (body) {
    return _extract_visual_patterns(body);
  }
  return '';
}

/** ``str.capitalize()`` for ASCII stage keys. */
function capitalize(text: string): string {
  return text ? text[0].toUpperCase() + text.slice(1).toLowerCase() : text;
}

export function _format_rule_block(title: string, rules: Iterable<string>): string {
  const lines = [`${title}:`];
  for (const rule of rules) {
    if (rule.startsWith('#### ')) {
      // Sub-heading rule: render as bold label, not a bullet, so the
      // LLM sees a clear section break instead of a nested heading.
      const newline = rule.indexOf('\n');
      const parts = newline < 0 ? [rule] : [rule.slice(0, newline), rule.slice(newline + 1)];
      const heading = pyStrip(parts[0].slice(5));
      lines.push(`**${heading}**`);
      if (parts.length > 1 && pyStrip(parts[1])) {
        lines.push(pyStrip(parts[1]));
      }
    } else {
      lines.push(`- ${rule}`);
    }
  }
  return lines.join('\n');
}

/**
 * Compose the **shared** diagram-context block: family name, common identity
 * cues, and the visual-pattern slice for the current diagram type.
 */
export function build_diagram_context(diagram_type: string | null): string {
  const normalized_type = normalize_diagram_type(diagram_type);
  const knowledge = load_domain_knowledge();

  const parts = [
    '=== DIAGRAM CONTEXT ===',
    (
      'Zero-bloat reminder: treat the entries below as reusable type '
      + 'signals and invariants. Do not turn them into sample-specific '
      + 'coordinates or one-off patches.'
    ),
  ];

  if (normalized_type && Object.prototype.hasOwnProperty.call(knowledge, normalized_type)) {
    const entry = knowledge[normalized_type];
    parts.push(`Diagram family: ${normalized_type}`);

    const common_rules = Object.prototype.hasOwnProperty.call(entry, 'common') ? entry.common : null;
    if (Array.isArray(common_rules) && common_rules.length) {
      parts.push(_format_rule_block('Identity and usage cues', common_rules as string[]));
    }
  } else {
    const fallback_type = normalized_type || 'unknown';
    parts.push(
      `No curated entry was found for diagram family \`${fallback_type}\`. `
      + 'Use the chart-type library, calibration anchors, subtype '
      + 'boundaries, and completeness checks to infer the correct '
      + 'structure.',
    );
  }

  const pattern_slice = get_diagram_pattern_slice(diagram_type);
  if (pattern_slice) {
    const display_name = normalized_type.split('_').join(' ');
    parts.push(`=== PATTERNS FOR ${display_name.toUpperCase()} ===\n${pattern_slice}`);
  }

  return parts.join('\n\n');
}

/**
 * Compose stage-specific knowledge for the given stage.
 *
 * When *full_mode* is ``false`` (default), returns only the rules for the
 * requested stage. When ``true``, returns **all** stage rules with the
 * current stage listed first.
 */
export function build_stage_knowledge(diagram_type: string | null, stage: string | null, full_mode = false): string {
  const normalized_type = normalize_diagram_type(diagram_type);
  const slug = _slugify(stage || '');
  const normalized_stage = Object.prototype.hasOwnProperty.call(STAGE_KEY_MAP, slug) ? STAGE_KEY_MAP[slug] : null;
  const knowledge = load_domain_knowledge();

  const parts: string[] = [];

  if (!normalized_type || !Object.prototype.hasOwnProperty.call(knowledge, normalized_type)) {
    return '';
  }

  const entry = knowledge[normalized_type];
  const rulesOf = (key: string): unknown => (Object.prototype.hasOwnProperty.call(entry, key) ? entry[key] : null);

  if (full_mode) {
    // Emit all stage rules, current stage first for freshest attention.
    const all_stages = ['structure', 'styling', 'layout'];
    let ordered_stages: string[] = [];
    if (normalized_stage && all_stages.includes(normalized_stage)) {
      ordered_stages.push(normalized_stage);
      ordered_stages.push(...all_stages.filter((s) => s !== normalized_stage));
    } else {
      ordered_stages = [...all_stages];
    }

    for (const stage_key of ordered_stages) {
      const stage_rules = rulesOf(stage_key);
      if (Array.isArray(stage_rules) && stage_rules.length) {
        parts.push(_format_rule_block(`${capitalize(stage_key)} priorities`, stage_rules as string[]));
      }
    }
  } else if (normalized_stage) {
    const stage_rules = rulesOf(normalized_stage);
    if (Array.isArray(stage_rules) && stage_rules.length) {
      parts.push(_format_rule_block(`${capitalize(normalized_stage)} priorities`, stage_rules as string[]));
    }
  } else {
    for (const stage_key of ['structure', 'styling', 'layout']) {
      const stage_rules = rulesOf(stage_key);
      if (Array.isArray(stage_rules) && stage_rules.length) {
        parts.push(_format_rule_block(`${capitalize(stage_key)} priorities`, stage_rules as string[]));
      }
    }
  }

  return parts.join('\n\n');
}

/**
 * Load group containment reference for architecture Structure stage.
 * Empty string if the file is missing.
 */
export function get_group_containment_reference(): string {
  return _read_optional_text(GROUP_CONTAINMENT_PATH);
}

// ---------------------------------------------------------------------------
// Router / Palette helpers
// ---------------------------------------------------------------------------

// ``generation_stage/styling/colorful`` is ported by WP16, which builds on
// this work package; Python imports it lazily inside get_selected_palette.
interface ColorfulModule {
  PALETTES: Record<string, unknown>;
  render_palette_card: (palette_key: string) => string;
}
const COLORFUL_PATH = '../generation_stage/styling/colorful.ts';
const colorful = (await import('../generation_stage/styling/colorful.ts').catch(() => null)) as ColorfulModule | null;

/**
 * Return the formatted palette card for the given ``palette_key``.
 *
 * Lookup is exact. Returns an empty string if the key is missing or unknown.
 * Rendering is delegated to ``colorful.render_palette_card``.
 */
export function get_selected_palette(palette_key: string | null): string {
  if (!palette_key) {
    return '';
  }
  if (!colorful) {
    throw new Error('generation_stage/styling/colorful.ts is not ported yet (WP16)');
  }
  const { PALETTES, render_palette_card } = colorful;
  const has = PALETTES instanceof Map ? PALETTES.has(palette_key) : Object.prototype.hasOwnProperty.call(PALETTES, palette_key);
  if (!has) {
    return '';
  }
  return render_palette_card(palette_key);
}
