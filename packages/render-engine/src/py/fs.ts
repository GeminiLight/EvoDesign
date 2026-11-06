// Runtime file-system abstraction (PHASE3_PLAN.md WP27).
//
// Pipeline modules never import ``node:fs`` / ``node:os``; they go through the
// active ``RuntimeFS`` (``getFS()``), either directly or through the
// ``node:fs``-shaped helpers at the bottom of this file (``readFileSync`` …),
// which keep the call sites of the port line-for-line comparable with Python.
//
// Two implementations:
//   * ``NodeFS`` (``src/node/fs.ts``) — the default under Node: the real disk.
//   * ``MemoryFS`` (here)              — an in-memory tree with Node's POSIX path
//     semantics, Node-shaped errors (``ENOENT: no such file or directory, open
//     '<path>'``, ``code``/``errno``/``syscall``/``path``) and deterministic
//     temp directories (``/tmp/<prefix>000001`` …). It is the default in
//     browsers. Read-only providers can be mounted under a directory (e.g. the
//     bundled ``evodesign/agentic_system`` assets).
//
// The default FS comes from the ``#platform`` subpath import (package.json
// ``imports``): ``src/node/platform.ts`` under Node, ``src/py/platform_browser.ts``
// for bundlers using the ``browser`` condition. Swap it with ``setFS`` /
// ``withFS``.

import { platform } from '#platform';
import { utf8Decode, utf8EncodeLossy } from './bytes.ts';

export interface RuntimeStat {
  isFile(): boolean;
  isDirectory(): boolean;
  size: number;
  mtimeMs: number;
}

export interface RuntimeFS {
  readonly kind: 'node' | 'memory';
  readText(path: string): string;
  readBytes(path: string): Uint8Array;
  writeText(path: string, text: string): void;
  writeBytes(path: string, data: Uint8Array): void;
  exists(path: string): boolean;
  /** ``mkdir -p``; with ``recursive=false`` it fails like ``fs.mkdirSync`` (EEXIST / ENOENT). */
  mkdirp(path: string, options?: { recursive?: boolean; mode?: number }): void;
  /** Entry names directly inside ``path`` (``fs.readdirSync`` order: sorted by UTF-16 code unit for MemoryFS). */
  list(path: string): string[];
  /** ``fs.rmSync(path, { recursive, force })`` */
  remove(path: string, options?: { recursive?: boolean; force?: boolean }): void;
  /** ``fs.statSync`` (follows links); throws ENOENT when missing. */
  stat(path: string): RuntimeStat;
  copyFile(source: string, dest: string): void;
  /** ``fs.realpathSync`` (MemoryFS: normalized absolute path; throws ENOENT when missing). */
  realpath(path: string): string;
  /** ``fs.mkdtempSync(prefix)`` */
  mkdtemp(prefix: string): string;
  /** ``os.tmpdir()`` */
  tmpdir(): string;
  /** ``os.homedir()`` */
  homedir(): string;
  /** ``process.cwd()`` */
  cwd(): string;
}

/** A read-only tree mounted into a MemoryFS (paths relative to the mount point, ``/`` separated). */
export interface ReadOnlyProvider {
  readText(path: string): string;
  readBytes?(path: string): Uint8Array;
  exists(path: string): boolean;
  isDir(path: string): boolean;
  list(path: string): string[];
}

// ---------------------------------------------------------------- errors

const ERRNO: Record<string, [number, string]> = {
  ENOENT: [-2, 'no such file or directory'],
  EEXIST: [-17, 'file already exists'],
  EISDIR: [-21, 'illegal operation on a directory'],
  ENOTDIR: [-20, 'not a directory'],
  ENOTEMPTY: [-66, 'directory not empty'],
  EROFS: [-30, 'read-only file system'],
};

