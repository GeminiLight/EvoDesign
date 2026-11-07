// Node host platform (PHASE3_PLAN.md WP27): ``#platform`` resolves here unless
// the bundler uses the ``browser`` condition.

import { AsyncLocalStorage } from 'node:async_hooks';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import type { Platform } from '../py/platform_types.ts';
import { nodeAssetProvider } from './assets.ts';
import { renderExcalidrawPage } from './excalidraw_page.ts';
import { NodeFS } from './fs.ts';
import { spawnProcess } from './spawn.ts';

/** This checkout's root (src/node → src → render-engine → packages → repo). */
const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..', '..', '..');

export const platform: Platform = {
  name: 'node',
  createDefaultFS: () => new NodeFS(),
  repoRoot: REPO_ROOT,
  assetProvider: nodeAssetProvider(join(REPO_ROOT, 'evodesign', 'agentic_system')),
  createAsyncContext: <T>() => new AsyncLocalStorage<T>(),
  spawn: spawnProcess,
  renderExcalidrawPage,
};
