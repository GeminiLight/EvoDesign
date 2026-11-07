// WP27: runtime IO abstraction — src/py/{path,fs,bytes,zlib}.ts against Node.
import { mkdtempSync, realpathSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import nodePath from 'node:path';
import { inflateSync, gunzipSync } from 'node:zlib';
import { describe, expect, it } from 'vitest';
import {
  base64ToBytes, bytesToBase64, latin1Decode, latin1Encode, readUInt32BE, utf8Decode, utf8EncodeLossy,
} from '../../src/py/bytes.ts';
import { MemoryFS, getFS, setFS, type RuntimeFS } from '../../src/py/fs.ts';
import * as path from '../../src/py/path.ts';
import { deflate, gunzip, gzip, inflate } from '../../src/py/zlib.ts';
import { NodeFS } from '../../src/node/fs.ts';

const posix = nodePath.posix;

describe('py/path matches node:path posix', () => {
  const samples = [
    '', '.', '..', '/', '//', '///a', 'a', 'a/', 'a//b', '/a/b/', '/a/./b/../c', '../a/../../b', 'a/b/../../..',
    '/..', '/../a', './', '.a', 'a.', 'a.b.c', '.hidden.txt', '/x/y.tar.gz', 'dir/.', 'dir/..', 'a/b/c/', '/a//b//',
  ];
  it('join/normalize/dirname/basename/extname/isAbsolute', () => {
    for (const a of samples) {
      expect(path.normalize(a), a).toBe(posix.normalize(a));
      expect(path.dirname(a), a).toBe(posix.dirname(a));
      expect(path.basename(a), a).toBe(posix.basename(a));
      expect(path.basename(a, '.c'), a).toBe(posix.basename(a, '.c'));
      expect(path.extname(a), a).toBe(posix.extname(a));
      expect(path.isAbsolute(a), a).toBe(posix.isAbsolute(a));
      for (const b of samples) expect(path.join(a, b), `${a} + ${b}`).toBe(posix.join(a, b));
    }
  });
  it('resolve/relative (NodeFS cwd = process.cwd())', () => {
    for (const a of samples) {
      expect(path.resolve(a), a).toBe(posix.resolve(a));
      for (const b of samples) {
        expect(path.resolve(a, b), `${a} , ${b}`).toBe(posix.resolve(a, b));
        expect(path.relative(a, b), `${a} -> ${b}`).toBe(posix.relative(a, b));
      }
    }
  });
});

describe('bytes / zlib', () => {
  it('utf-8, latin1, base64 like Buffer', () => {
    for (const text of ['', 'abc', 'héllo wörld', '图表 🙂', '﻿bom', 'lone \ud800 surrogate']) {
      expect(Buffer.from(utf8EncodeLossy(text)).equals(Buffer.from(text, 'utf-8'))).toBe(true);
      expect(utf8Decode(Buffer.from(text, 'utf-8'))).toBe(Buffer.from(text, 'utf-8').toString('utf-8'));
      const bytes = Buffer.from(text, 'utf-8');
      expect(bytesToBase64(bytes)).toBe(bytes.toString('base64'));
      expect(Buffer.from(base64ToBytes(bytes.toString('base64'))).equals(bytes)).toBe(true);
      expect(latin1Decode(bytes)).toBe(bytes.toString('latin1'));
      expect(Buffer.from(latin1Encode(bytes.toString('latin1'))).equals(bytes)).toBe(true);
    }
    expect(readUInt32BE(Uint8Array.from([0xff, 0, 0, 1]), 0)).toBe(Buffer.from([0xff, 0, 0, 1]).readUInt32BE(0));
  });
  it('deflate/gzip are readable by node:zlib and round-trip', () => {
    const data = utf8EncodeLossy('evodesign '.repeat(500));
    expect(Buffer.from(inflateSync(deflate(data, 6))).equals(Buffer.from(data))).toBe(true);
    expect(Buffer.from(gunzipSync(gzip(data))).equals(Buffer.from(data))).toBe(true);
    expect(Buffer.from(inflate(deflate(data))).equals(Buffer.from(data))).toBe(true);
    expect(Buffer.from(gunzip(gzip(data))).equals(Buffer.from(data))).toBe(true);
  });
});

/** Run the same script against NodeFS (in a temp dir) and MemoryFS; compare observable results. */
function script(fs: RuntimeFS, root: string): unknown[] {
  const out: unknown[] = [];
  const attempt = (fn: () => unknown) => {
    try {
      out.push(['ok', fn()]);
    } catch (error) {
      const e = error as { code?: string; message: string; syscall?: string };
      out.push(['err', e.code, e.syscall, e.message.split(root).join('<ROOT>')]);
    }
  };
  const p = (rel: string) => `${root}/${rel}`;
  attempt(() => fs.exists(p('a')));
  attempt(() => fs.mkdirp(p('a/b/c')));
  attempt(() => fs.mkdirp(p('a/b/c')));
  attempt(() => fs.mkdirp(p('a/b'), { recursive: false }));
  attempt(() => fs.mkdirp(p('x/y'), { recursive: false }));
  attempt(() => fs.writeText(p('a/b/z.txt'), 'zed'));
  attempt(() => fs.writeText(p('a/b/ä.json'), '{"k": "中"}'));
  attempt(() => fs.writeBytes(p('a/b/bin'), Uint8Array.from([0, 255, 10])));
  attempt(() => fs.writeText(p('missing/f.txt'), 'x'));
  attempt(() => fs.writeText(p('a/b'), 'x'));
  attempt(() => fs.readText(p('a/b/z.txt')));
  attempt(() => fs.readText(p('a/b/ä.json')));
  attempt(() => [...fs.readBytes(p('a/b/bin'))]);
  attempt(() => fs.readText(p('a/b/nope.txt')));
  attempt(() => fs.readText(p('a/b')));
  attempt(() => fs.readText(p('a/b/z.txt/q')));
  attempt(() => fs.list(p('a/b')));
  attempt(() => fs.list(p('a/b/z.txt')));
  attempt(() => fs.list(p('none')));
  attempt(() => [fs.stat(p('a/b')).isDirectory(), fs.stat(p('a/b')).isFile()]);
  attempt(() => [fs.stat(p('a/b/z.txt')).isFile(), fs.stat(p('a/b/z.txt')).size]);
  attempt(() => fs.stat(p('a/none')));
  attempt(() => fs.copyFile(p('a/b/z.txt'), p('a/z2.txt')));
  attempt(() => fs.readText(p('a/z2.txt')));
  attempt(() => fs.copyFile(p('a/none'), p('a/z3.txt')));
  attempt(() => fs.realpath(p('a/b/../b/./z.txt')).split(root).join('<ROOT>'));
  attempt(() => fs.realpath(p('a/none')));
  attempt(() => fs.remove(p('a/none')));
  attempt(() => fs.remove(p('a/none'), { force: true }));
  attempt(() => fs.remove(p('a/b/z.txt')));
  attempt(() => fs.exists(p('a/b/z.txt')));
  attempt(() => fs.remove(p('a'), { recursive: true }));
  attempt(() => fs.exists(p('a')));
  attempt(() => fs.list(root));
  return out;
}

describe('MemoryFS behaves like NodeFS', () => {
  it('same results and error codes/messages for a scripted session', () => {
    const real = realpathSync(mkdtempSync(nodePath.join(tmpdir(), 'wp27-')));
    try {
      const expected = script(new NodeFS(), real);
      const memory = new MemoryFS();
      memory.mkdirp('/work/root');
      const actual = script(memory, '/work/root');
      expect(actual).toEqual(expected);
    } finally {
      rmSync(real, { recursive: true, force: true });
    }
  });

  it('deterministic temp dirs, relative paths against cwd, mounts are read-only', () => {
    const memory = new MemoryFS({ cwd: '/w', tmpdir: '/tmp' });
    expect(memory.mkdtemp('/tmp/run-')).toBe('/tmp/run-00000001');
    expect(memory.mkdtemp('/tmp/run-')).toBe('/tmp/run-00000002');
    memory.writeText('rel.txt', 'r');
    expect(memory.readText('/w/rel.txt')).toBe('r');
    memory.mount('/assets', {
      readText: (p) => `content of ${p}`,
      exists: (p) => p === 'dir/a.md' || p === 'dir',
      isDir: (p) => p === 'dir',
      list: (p) => (p === '' ? ['dir'] : p === 'dir' ? ['a.md'] : []),
    });
    expect(memory.exists('/assets/dir/a.md')).toBe(true);
    expect(memory.readText('/assets/dir/a.md')).toBe('content of dir/a.md');
    expect(memory.list('/assets/dir')).toEqual(['a.md']);
    expect(memory.stat('/assets/dir').isDirectory()).toBe(true);
    expect(() => memory.writeText('/assets/dir/new.md', 'x')).toThrow(/EROFS|ENOENT/);
  });

  it('setFS swaps the active file system for path.resolve and the helpers', () => {
    const before = getFS();
    const memory = new MemoryFS({ cwd: '/mem' });
    setFS(memory);
    try {
      expect(path.resolve('x')).toBe('/mem/x');
      expect(getFS()).toBe(memory);
    } finally {
      setFS(null);
    }
    expect(getFS().kind).toBe(before.kind);
  });
});
