// Ported from evodesign/utils/io_utils.py — keep in sync.
// server-only
//
// Generic file I/O utilities. No domain-specific dependencies.
//
// ``image_to_data_url(max_edge=...)`` reproduces Pillow 13's
// ``Image.thumbnail(size, LANCZOS)`` (reducing_gap=2.0): the aspect-ratio
// rounding of ``thumbnail``, ``Image.reduce`` when the image is at least 4x
// too large, and the two-pass fixed-point resampler of libImaging/Resample.c
// (RGBA goes through premultiplied RGBa like ``Image.resize``). The PNG bytes
// differ from PIL's encoder; the decoded pixels are what the critic sees and
// what the cassette compares (PHASE2_PLAN.md appendix C).
import { withPyFloats } from '../py/float_marks.ts';
import { decode as decodePng } from 'fast-png';
import { bytesToBase64, concatBytes, latin1Decode, readUInt32BE, writeUInt32BE } from '../py/bytes.ts';
import { copyFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from '../py/fs.ts';
import { dirname, extname } from '../py/path.ts';
import { deflate, inflate } from '../py/zlib.ts';
import { ValueError } from '../py/errors.ts';
import { pyJsonDumps } from '../py/json.ts';
import { pyJsonLoadsExact } from '../py/json_decoder.ts';

/** Create directories (mkdir -p). */
export function ensure_dirs(...dirs: string[]): void {
  for (const d of dirs) {
    mkdirSync(d, { recursive: true });
  }
}

/** Save data as JSON. Returns the path written. */
export function save_json(data: unknown, path: string): string {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, pyJsonDumps(withPyFloats(data), { indent: 4, ensureAscii: false }), 'utf-8');
  return path;
}

/** Load JSON from file. */
export function load_json(path: string): unknown {
  return pyJsonLoadsExact(readFileSync(path, 'utf-8'));
}

/** Copy a file from source to dest. Returns dest path. */
export function copy_file(source: string, dest: string): string {
  if (!existsSync(source)) {
    throw new FileNotFoundError(`Source file not found: ${source}`);
  }
  mkdirSync(dirname(dest), { recursive: true });
  copyFileSync(source, dest);
  return dest;
}

export class FileNotFoundError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'FileNotFoundError';
  }
}

// ``mimetypes.guess_type`` for the extensions the pipeline produces.
const MIME_TYPES: Record<string, string> = {
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.jpe': 'image/jpeg',
  '.gif': 'image/gif',
  '.webp': 'image/webp',
  '.svg': 'image/svg+xml',
  '.bmp': 'image/bmp',
  '.tif': 'image/tiff',
  '.tiff': 'image/tiff',
  '.ico': 'image/vnd.microsoft.icon',
  '.json': 'application/json',
  '.txt': 'text/plain',
  '.html': 'text/html',
  '.pdf': 'application/pdf',
};

function guess_type(path: string): string | null {
  return MIME_TYPES[extname(path).toLowerCase()] ?? null;
}

/**
 * Encode an image, optionally bounding review input without changing the file.
 *
 * Geometry-sensitive refiner inputs must use the default (original pixels).
 * The critic uses a bounded, lossless PNG instead of a 4x product export.
 */
export function image_to_data_url(image_path: string, max_edge: number | null = null): string {
  if (max_edge !== null && max_edge !== undefined) {
    if (max_edge < 1) {
      throw new ValueError('max_edge must be positive');
    }
    const image = openImage(image_path);
    if (Math.max(image.width, image.height) > max_edge) {
      const thumb = thumbnail(image, [max_edge, max_edge]);
      return 'data:image/png;base64,' + bytesToBase64(encodePng(thumb));
    }
  }
  let mime_type = guess_type(image_path);
  if (mime_type === null) {
    mime_type = 'application/octet-stream';
  }
  const b64 = bytesToBase64(readFileSync(image_path));
  return `data:${mime_type};base64,${b64}`;
}

// ── Pillow emulation ──────────────────────────────────────────────────────

