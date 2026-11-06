// Byte helpers that replace Node's ``Buffer`` in pipeline modules (PHASE3_PLAN.md WP27).
// Pure TS on top of ``Uint8Array`` / ``TextEncoder`` / ``TextDecoder`` (available in
// Node and browsers), with ``Buffer``'s semantics where the port relies on them.

const encoder = new TextEncoder();
// ``ignoreBOM``: ``Buffer.toString('utf-8')`` keeps a leading U+FEFF.
const decoder = new TextDecoder('utf-8', { ignoreBOM: true });

/** ``Buffer.from(text, 'utf-8')`` (lone surrogates become U+FFFD, like Node). */
export function utf8EncodeLossy(text: string): Uint8Array {
  return encoder.encode(text);
}

/** ``buffer.toString('utf-8')`` (invalid sequences become U+FFFD, BOM kept). */
export function utf8Decode(bytes: Uint8Array): string {
  return decoder.decode(bytes);
}

/** ``buffer.toString('latin1')`` */
export function latin1Decode(bytes: Uint8Array, start = 0, end = bytes.length): string {
  let out = '';
  const CHUNK = 0x8000;
  for (let i = start; i < end; i += CHUNK) {
    out += String.fromCharCode(...bytes.subarray(i, Math.min(end, i + CHUNK)));
  }
  return out;
}

/** ``Buffer.from(text, 'latin1')`` */
export function latin1Encode(text: string): Uint8Array {
  const out = new Uint8Array(text.length);
  for (let i = 0; i < text.length; i += 1) out[i] = text.charCodeAt(i) & 0xff;
  return out;
}

const B64 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
const B64_LOOKUP = (() => {
  const table = new Int16Array(256).fill(-1);
  for (let i = 0; i < B64.length; i += 1) table[B64.charCodeAt(i)] = i;
  table['-'.charCodeAt(0)] = 62; // Buffer also accepts base64url
  table['_'.charCodeAt(0)] = 63;
  return table;
})();

/** ``buffer.toString('base64')`` */
export function bytesToBase64(bytes: Uint8Array): string {
  let out = '';
  let i = 0;
  for (; i + 2 < bytes.length; i += 3) {
    const n = (bytes[i] << 16) | (bytes[i + 1] << 8) | bytes[i + 2];
    out += B64[(n >> 18) & 63] + B64[(n >> 12) & 63] + B64[(n >> 6) & 63] + B64[n & 63];
  }
  const rest = bytes.length - i;
  if (rest === 1) {
    const n = bytes[i] << 16;
    out += `${B64[(n >> 18) & 63]}${B64[(n >> 12) & 63]}==`;
  } else if (rest === 2) {
    const n = (bytes[i] << 16) | (bytes[i + 1] << 8);
    out += `${B64[(n >> 18) & 63]}${B64[(n >> 12) & 63]}${B64[(n >> 6) & 63]}=`;
  }
  return out;
}

/** ``Buffer.from(text, 'base64')`` (lenient like Node: skips invalid characters, stops at ``=``). */
export function base64ToBytes(text: string): Uint8Array {
  const out: number[] = [];
  let acc = 0;
  let bits = 0;
  for (let i = 0; i < text.length; i += 1) {
    const code = text.charCodeAt(i);
    if (code === 61) break; // '='
    const value = code < 256 ? B64_LOOKUP[code] : -1;
    if (value < 0) continue;
    acc = (acc << 6) | value;
    bits += 6;
    if (bits >= 8) {
      bits -= 8;
      out.push((acc >> bits) & 0xff);
    }
  }
  return Uint8Array.from(out);
}

/** ``Buffer.concat(chunks)`` */
export function concatBytes(chunks: readonly Uint8Array[]): Uint8Array {
  const total = chunks.reduce((sum, chunk) => sum + chunk.length, 0);
  const out = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    out.set(chunk, offset);
    offset += chunk.length;
  }
  return out;
}

/** ``Buffer.compare(a, b) === 0`` */
export function bytesEqual(a: Uint8Array, b: Uint8Array): boolean {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i += 1) if (a[i] !== b[i]) return false;
  return true;
}

/** ``buffer.readUInt32BE(offset)`` */
export function readUInt32BE(bytes: Uint8Array, offset: number): number {
  if (offset < 0 || offset + 4 > bytes.length) throw new RangeError(`The value of "offset" is out of range. It must be >= 0 and <= ${bytes.length - 4}. Received ${offset}`);
  return ((bytes[offset] << 24) >>> 0) + (bytes[offset + 1] << 16) + (bytes[offset + 2] << 8) + bytes[offset + 3];
}

/** ``buffer.writeUInt32BE(value, offset)`` */
export function writeUInt32BE(bytes: Uint8Array, value: number, offset: number): void {
  bytes[offset] = (value >>> 24) & 0xff;
  bytes[offset + 1] = (value >>> 16) & 0xff;
  bytes[offset + 2] = (value >>> 8) & 0xff;
  bytes[offset + 3] = value & 0xff;
}
