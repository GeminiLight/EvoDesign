// Ported from evodesign/agentic_system/render_engine/shared/image_cropper.py — keep in sync.
// server-only (reads and writes image files)
//
// Python runs the crop with OpenCV + numpy. The TS port works on decoded
// pixels (fast-png) and reproduces the OpenCV operations it uses bit for bit:
//
//   cv2.imread(path)            IMREAD_COLOR: 8-bit, 3 channels. Alpha is
//                               stripped (not composited), grey is replicated,
//                               palettes are expanded, 16-bit samples keep
//                               their high byte (png_set_strip_16).
//   cv2.cvtColor(BGR2GRAY)      fixed point: (B*1868 + G*9617 + R*4899 + 8192) >> 14
//   cv2.threshold(OTSU)         getThreshVal_Otsu_8u (double accumulation)
//   cv2.morphologyEx(5x5 ones)  rectangular min/max filters; the default border
//                               value never wins (pixels outside are ignored);
//                               ``iterations=n`` with a rect kernel equals one
//                               pass with a ((5-1)*n+1)² kernel
//   cv2.findNonZero/boundingRect  min/max of the non-zero coordinates
//   cv2.imwrite(.png)           8-bit RGB PNG (colour type 2); the bytes differ
//                               from libpng's, the pixels do not
//
// Only PNG input is supported (the renderers only produce PNG); any other
// file is treated like an image cv2 could not read.
//
// ``smart_crop`` is a LangChain ``@tool`` in Python and is only called as
// ``smart_crop.invoke(input={...})``; the TS export keeps that calling form.

import { concatBytes, writeUInt32BE } from '../../py/bytes.ts';
import { readFileSync, writeFileSync } from '../../py/fs.ts';
import { deflate } from '../../py/zlib.ts';
import { decode as decodePng } from 'fast-png';
import { IndexError } from '../../py/errors.ts';
import { getLogger } from '../../py/logging.ts';

const logger = getLogger('evodesign.agentic_system.render_engine.shared.image_cropper');

/** ``cv2.error`` */
export class cv2_error extends Error {
  constructor(message = '') {
    super(message);
    this.name = 'error';
  }
}

/** An 8-bit 3-channel image in OpenCV's BGR order (row-major, interleaved). */
interface BgrImage {
  width: number;
  height: number;
  data: Uint8Array;
}

/** ``cv2.imread(path)`` (IMREAD_COLOR) for PNG files; null when unreadable. */
function _imread(path: string): BgrImage | null {
  let bytes: Uint8Array;
  try {
    bytes = readFileSync(path);
  } catch {
    return null;
  }
  let png: ReturnType<typeof decodePng>;
  try {
    png = decodePng(bytes);
  } catch {
    return null;
  }
  const { width, height, channels, depth, palette } = png;
  const src = png.data as ArrayLike<number>;
  // 16-bit samples: the high byte (cv2 IMREAD_COLOR converts to 8-bit); 1/2/4-bit gray is scaled to 0..255.
  const sample = depth === 16
    ? (v: number) => v >> 8
    : depth < 8 && !palette ? (v: number) => Math.round((v * 255) / ((1 << depth) - 1)) : (v: number) => v;
  const data = new Uint8Array(width * height * 3);
  for (let p = 0, j = 0; j < data.length; p += 1, j += 3) {
    let r: number;
    let g: number;
    let b: number;
    if (palette) {
      const entry = palette[src[p]] ?? [0, 0, 0];
      [r, g, b] = entry;
    } else if (channels >= 3) {
      r = sample(src[p * channels]);
      g = sample(src[p * channels + 1]);
      b = sample(src[p * channels + 2]);
    } else {
      r = g = b = sample(src[p * channels]);
    }
    data[j] = b;
    data[j + 1] = g;
    data[j + 2] = r;
  }
  return { width, height, data };
}

/** ``img[y0:y1, x0:x1]`` (bounds already clipped). */
function _slice(img: BgrImage, y0: number, y1: number, x0: number, x1: number): BgrImage {
  const clip = (v: number, n: number) => Math.max(0, Math.min(n, v));
  y0 = clip(y0, img.height);
  y1 = clip(y1, img.height);
  x0 = clip(x0, img.width);
  x1 = clip(x1, img.width);
  const width = Math.max(0, x1 - x0);
  const height = Math.max(0, y1 - y0);
  const data = new Uint8Array(width * height * 3);
  for (let y = 0; y < height; y += 1) {
    const from = ((y0 + y) * img.width + x0) * 3;
    data.set(img.data.subarray(from, from + width * 3), y * width * 3);
  }
  return { width, height, data };
}

