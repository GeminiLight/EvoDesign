// Python numeric semantics (MIGRATION_PLAN.md §4).
//
//   round(x)        -> pyRound(x)        banker's rounding on the exact double
//   round(x, n)     -> pyRound(x, n)     correctly rounded like CPython (dtoa mode 3)
//   a // b          -> floorDiv(a, b)    CPython float floor division
//   a % b           -> pyMod(a, b)       result takes the sign of b
//   divmod(a, b)    -> pyDivmod(a, b)
//   int(x)          -> pyInt(x)          truncation toward zero (Math.trunc)
//
// TS has a single number type. Values that were Python ints stay exact as long
// as they are safe integers, and these helpers return the same numbers Python
// would for both ints and floats.

import { OverflowError, ValueError, ZeroDivisionError } from './errors.ts';

/**
 * Marks a number that must be *formatted* as a Python float (``1.0`` rather
 * than ``1``) by ``pyJsonDumps`` / ``pyStr`` / ``pyRepr``. Only needed where an
 * integral float reaches a string (e.g. a hash payload); arithmetic should
 * use plain numbers.
 */
export class PyFloat {
  constructor(readonly value: number) {}
  valueOf(): number {
    return this.value;
  }
}

/** Wrap ``value`` so it is formatted as a Python float. */
export function pyFloat(value: number): PyFloat {
  return new PyFloat(value);
}

const NDIGITS_MAX = Math.trunc((53 - -1021) * 0.30102999566398119521373889472449302676818988146211);
const NDIGITS_MIN = -Math.trunc((1024 + 1) * 0.30102999566398119521373889472449302676818988146211);

/** Exact decomposition of a finite double: ``x == mantissa * 2 ** exponent`` (mantissa >= 0). */
export function exactParts(x: number): { negative: boolean; mantissa: bigint; exponent: number } {
  const view = new DataView(new ArrayBuffer(8));
  view.setFloat64(0, x);
  const hi = view.getUint32(0);
  const lo = view.getUint32(4);
  const negative = (hi >>> 31) === 1;
  const biased = (hi >>> 20) & 0x7ff;
  let mantissa = (BigInt(hi & 0xfffff) << 32n) | BigInt(lo);
  let exponent: number;
  if (biased === 0) {
    exponent = -1074;
  } else {
    mantissa |= 1n << 52n;
    exponent = biased - 1075;
  }
  return { negative, mantissa, exponent };
}

function bigPow10(n: number): bigint {
  return 10n ** BigInt(n);
}

/** Round the exact rational ``num / den`` (both >= 0) to an integer, ties to even. */
function roundHalfEvenRational(num: bigint, den: bigint): bigint {
  const quotient = num / den;
  const twice = (num % den) * 2n;
  if (twice > den) return quotient + 1n;
  if (twice < den) return quotient;
  return quotient % 2n === 0n ? quotient : quotient + 1n;
}

/**
 * ``round(x)`` (no ndigits): nearest integer, ties to even.
 * ``round(x, ndigits)``: CPython ``float.__round__`` — the exact binary value
 * is rounded half-to-even at ``ndigits`` decimal places, then parsed back
 * with correct rounding. ``round(2.675, 2) == 2.67`` like Python.
 */
export function pyRound(x: number, ndigits?: number | null): number {
  if (ndigits === undefined || ndigits === null) {
    if (Number.isNaN(x)) throw new ValueError('cannot convert float NaN to integer');
    if (!Number.isFinite(x)) throw new OverflowError('cannot convert float infinity to integer');
    const floor = Math.floor(x);
    const diff = x - floor; // exact for every finite double
    let result: number;
    if (diff > 0.5) result = floor + 1;
    else if (diff < 0.5) result = floor;
    else result = floor % 2 === 0 ? floor : floor + 1;
    return result === 0 ? 0 : result; // Python ints have no -0
  }
  if (ndigits > NDIGITS_MAX) return x;
  if (ndigits < NDIGITS_MIN) return 0.0 * x;
  if (x === 0 || !Number.isFinite(x)) return x;
  const { negative, mantissa, exponent } = exactParts(x);
  // value = mantissa * 2**exponent; scaled = value * 10**ndigits.
  let num = mantissa;
  let den = 1n;
  if (exponent >= 0) num <<= BigInt(exponent);
  else den <<= BigInt(-exponent);
  if (ndigits >= 0) num *= bigPow10(ndigits);
  else den *= bigPow10(-ndigits);
  const rounded = roundHalfEvenRational(num, den);
  const text = `${negative ? '-' : ''}${rounded.toString()}e${-ndigits}`;
  const result = Number(text);
  if (!Number.isFinite(result)) throw new OverflowError('rounded value too large to represent');
  return result;
}