type Mode = 'L' | 'LA' | 'RGB' | 'RGBA';

/** An 8-bit image: ``bands`` channel planes interleaved, row-major. */
interface Raster {
  mode: Mode;
  width: number;
  height: number;
  bands: number;
  data: Uint8Array; // width * height * bands
}

const BANDS: Record<Mode, number> = { L: 1, LA: 2, RGB: 3, RGBA: 4 };

/** ``Image.open`` + ``load()`` for PNG files (the only format the pipeline renders). */
function openImage(path: string): Raster {
  const bytes = readFileSync(path);
  const signature = '89504e470d0a1a0a';
  if (Array.from(bytes.subarray(0, 8), (b) => b.toString(16).padStart(2, '0')).join('') !== signature) {
    throw new OSError(`cannot identify image file '${path}'`);
  }
  const bitDepth = bytes[24];
  const colorType = bytes[25];
  const modes: Record<number, Mode> = { 0: 'L', 2: 'RGB', 4: 'LA', 6: 'RGBA' };
  const mode = modes[colorType];
  if (!mode || bitDepth !== 8) {
    // Palette / 1-bit / 16-bit PNGs take other Pillow code paths (NEAREST for
    // "P", mode conversions for 16-bit) that the renderer never produces.
    throw new NotImplementedImageError(`image_to_data_url: unsupported PNG (color type ${colorType}, bit depth ${bitDepth}) in ${path}`);
  }
  const bands = BANDS[mode];
  if (bytes[28] === 0) {
    const width = readUInt32BE(bytes, 16);
    const height = readUInt32BE(bytes, 20);
    return { mode, width, height, bands, data: decodeNonInterlaced8(bytes, width, height, bands) };
  }
  // Adam7-interlaced: let fast-png de-interlace (rare; Pillow decodes to the same pixels).
  // 8-bit gray / gray+alpha / RGB / RGBA decode to exactly ``bands`` interleaved channels.
  const png = decodePng(bytes);
  return { mode, width: png.width, height: png.height, bands, data: Uint8Array.from(png.data as Uint8Array) };
}

function paeth(a: number, b: number, c: number): number {
  const p = a + b - c;
  const pa = Math.abs(p - a);
  const pb = Math.abs(p - b);
  const pc = Math.abs(p - c);
  return pa <= pb && pa <= pc ? a : pb <= pc ? b : c;
}

/**
 * Decode the IDAT stream of a non-interlaced 8-bit PNG straight into
 * ``bands`` interleaved channels (a generic decoder would expand to RGBA first, which
 * dominated the run time on 4x exports).
 */
function decodeNonInterlaced8(bytes: Uint8Array, width: number, height: number, bands: number): Uint8Array {
  const idat: Uint8Array[] = [];
  for (let pos = 8; pos + 8 <= bytes.length;) {
    const length = readUInt32BE(bytes, pos);
    const type = latin1Decode(bytes, pos + 4, pos + 8);
    if (type === 'IDAT') idat.push(bytes.subarray(pos + 8, pos + 8 + length));
    if (type === 'IEND') break;
    pos += 12 + length;
  }
  const raw = inflate(concatBytes(idat));
  const stride = width * bands;
  if (raw.length < (stride + 1) * height) throw new OSError('image file is truncated');
  const out = new Uint8Array(stride * height);
  // The row above the first row is all zeros (PNG spec).
  const zeros = new Uint8Array(stride);
  for (let y = 0; y < height; y += 1) {
    const filter = raw[y * (stride + 1)];
    const src = raw.subarray(y * (stride + 1) + 1, (y + 1) * (stride + 1));
    const cur = out.subarray(y * stride, (y + 1) * stride);
    const up = y > 0 ? out.subarray((y - 1) * stride, y * stride) : zeros;
    const first = Math.min(bands, stride);
    switch (filter) {
      case 0:
        cur.set(src);
        break;
      case 1:
        for (let i = 0; i < first; i += 1) cur[i] = src[i];
        for (let i = bands; i < stride; i += 1) cur[i] = (src[i] + cur[i - bands]) & 255;
        break;
      case 2:
        for (let i = 0; i < stride; i += 1) cur[i] = (src[i] + up[i]) & 255;
        break;
      case 3:
        for (let i = 0; i < first; i += 1) cur[i] = (src[i] + (up[i] >> 1)) & 255;
        for (let i = bands; i < stride; i += 1) cur[i] = (src[i] + ((cur[i - bands] + up[i]) >> 1)) & 255;
        break;
      case 4:
        for (let i = 0; i < first; i += 1) cur[i] = (src[i] + up[i]) & 255; // paeth(0, b, 0) = b
        for (let i = bands; i < stride; i += 1) cur[i] = (src[i] + paeth(cur[i - bands], up[i], up[i - bands])) & 255;
        break;
      default:
        throw new OSError(`unknown PNG filter type ${filter}`);
    }
  }
  return out;
}

