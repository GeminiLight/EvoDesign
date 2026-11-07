// ``zlib`` / ``gzip`` in pure JS (PHASE3_PLAN.md WP27) on top of pako 2.1.0
// (exact pin). Output bytes are valid zlib/gzip streams but not necessarily
// byte-identical to Node's/CPython's zlib; nothing in the pipeline compares
// compressed bytes except PNG files, which the parity tools compare by decoded
// pixels (PHASE2_PLAN.md appendix, image rule).

import pako from 'pako';

type Level = 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | -1;

/** ``zlib.compress(data, level)`` */
export function deflate(data: Uint8Array, level: Level = -1): Uint8Array {
  return pako.deflate(data, { level });
}

/** ``zlib.decompress(data)`` */
export function inflate(data: Uint8Array): Uint8Array {
  return pako.inflate(data);
}

/** ``gzip.compress(data, compresslevel)`` */
export function gzip(data: Uint8Array, level: Level = 9): Uint8Array {
  return pako.gzip(data, { level });
}

/** ``gzip.decompress(data)`` */
export function gunzip(data: Uint8Array): Uint8Array {
  return pako.ungzip(data);
}
