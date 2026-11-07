// NodeFS: the RuntimeFS backed by the real disk (PHASE3_PLAN.md WP27).
// Node-only (``src/node/`` may import ``node:*``).

import {
  copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, realpathSync, rmSync, statSync, writeFileSync,
} from 'node:fs';
import { homedir, tmpdir } from 'node:os';
import type { RuntimeFS, RuntimeStat } from '../py/fs.ts';

function bytes(buffer: Buffer): Uint8Array {
  return new Uint8Array(buffer.buffer, buffer.byteOffset, buffer.byteLength);
}

export class NodeFS implements RuntimeFS {
  readonly kind = 'node' as const;
  readText(path: string): string { return readFileSync(path, 'utf-8'); }
  readBytes(path: string): Uint8Array { return bytes(readFileSync(path)); }
  writeText(path: string, text: string): void { writeFileSync(path, text, 'utf-8'); }
  writeBytes(path: string, data: Uint8Array): void { writeFileSync(path, data); }
  exists(path: string): boolean { return existsSync(path); }
  mkdirp(path: string, options: { recursive?: boolean; mode?: number } = { recursive: true }): void {
    mkdirSync(path, { recursive: options.recursive ?? false, ...(options.mode === undefined ? {} : { mode: options.mode }) });
  }
  list(path: string): string[] { return readdirSync(path); }
  remove(path: string, options: { recursive?: boolean; force?: boolean } = {}): void { rmSync(path, options); }
  stat(path: string): RuntimeStat { return statSync(path); }
  copyFile(source: string, dest: string): void { copyFileSync(source, dest); }
  realpath(path: string): string { return realpathSync(path); }
  mkdtemp(prefix: string): string { return mkdtempSync(prefix); }
  tmpdir(): string { return tmpdir(); }
  homedir(): string { return homedir(); }
  cwd(): string { return process.cwd(); }
}