class OSError extends Error {
  override name = 'OSError';
}

class NotImplementedImageError extends Error {
  override name = 'NotImplementedError';
}

const CRC_TABLE = (() => {
  const table = new Int32Array(256);
  for (let n = 0; n < 256; n += 1) {
    let c = n;
    for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c;
  }
  return table;
})();

function pngChunk(type: string, body: Uint8Array): Uint8Array {
  const chunk = new Uint8Array(12 + body.length);
  writeUInt32BE(chunk, body.length, 0);
  for (let i = 0; i < 4; i += 1) chunk[4 + i] = type.charCodeAt(i) & 0xff;
  chunk.set(body, 8);
  let crc = -1;
  for (let i = 4; i < 8 + body.length; i += 1) crc = CRC_TABLE[(crc ^ chunk[i]) & 255] ^ (crc >>> 8);
  writeUInt32BE(chunk, (crc ^ -1) >>> 0, 8 + body.length);
  return chunk;
}

/**
 * ``image.save(buffer, format="PNG")``: 8-bit, non-interlaced, zlib level 6
 * (Pillow's default ``compress_level``), adaptive per-row filter (minimum sum
 * of absolute differences). The bytes differ from Pillow's encoder; the
 * pixels are identical (PHASE2_PLAN.md appendix C).
 */
function encodePng(image: Raster): Uint8Array {
  const { width, height, bands, data } = image;
  const stride = width * bands;
  const raw = new Uint8Array((stride + 1) * height);
  // Row above the first row is all zeros (PNG spec).
  const zeros = new Uint8Array(stride);
  for (let y = 0; y < height; y += 1) {
    const cur = data.subarray(y * stride, (y + 1) * stride);
    const up = y > 0 ? data.subarray((y - 1) * stride, y * stride) : zeros;
    const sums = [0, 0, 0, 0, 0];
    let s0 = 0, s1 = 0, s2 = 0, s3 = 0, s4 = 0;
    for (let i = 0; i < stride; i += 1) {
      const x = cur[i];
      const a = i >= bands ? cur[i - bands] : 0;
      const b = up[i];
      const c = i >= bands ? up[i - bands] : 0;
      let v = x;
      s0 += v < 128 ? v : 256 - v;
      v = (x - a) & 255;
      s1 += v < 128 ? v : 256 - v;
      v = (x - b) & 255;
      s2 += v < 128 ? v : 256 - v;
      v = (x - ((a + b) >> 1)) & 255;
      s3 += v < 128 ? v : 256 - v;
      v = (x - paeth(a, b, c)) & 255;
      s4 += v < 128 ? v : 256 - v;
    }
    sums[0] = s0; sums[1] = s1; sums[2] = s2; sums[3] = s3; sums[4] = s4;
    let best = 0;
    for (let f = 1; f < 5; f += 1) if (sums[f] < sums[best]) best = f;
    const o = y * (stride + 1);
    raw[o] = best;
    for (let i = 0; i < stride; i += 1) {
      const x = cur[i];
      const a = i >= bands ? cur[i - bands] : 0;
      const b = up[i];
      let v: number;
      if (best === 0) v = x;
      else if (best === 1) v = x - a;
      else if (best === 2) v = x - b;
      else if (best === 3) v = x - ((a + b) >> 1);
      else v = x - paeth(a, b, i >= bands ? up[i - bands] : 0);
      raw[o + 1 + i] = v & 255;
    }
  }
  const header = new Uint8Array(13);
  writeUInt32BE(header, width, 0);
  writeUInt32BE(header, height, 4);
  header[8] = 8;
  header[9] = { L: 0, LA: 4, RGB: 2, RGBA: 6 }[image.mode];
  return concatBytes([
    Uint8Array.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    pngChunk('IHDR', header),
    pngChunk('IDAT', deflate(raw, 6)),
    pngChunk('IEND', new Uint8Array(0)),
  ]);
}

