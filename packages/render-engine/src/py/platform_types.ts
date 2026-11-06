// Host platform contract (PHASE3_PLAN.md WP27).
//
// Everything the pipeline needs from its host that is not plain ECMAScript:
// the default file system, the repository root (Python's ``Path(__file__)``
// anchors), the read-only ``evodesign/agentic_system`` assets, a
// ``contextvars.ContextVar`` stand-in, subprocesses and the in-process
// Excalidraw renderer. ``src/node/platform.ts`` implements it for Node and
// ``src/py/platform_browser.ts`` for browsers; ``#platform`` (package.json
// ``imports``) picks one by the ``browser`` export condition.

import type { RuntimeFS } from './fs.ts';

/** ``AsyncLocalStorage``-shaped context (``contextvars.ContextVar``). */
export interface AsyncContext<T> {
  run<R>(store: T, fn: () => R): R;
  getStore(): T | undefined;
}

/** Read-only view of ``evodesign/agentic_system`` (paths relative to it, ``/`` separated). */
export interface AssetProvider {
  readText(path: string): string;
  exists(path: string): boolean;
  isDir(path: string): boolean;
  /** Entries (file and directory names) directly inside ``path``. */
  list(path: string): string[];
}

/** ``subprocess.run`` result (stdout/stderr captured). */
export interface SpawnResult {
  returncode: number;
  stdout: Uint8Array;
  stderr: Uint8Array;
  /** True when the process was killed after ``timeoutSeconds``. */
  timedOut: boolean;
}

export interface SpawnOptions {
  input: Uint8Array;
  cwd: string;
  timeoutSeconds: number;
}

/** Options of the in-process ``render-excalidraw.ts`` (see ``canvas_render._cli_render``). */
export interface ExcalidrawPageOptions {
  url: string;
  viewportWidth: number;
  viewportHeight: number;
  timeoutMs: number;
  exportScale: number;
  margin: number;
}

/** Renders a scene through the Excalidraw renderer page; returns PNG bytes. */
export type ExcalidrawPageRenderer = (
  options: ExcalidrawPageOptions,
  scene: unknown,
  normalizeScene: (scene: unknown) => Record<string, unknown>,
  stderr: string[],
) => Promise<Uint8Array>;

export interface Platform {
  readonly name: 'node' | 'browser';
  /** The file system ``getFS()`` returns until ``setFS`` is called. */
  createDefaultFS(): RuntimeFS;
  /** Absolute path of the EvoDesign checkout (Python ``Path(__file__).parents[...]`` anchors). */
  readonly repoRoot: string;
  /** Provider for ``evodesign/agentic_system`` assets; null when the host must install one. */
  readonly assetProvider: AssetProvider | null;
  createAsyncContext<T>(): AsyncContext<T>;
  /** ``subprocess.run(cmd, input=…, cwd=…, timeout=…)``; null when the host cannot spawn. */
  readonly spawn: ((cmd: string[], options: SpawnOptions) => Promise<SpawnResult>) | null;
  /** The in-process Excalidraw renderer (playwright under Node); null when unavailable. */
  readonly renderExcalidrawPage: ExcalidrawPageRenderer | null;
}
