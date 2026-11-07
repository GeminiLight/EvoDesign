import { createHash } from 'node:crypto';
import { existsSync } from 'node:fs';
import { join } from 'node:path';
import { inflateSync } from 'node:zlib';
import { PNG } from 'pngjs';
import type { Adapter } from '../parity/functions.test.ts';
import { FIXTURES } from '../harness/fixtures.ts';

// The recorded image paths point into the run's (deleted) temp output dir;
// every one of those files is kept as fixtures/runs/<run>/artifacts/<path>
// (PNG artifacts are stored byte-for-byte). Downscaled results are PNGs
// re-encoded by PIL; they are compared by decoded RGBA pixels (PHASE2_PLAN.md
// appendix C), so an identical-pixel TS result is mapped to the fixture value.
function artifactPath(path: string, source: string): string {
  const run = source.startsWith('run:') ? source.slice(4) : null;
  const at = path.indexOf('/out/');
  if (!run || at < 0) return path;
  const candidate = join(FIXTURES, 'runs', run, 'artifacts', path.slice(at + '/out/'.length));
  return existsSync(candidate) ? candidate : path;
}

function paeth(a: number, b: number, c: number): number {
  const p = a + b - c;
  const pa = Math.abs(p - a);
  const pb = Math.abs(p - b);
  const pc = Math.abs(p - c);
  return pa <= pb && pa <= pc ? a : pb <= pc ? b : c;
}

// Pixel identity key. Non-interlaced 8-bit PNGs (what both PIL and the TS
// port write) are unfiltered directly — pngjs's RGBA expansion of two
// ~3000px images per vector cost seconds of the synchronous test; anything
// else goes through pngjs. Same colour type + same unfiltered bytes ⇔ same
// pixels in the same mode.
function rgbaKey(dataUrl: unknown): string | null {
  if (typeof dataUrl !== 'string' || !dataUrl.startsWith('data:image/png;base64,')) return null;
  const bytes = Buffer.from(dataUrl.slice('data:image/png;base64,'.length), 'base64');
  const bands = ({ 0: 1, 2: 3, 4: 2, 6: 4 } as Record<number, number>)[bytes[25]];
  if (bytes[24] !== 8 || bytes[28] !== 0 || !bands) {
    const png = PNG.sync.read(bytes);
    return `rgba:${png.width}x${png.height}:${createHash('sha256').update(png.data).digest('hex')}`;
  }
  const width = bytes.readUInt32BE(16);
  const height = bytes.readUInt32BE(20);
  const idat: Buffer[] = [];
  for (let pos = 8; pos + 8 <= bytes.length;) {
    const length = bytes.readUInt32BE(pos);
    const type = bytes.toString('latin1', pos + 4, pos + 8);
    if (type === 'IDAT') idat.push(bytes.subarray(pos + 8, pos + 8 + length));
    if (type === 'IEND') break;
    pos += 12 + length;
  }
  const raw = inflateSync(Buffer.concat(idat));
  const stride = width * bands;
  const out = new Uint8Array(stride * height);
  for (let y = 0; y < height; y += 1) {
    const filter = raw[y * (stride + 1)];
    const src = y * (stride + 1) + 1;
    const row = y * stride;
    for (let i = 0; i < stride; i += 1) {
      const a = i >= bands ? out[row + i - bands] : 0;
      const b = y > 0 ? out[row - stride + i] : 0;
      const c = i >= bands && y > 0 ? out[row - stride + i - bands] : 0;
      const pred = filter === 0 ? 0 : filter === 1 ? a : filter === 2 ? b : filter === 3 ? (a + b) >> 1 : paeth(a, b, c);
      out[row + i] = (raw[src + i] + pred) & 255;
    }
  }
  return `ct${bytes[25]}:${width}x${height}:${createHash('sha256').update(out).digest('hex')}`;
}

export default {
  image_to_data_url: {
    args: (bound, vector) => [artifactPath(bound[0] as string, vector.source), ...bound.slice(1)],
    result: (actual, vector) => {
      if (actual === vector.result) return actual;
      const key = rgbaKey(actual);
      return key !== null && key === rgbaKey(vector.result) ? vector.result : actual;
    },
    // args_after holds the recorded temp path, not the remapped fixture path.
    checkMutation: false,
  },
} satisfies Record<string, Adapter>;