/** ``a // b`` with CPython ``float_floor_div`` semantics (exact for safe ints). */
export function floorDiv(a: number, b: number): number {
  return pyDivmod(a, b)[0];
}

/** ``a % b`` with CPython ``float_rem`` semantics (sign of the divisor). */
export function pyMod(a: number, b: number): number {
  if (b === 0) throw new ZeroDivisionError('float modulo');
  let mod = a % b; // fmod
  if (mod) {
    if ((b < 0) !== (mod < 0)) mod += b;
  } else {
    mod = b < 0 && !(Number.isSafeInteger(a) && Number.isSafeInteger(b)) ? -0 : 0;
  }
  return mod;
}

/** ``divmod(a, b)`` with CPython ``float_divmod`` semantics. */
export function pyDivmod(a: number, b: number): [number, number] {
  if (b === 0) throw new ZeroDivisionError('float divmod()');
  let mod = a % b;
  let div = (a - mod) / b;
  if (mod) {
    if ((b < 0) !== (mod < 0)) {
      mod += b;
      div -= 1.0;
    }
  } else {
    mod = b < 0 ? -0 : 0;
  }
  let floordiv: number;
  if (div) {
    floordiv = Math.floor(div);
    if (div - floordiv > 0.5) floordiv += 1.0;
  } else {
    floordiv = Object.is(a / b, -0) || a / b < 0 ? -0 : 0; // copysign(0.0, a / b)
  }
  if (Number.isSafeInteger(a) && Number.isSafeInteger(b)) {
    // Python ints: same values (the float algorithm is exact here) but no -0.
    return [floordiv === 0 ? 0 : floordiv, mod === 0 ? 0 : mod];
  }
  return [floordiv, mod];
}

/** ``int(x)`` for numbers (truncation) and numeric strings (base 10). */
export function pyInt(value: number | string | boolean, base = 10): number {
  if (typeof value === 'boolean') return value ? 1 : 0;
  if (typeof value === 'number') {
    if (Number.isNaN(value)) throw new ValueError('cannot convert float NaN to integer');
    if (!Number.isFinite(value)) throw new OverflowError('cannot convert float infinity to integer');
    const truncated = Math.trunc(value);
    return truncated === 0 ? 0 : truncated;
  }
  const text = value.trim().replace(/_/g, '');
  const pattern = base === 16 ? /^[+-]?(0x)?[0-9a-f]+$/i : base === 10 ? /^[+-]?\d+$/ : /^[+-]?[0-9a-z]+$/i;
  if (!pattern.test(text)) throw new ValueError(`invalid literal for int() with base ${base}: '${value}'`);
  const negative = text.startsWith('-');
  let digits = text.replace(/^[+-]/, '');
  if (base === 16) digits = digits.replace(/^0x/i, '');
  let result = 0n;
  const bigBase = BigInt(base);
  for (const ch of digits.toLowerCase()) {
    const digit = parseInt(ch, 36);
    if (Number.isNaN(digit) || digit >= base) throw new ValueError(`invalid literal for int() with base ${base}: '${value}'`);
    result = result * bigBase + BigInt(digit);
  }
  const number = Number(negative ? -result : result);
  return number === 0 ? 0 : number;
}

/** ``float(x)`` for numbers and strings (accepts ``inf``, ``nan``, ``1e5``, surrounding whitespace). */
export function pyFloatParse(value: number | string | boolean): number {
  if (typeof value === 'boolean') return value ? 1 : 0;
  if (typeof value === 'number') return value;
  const text = value.trim().replace(/_/g, '').toLowerCase();
  if (/^[+-]?(inf|infinity)$/.test(text)) return text.startsWith('-') ? -Infinity : Infinity;
  if (/^[+-]?nan$/.test(text)) return NaN;
  if (!/^[+-]?(\d+\.?\d*|\.\d+)(e[+-]?\d+)?$/.test(text)) throw new ValueError(`could not convert string to float: '${value}'`);
  return Number(text);
}

/** ``abs(x)`` */
export function pyAbs(x: number): number {
  return Math.abs(x);
}

/** ``sum(iterable, start=0)`` left to right (CPython 3.11: no compensated summation). */
export function pySum(values: Iterable<number | boolean>, start = 0): number {
  let total = start;
  for (const value of values) total += Number(value);
  return total;
}