/** ``cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)`` (8-bit fixed point). */
function _bgr2gray(img: BgrImage): Uint8Array {
  const out = new Uint8Array(img.width * img.height);
  for (let i = 0, j = 0; i < out.length; i += 1, j += 3) {
    out[i] = (img.data[j] * 1868 + img.data[j + 1] * 9617 + img.data[j + 2] * 4899 + 8192) >> 14;
  }
  return out;
}

const FLT_EPSILON = 1.1920928955078125e-7;

/** ``getThreshVal_Otsu_8u``. */
function _otsu_threshold(gray: Uint8Array): number {
  const N = 256;
  const h = new Float64Array(N);
  for (let i = 0; i < gray.length; i += 1) h[gray[i]] += 1;
  let mu = 0;
  const scale = 1 / gray.length;
  for (let i = 0; i < N; i += 1) mu += i * h[i];
  mu *= scale;
  let mu1 = 0;
  let q1 = 0;
  let max_sigma = 0;
  let max_val = 0;
  for (let i = 0; i < N; i += 1) {
    const p_i = h[i] * scale;
    mu1 *= q1;
    q1 += p_i;
    const q2 = 1 - q1;
    if (Math.min(q1, q2) < FLT_EPSILON || Math.max(q1, q2) > 1 - FLT_EPSILON) continue;
    mu1 = (mu1 + i * p_i) / q1;
    const mu2 = (mu - q1 * mu1) / q2;
    const sigma = q1 * q2 * (mu1 - mu2) * (mu1 - mu2);
    if (sigma > max_sigma) {
      max_sigma = sigma;
      max_val = i;
    }
  }
  return max_val;
}

/** Rectangular min (erode) / max (dilate) filter with radius ``r``; outside pixels are ignored. */
function _rect_filter(src: Uint8Array, width: number, height: number, r: number, dilate: boolean): Uint8Array {
  const tmp = new Uint8Array(src.length);
  const out = new Uint8Array(src.length);
  const pick = dilate ? Math.max : Math.min;
  for (let y = 0; y < height; y += 1) {
    const row = y * width;
    for (let x = 0; x < width; x += 1) {
      let v = src[row + x];
      const lo = Math.max(0, x - r);
      const hi = Math.min(width - 1, x + r);
      for (let k = lo; k <= hi; k += 1) v = pick(v, src[row + k]);
      tmp[row + x] = v;
    }
  }
  for (let y = 0; y < height; y += 1) {
    const lo = Math.max(0, y - r);
    const hi = Math.min(height - 1, y + r);
    for (let x = 0; x < width; x += 1) {
      let v = tmp[y * width + x];
      for (let k = lo; k <= hi; k += 1) v = pick(v, tmp[k * width + x]);
      out[y * width + x] = v;
    }
  }
  return out;
}

/** ``cv2.morphologyEx(src, op, np.ones((5, 5)), iterations=n)`` for MORPH_CLOSE / MORPH_OPEN. */
function _morphology(src: Uint8Array, width: number, height: number, op: 'close' | 'open', iterations: number): Uint8Array {
  const r = 2 * iterations; // ((5 - 1) * iterations + 1) // 2
  if (op === 'close') {
    return _rect_filter(_rect_filter(src, width, height, r, true), width, height, r, false);
  }
  return _rect_filter(_rect_filter(src, width, height, r, false), width, height, r, true);
}

/** ``cv2.boundingRect(cv2.findNonZero(mask))``; null when there is no non-zero pixel. */
function _bounding_rect(mask: Uint8Array, width: number, height: number): [number, number, number, number] | null {
  let minX = width;
  let minY = height;
  let maxX = -1;
  let maxY = -1;
  for (let y = 0; y < height; y += 1) {
    const row = y * width;
    for (let x = 0; x < width; x += 1) {
      if (mask[row + x]) {
        if (x < minX) minX = x;
        if (x > maxX) maxX = x;
        if (y < minY) minY = y;
        maxY = y;
      }
    }
  }
  if (maxX < 0) return null;
  return [minX, minY, maxX - minX + 1, maxY - minY + 1];
}

const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let n = 0; n < 256; n += 1) {
    let c = n;
    for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c >>> 0;
  }
  return table;
})();

