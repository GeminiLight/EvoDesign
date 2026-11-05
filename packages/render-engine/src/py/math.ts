// Python ``math`` module (MIGRATION_PLAN.md §4).
//
// Every ``math.*`` call in the port goes through here so that last-bit
// differences between V8 and CPython can be fixed in one place.
//
// * ``hypot`` / ``dist`` are ports of CPython 3.11 ``vector_norm`` (an
//   extended-precision algorithm); ``Math.hypot`` differs from Python in the
//   last bit for roughly a quarter of inputs, so never use ``Math.hypot``.
// * ``ceil`` / ``floor`` return ints and raise like Python on NaN/inf.
// * ``sqrt`` / ``log`` raise ``ValueError`` on domain errors like Python.
// * ``sin`` / ``cos`` / ``atan2`` / ``log`` / ``exp`` use V8's fdlibm; see
//   notes/WP01.md for the measured agreement with CPython on macOS.

import { OverflowError, ValueError } from './errors.ts';

export const pi = Math.PI;
export const e = Math.E;
export const tau = 2 * Math.PI;
export const inf = Infinity;
export const nan = NaN;

/** ``math.frexp(x)`` -> ``[mantissa, exponent]`` with ``0.5 <= |mantissa| < 1``. */
export function frexp(x: number): [number, number] {
  if (x === 0 || !Number.isFinite(x)) return [x, 0];
  const view = new DataView(new ArrayBuffer(8));
  view.setFloat64(0, x);
  let biased = (view.getUint16(0) >>> 4) & 0x7ff;
  let shift = 0;
  if (biased === 0) {
    // Subnormal: normalise by 2**64 first.
    view.setFloat64(0, x * 18446744073709551616);
    biased = (view.getUint16(0) >>> 4) & 0x7ff;
    shift = -64;
  }
  const exponent = biased - 1022;
  // Replace the exponent bits with 1022 (value in [0.5, 1)).
  const hi = view.getUint16(0);
  view.setUint16(0, (hi & 0x800f) | (1022 << 4));
  return [view.getFloat64(0), exponent + shift];
}

/** Exact ``2 ** k`` for integer ``k`` in [-1074, 1023]. */
function pow2(k: number): number {
  if (k > 1023) return Infinity;
  if (k < -1074) return 0;
  if (k < -1022) return pow2(k + 64) / 18446744073709551616;
  const view = new DataView(new ArrayBuffer(8));
  view.setUint16(0, (k + 1023) << 4);
  return view.getFloat64(0);
}

/** ``math.ldexp(x, i)`` */
export function ldexp(x: number, i: number): number {
  if (x === 0 || !Number.isFinite(x)) return x;
  // Split the scaling so intermediate powers stay representable.
  let result = x;
  let k = i;
  while (k > 1000) {
    result *= pow2(1000);
    k -= 1000;
  }
  while (k < -1000) {
    result *= pow2(-1000);
    k += 1000;
  }
  return result * pow2(k);
}

const DBL_MIN = 2.2250738585072014e-308;
const T27 = 134217729.0; // ldexp(1.0, 27) + 1.0

/** CPython 3.11 ``vector_norm`` over non-negative finite (or inf/nan flagged) components. */
function vectorNorm(vec: number[], max: number, foundNan: boolean): number {
  const n = vec.length;
  if (max === Infinity) return max;
  if (foundNan) return NaN;
  if (max === 0 || n <= 1) return max;
  const maxE = frexp(max)[1];
  if (maxE < -1023) {
    for (let i = 0; i < n; i += 1) vec[i] /= DBL_MIN;
    return DBL_MIN * vectorNorm(vec, max / DBL_MIN, foundNan);
  }
  const scale = pow2(-maxE);
  let csum = 1.0;
  let frac1 = 0.0;
  let frac2 = 0.0;
  let frac3 = 0.0;
  let x: number;
  let t: number;
  let hi: number;
  let lo: number;
  let oldcsum: number;
  for (let i = 0; i < n; i += 1) {
    x = vec[i];
    x *= scale;
    t = x * T27;
    hi = t - (t - x);
    lo = x - hi;

    x = hi * hi;
    oldcsum = csum;
    csum += x;
    frac1 += (oldcsum - csum) + x;

    x = 2.0 * hi * lo;
    oldcsum = csum;
    csum += x;
    frac2 += (oldcsum - csum) + x;

    frac3 += lo * lo;
  }
  const h = Math.sqrt(csum - 1.0 + (frac1 + frac2 + frac3));

  x = h;
  t = x * T27;
  hi = t - (t - x);
  lo = x - hi;

  x = -hi * hi;
  oldcsum = csum;
  csum += x;
  frac1 += (oldcsum - csum) + x;

  x = -2.0 * hi * lo;
  oldcsum = csum;
  csum += x;
  frac2 += (oldcsum - csum) + x;

  x = -lo * lo;
  oldcsum = csum;
  csum += x;
  frac3 += (oldcsum - csum) + x;

  x = csum - 1.0 + (frac1 + frac2 + frac3);
  return (h + x / (2.0 * h)) / scale;
}

/** ``math.hypot(*coordinates)`` — bit-identical to CPython 3.11. */
export function hypot(...coordinates: number[]): number {
  const vec: number[] = [];
  let max = 0.0;
  let foundNan = false;
  for (const value of coordinates) {
    const x = Math.abs(Number(value));
    vec.push(x);
    foundNan ||= Number.isNaN(x);
    if (x > max) max = x;
  }
  return vectorNorm(vec, max, foundNan);
}

