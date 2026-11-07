// Ported from evodesign/agentic_system/render_engine/shared/order_keys.py — keep in sync.
//
// Sequential keys compatible with Excalidraw's fractional indexing.

import { ValueError } from '../../py/errors.ts';
import { cpLen, numberStr, pyZfill } from '../../py/str.ts';

export function sequential_index(position: number): string {
  // The head encodes the integer-part length: a0, b00, ... e00000.
  // a00000 is invalid: it is a0 plus a fraction ending in zero.
  const digits = pyZfill(numberStr(position), 5);
  if (position < 0 || cpLen(digits) > 26) {
    throw new ValueError('Canvas element position is out of range');
  }
  return String.fromCodePoint('a'.codePointAt(0)! + cpLen(digits) - 1) + digits;
}