function _png_chunk(type: string, body: Uint8Array): Uint8Array {
  const head = new Uint8Array(8);
  writeUInt32BE(head, body.length, 0);
  for (let i = 0; i < 4; i += 1) head[4 + i] = type.charCodeAt(i) & 0xff;
  let c = 0xffffffff;
  for (let i = 4; i < 8; i += 1) c = CRC_TABLE[(c ^ head[i]) & 0xff] ^ (c >>> 8);
  for (let i = 0; i < body.length; i += 1) c = CRC_TABLE[(c ^ body[i]) & 0xff] ^ (c >>> 8);
  const crc = new Uint8Array(4);
  writeUInt32BE(crc, (c ^ 0xffffffff) >>> 0, 0);
  return concatBytes([head, body, crc]);
}

/** ``cv2.imwrite(path, img)`` for a 3-channel image: an 8-bit RGB PNG. */
function _imwrite_png(path: string, img: BgrImage): boolean {
  if (img.width === 0 || img.height === 0) return false; // cv2 rejects empty images
  const stride = img.width * 3;
  const raw = new Uint8Array((stride + 1) * img.height);
  const rgbRow = new Uint8Array(stride);
  const prevRow = new Uint8Array(stride);
  for (let y = 0; y < img.height; y += 1) {
    const src = y * stride;
    for (let x = 0; x < stride; x += 3) {
      rgbRow[x] = img.data[src + x + 2];
      rgbRow[x + 1] = img.data[src + x + 1];
      rgbRow[x + 2] = img.data[src + x];
    }
    // Filter "Up" (2): cheap and compact for diagrams; the pixel data is what matters.
    const out = y * (stride + 1);
    raw[out] = 2;
    for (let i = 0; i < stride; i += 1) raw[out + 1 + i] = (rgbRow[i] - prevRow[i]) & 0xff;
    prevRow.set(rgbRow);
  }
  const ihdr = new Uint8Array(13);
  writeUInt32BE(ihdr, img.width, 0);
  writeUInt32BE(ihdr, img.height, 4);
  ihdr[8] = 8; // bit depth
  ihdr[9] = 2; // colour type RGB
  const png = concatBytes([
    Uint8Array.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    _png_chunk('IHDR', ihdr),
    _png_chunk('IDAT', deflate(raw, 6)),
    _png_chunk('IEND', new Uint8Array(0)),
  ]);
  writeFileSync(path, png);
  return true;
}

/** ``os.path.splitext(path)[0]`` */
function _splitext_root(path: string): string {
  const slash = path.lastIndexOf('/');
  const dot = path.lastIndexOf('.');
  if (dot <= slash + 1) return path;
  // A leading run of dots in the basename is not an extension separator.
  const base = path.slice(slash + 1, dot);
  if (/^\.*$/.test(base)) return path;
  return path.slice(0, dot);
}

/**
 * Removes bottom watermarks and automatically crops white/light-gray margins.
 *
 * Args:
 *     image_path (str): Path to the source image.
 *     output_path (str): Path to save the processed image (forced to .png).
 *     padding (int): Extra margin to leave around the content (default: 0px for very tight crop).
 *     bottom_offset (int): Pixels to cut from the bottom to remove watermarks (default: auto based on canvas_engine).
 *     top_left_margin (int): Pixels to cut from top-left to remove menu icons (default: auto based on canvas_engine).
 *     canvas_engine (str): Canvas rendering engine - "excalidraw" or "tldraw" (affects which UI elements to remove).
 * Returns:
 *     str: A message indicating the result of the operation.
 */
