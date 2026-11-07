// POSIX path helpers with Node ``node:path`` (posix) semantics (PHASE3_PLAN.md WP27).
//
// Pipeline modules import these instead of ``node:path`` so the same code runs
// in browsers. ``resolve`` uses the working directory of the active RuntimeFS
// (``getFS().cwd()``): ``process.cwd()`` for NodeFS, a fixed pseudo directory
// for MemoryFS. Windows paths are not supported (Node on Windows would use
// ``path.win32``; the pipeline only runs on POSIX hosts and in browsers).

import { getFS } from './fs.ts';

export const sep = '/';
export const delimiter = ':';

/** Node's ``normalizeString`` for POSIX (resolves ``.``/``..``, drops empty segments). */
function normalizeString(path: string, allowAboveRoot: boolean): string {
  let res = '';
  let lastSegmentLength = 0;
  let lastSlash = -1;
  let dots = 0;
  let code = 0;
  for (let i = 0; i <= path.length; ++i) {
    if (i < path.length) code = path.charCodeAt(i);
    else if (code === 47) break;
    else code = 47;
    if (code === 47) {
      if (lastSlash === i - 1 || dots === 1) {
        // NOOP
      } else if (dots === 2) {
        if (res.length < 2 || lastSegmentLength !== 2 || res.charCodeAt(res.length - 1) !== 46 || res.charCodeAt(res.length - 2) !== 46) {
          if (res.length > 2) {
            const lastSlashIndex = res.lastIndexOf('/');
            if (lastSlashIndex === -1) {
              res = '';
              lastSegmentLength = 0;
            } else {
              res = res.slice(0, lastSlashIndex);
              lastSegmentLength = res.length - 1 - res.lastIndexOf('/');
            }
            lastSlash = i;
            dots = 0;
            continue;
          } else if (res.length !== 0) {
            res = '';
            lastSegmentLength = 0;
            lastSlash = i;
            dots = 0;
            continue;
          }
        }
        if (allowAboveRoot) {
          res += res.length > 0 ? '/..' : '..';
          lastSegmentLength = 2;
        }
      } else {
        if (res.length > 0) res += `/${path.slice(lastSlash + 1, i)}`;
        else res = path.slice(lastSlash + 1, i);
        lastSegmentLength = i - lastSlash - 1;
      }
      lastSlash = i;
      dots = 0;
    } else if (code === 46 && dots !== -1) {
      ++dots;
    } else {
      dots = -1;
    }
  }
  return res;
}

export function isAbsolute(path: string): boolean {
  return path.length > 0 && path.charCodeAt(0) === 47;
}

export function normalize(path: string): string {
  if (path.length === 0) return '.';
  const absolute = isAbsolute(path);
  const trailingSeparator = path.charCodeAt(path.length - 1) === 47;
  let out = normalizeString(path, !absolute);
  if (out.length === 0) {
    if (absolute) return '/';
    return trailingSeparator ? './' : '.';
  }
  if (trailingSeparator) out += '/';
  return absolute ? `/${out}` : out;
}

export function join(...paths: string[]): string {
  if (paths.length === 0) return '.';
  let joined: string | undefined;
  for (const arg of paths) {
    if (typeof arg !== 'string') throw new TypeError(`The "path" argument must be of type string. Received ${typeof arg}`);
    if (arg.length > 0) joined = joined === undefined ? arg : `${joined}/${arg}`;
  }
  return joined === undefined ? '.' : normalize(joined);
}

export function resolve(...paths: string[]): string {
  let resolvedPath = '';
  let resolvedAbsolute = false;
  for (let i = paths.length - 1; i >= -1 && !resolvedAbsolute; i--) {
    const path = i >= 0 ? paths[i] : getFS().cwd();
    if (typeof path !== 'string') throw new TypeError(`The "path" argument must be of type string. Received ${typeof path}`);
    if (path.length === 0) continue;
    resolvedPath = `${path}/${resolvedPath}`;
    resolvedAbsolute = path.charCodeAt(0) === 47;
  }
  resolvedPath = normalizeString(resolvedPath, !resolvedAbsolute);
  if (resolvedAbsolute) return `/${resolvedPath}`;
  return resolvedPath.length > 0 ? resolvedPath : '.';
}

