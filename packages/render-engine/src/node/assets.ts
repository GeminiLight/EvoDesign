// Node asset provider: reads ``evodesign/agentic_system`` from this checkout
// (PHASE3_PLAN.md WP27; moved here from src/py/assets.ts).

import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import type { AssetProvider } from '../py/platform_types.ts';

export function nodeAssetProvider(root: string): AssetProvider {
  return {
    readText: (path) => readFileSync(join(root, path), 'utf-8'),
    exists: (path) => existsSync(join(root, path)),
    isDir: (path) => {
      const full = join(root, path);
      return existsSync(full) && statSync(full).isDirectory();
    },
    list: (path) => readdirSync(join(root, path)),
  };
}
