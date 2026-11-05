// Single entry point for reading Python-side asset files (MIGRATION_PLAN.md §2, §4).
//
// Ported modules never touch the file system directly. Paths are relative to
// ``evodesign/agentic_system`` — the directory Python code reaches through
// ``Path(__file__).resolve().parents[...]`` — so the TS port keeps reading the
// very same files as Python (single source of truth):
//
//   Path(__file__).parent / "assets/material_icons.json"       (common/node_icons.py)
//     -> readAssetJson('common/assets/material_icons.json')
//   TYPE_PATTERNS_DIR.glob("*.md")                              (common/diagram_types.py)
//     -> globAssets('system_prompt/type_patterns', '*.md')
//
// This is the only module allowed to import ``node:*``. For the browser build
// (plan §10) install a bundled provider with ``setAssetProvider``.

import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs';
import { dirname, join, relative, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { pyJsonLoads } from './json.ts';
import { cpCompare } from './sort.ts';

export interface AssetProvider {
  readText(path: string): string;
  exists(path: string): boolean;
  isDir(path: string): boolean;
  /** Entries (file and directory names) directly inside ``path``. */
  list(path: string): string[];
}

/** Absolute path of ``evodesign/agentic_system`` in this checkout. */
export const AGENTIC_SYSTEM_ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..', '..', 'evodesign', 'agentic_system');

const nodeProvider: AssetProvider = {
  readText: (path) => readFileSync(join(AGENTIC_SYSTEM_ROOT, path), 'utf-8'),
  exists: (path) => existsSync(join(AGENTIC_SYSTEM_ROOT, path)),
  isDir: (path) => {
    const full = join(AGENTIC_SYSTEM_ROOT, path);
    return existsSync(full) && statSync(full).isDirectory();
  },
  list: (path) => readdirSync(join(AGENTIC_SYSTEM_ROOT, path)),
};

let provider: AssetProvider = nodeProvider;
const textCache = new Map<string, string>();

/** Replace the file-system provider (browser bundles, tests). Clears caches. */
export function setAssetProvider(next: AssetProvider | null): void {
  provider = next ?? nodeProvider;
  textCache.clear();
}

function normalize(path: string): string {
  return path.split(/[\\/]+/).filter((part) => part && part !== '.').join('/');
}

/** Absolute path of an asset under ``evodesign/agentic_system`` (Node only). */
export function assetPath(path: string): string {
  return join(AGENTIC_SYSTEM_ROOT, normalize(path));
}

/** ``path.read_text(encoding="utf-8")`` (cached). */
export function readAssetText(path: string): string {
  const key = normalize(path);
  let text = textCache.get(key);
  if (text === undefined) {
    text = provider.readText(key);
    textCache.set(key, text);
  }
  return text;
}

/** ``json.loads(path.read_text())`` — a fresh object on every call (callers may mutate it). */
export function readAssetJson(path: string): unknown {
  return pyJsonLoads(readAssetText(path));
}

/** ``path.exists()`` */
export function assetExists(path: string): boolean {
  return provider.exists(normalize(path));
}

/** ``path.is_dir()`` */
export function assetIsDir(path: string): boolean {
  return provider.isDir(normalize(path));
}

function globSegment(pattern: string): RegExp {
  const body = pattern.replace(/[.+^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '[^/]*').replace(/\?/g, '[^/]');
  return new RegExp(`^${body}$`);
}

/**
 * ``Path(dir).glob(pattern)`` for simple ``*``/``?`` patterns with ``/``
 * separated segments (``*.md`` or a two-level ``<dir>/<file>`` pattern for icons). Returns paths relative to
 * ``evodesign/agentic_system``, sorted by code point (Python's glob order is
 * file-system dependent; every Python caller sorts or only counts).
 * Hidden entries are matched only by patterns starting with ``.``, like pathlib.
 */
export function globAssets(dir: string, pattern: string): string[] {
  const base = normalize(dir);
  if (!assetIsDir(base)) return [];
  const segments = pattern.split('/').map((segment) => ({ segment, regex: globSegment(segment) }));
  let current = [base];
  segments.forEach(({ segment, regex }, index) => {
    const last = index === segments.length - 1;
    const next: string[] = [];
    for (const parent of current) {
      for (const name of provider.list(parent)) {
        if (name.startsWith('.') && !segment.startsWith('.')) continue;
        if (!regex.test(name)) continue;
        const child = parent ? `${parent}/${name}` : name;
        if (!last && !provider.isDir(child)) continue;
        next.push(child);
      }
    }
    current = next;
  });
  return current.sort(cpCompare);
}

/** ``PurePath(path).stem`` */
export function pathStem(path: string): string {
  const name = path.split('/').pop() ?? '';
  const dot = name.lastIndexOf('.');
  return dot > 0 ? name.slice(0, dot) : name;
}

/** ``PurePath(path).name`` */
export function pathName(path: string): string {
  return path.split('/').pop() ?? '';
}

/** Relative path from the agentic_system root (for messages / debugging). */
export function relativeAssetPath(absolute: string): string {
  return relative(AGENTIC_SYSTEM_ROOT, absolute).split(sep).join('/');
}