export function _smart_crop(
  image_path: string,
  output_path: string,
  padding = 0,
  bottom_offset: number | null = null,
  top_left_margin: number | null = null,
  canvas_engine = 'tldraw',
): string {
  // Auto-determine margins based on canvas engine if not specified
  if (bottom_offset === null || bottom_offset === undefined) {
    if (canvas_engine.toLowerCase() === 'tldraw') {
      bottom_offset = 120; // Tldraw has bottom watermark
    } else if (canvas_engine.toLowerCase() === 'excalidraw') {
      bottom_offset = 0; // Excalidraw exportToBlob output is chrome-free
    } else {
      bottom_offset = 100; // Default
    }
  }

  if (top_left_margin === null || top_left_margin === undefined) {
    if (canvas_engine.toLowerCase() === 'excalidraw') {
      top_left_margin = 0; // exportToBlob output has no top-left icon
    } else if (canvas_engine.toLowerCase() === 'tldraw') {
      top_left_margin = 0; // Tldraw doesn't have top-left icon
    } else {
      top_left_margin = 0; // Default
    }
  }
  // 1. Load image
  const img = _imread(image_path);
  if (img === null) {
    return `Error: Could not read image at ${image_path}`;
  }

  const h = img.height;
  const w = img.width;

  // 2. Step 1: Remove UI elements from top-left and bottom (canvas-engine-dependent)
  let img_working = _slice(img, _pyIndex(top_left_margin, h), h, _pyIndex(top_left_margin, w), w);

  // Cut off the bottom area to eliminate fixed UI elements (e.g., watermarks)
  const safe_h = Math.max(0, img_working.height - bottom_offset);
  img_working = _slice(img_working, 0, safe_h, 0, img_working.width);

  // Native Excalidraw exports have clean, uniform padding, with no UI to
  // remove. A dark title can dominate Otsu's threshold and erase pale frame
  // borders or dashed relations from the bounds. Morphological opening also
  // erases thin strokes. Preserve every visible deviation from the exported
  // canvas color, including single-pixel lines and tinted backgrounds.
  const ww = img_working.width;
  const wh = img_working.height;
  let thresh: Uint8Array;
  if (canvas_engine.toLowerCase() === 'excalidraw') {
    if (ww === 0 || wh === 0) {
      throw new IndexError('index 0 is out of bounds for axis 0 with size 0');
    }
    const d = img_working.data;
    const b0 = d[0];
    const g0 = d[1];
    const r0 = d[2];
    thresh = new Uint8Array(ww * wh);
    for (let i = 0, j = 0; i < thresh.length; i += 1, j += 3) {
      const difference = Math.max(Math.abs(d[j] - b0), Math.abs(d[j + 1] - g0), Math.abs(d[j + 2] - r0));
      thresh[i] = difference > 2 ? 255 : 0;
    }
  } else {
    if (ww === 0 || wh === 0) {
      throw new cv2_error("(-215:Assertion failed) !_src.empty() in function 'cvtColor'");
    }
    const gray = _bgr2gray(img_working);
    const t = _otsu_threshold(gray);
    thresh = new Uint8Array(gray.length);
    for (let i = 0; i < gray.length; i += 1) thresh[i] = gray[i] > t ? 0 : 255;
    thresh = _morphology(thresh, ww, wh, 'close', 2);
    thresh = _morphology(thresh, ww, wh, 'open', 1);
  }

  // 6. Bounding Box Calculation
  // Find all non-zero (white) pixels which represent the actual diagram content
  const coords = _bounding_rect(thresh, ww, wh);

  if (coords === null) {
    return 'Warning: No valid content detected after watermark removal.';
  }

  // Calculate the minimal upright bounding rectangle
  const [x, y, cw, ch] = coords;

  // 7. Apply Padding and Boundary Constraints
  const h_work = wh;
  const w_work = ww;
  const final_x1 = Math.max(0, x - padding);
  const final_y1 = Math.max(0, y - padding);
  const final_x2 = Math.min(w_work, x + cw + padding);
  const final_y2 = Math.min(h_work, y + ch + padding);

  // 8. Final Crop and Export
  // Slice the image using calculated coordinates
  const final_img = _slice(img_working, final_y1, final_y2, final_x1, final_x2);

  // Ensure output is PNG for lossless quality in papers/reports
  const final_output_path = _splitext_root(output_path) + '.png';
  _imwrite_png(final_output_path, final_img);

  const result_msg = `Resized: ${w}x${h} -> ${final_img.width}x${final_img.height}\n`
    + `Saved to: ${final_output_path}`;
  logger.info('%s', result_msg);
  return result_msg;
}

/** Python slice start semantics for a (possibly negative) start index. */
function _pyIndex(start: number, length: number): number {
  return start < 0 ? Math.max(0, length + start) : start;
}

export interface SmartCropInput {
  image_path: string;
  output_path: string;
  padding?: number;
  bottom_offset?: number | null;
  top_left_margin?: number | null;
  canvas_engine?: string;
}

/** The ``@tool``-decorated ``smart_crop``: call as ``smart_crop.invoke({...})``. */
export const smart_crop = {
  name: 'smart_crop',
  description: 'Removes bottom watermarks and automatically crops white/light-gray margins.',
  func: _smart_crop,
  invoke(input: SmartCropInput): string {
    return _smart_crop(
      input.image_path,
      input.output_path,
      input.padding ?? 0,
      input.bottom_offset ?? null,
      input.top_left_margin ?? null,
      input.canvas_engine ?? 'tldraw',
    );
  },
};