/** An error shaped like Node's ``SystemError`` from ``fs.*Sync``. */
export function fsError(code: keyof typeof ERRNO | string, syscall: string, path: string, dest?: string): Error {
  const [errno, text] = ERRNO[code] ?? [-1, code.toLowerCase()];
  const target = dest === undefined ? `'${path}'` : `'${path}' -> '${dest}'`;
  // Node reports read(2) failures (EISDIR on a directory) without the path.
  const message = syscall === 'read' ? `${code}: ${text}, ${syscall}` : `${code}: ${text}, ${syscall} ${target}`;
  const error = new Error(message) as Error & Record<string, unknown>;
  error.errno = errno;
  error.code = code;
  error.syscall = syscall;
  error.path = path;
  if (dest !== undefined) error.dest = dest;
  return error;
}

// ---------------------------------------------------------------- MemoryFS

interface MemFile { kind: 'file'; data: Uint8Array; mtimeMs: number }
interface MemDir { kind: 'dir'; entries: Map<string, MemNode>; mtimeMs: number }
type MemNode = MemFile | MemDir;

export interface MemoryFSOptions {
  /** ``process.cwd()`` stand-in (default ``/workspace``). */
  cwd?: string;
  /** ``os.tmpdir()`` stand-in (default ``/tmp``). */
  tmpdir?: string;
  /** ``os.homedir()`` stand-in (default ``/home/user``). */
  homedir?: string;
}

/** POSIX normalization of an absolute path (``.``/``..``/repeated ``/`` removed). */
function normalizeAbsolute(path: string): string[] {
  const parts: string[] = [];
  for (const part of path.split('/')) {
    if (!part || part === '.') continue;
    if (part === '..') parts.pop();
    else parts.push(part);
  }
  return parts;
}

