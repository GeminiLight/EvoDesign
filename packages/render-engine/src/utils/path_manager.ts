// Ported from evodesign/utils/path_manager.py — keep in sync.
// server-only
//
// Centralized path management for the EvoDesign project.
//
// Paths are strings (Python ``Path`` objects); ``Path.resolve()`` is
// ``_path_resolve`` from config/settings.ts.

import { mkdirSync } from 'node:fs';
import { dirname, join, relative, resolve, isAbsolute } from 'node:path';
import { fileURLToPath } from 'node:url';
import { ValueError } from '../py/errors.ts';
import { pyRepr, pyStrip } from '../py/str.ts';
import { cpCompare } from '../py/sort.ts';
import { _path_resolve } from '../config/settings.ts';

// Package root (``evodesign/``) and repository root.
export const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..', '..', '..');
export const PACKAGE_ROOT = join(REPO_ROOT, 'evodesign');

// Common directories
export const AGENTIC_SYSTEM_DIR = join(PACKAGE_ROOT, 'agentic_system');
export const RESOURCES_DIR = join(PACKAGE_ROOT, 'resources');
export const DATA_DIR = join(PACKAGE_ROOT, 'data');
export const DATASET_DIR = join(REPO_ROOT, 'dataset');
export const RESULTS_DIR = join(PACKAGE_ROOT, 'results');
export const SCRIPTS_DIR = join(REPO_ROOT, 'scripts');
export const CONFIG_DIR = join(REPO_ROOT, 'configs');
export const DESIGN_MEMORY_DIR = join(PACKAGE_ROOT, 'design_memory');
export const EVALUATION_DIR = join(REPO_ROOT, 'evaluation');
export const BASELINES_DIR = join(REPO_ROOT, 'baselines');
export const EXAMPLES_DIR = join(REPO_ROOT, 'examples');
export const EXPERIMENTS_DIR = join(REPO_ROOT, 'experiments');
export const DEFAULT_TEST_DATASET = join(DATASET_DIR, 'test', 'data.json');

// Resource subdirectories
export const FONTS_DIR = join(RESOURCES_DIR, 'fonts');
export const IMAGES_DIR = join(RESOURCES_DIR, 'images');
export const FIGURES_DIR = join(RESOURCES_DIR, 'figures');

// Stage directories
export const GENERATION_STAGE_DIR = join(AGENTIC_SYSTEM_DIR, 'generation_stage');
export const VERIFICATION_STAGE_DIR = join(AGENTIC_SYSTEM_DIR, 'verification_stage');
export const REFINEMENT_STAGE_DIR = join(AGENTIC_SYSTEM_DIR, 'refinement_stage');
export const RENDER_ENGINE_DIR = join(AGENTIC_SYSTEM_DIR, 'render_engine');

// Font files
export const FONT_FILES: Record<string, string> = {
  mono: join(FONTS_DIR, 'IBMPlexMono-Medium.ttf'),
  sans: join(FONTS_DIR, 'IBMPlexSans-Medium.ttf'),
  serif: join(FONTS_DIR, 'IBMPlexSerif-Medium.ttf'),
  draw: join(FONTS_DIR, 'Shantell_Sans-Informal_Regular.ttf'),
};

// Material icons directory
export const MATERIAL_ICONS_DIR = join(RESOURCES_DIR, 'icons', 'material-design-icons', 'filled');

// Environment file — repository-root .env
export const ENV_FILE = join(REPO_ROOT, '.env');

/**
 * Get an absolute path from a relative path.
 *
 * @param relative_path Relative path string (e.g., 'resources/fonts')
 * @param base Base directory (defaults to PACKAGE_ROOT)
 */
export function get_path(relative_path: string, base: string | null = null): string {
  base = base || PACKAGE_ROOT;
  return _path_resolve(join(base, relative_path));
}

/** Ensure a directory exists, creating it if necessary. */
export function ensure_dir(path: string): string {
  mkdirSync(path, { recursive: true });
  return path;
}

const ALLOWED = new Set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.');

/**
 * Return a single filesystem-safe path segment or raise ``ValueError``.
 *
 * Dataset ids, tags, and sample ids are user/data controlled. They must never
 * be joined directly into output paths because ``..`` or separators can escape
 * the intended experiment directory.
 */
export function safe_path_segment(value: unknown, field_name = 'path segment'): string {
  if (typeof value !== 'string') {
    throw new ValueError(`${field_name} must be a string.`);
  }
  const raw = value;
  if (!raw) {
    throw new ValueError(`${field_name} must not be empty.`);
  }
  if (raw !== pyStrip(raw)) {
    throw new ValueError(`${field_name} must not contain leading or trailing whitespace.`);
  }
  if (raw === '.' || raw === '..') {
    throw new ValueError(`${field_name} must be a normal file name segment: ${pyRepr(raw)}.`);
  }
  if (raw.includes('/') || raw.includes('\\') || raw.includes('\x00')) {
    throw new ValueError(`${field_name} must not contain path separators: ${pyRepr(raw)}.`);
  }
  const invalid = [...new Set([...raw].filter((ch) => !ALLOWED.has(ch)))].sort(cpCompare);
  if (invalid.length) {
    const sample = invalid.slice(0, 8).join('');
    throw new ValueError(
      `${field_name} contains unsupported character(s) ${pyRepr(sample)}; `
      + "use only letters, numbers, '-', '_', and '.'.",
    );
  }
  return raw;
}

/** Join safe segments under ``root`` and verify the result stays inside it. */
export function safe_join_under(root: string, ...segments: unknown[]): string {
  const root_path = _path_resolve(root);
  const safe_segments = segments.map((segment, idx) => safe_path_segment(segment, `path segment ${idx + 1}`));
  const joined = _path_resolve(join(root_path, ...safe_segments));
  const rel = relative(root_path, joined);
  if (rel === '..' || rel.startsWith('../') || isAbsolute(rel)) {
    throw new ValueError(`Resolved output path escapes root ${root_path}: ${joined}`);
  }
  return joined;
}

/** Get the evodesign package root directory. */
export function get_package_root(): string {
  return PACKAGE_ROOT;
}

/** Get the repository root directory. */
export function get_repo_root(): string {
  return REPO_ROOT;
}

/** Get the .env file path. */
export function get_env_file(): string {
  return ENV_FILE;
}

/** Get the path to a font file ('mono', 'sans', 'serif', 'draw'). */
export function get_font_path(font_name: string): string {
  const font_key = font_name.toLowerCase();
  if (!(font_key in FONT_FILES)) {
    throw new ValueError(`Unknown font: ${font_name}. Available fonts: ${pyRepr(Object.keys(FONT_FILES))}`);
  }
  return FONT_FILES[font_key];
}

export const __all__ = [
  'PACKAGE_ROOT',
  'REPO_ROOT',
  'RESOURCES_DIR',
  'DATASET_DIR',
  'EXAMPLES_DIR',
  'EXPERIMENTS_DIR',
  'DEFAULT_TEST_DATASET',
  'FONTS_DIR',
  'FONT_FILES',
  'MATERIAL_ICONS_DIR',
  'ENV_FILE',
  'get_path',
  'ensure_dir',
  'safe_path_segment',
  'safe_join_under',
  'get_package_root',
  'get_repo_root',
  'get_env_file',
  'get_font_path',
];
