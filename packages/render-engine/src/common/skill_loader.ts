// Ported from evodesign/agentic_system/common/skill_loader.py — keep in sync.
//
// Skill Loader
// ============
//
// Loads the EvoDesign system prompt from ``evodesign_prompt.md`` — a compact
// anti-drift prompt (~2K tokens) that prevents semantic drift across the
// 3-stage pipeline (Structure → Styling → Layout).
//
// Per-type knowledge is injected per-stage via ``build_stage_knowledge()`` in
// the task prompt, NOT in the system prompt, so the system prompt stays
// cacheable and identical for every agent.
//
// Public surface: ``EVODESIGN_SKILL_SYSTEM_PROMPT`` — the base system prompt
// (no type knowledge); shared by all agents. Files are read through
// ``py/assets.ts`` (paths relative to ``evodesign/agentic_system``).

import { assetExists, assetIsDir, readAssetText } from '../py/assets.ts';
import { pyStrip } from '../py/str.ts';

export const SYSTEM_PROMPT_DIR_NAME = 'system_prompt';
export const MAIN_PROMPT_FILE = 'evodesign_prompt.md';

export class FileNotFoundError extends Error {
  override name = 'FileNotFoundError';
}

/** Locate ``agentic_system/system_prompt/`` relative to this module. */
export function _locate_skill_dir(): string {
  const prompt_dir = SYSTEM_PROMPT_DIR_NAME;
  if (assetIsDir(prompt_dir)) {
    return prompt_dir;
  }
  throw new FileNotFoundError(
    `Could not locate '${SYSTEM_PROMPT_DIR_NAME}/' at ${prompt_dir}. `
    + 'The prompt markdown files are expected under agentic_system/system_prompt.',
  );
}

const isFile = (path: string): boolean => assetExists(path) && !assetIsDir(path);

let _cachedBasePrompt: string | null = null;

/** Assemble the base system prompt from evodesign_prompt.md + digest files (``lru_cache(maxsize=1)``). */
export function _load_base_system_prompt(): string {
  if (_cachedBasePrompt !== null) return _cachedBasePrompt;
  const skill_dir = _locate_skill_dir();
  const prompt_path = `${skill_dir}/${MAIN_PROMPT_FILE}`;
  if (!isFile(prompt_path)) {
    throw new FileNotFoundError(`System prompt file missing: ${prompt_path}`);
  }

  let prompt_text = pyStrip(readAssetText(prompt_path));

  const divider = '\n\n' + '='.repeat(80) + '\n\n';

  // Append diagram type digest so every agent knows the supported families
  const diagram_type_digest_path = `${skill_dir}/diagram_type_digest.md`;
  if (isFile(diagram_type_digest_path)) {
    const diagram_type_digest = pyStrip(readAssetText(diagram_type_digest_path));
    prompt_text += divider + diagram_type_digest;
  }

  // Append palette digest so every agent knows which palettes exist
  // and when each one fits.
  const palette_digest_path = `${skill_dir}/palette_digest.md`;
  if (isFile(palette_digest_path)) {
    const palette_digest = pyStrip(readAssetText(palette_digest_path));
    prompt_text += divider + palette_digest;
  }

  _cachedBasePrompt = prompt_text;
  return prompt_text;
}

export const EVODESIGN_SKILL_SYSTEM_PROMPT: string = _load_base_system_prompt();

export const __all__ = ['EVODESIGN_SKILL_SYSTEM_PROMPT'];