export function relative(from: string, to: string): string {
  if (from === to) return '';
  from = resolve(from);
  to = resolve(to);
  if (from === to) return '';
  const fromStart = 1;
  const fromEnd = from.length;
  const fromLen = fromEnd - fromStart;
  const toStart = 1;
  const toLen = to.length - toStart;
  const length = fromLen < toLen ? fromLen : toLen;
  let lastCommonSep = -1;
  let i = 0;
  for (; i < length; i++) {
    const fromCode = from.charCodeAt(fromStart + i);
    if (fromCode !== to.charCodeAt(toStart + i)) break;
    else if (fromCode === 47) lastCommonSep = i;
  }
  if (i === length) {
    if (toLen > length) {
      if (to.charCodeAt(toStart + i) === 47) return to.slice(toStart + i + 1);
      if (i === 0) return to.slice(toStart + i);
    } else if (fromLen > length) {
      if (from.charCodeAt(fromStart + i) === 47) lastCommonSep = i;
      else if (i === 0) lastCommonSep = 0;
    }
  }
  let out = '';
  for (i = fromStart + lastCommonSep + 1; i <= fromEnd; ++i) {
    if (i === fromEnd || from.charCodeAt(i) === 47) out += out.length === 0 ? '..' : '/..';
  }
  return `${out}${to.slice(toStart + lastCommonSep)}`;
}

export function dirname(path: string): string {
  if (path.length === 0) return '.';
  const hasRoot = path.charCodeAt(0) === 47;
  let end = -1;
  let matchedSlash = true;
  for (let i = path.length - 1; i >= 1; --i) {
    if (path.charCodeAt(i) === 47) {
      if (!matchedSlash) {
        end = i;
        break;
      }
    } else {
      matchedSlash = false;
    }
  }
  if (end === -1) return hasRoot ? '/' : '.';
  if (hasRoot && end === 1) return '//';
  return path.slice(0, end);
}

export function basename(path: string, suffix?: string): string {
  let start = 0;
  let end = -1;
  let matchedSlash = true;
  if (suffix !== undefined && suffix.length > 0 && suffix.length <= path.length) {
    if (suffix === path) return '';
    let extIdx = suffix.length - 1;
    let firstNonSlashEnd = -1;
    for (let i = path.length - 1; i >= 0; --i) {
      const code = path.charCodeAt(i);
      if (code === 47) {
        if (!matchedSlash) {
          start = i + 1;
          break;
        }
      } else {
        if (firstNonSlashEnd === -1) {
          matchedSlash = false;
          firstNonSlashEnd = i + 1;
        }
        if (extIdx >= 0) {
          if (code === suffix.charCodeAt(extIdx)) {
            if (--extIdx === -1) end = i;
          } else {
            extIdx = -1;
            end = firstNonSlashEnd;
          }
        }
      }
    }
    if (start === end) end = firstNonSlashEnd;
    else if (end === -1) end = path.length;
    return path.slice(start, end);
  }
  for (let i = path.length - 1; i >= 0; --i) {
    if (path.charCodeAt(i) === 47) {
      if (!matchedSlash) {
        start = i + 1;
        break;
      }
    } else if (end === -1) {
      matchedSlash = false;
      end = i + 1;
    }
  }
  if (end === -1) return '';
  return path.slice(start, end);
}

export function extname(path: string): string {
  let startDot = -1;
  let startPart = 0;
  let end = -1;
  let matchedSlash = true;
  let preDotState = 0;
  for (let i = path.length - 1; i >= 0; --i) {
    const code = path.charCodeAt(i);
    if (code === 47) {
      if (!matchedSlash) {
        startPart = i + 1;
        break;
      }
      continue;
    }
    if (end === -1) {
      matchedSlash = false;
      end = i + 1;
    }
    if (code === 46) {
      if (startDot === -1) startDot = i;
      else if (preDotState !== 1) preDotState = 1;
    } else if (startDot !== -1) {
      preDotState = -1;
    }
  }
  if (startDot === -1 || end === -1 || preDotState === 0 || (preDotState === 1 && startDot === end - 1 && startDot === startPart + 1)) {
    return '';
  }
  return path.slice(startDot, end);
}

export const posix = { sep, delimiter, isAbsolute, normalize, join, resolve, relative, dirname, basename, extname };
export default posix;