/** ``Image.thumbnail(size, Resampling.LANCZOS)`` (reducing_gap=2.0); returns the new image. */
function thumbnail(image: Raster, size: [number, number]): Raster {
  const provided = [Math.floor(size[0]), Math.floor(size[1])] as const;
  const roundAspect = (number: number, key: (n: number) => number): number => {
    const lo = Math.floor(number);
    const hi = Math.ceil(number);
    // min(floor, ceil, key=key): the first one wins a tie.
    return Math.max(key(hi) < key(lo) ? hi : lo, 1);
  };
  let [x, y] = provided;
  if (x >= image.width && y >= image.height) return image;
  const aspect = image.width / image.height;
  if (x / y >= aspect) {
    const yy = y;
    x = roundAspect(y * aspect, (n) => Math.abs(aspect - n / yy));
  } else {
    const xx = x;
    y = roundAspect(x / aspect, (n) => (n === 0 ? 0 : Math.abs(aspect - xx / n)));
  }
  if (image.width === x && image.height === y) return image;
  return resize(image, [x, y], 2.0);
}

const LANCZOS_SUPPORT = 3.0;

/** ``Image.resize(size, LANCZOS, box=None, reducing_gap)`` */
function resize(image: Raster, size: [number, number], reducing_gap: number): Raster {
  if (image.mode === 'RGBA' || image.mode === 'LA') {
    const premultiplied = premultiply(image);
    const resized = resize({ ...premultiplied, mode: image.mode === 'RGBA' ? 'RGB' : 'L' }, size, reducing_gap);
    return unpremultiply({ ...resized, mode: image.mode, bands: image.bands });
  }
  let box: [number, number, number, number] = [0, 0, image.width, image.height];
  let source = image;
  const factor_x = Math.trunc((box[2] - box[0]) / size[0] / reducing_gap) || 1;
  const factor_y = Math.trunc((box[3] - box[1]) / size[1] / reducing_gap) || 1;
  if (factor_x > 1 || factor_y > 1) {
    const filter_support = LANCZOS_SUPPORT - 0.5;
    const scale_x = (box[2] - box[0]) / size[0];
    const scale_y = (box[3] - box[1]) / size[1];
    const support_x = filter_support * scale_x;
    const support_y = filter_support * scale_y;
    const reduce_box: [number, number, number, number] = [
      Math.max(0, Math.trunc(box[0] - support_x)),
      Math.max(0, Math.trunc(box[1] - support_y)),
      Math.min(image.width, Math.ceil(box[2] + support_x)),
      Math.min(image.height, Math.ceil(box[3] + support_y)),
    ];
    source = reduce(image, factor_x, factor_y, reduce_box);
    box = [
      (box[0] - reduce_box[0]) / factor_x,
      (box[1] - reduce_box[1]) / factor_y,
      (box[2] - reduce_box[0]) / factor_x,
      (box[3] - reduce_box[1]) / factor_y,
    ];
  }
  return resample(source, size[0], size[1], box);
}

// libImaging/Convert.c rgbA2rgba / rgba2rgbA (and the LA equivalents).
function premultiply(image: Raster): Raster {
  const out = new Uint8Array(image.data.length);
  const { bands, data } = image;
  for (let i = 0; i < data.length; i += bands) {
    const alpha = data[i + bands - 1];
    for (let c = 0; c < bands - 1; c += 1) {
      const tmp = data[i + c] * alpha + 128;
      out[i + c] = ((tmp >> 8) + tmp) >> 8;
    }
    out[i + bands - 1] = alpha;
  }
  return { ...image, data: out };
}

