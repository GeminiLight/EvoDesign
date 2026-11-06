// Ported from evodesign/agentic_system/render_engine/shared/png_validation.py — keep in sync.
// server-only (reads the rendered file from disk)
//
// PNG artifact validation shared by render entrypoints.
//
// Python opens the file with Pillow (``Image.open`` + ``verify()``). The TS
// port re-implements exactly the checks those two calls make on a PNG:
//
//   Image.open (PngImagePlugin._open)
//     * 8-byte signature, else the PNG plugin declines → other formats are
//       tried (common magic numbers below give the ``format`` Pillow would
//       report) → ``UnidentifiedImageError`` ("unreadable PNG");
//     * chunks before the first IDAT: header + type must match ``\w\w\w\w``
//       (``SyntaxError``), the data must be complete (``_safe_read`` →
//       ``OSError``), the CRC must be present and match (``SyntaxError``);
//       ``SyntaxError`` / ``struct.error`` make the open fail → "unreadable";
//     * IHDR must be present and carry a mode Pillow knows.
//   verify (ChunkStream.verify, from the first IDAT)
//     * every chunk up to IEND is read and CRC-checked; a short header is
//       ``OSError("truncated PNG file")``, short data ``OSError``, bad CRC
//       ``SyntaxError`` → "corrupt PNG". IEND's own CRC is not checked.

import { bytesEqual, latin1Decode, latin1Encode, readUInt32BE } from '../../py/bytes.ts';
import { existsSync, readFileSync, statSync } from '../../py/fs.ts';
import { IndexError, RuntimeError, ValueError } from '../../py/errors.ts';
import { pyRepr } from '../../py/str.ts';

class _PngSyntaxError extends Error {}
class _PngOSError extends Error {}
class _PngUnidentified extends Error {}

const _MAGIC = Uint8Array.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
const _CID_RE = /^[A-Za-z0-9_]{4}$/;

const _CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let n = 0; n < 256; n += 1) {
    let c = n;
    for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c >>> 0;
  }
  return table;
})();