function codeUnitCompare(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

export class MemoryFS implements RuntimeFS {
  readonly kind = 'memory' as const;
  private readonly root: MemDir = { kind: 'dir', entries: new Map(), mtimeMs: 0 };
  private readonly mounts: { parts: string[]; provider: ReadOnlyProvider }[] = [];
  private readonly _cwd: string;
  private readonly _tmpdir: string;
  private readonly _homedir: string;
  private tick = 0;
  private tempCounter = 0;
  /** Absolute paths that were looked up but did not exist (debugging aid). */
  readonly misses: Set<string> = new Set<string>();

  constructor(options: MemoryFSOptions = {}) {
    this._cwd = options.cwd ?? '/workspace';
    this._tmpdir = options.tmpdir ?? '/tmp';
    this._homedir = options.homedir ?? '/home/user';
    this.mkdirp(this._cwd);
    this.mkdirp(this._tmpdir);
    this.mkdirp(this._homedir);
  }

  cwd(): string { return this._cwd; }
  tmpdir(): string { return this._tmpdir; }
  homedir(): string { return this._homedir; }

  /** Mount a read-only provider at ``dir`` (absolute). Mounted paths cannot be written. */
  mount(dir: string, provider: ReadOnlyProvider): void {
    this.mounts.push({ parts: this.parts(dir), provider });
    this.mounts.sort((a, b) => b.parts.length - a.parts.length);
  }

  /** Seed files (absolute path → text or bytes), creating parent directories. */
  seed(files: Record<string, string | Uint8Array>): void {
    for (const [path, data] of Object.entries(files)) {
      this.mkdirp(parentOf(this.abs(path)));
      if (typeof data === 'string') this.writeText(path, data);
      else this.writeBytes(path, data);
    }
  }

  private abs(path: string): string {
    if (typeof path !== 'string') throw new TypeError(`The "path" argument must be of type string. Received ${typeof path}`);
    return path.startsWith('/') ? path : `${this._cwd}/${path}`;
  }

  private parts(path: string): string[] {
    return normalizeAbsolute(this.abs(path));
  }

  private mountFor(parts: string[]): { provider: ReadOnlyProvider; rel: string } | null {
    for (const mount of this.mounts) {
      if (mount.parts.length <= parts.length && mount.parts.every((p, i) => parts[i] === p)) {
        return { provider: mount.provider, rel: parts.slice(mount.parts.length).join('/') };
      }
    }
    return null;
  }

  /** The node at ``parts`` (memory tree only), or an error code. */
  private lookup(parts: string[]): MemNode | 'ENOENT' | 'ENOTDIR' {
    let node: MemNode = this.root;
    for (const part of parts) {
      if (node.kind !== 'dir') return 'ENOTDIR';
      const next = node.entries.get(part);
      if (!next) return 'ENOENT';
      node = next;
    }
    return node;
  }

  /** ``{kind}`` of the entry at ``path`` across memory tree and mounts, or null. */
  private entryKind(path: string): 'file' | 'dir' | null {
    const parts = this.parts(path);
    const node = this.lookup(parts);
    if (typeof node !== 'string') return node.kind;
    const mount = this.mountFor(parts);
    if (mount) {
      if (mount.rel === '' || mount.provider.isDir(mount.rel)) return 'dir';
      if (mount.provider.exists(mount.rel)) return 'file';
    }
    return null;
  }

  private parentDir(path: string, syscall: string): { dir: MemDir; name: string } {
    const parts = this.parts(path);
    if (!parts.length) throw fsError('EISDIR', syscall, path);
    const parent = this.lookup(parts.slice(0, -1));
    if (parent === 'ENOENT' || parent === 'ENOTDIR') {
      if (this.mountFor(parts)) throw fsError('EROFS', syscall, path);
      throw fsError(parent, syscall, path);
    }
    if (parent.kind !== 'dir') throw fsError('ENOTDIR', syscall, path);
    return { dir: parent, name: parts[parts.length - 1] };
  }

  readBytes(path: string): Uint8Array {
    const parts = this.parts(path);
    const node = this.lookup(parts);
    if (typeof node !== 'string') {
      if (node.kind === 'dir') throw fsError('EISDIR', 'read', path);
      return node.data.slice();
    }
    const mount = this.mountFor(parts);
    if (mount && mount.rel && mount.provider.exists(mount.rel) && !mount.provider.isDir(mount.rel)) {
      return mount.provider.readBytes ? mount.provider.readBytes(mount.rel) : utf8EncodeLossy(mount.provider.readText(mount.rel));
    }
    if (mount && (mount.rel === '' || mount.provider.isDir(mount.rel))) throw fsError('EISDIR', 'read', path);
    this.misses.add(this.abs(path));
    throw fsError(node === 'ENOTDIR' ? 'ENOTDIR' : 'ENOENT', 'open', path);
  }

  readText(path: string): string {
    const parts = this.parts(path);
    if (typeof this.lookup(parts) === 'string') {
      const mount = this.mountFor(parts);
      if (mount && mount.rel && mount.provider.exists(mount.rel) && !mount.provider.isDir(mount.rel)) return mount.provider.readText(mount.rel);
    }
    return utf8Decode(this.readBytes(path));
  }

  writeBytes(path: string, data: Uint8Array): void {
    const { dir, name } = this.parentDir(path, 'open');
    const existing = dir.entries.get(name);
    if (existing?.kind === 'dir') throw fsError('EISDIR', 'open', path);
    const mtimeMs = ++this.tick;
    dir.entries.set(name, { kind: 'file', data: Uint8Array.from(data), mtimeMs });
    dir.mtimeMs = mtimeMs;
  }

  writeText(path: string, text: string): void {
    this.writeBytes(path, utf8EncodeLossy(text));
  }

  exists(path: string): boolean {
    const found = this.entryKind(path) !== null;
    if (!found) this.misses.add(this.abs(path));
    return found;
  }

  mkdirp(path: string, options: { recursive?: boolean; mode?: number } = { recursive: true }): void {
    const parts = this.parts(path);
    const recursive = options.recursive ?? false;
    if (!recursive) {
      if (this.entryKind(path) !== null) throw fsError('EEXIST', 'mkdir', path);
      const { dir, name } = this.parentDir(path, 'mkdir');
      dir.entries.set(name, { kind: 'dir', entries: new Map(), mtimeMs: ++this.tick });
      return;
    }
    let node: MemDir = this.root;
    for (let i = 0; i < parts.length; i += 1) {
      const next = node.entries.get(parts[i]);
      if (next?.kind === 'dir') {
        node = next;
        continue;
      }
      if (next) throw fsError(i === parts.length - 1 ? 'EEXIST' : 'ENOTDIR', 'mkdir', path);
      const mount = this.mountFor(parts.slice(0, i + 1));
      if (mount && (mount.rel === '' || mount.provider.isDir(mount.rel))) {
        // A mounted directory: materialize it so writes below it are possible.
      } else if (mount && mount.provider.exists(mount.rel)) {
        throw fsError(i === parts.length - 1 ? 'EEXIST' : 'ENOTDIR', 'mkdir', path);
      }
      const created: MemDir = { kind: 'dir', entries: new Map(), mtimeMs: ++this.tick };
      node.entries.set(parts[i], created);
      node = created;
    }
  }

  list(path: string): string[] {
    const parts = this.parts(path);
    const node = this.lookup(parts);
    const names = new Set<string>();
    let found = false;
    if (typeof node !== 'string') {
      if (node.kind !== 'dir') throw fsError('ENOTDIR', 'scandir', path);
      found = true;
      for (const name of node.entries.keys()) names.add(name);
    }
    const mount = this.mountFor(parts);
    if (mount && (mount.rel === '' || mount.provider.isDir(mount.rel))) {
      found = true;
      for (const name of mount.provider.list(mount.rel)) names.add(name);
    }
    if (!found) {
      this.misses.add(this.abs(path));
      throw fsError(node === 'ENOTDIR' ? 'ENOTDIR' : 'ENOENT', 'scandir', path);
    }
    return [...names].sort(codeUnitCompare);
  }

  remove(path: string, options: { recursive?: boolean; force?: boolean } = {}): void {
    const parts = this.parts(path);
    const node = this.lookup(parts);
    if (typeof node === 'string') {
      if (this.mountFor(parts) && this.entryKind(path) !== null) throw fsError('EROFS', 'rm', path);
      if (options.force) return;
      throw fsError('ENOENT', 'lstat', path);
    }
    if (node.kind === 'dir' && !options.recursive) {
      const error = fsError('ERR_FS_EISDIR', 'rm', path);
      error.message = `Path is a directory: rm returned EISDIR (is a directory) ${this.abs(path)}`;
      throw error;
    }
    if (!parts.length) throw fsError('EROFS', 'rm', path);
    const parent = this.lookup(parts.slice(0, -1)) as MemDir;
    parent.entries.delete(parts[parts.length - 1]);
    parent.mtimeMs = ++this.tick;
  }

  stat(path: string): RuntimeStat {
    const parts = this.parts(path);
    const node = this.lookup(parts);
    if (typeof node !== 'string') {
      const size = node.kind === 'file' ? node.data.length : 64;
      return { isFile: () => node.kind === 'file', isDirectory: () => node.kind === 'dir', size, mtimeMs: node.mtimeMs };
    }
    const kind = this.entryKind(path);
    if (kind === 'dir') return { isFile: () => false, isDirectory: () => true, size: 64, mtimeMs: 0 };
    if (kind === 'file') {
      const size = this.readBytes(path).length;
      return { isFile: () => true, isDirectory: () => false, size, mtimeMs: 0 };
    }
    this.misses.add(this.abs(path));
    throw fsError(node === 'ENOTDIR' ? 'ENOTDIR' : 'ENOENT', 'stat', path);
  }

  copyFile(source: string, dest: string): void {
    let data: Uint8Array;
    try {
      data = this.readBytes(source);
    } catch (error) {
      const code = (error as { code?: string }).code ?? 'ENOENT';
      throw fsError(code, 'copyfile', source, dest);
    }
    try {
      this.writeBytes(dest, data);
    } catch (error) {
      const code = (error as { code?: string }).code ?? 'ENOENT';
      throw fsError(code, 'copyfile', source, dest);
    }
  }

  realpath(path: string): string {
    if (this.entryKind(path) === null) {
      this.misses.add(this.abs(path));
      throw fsError('ENOENT', 'lstat', path);
    }
    return `/${this.parts(path).join('/')}`;
  }

  mkdtemp(prefix: string): string {
    for (;;) {
      this.tempCounter += 1;
      const candidate = `${prefix}${String(this.tempCounter).padStart(8, '0')}`;
      if (this.entryKind(candidate) !== null) continue;
      this.mkdirp(candidate, { recursive: false });
      return candidate;
    }
  }

  /** Every file in the memory tree under ``dir`` (absolute paths, sorted). Mounts excluded. */
  files(dir = '/'): string[] {
    const out: string[] = [];
    const start = this.lookup(this.parts(dir));
    if (typeof start === 'string') return out;
    const walk = (node: MemNode, path: string) => {
      if (node.kind === 'file') out.push(path || '/');
      else for (const [name, child] of node.entries) walk(child, `${path}/${name}`);
    };
    const base = `/${this.parts(dir).join('/')}`;
    walk(start, base === '/' ? '' : base);
    return out.sort(codeUnitCompare);
  }
}

function parentOf(path: string): string {
  const index = path.lastIndexOf('/');
  return index <= 0 ? '/' : path.slice(0, index);
}

// ---------------------------------------------------------------- active FS

let current: RuntimeFS | null = null;

/** The active file system (created lazily from the platform default). */
export function getFS(): RuntimeFS {
  if (current === null) current = platform.createDefaultFS();
  return current;
}

/** Replace the active file system; ``null`` restores the platform default. */
export function setFS(next: RuntimeFS | null): void {
  current = next;
}

/** Run ``body`` with ``fs`` active and restore the previous FS afterwards (also for promises). */
export function withFS<T>(fs: RuntimeFS, body: () => T): T {
  const previous = current;
  current = fs;
  let result: T;
  try {
    result = body();
  } catch (error) {
    current = previous;
    throw error;
  }
  if (result && typeof (result as { then?: unknown }).then === 'function') {
    return (result as unknown as Promise<unknown>).finally(() => {
      current = previous;
    }) as unknown as T;
  }
  current = previous;
  return result;
}

// ---------------------------------------------------------------- node:fs-shaped helpers

type Encoding = 'utf-8' | 'utf8';

/** ``fs.readFileSync(path, 'utf-8')`` → string; without encoding → bytes. */
export function readFileSync(path: string, encoding: Encoding): string;
export function readFileSync(path: string): Uint8Array;
export function readFileSync(path: string, encoding?: Encoding): string | Uint8Array {
  return encoding ? getFS().readText(path) : getFS().readBytes(path);
}

export function writeFileSync(path: string, data: string | Uint8Array, _encoding?: Encoding): void {
  if (typeof data === 'string') getFS().writeText(path, data);
  else getFS().writeBytes(path, data);
}

export function existsSync(path: string): boolean {
  return getFS().exists(path);
}

export function mkdirSync(path: string, options: { recursive?: boolean; mode?: number } = {}): void {
  getFS().mkdirp(path, { recursive: options.recursive ?? false, mode: options.mode });
}

export function statSync(path: string): RuntimeStat {
  return getFS().stat(path);
}

export function copyFileSync(source: string, dest: string): void {
  getFS().copyFile(source, dest);
}

export function rmSync(path: string, options: { recursive?: boolean; force?: boolean } = {}): void {
  getFS().remove(path, options);
}

export function readdirSync(path: string): string[] {
  return getFS().list(path);
}

export function realpathSync(path: string): string {
  return getFS().realpath(path);
}

export function mkdtempSync(prefix: string): string {
  return getFS().mkdtemp(prefix);
}

/** ``os.tmpdir()`` of the active FS. */
export function tmpdir(): string {
  return getFS().tmpdir();
}

/** ``os.homedir()`` of the active FS. */
export function homedir(): string {
  return getFS().homedir();
}

/** ``process.cwd()`` of the active FS. */
export function cwd(): string {
  return getFS().cwd();
}