function unpremultiply(image: Raster): Raster {
  const out = new Uint8Array(image.data.length);
  const { bands, data } = image;
  for (let i = 0; i < data.length; i += bands) {
    const alpha = data[i + bands - 1];
    for (let c = 0; c < bands - 1; c += 1) {
      if (alpha === 255 || alpha === 0) out[i + c] = data[i + c];
      else out[i + c] = Math.min(255, Math.trunc((255 * data[i + c]) / alpha));
    }
    out[i + bands - 1] = alpha;
  }
  return { ...image, data: out };
}

/**
 * ``Image.reduce((xscale, yscale), box)`` — libImaging/Reduce.c: every output
 * pixel is the rounded mean of an ``xscale × yscale`` block; the last
 * column/row averages the partial block that is left.
 */
function reduce(image: Raster, xscale: number, yscale: number, box: [number, number, number, number]): Raster {
  const [x0, y0, x1, y1] = box;
  const boxW = x1 - x0;
  const boxH = y1 - y0;
  const width = Math.ceil(boxW / xscale);
  const height = Math.ceil(boxH / yscale);
  const { bands } = image;
  const out = new Uint8Array(width * height * bands);
  for (let y = 0; y < height; y += 1) {
    const yFrom = y0 + y * yscale;
    const yTo = Math.min(yFrom + yscale, y1);
    for (let x = 0; x < width; x += 1) {
      const xFrom = x0 + x * xscale;
      const xTo = Math.min(xFrom + xscale, x1);
      const count = (yTo - yFrom) * (xTo - xFrom);
      const multiplier = divisionUint32(count, 8);
      const amend = Math.trunc(count / 2);
      for (let c = 0; c < bands; c += 1) {
        let ss = amend;
        for (let yy = yFrom; yy < yTo; yy += 1) {
          for (let xx = xFrom; xx < xTo; xx += 1) ss += image.data[(yy * image.width + xx) * bands + c];
        }
        // Reduce.c: (ss * multiplier) >> 24 in uint32 arithmetic.
        // (ss * multiplier) < 2**32 here, so the uint32 product never wraps.
        out[(y * width + x) * bands + c] = Math.floor((ss * multiplier) / 16777216);
      }
    }
  }
  return { ...image, width, height, data: out };
}

/** Reduce.c division_UINT32: (UINT32)((float)(1 << 30) * 4.0 / ((1 << result_bits) * divider)). */
function divisionUint32(divider: number, result_bits: number): number {
  const max_dividend = (1 << result_bits) * divider;
  const max_int = Math.fround(Math.fround(1 << 30) * 4.0);
  return Math.trunc(Math.fround(max_int / max_dividend)) >>> 0;
}

function sincFilter(x: number): number {
  if (x === 0.0) return 1.0;
  x *= Math.PI;
  return Math.sin(x) / x;
}

function lanczosFilter(x: number): number {
  // truncated sinc
  if (-3.0 <= x && x < 3.0) return sincFilter(x) * sincFilter(x / 3);
  return 0.0;
}

const PRECISION_BITS = 32 - 8 - 2;