function _crc32(bytes: Uint8Array, start: number, end: number, crc = 0): number {
  let c = (crc ^ 0xffffffff) >>> 0;
  for (let i = start; i < end; i += 1) c = _CRC_TABLE[(c ^ bytes[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

/** Pillow's ``format`` for non-PNG files it can identify (by magic number); null = unidentified. */
function _guess_other_format(bytes: Uint8Array): string | null {
  const ascii = (start: number, end: number) => latin1Decode(bytes, start, end);
  if (bytes.length >= 3 && bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff) return 'JPEG';
  if (ascii(0, 6) === 'GIF87a' || ascii(0, 6) === 'GIF89a') return 'GIF';
  if (ascii(0, 2) === 'BM' && bytes.length >= 18) return 'BMP';
  if (ascii(0, 4) === 'RIFF' && ascii(8, 12) === 'WEBP') return 'WEBP';
  if (ascii(0, 4) === 'II*\0' || ascii(0, 4) === 'MM\0*') return 'TIFF';
  if (bytes.length >= 4 && bytes[0] === 0 && bytes[1] === 0 && bytes[2] === 1 && bytes[3] === 0) return 'ICO';
  if (ascii(0, 4) === '8BPS') return 'PSD';
  return null;
}

// (color type, bit depth) combinations Pillow's _MODES table accepts.
const _VALID_MODES = new Set([
  '0:1', '0:2', '0:4', '0:8', '0:16',
  '2:8', '2:16',
  '3:1', '3:2', '3:4', '3:8',
  '4:8', '4:16',
  '6:8', '6:16',
]);

interface _Chunk { cid: string; pos: number; length: number }

/** ``ChunkStream.read``: 8-byte header; ``struct.error`` when short, ``SyntaxError`` on a bad type. */
function _read_chunk(bytes: Uint8Array, offset: number): _Chunk | 'struct' {
  if (offset + 8 > bytes.length) {
    // i32(s) on fewer than 4 bytes is struct.error; 4..7 bytes give a short cid
    if (offset + 4 > bytes.length) return 'struct';
    const cid = latin1Decode(bytes, offset + 4, Math.min(bytes.length, offset + 8));
    if (!_CID_RE.test(cid)) throw new _PngSyntaxError(`broken PNG file (chunk ${cid})`);
    return 'struct';
  }
  const length = readUInt32BE(bytes, offset);
  const cid = latin1Decode(bytes, offset + 4, offset + 8);
  if (!_CID_RE.test(cid)) throw new _PngSyntaxError(`broken PNG file (chunk ${cid})`);
  return { cid, pos: offset + 8, length };
}

/** ``ChunkStream.crc`` — reads the 4-byte CRC after the data. */
function _check_crc(bytes: Uint8Array, chunk: _Chunk): void {
  const end = chunk.pos + chunk.length;
  if (end + 4 > bytes.length) throw new _PngSyntaxError(`broken PNG file (incomplete checksum in ${chunk.cid})`);
  const expected = _crc32(bytes, chunk.pos, end, _crc32(latin1Encode(chunk.cid), 0, 4));
  if (expected !== readUInt32BE(bytes, end)) throw new _PngSyntaxError(`broken PNG file (bad header checksum in ${chunk.cid})`);
}

/** ``Image.open(path)`` + ``image.format`` + ``image.verify()`` for a PNG file. */
function _open_and_verify(bytes: Uint8Array): string {
  if (bytes.length < 8 || !bytesEqual(bytes.subarray(0, 8), _MAGIC)) {
    const other = _guess_other_format(bytes);
    if (other === null) throw new _PngUnidentified();
    return other;
  }
  // --- PngImageFile._open ---
  let offset = 8;
  let haveHeader = false;
  let sizeOk = false;
  let modeOk = false;
  let idatOffset = -1;
  try {
    for (;;) {
      const chunk = _read_chunk(bytes, offset);
      if (chunk === 'struct') throw new _PngUnidentified();
      if (chunk.cid === 'IDAT' || chunk.cid === 'fdAT' || chunk.cid === 'IEND') {
        // chunk_IDAT / chunk_IEND raise EOFError: the header loop ends here.
        // ImageFile.__init__ then rejects a missing mode/size (SyntaxError).
        if (!haveHeader || !modeOk || !sizeOk) throw new _PngUnidentified();
        // After IEND the tile list is empty: verify() fails on ``self.tile[0]``.
        if (chunk.cid === 'IEND') throw new IndexError('list index out of range');
        idatOffset = offset;
        break;
      }
      if (chunk.pos + chunk.length > bytes.length) throw new _PngOSError('Truncated File Read');
      if (chunk.cid === 'IHDR') {
        // ValueError is not caught by Image.open nor by validate_png_file.
        if (chunk.length < 13) throw new ValueError('Truncated IHDR chunk');
        sizeOk = readUInt32BE(bytes, chunk.pos) > 0 && readUInt32BE(bytes, chunk.pos + 4) > 0;
        modeOk = _VALID_MODES.has(`${bytes[chunk.pos + 9]}:${bytes[chunk.pos + 8]}`);
        if (bytes[chunk.pos + 11]) throw new _PngSyntaxError('unknown filter category');
        haveHeader = true;
      }
      _check_crc(bytes, chunk);
      offset = chunk.pos + chunk.length + 4;
    }
  } catch (error) {
    if (error instanceof _PngSyntaxError) throw new _PngUnidentified();
    throw error;
  }
  // --- PngImageFile.verify → ChunkStream.verify ---
  offset = idatOffset;
  for (;;) {
    const chunk = _read_chunk(bytes, offset);
    if (chunk === 'struct') throw new _PngOSError('truncated PNG file');
    if (chunk.cid === 'IEND') break;
    if (chunk.pos + chunk.length > bytes.length) throw new _PngOSError('Truncated File Read');
    _check_crc(bytes, chunk);
    offset = chunk.pos + chunk.length + 4;
  }
  return 'PNG';
}

/** Raise RuntimeError when output_file is missing, empty, or not a valid PNG. */
export function validate_png_file(output_file: string, context: string): void {
  if (!existsSync(output_file)) {
    throw new RuntimeError(`${context} did not create output file: ${output_file}`);
  }
  if (statSync(output_file).size <= 0) {
    throw new RuntimeError(`${context} created an empty output file: ${output_file}`);
  }
  let format: string;
  try {
    format = _open_and_verify(readFileSync(output_file));
  } catch (error) {
    if (error instanceof _PngUnidentified) {
      throw new RuntimeError(`${context} created an unreadable PNG: ${output_file}`);
    }
    if (error instanceof _PngOSError || error instanceof _PngSyntaxError) {
      throw new RuntimeError(`${context} created a corrupt PNG: ${output_file}`);
    }
    throw error;
  }
  if (format !== 'PNG') {
    throw new RuntimeError(
      `${context} created a non-PNG image: ${output_file} `
      + `(format=${pyRepr(format)})`,
    );
  }
}

export const __all__ = ['validate_png_file'];
