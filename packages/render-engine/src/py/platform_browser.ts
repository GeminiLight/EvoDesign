// Browser host platform (PHASE3_PLAN.md WP27), selected for ``#platform`` by the
// ``browser`` export condition. No ``node:*`` imports.
//
//   * file system: a fresh ``MemoryFS`` (cwd ``/workspace``, tmp ``/tmp``);
//   * repoRoot:    the pseudo path ``/evodesign`` (paths only, nothing is read
//                  from it unless the host mounts or seeds files there);
//   * assets:      none — the host installs a bundled provider (WP31,
//                  ``setAssetProvider``);
//   * context:     a single-threaded ``AsyncLocalStorage`` stand-in (see below);
//   * subprocess / in-process renderer: unavailable (WP28 installs a PngRenderer).

import { MemoryFS } from './fs.ts';
import type { AsyncContext, Platform } from './platform_types.ts';

/**
 * ``AsyncLocalStorage`` stand-in without async_hooks: ``run`` sets the store
 * for the synchronous part of ``fn`` and, when ``fn`` returns a promise, until
 * that promise settles. Correct for strictly nested runs (one pipeline at a
 * time in a Worker); overlapping concurrent runs on the same context would see
 * each other's store (see migration/notes/WP27.md).
 */
class BrowserAsyncContext<T> implements AsyncContext<T> {
  private store: T | undefined = undefined;

  run<R>(store: T, fn: () => R): R {
    const previous = this.store;
    this.store = store;
    let result: R;
    try {
      result = fn();
    } catch (error) {
      this.store = previous;
      throw error;
    }
    if (result && typeof (result as { then?: unknown }).then === 'function') {
      return (result as unknown as Promise<unknown>).finally(() => {
        this.store = previous;
      }) as unknown as R;
    }
    this.store = previous;
    return result;
  }

  getStore(): T | undefined {
    return this.store;
  }
}

export const platform: Platform = {
  name: 'browser',
  createDefaultFS: () => new MemoryFS(),
  repoRoot: '/evodesign',
  assetProvider: null,
  createAsyncContext: <T>() => new BrowserAsyncContext<T>(),
  spawn: null,
  renderExcalidrawPage: null,
};