/** Resample.c precompute_coeffs + normalize_coeffs_8bpc. */
function precomputeCoeffs(inSize: number, in0: number, in1: number, outSize: number): { ksize: number; bounds: Int32Array; kk: Int32Array } {
  const scale = (in1 - in0) / outSize;
  let filterscale = scale;
  if (filterscale < 1.0) filterscale = 1.0;
  const support = LANCZOS_SUPPORT * filterscale;
  const ksize = Math.ceil(support) * 2 + 1;
  const prekk = new Float64Array(outSize * ksize);
  const bounds = new Int32Array(outSize * 2);
  for (let xx = 0; xx < outSize; xx += 1) {
    const center = in0 + (xx + 0.5) * scale;
    let ww = 0.0;
    const ss = 1.0 / filterscale;
    let xmin = Math.trunc(center - support + 0.5);
    if (xmin < 0) xmin = 0;
    let xmax = Math.trunc(center + support + 0.5);
    if (xmax > inSize) xmax = inSize;
    xmax -= xmin;
    const base = xx * ksize;
    for (let x = 0; x < xmax; x += 1) {
      const w = lanczosFilter((x + xmin - center + 0.5) * ss);
      prekk[base + x] = w;
      ww += w;
    }
    for (let x = 0; x < xmax; x += 1) {
      if (ww !== 0.0) prekk[base + x] /= ww;
    }
    bounds[xx * 2] = xmin;
    bounds[xx * 2 + 1] = xmax;
  }
  const kk = new Int32Array(outSize * ksize);
  for (let i = 0; i < prekk.length; i += 1) {
    kk[i] = prekk[i] < 0
      ? Math.trunc(-0.5 + prekk[i] * (1 << PRECISION_BITS))
      : Math.trunc(0.5 + prekk[i] * (1 << PRECISION_BITS));
  }
  return { ksize, bounds, kk };
}

function clip8(value: number): number {
  if (value >= 1 << PRECISION_BITS << 8) return 255;
  if (value <= 0) return 0;
  return Math.floor(value / (1 << PRECISION_BITS));
}

// The accumulators are INT32 like Resample.c (wrapping int32 adds are
// associative mod 2**32, so the order of summation cannot change the
// result); the loops are arranged for speed (bands unrolled, vertical pass row-major) —
// the thumbnail of a 4x export would otherwise block the event loop for
// seconds.

/** Resample.c ImagingResampleHorizontal_8bpc for rows ``[ybox_first, ybox_first + rows)``. */
function resampleHorizontal(data: Uint8Array, inWidth: number, bands: number, rows: number, ybox_first: number, xsize: number, horiz: { ksize: number; bounds: Int32Array; kk: Int32Array }): Uint8Array {
  const out = new Uint8Array(xsize * rows * bands);
  const { ksize, bounds, kk } = horiz;
  const half = 1 << (PRECISION_BITS - 1);
  let o = 0;
  for (let yy = 0; yy < rows; yy += 1) {
    const rowIn = (yy + ybox_first) * inWidth * bands;
    for (let xx = 0; xx < xsize; xx += 1) {
      const xmin = bounds[xx * 2];
      const xmax = bounds[xx * 2 + 1];
      const k = xx * ksize;
      let p = rowIn + xmin * bands;
      if (bands === 4) {
        let s0 = half, s1 = half, s2 = half, s3 = half;
        for (let x = 0; x < xmax; x += 1, p += 4) {
          const w = kk[k + x];
          s0 += data[p] * w;
          s1 += data[p + 1] * w;
          s2 += data[p + 2] * w;
          s3 += data[p + 3] * w;
        }
        out[o] = clip8(s0 | 0);
        out[o + 1] = clip8(s1 | 0);
        out[o + 2] = clip8(s2 | 0);
        out[o + 3] = clip8(s3 | 0);
        o += 4;
      } else if (bands === 3) {
        let s0 = half, s1 = half, s2 = half;
        for (let x = 0; x < xmax; x += 1, p += 3) {
          const w = kk[k + x];
          s0 += data[p] * w;
          s1 += data[p + 1] * w;
          s2 += data[p + 2] * w;
        }
        out[o] = clip8(s0 | 0);
        out[o + 1] = clip8(s1 | 0);
        out[o + 2] = clip8(s2 | 0);
        o += 3;
      } else {
        for (let c = 0; c < bands; c += 1) {
          let ss = half;
          for (let x = 0, q = p + c; x < xmax; x += 1, q += bands) ss += data[q] * kk[k + x];
          out[o++] = clip8(ss | 0);
        }
      }
    }
  }
  return out;
}

