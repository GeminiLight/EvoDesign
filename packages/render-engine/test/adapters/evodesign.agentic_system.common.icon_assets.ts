// Parity adapter for common.icon_assets (WP02).
//
// Some recorded vectors come from pytest cases that monkeypatch
// ``icon_assets.icon_assets_root`` to a tmp directory with a hand-written
// manifest / SVG set (evodesign/tests/render_engine/test_icon_assets.py,
// test_icon_url_adder.py). ES modules cannot be monkeypatched, so instead the
// adapter installs a virtual asset provider (py/assets.ts setAssetProvider)
// that serves exactly the files the test created under the icon root, and
// falls back to the real file system for every other asset. Nothing is
// skipped; the functions run unchanged against the reconstructed directory.
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs';
import type { Adapter } from '../parity/functions.test.ts';
import type { Vector } from '../harness/fixtures.ts';
import { assetPath, setAssetProvider } from '../../src/py/assets.ts';
import { manifest_icon_names } from '../../src/common/icon_assets.ts';

const ROOT = 'tool_services/public/icons/material-design-icons';

/** Install a provider whose icon root holds exactly ``files`` (relative path -> text). */
export function useVirtualIconRoot(files: Record<string, string> | null): void {
  manifest_icon_names.cache_clear();
  if (files === null) {
    setAssetProvider(null);
    return;
  }
  const inRoot = (path: string) => path === ROOT || path.startsWith(`${ROOT}/`);
  const rel = (path: string) => path.slice(ROOT.length).replace(/^\//, '');
  const dirs = new Set<string>(['']);
  for (const file of Object.keys(files)) {
    const parts = file.split('/');
    for (let i = 1; i < parts.length; i += 1) dirs.add(parts.slice(0, i).join('/'));
  }
  setAssetProvider({
    readText: (path) => {
      if (!inRoot(path)) return readFileSync(assetPath(path), 'utf-8');
      const content = files[rel(path)];
      if (content === undefined) throw new Error(`ENOENT: ${path}`);
      return content;
    },
    exists: (path) => (inRoot(path) ? dirs.has(rel(path)) || rel(path) in files : existsSync(assetPath(path))),
    isDir: (path) => (inRoot(path) ? dirs.has(rel(path)) : existsSync(assetPath(path)) && statSync(assetPath(path)).isDirectory()),
    list: (path) => {
      if (!inRoot(path)) return readdirSync(assetPath(path));
      const base = rel(path);
      const prefix = base ? `${base}/` : '';
      const names = new Set<string>();
      for (const entry of [...dirs, ...Object.keys(files)]) {
        if (entry && entry.startsWith(prefix) && entry !== base) names.add(entry.slice(prefix.length).split('/')[0]);
      }
      return [...names];
    },
  });
}

const SETTINGS_MANIFEST = JSON.stringify({ colors: { blue: { icons: [{ name: 'settings' }] } } });
const SETTINGS_AND_CLOUD_MANIFEST = JSON.stringify({ colors: { blue: { icons: [{ name: 'settings' }, { name: 'cloud_queue' }] } } });

/** Per-vector-line tmp roots, keyed by the pytest case that recorded them. */
function perLine(roots: Record<number, Record<string, string>>): Adapter {
  return {
    args: (bound: unknown[], vector: Vector) => {
      useVirtualIconRoot(roots[vector.line] ?? null);
      return bound;
    },
    // Restore the real file system after every call that returns (a raising
    // call is restored by the next vector's ``args``; the last function run,
    // resolve_icon_svg_path, never raises).
    result: (actual: unknown) => {
      useVirtualIconRoot(null);
      return actual;
    },
  };
}

// test_require_icon_assets_available_fails_without_generated_svgs (line 1),
// test_require_icon_assets_available_accepts_manifest_and_svg (line 2).
const requireAvailableRoots = {
  1: { 'manifest.json': '{"colors": {}}' },
  2: { 'manifest.json': SETTINGS_MANIFEST, 'blue/settings.svg': '<svg />' },
};
// test_*_icon_conversion_fails_for_missing_svg_asset, test_add_icon_urls_fails_fast_*:
// an empty tmp root.
const emptyRoots = { 1: {}, 2: {}, 3: {} };

export default {
  icon_svg_count: perLine(requireAvailableRoots),
  require_icon_assets_available: perLine(requireAvailableRoots),
  // test_manifest_icon_names_are_loaded_from_tool_service_manifest
  icon_name_exists: perLine({ 1: { 'manifest.json': SETTINGS_AND_CLOUD_MANIFEST }, 2: { 'manifest.json': SETTINGS_AND_CLOUD_MANIFEST }, 3: { 'manifest.json': SETTINGS_AND_CLOUD_MANIFEST } }),
  require_icon_svg_path: perLine(emptyRoots),
  resolve_icon_svg_path: perLine(emptyRoots),
} satisfies Record<string, Adapter>;