/** ``math.dist(p, q)`` — bit-identical to CPython 3.11. */
export function dist(p: readonly number[], q: readonly number[]): number {
  if (p.length !== q.length) throw new ValueError('both points must have the same number of dimensions');
  const vec: number[] = [];
  let max = 0.0;
  let foundNan = false;
  for (let i = 0; i < p.length; i += 1) {
    const x = Math.abs(Number(p[i]) - Number(q[i]));
    vec.push(x);
    foundNan ||= Number.isNaN(x);
    if (x > max) max = x;
  }
  return vectorNorm(vec, max, foundNan);
}

/** ``math.ceil(x)`` (returns an int; raises on NaN/inf). */
export function ceil(x: number): number {
  if (Number.isNaN(x)) throw new ValueError('cannot convert float NaN to integer');
  if (!Number.isFinite(x)) throw new OverflowError('cannot convert float infinity to integer');
  const r = Math.ceil(x);
  return r === 0 ? 0 : r;
}

/** ``math.floor(x)`` (returns an int; raises on NaN/inf). */
export function floor(x: number): number {
  if (Number.isNaN(x)) throw new ValueError('cannot convert float NaN to integer');
  if (!Number.isFinite(x)) throw new OverflowError('cannot convert float infinity to integer');
  const r = Math.floor(x);
  return r === 0 ? 0 : r;
}

/** ``math.trunc(x)`` */
export function trunc(x: number): number {
  if (Number.isNaN(x)) throw new ValueError('cannot convert float NaN to integer');
  if (!Number.isFinite(x)) throw new OverflowError('cannot convert float infinity to integer');
  const r = Math.trunc(x);
  return r === 0 ? 0 : r;
}

/** ``math.copysign(x, y)`` */
export function copysign(x: number, y: number): number {
  const magnitude = Math.abs(x);
  const negative = y < 0 || Object.is(y, -0) || (Number.isNaN(y) && signBit(y));
  return negative ? -magnitude : magnitude;
}

function signBit(x: number): boolean {
  const view = new DataView(new ArrayBuffer(8));
  view.setFloat64(0, x);
  return (view.getUint8(0) & 0x80) !== 0;
}

/** ``math.fabs(x)`` */
export function fabs(x: number): number {
  return Math.abs(x);
}

/** ``math.sqrt(x)`` (correctly rounded in both runtimes). */
export function sqrt(x: number): number {
  if (x < 0) throw new ValueError('math domain error');
  return Math.sqrt(x);
}

/** ``math.log(x[, base])`` — ``log(x) / log(base)`` like CPython. */
export function log(x: number, base?: number): number {
  const num = logOne(x);
  if (base === undefined) return num;
  const den = logOne(base);
  if (den === 0) throw new ValueError('float division by zero');
  return num / den;
}

function logOne(x: number): number {
  if (Number.isNaN(x)) return x;
  if (x <= 0) throw new ValueError('math domain error');
  return Math.log(x);
}

/** ``math.log2(x)`` */
export function log2(x: number): number {
  if (Number.isNaN(x)) return x;
  if (x <= 0) throw new ValueError('math domain error');
  return Math.log2(x);
}

/** ``math.log10(x)`` */
export function log10(x: number): number {
  if (Number.isNaN(x)) return x;
  if (x <= 0) throw new ValueError('math domain error');
  return Math.log10(x);
}

/** ``math.exp(x)`` */
export function exp(x: number): number {
  const r = Math.exp(x);
  if (r === Infinity && Number.isFinite(x)) throw new OverflowError('math range error');
  return r;
}

/** ``math.pow(x, y)`` / ``x ** y`` for floats. */
export function pow(x: number, y: number): number {
  return Math.pow(x, y);
}

export function sin(x: number): number {
  if (!Number.isFinite(x) && !Number.isNaN(x)) throw new ValueError('math domain error');
  return Math.sin(x);
}

export function cos(x: number): number {
  if (!Number.isFinite(x) && !Number.isNaN(x)) throw new ValueError('math domain error');
  return Math.cos(x);
}

export function tan(x: number): number {
  if (!Number.isFinite(x) && !Number.isNaN(x)) throw new ValueError('math domain error');
  return Math.tan(x);
}

export function atan2(y: number, x: number): number {
  return Math.atan2(y, x);
}

export function atan(x: number): number {
  return Math.atan(x);
}

export function asin(x: number): number {
  if (x < -1 || x > 1) throw new ValueError('math domain error');
  return Math.asin(x);
}

export function acos(x: number): number {
  if (x < -1 || x > 1) throw new ValueError('math domain error');
  return Math.acos(x);
}

/** ``math.degrees(x)`` — CPython multiplies by ``180 / pi``. */
export function degrees(x: number): number {
  return x * (180.0 / Math.PI);
}

/** ``math.radians(x)`` — CPython multiplies by ``pi / 180``. */
export function radians(x: number): number {
  return x * (Math.PI / 180.0);
}

export function isfinite(x: number): boolean {
  return Number.isFinite(x);
}

export function isinf(x: number): boolean {
  return x === Infinity || x === -Infinity;
}

export function isnan(x: number): boolean {
  return Number.isNaN(x);
}

/** ``math.isclose(a, b, *, rel_tol=1e-09, abs_tol=0.0)`` */
export function isclose(a: number, b: number, relTol = 1e-9, absTol = 0.0): boolean {
  if (relTol < 0 || absTol < 0) throw new ValueError('tolerances must be non-negative');
  if (a === b) return true;
  if (!Number.isFinite(a) || !Number.isFinite(b)) return false;
  const diff = Math.abs(b - a);
  return (diff <= Math.abs(relTol * b)) || (diff <= Math.abs(relTol * a)) || (diff <= absTol);
}