/** Resample.c ImagingResampleVertical_8bpc. */
function resampleVertical(data: Uint8Array, width: number, bands: number, ysize: number, vert: { ksize: number; bounds: Int32Array; kk: Int32Array }): Uint8Array {
  const rowLen = width * bands;
  const out = new Uint8Array(rowLen * ysize);
  const acc = new Int32Array(rowLen);
  const { ksize, bounds, kk } = vert;
  const half = 1 << (PRECISION_BITS - 1);
  for (let yy = 0; yy < ysize; yy += 1) {
    const k = yy * ksize;
    const ymin = bounds[yy * 2];
    const ymax = bounds[yy * 2 + 1];
    acc.fill(half);
    let y = 0;
    // Four source rows per sweep over the accumulator row.
    for (; y + 4 <= ymax; y += 4) {
      const w0 = kk[k + y], w1 = kk[k + y + 1], w2 = kk[k + y + 2], w3 = kk[k + y + 3];
      const r0 = (y + ymin) * rowLen, r1 = r0 + rowLen, r2 = r1 + rowLen, r3 = r2 + rowLen;
      for (let i = 0; i < rowLen; i += 1) {
        acc[i] = (acc[i] + Math.imul(data[r0 + i], w0) + Math.imul(data[r1 + i], w1) + Math.imul(data[r2 + i], w2) + Math.imul(data[r3 + i], w3)) | 0;
      }
    }
    for (; y < ymax; y += 1) {
      const w = kk[k + y];
      const rowIn = (y + ymin) * rowLen;
      for (let i = 0; i < rowLen; i += 1) acc[i] = (acc[i] + Math.imul(data[rowIn + i], w)) | 0;
    }
    const rowOut = yy * rowLen;
    for (let i = 0; i < rowLen; i += 1) out[rowOut + i] = clip8(acc[i]);
  }
  return out;
}

/**
 * Resample.c ImagingResampleInner as built in Pillow 13: two passes, and the
 * vertical pass goes first when the image loses more than twice as many rows
 * as columns. (Read from the disassembly of ``ImagingResample`` in the
 * installed ``_imaging`` module; the pass order changes the rounding of the
 * intermediate image, so it decides pixel identity. Checked against PIL on
 * 300 random sizes, both orders.)
 */
function resample(image: Raster, xsize: number, ysize: number, box: [number, number, number, number]): Raster {
  const { bands } = image;
  const need_horizontal = xsize !== image.width || box[0] !== 0 || box[2] !== xsize;
  const need_vertical = ysize !== image.height || box[1] !== 0 || box[3] !== ysize;
  const xreduce = image.width - xsize;
  const yreduce = image.height - ysize;
  const horizontal_first = !(yreduce >= 1 && yreduce > 2 * xreduce);
  const horiz = precomputeCoeffs(image.width, box[0], box[2], xsize);
  const vert = precomputeCoeffs(image.height, box[1], box[3], ysize);

  let current = image;
  if (horizontal_first) {
    if (need_horizontal) {
      // Only rows [ybox_first, ybox_last) feed the vertical pass.
      const ybox_first = vert.bounds[0];
      const ybox_last = vert.bounds[ysize * 2 - 2] + vert.bounds[ysize * 2 - 1];
      for (let i = 0; i < ysize; i += 1) vert.bounds[i * 2] -= ybox_first;
      const rows = ybox_last - ybox_first;
      const out = resampleHorizontal(current.data, current.width, bands, rows, ybox_first, xsize, horiz);
      current = { ...current, width: xsize, height: rows, data: out };
    }
    if (need_vertical) {
      const out = resampleVertical(current.data, current.width, bands, ysize, vert);
      current = { ...current, height: ysize, data: out };
    }
  } else {
    if (need_vertical) {
      const out = resampleVertical(current.data, current.width, bands, ysize, vert);
      current = { ...current, height: ysize, data: out };
    }
    if (need_horizontal) {
      const out = resampleHorizontal(current.data, current.width, bands, current.height, 0, xsize, horiz);
      current = { ...current, width: xsize, data: out };
    }
  }
  return current;
}
