// Active host platform (PHASE3_PLAN.md WP27): ``#platform`` resolves to the Node
// implementation (``src/node/platform.ts``) or, under the ``browser`` export
// condition, to ``src/py/platform_browser.ts``. Hosts can override single
// capabilities with ``setPlatform`` (e.g. a browser renderer, a bundled asset
// provider).

import { platform as hostPlatform } from '#platform';
import type { Platform } from './platform_types.ts';

export type { AssetProvider, AsyncContext, ExcalidrawPageOptions, ExcalidrawPageRenderer, Platform, SpawnOptions, SpawnResult } from './platform_types.ts';

let active: Platform = hostPlatform;

export function getPlatform(): Platform {
  return active;
}

/** Override parts of the host platform; ``null`` restores the default. */
export function setPlatform(overrides: Partial<Platform> | null): void {
  active = overrides === null ? hostPlatform : { ...active, ...overrides };
}
