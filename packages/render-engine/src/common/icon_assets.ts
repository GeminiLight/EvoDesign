// Ported from evodesign/agentic_system/common/icon_assets.py — keep in sync.
//
// Shared Material icon asset contract.
//
// The canonical runtime URL is ``/icons/material-design-icons/{color}/{icon}.svg``.
// Actual SVG files are generated locally and ignored by git, while
// ``manifest.json`` is tracked and is the stable icon-name catalog.
//
// Paths: Python returns ``pathlib.Path`` objects. The port returns POSIX path
// strings relative to ``evodesign/agentic_system`` (the ``py/assets.ts``
// convention), so they can be handed straight to ``readAssetText`` etc.

import { assetExists, globAssets, readAssetText } from '../py/assets.ts';
import { pyGet, pyValues } from '../py/dict.ts';
import { IndexError, KeyError, RuntimeError, ValueError } from '../py/errors.ts';
import { pyJsonLoads } from '../py/json.ts';
import { pyRepr, pyRsplit, pyStrip } from '../py/str.ts';
import { isDict, isList, isStr, truthy } from '../py/truthy.ts';
import { TLDrawColorValidator } from './tldraw_utils.ts';

export const ICON_ROUTE_PREFIX = '/icons/material-design-icons/';
export const LEGACY_ICON_ROUTE_PREFIX = '/material-icons/';
export const ICON_FALLBACK_NAME = 'label';
export const FALLBACK_ICON_FOLDER = 'filled';

/** ``Path(__file__).resolve().parents[1] / "tool_services/public/icons/material-design-icons"`` */
export function icon_assets_root(): string {
  return 'tool_services/public/icons/material-design-icons';
}

export function icon_manifest_path(): string {
  return `${icon_assets_root()}/manifest.json`;
}

/** Return the number of generated Material icon SVG files available locally. */
export function icon_svg_count(): number {
  const root = icon_assets_root();
  if (!assetExists(root)) {
    return 0;
  }
  return globAssets(root, '*/*.svg').length;
}

/** Fail fast when icon generation is enabled but runtime SVG assets are absent. */
export function require_icon_assets_available(): null {
  const manifest = icon_manifest_path();
  if (!assetExists(manifest)) {
    throw new RuntimeError(
      'Icon generation is enabled, but the Material icon manifest is missing: '
      + `${manifest}. Disable icons or run the icon setup step first.`,
    );
  }
  if (icon_svg_count() === 0) {
    throw new RuntimeError(
      'Icon generation is enabled, but no Material icon SVG files were found under '
      + `${icon_assets_root()}. Disable icons or run `
      + '`python -m evodesign.scripts.setup_icons` before generating diagrams with icons.',
    );
  }
  // Surface an unreadable/empty catalog here rather than letting every icon
  // name validate as "unknown catalog, allow anything" until render time.
  manifest_icon_names();
  return null;
}

/** Raised when the tracked icon manifest exists but cannot be trusted. */
export class IconManifestError extends RuntimeError {}

let _manifestIconNamesCache: ReadonlySet<string> | null = null;

/**
 * Return the catalog of known icon names.
 *
 * An empty result means "no manifest is installed", which callers treat as an
 * unknown catalog. A manifest that exists but cannot be parsed, or that
 * carries no icon names, raises instead: silently returning an empty set there
 * would turn every hallucinated icon name into a valid one. Failures are not
 * memoized (``lru_cache`` semantics), so a repaired manifest is picked up on
 * the next call.
 */
export function manifest_icon_names(): ReadonlySet<string> {
  if (_manifestIconNamesCache !== null) return _manifestIconNamesCache;
  const manifest_path = icon_manifest_path();
  if (!assetExists(manifest_path)) {
    _manifestIconNamesCache = new Set<string>();
    return _manifestIconNamesCache;
  }

  let manifest: unknown;
  try {
    manifest = pyJsonLoads(readAssetText(manifest_path));
  } catch (exc) {
    // OSError / json.JSONDecodeError
    throw new IconManifestError(
      `Material icon manifest is unreadable: ${manifest_path}: ${(exc as Error)?.message ?? String(exc)}. `
      + 'Restore it from git or re-run `python -m evodesign.scripts.setup_icons`.',
    );
  }

  const names = new Set<string>();
  const colors = isDict(manifest) ? pyGet(manifest, 'colors') : null;
  if (isDict(colors)) {
    for (const color_data of pyValues(colors)) {
      if (!isDict(color_data)) {
        continue;
      }
      const icons = pyGet(color_data, 'icons');
      if (!isList(icons)) {
        continue;
      }
      for (const icon of icons) {
        if (!isDict(icon)) {
          continue;
        }
        const name = pyGet(icon, 'name');
        if (isStr(name) && name) {
          names.add(name);
        }
      }
    }
  }

  if (!names.size) {
    throw new IconManifestError(
      `Material icon manifest declares no icon names: ${manifest_path}. `
      + 'Restore it from git or re-run `python -m evodesign.scripts.setup_icons`.',
    );
  }
  _manifestIconNamesCache = names;
  return names;
}
/** ``manifest_icon_names.cache_clear()`` */
manifest_icon_names.cache_clear = (): void => {
  _manifestIconNamesCache = null;
};

/** Return whether *icon_name* is in the catalog (permissive without one). */
export function icon_name_exists(icon_name: string): boolean {
  const names = manifest_icon_names();
  return !names.size || names.has(icon_name);
}

export function color_to_icon_folder(color: string | null): string {
  return TLDrawColorValidator.normalize_color(truthy(color) ? color! : 'black').replaceAll('-', '_');
}

export function icon_name_from_filename(filename: string): string {
  const name = pyRsplit(filename, '/', 1).at(-1)!;
  return name.endsWith('.svg') ? name.slice(0, -4) : name;
}

export function icon_filename(icon_name: string): string {
  const name = pyRsplit(icon_name, '/', 1).at(-1)!;
  return name.endsWith('.svg') ? name : `${name}.svg`;
}

/**
 * ``template.format(**fields)`` for plain ``{name}`` replacement fields and
 * ``{{`` / ``}}`` escapes (conversions and format specs are not used by icon
 * URL templates and raise ``ValueError`` here).
 */
function _strFormat(template: string, fields: Record<string, string>): string {
  let out = '';
  let i = 0;
  while (i < template.length) {
    const ch = template[i];
    if (ch === '{') {
      if (template[i + 1] === '{') {
        out += '{';
        i += 2;
        continue;
      }
      const close = template.indexOf('}', i + 1);
      if (close < 0) throw new ValueError("expected '}' before end of string");
      const field = template.slice(i + 1, close);
      if (field === '' || /^\d+$/.test(field)) throw new IndexError('Replacement index 0 out of range for positional args tuple');
      if (/[!:.[{]/.test(field)) throw new ValueError(`unsupported format field ${pyRepr(field)} in port`);
      if (!Object.prototype.hasOwnProperty.call(fields, field)) throw new KeyError(pyRepr(field));
      out += fields[field];
      i = close + 1;
      continue;
    }
    if (ch === '}') {
      if (template[i + 1] === '}') {
        out += '}';
        i += 2;
        continue;
      }
      throw new ValueError("Single '}' encountered in format string");
    }
    out += ch;
    i += 1;
  }
  return out;
}

export function format_icon_url(icon_name: string, icon_color: string, base_url: string): string {
  return _strFormat(base_url, {
    color: color_to_icon_folder(icon_color),
    icon: icon_name_from_filename(icon_name),
  });
}

/** Return whether a URL/path points at the bundled Material icon route. */
export function is_local_material_icon_url(icon_url: string): boolean {
  const path = icon_url_path(icon_url);
  return path.includes(ICON_ROUTE_PREFIX) || path.includes(LEGACY_ICON_ROUTE_PREFIX);
}

const _WHATWG_C0_CONTROL_OR_SPACE = /^[\x00-\x20]+/;
const _SCHEME_CHARS = /^[A-Za-z0-9+.-]*$/;
const _USES_PARAMS = new Set(['', 'ftp', 'hdl', 'prospero', 'http', 'imap',
  'https', 'shttp', 'rtsp', 'rtsps', 'rtspu', 'sip',
  'sips', 'mms', 'sftp', 'tel']);

/** ``urllib.parse.urlparse(url)`` (CPython 3.11) -> scheme, netloc, path. */
function _urlparse(source: string): { scheme: string; netloc: string; path: string } {
  let url = source.replace(_WHATWG_C0_CONTROL_OR_SPACE, '');
  for (const b of ['\t', '\r', '\n']) url = url.replaceAll(b, '');
  let scheme = '';
  let netloc = '';
  const i = url.indexOf(':');
  if (i > 0 && /^[A-Za-z]/.test(url[0]) && _SCHEME_CHARS.test(url.slice(0, i))) {
    scheme = url.slice(0, i).toLowerCase();
    url = url.slice(i + 1);
  }
  if (url.slice(0, 2) === '//') {
    let delim = url.length;
    for (const c of '/?#') {
      const wdelim = url.indexOf(c, 2);
      if (wdelim >= 0) delim = Math.min(delim, wdelim);
    }
    netloc = url.slice(2, delim);
    url = url.slice(delim);
    if ((netloc.includes('[') && !netloc.includes(']')) || (netloc.includes(']') && !netloc.includes('['))) {
      throw new ValueError('Invalid IPv6 URL');
    }
  }
  if (url.includes('#')) url = url.slice(0, url.indexOf('#'));
  if (url.includes('?')) url = url.slice(0, url.indexOf('?'));
  if (_USES_PARAMS.has(scheme) && url.includes(';')) {
    // _splitparams
    let j: number;
    if (url.includes('/')) {
      j = url.indexOf(';', url.lastIndexOf('/'));
      if (j >= 0) url = url.slice(0, j);
    } else {
      j = url.indexOf(';');
      url = url.slice(0, j);
    }
  }
  return { scheme, netloc, path: url };
}

export function icon_url_path(icon_url: string): string {
  if (!isStr(icon_url) || !icon_url) {
    return '';
  }
  const parsed = _urlparse(icon_url);
  return parsed.scheme || parsed.netloc ? parsed.path : icon_url;
}

export function icon_folder_hint(icon_url: string): string | null {
  const path = icon_url_path(icon_url);
  for (const prefix of [ICON_ROUTE_PREFIX, LEGACY_ICON_ROUTE_PREFIX]) {
    if (!path.includes(prefix)) {
      continue;
    }
    const suffix = path.slice(path.indexOf(prefix) + prefix.length).replace(/^\/+/, '');
    const slash = suffix.indexOf('/');
    const folder = slash < 0 ? suffix : suffix.slice(0, slash);
    if (folder) {
      return folder;
    }
  }
  return null;
}

/** ``root / folder / filename`` (pathlib joining; an absolute part resets). */
function _joinPath(...parts: string[]): string {
  let out = '';
  for (const part of parts) {
    if (part.startsWith('/')) out = part;
    else out = out ? `${out.replace(/\/+$/, '')}/${part}` : part;
  }
  return out;
}

export function resolve_icon_svg_path(filename: string, folders: Iterable<string>): string | null {
  if (!truthy(filename)) {
    return null;
  }
  filename = icon_filename(filename);
  const root = icon_assets_root();
  const seen = new Set<string>();
  for (const folder of folders) {
    if (!truthy(folder) || seen.has(folder)) {
      continue;
    }
    seen.add(folder);
    const candidate = _joinPath(root, folder, filename);
    if (assetExists(candidate)) {
      return candidate;
    }
  }
  return null;
}

/** Resolve a concrete SVG asset or raise with an actionable diagnostic. */
export function require_icon_svg_path(
  icon_name: string,
  icon_color: string | null = null,
  icon_url = '',
  element_id: string | null = null,
): string {
  if (!isStr(icon_name) || !pyStrip(icon_name)) {
    const target = truthy(element_id) ? ` for ${element_id}` : '';
    throw new RuntimeError(`Icon asset reference${target} is missing an icon name.`);
  }

  const candidate_folders: string[] = [];
  const folder_hint = icon_folder_hint(icon_url);
  if (truthy(folder_hint)) {
    candidate_folders.push(folder_hint!);
  }
  if (truthy(icon_color)) {
    candidate_folders.push(color_to_icon_folder(icon_color));
  }
  candidate_folders.push(FALLBACK_ICON_FOLDER);

  const resolved = resolve_icon_svg_path(pyStrip(icon_name), candidate_folders);
  if (resolved !== null) {
    return resolved;
  }

  const target = truthy(element_id) ? ` for ${element_id}` : '';
  const folders = [...new Set(candidate_folders)].join(', ');
  throw new RuntimeError(
    `Icon asset not found${target}: icon=${pyRepr(icon_name)}, `
    + `color=${pyRepr(icon_color)}, folders=[${folders}], root=${icon_assets_root()}. `
    + 'Run `python -m evodesign.scripts.setup_icons` or disable icon generation.',
  );
}

export const __all__ = [
  'ICON_FALLBACK_NAME',
  'ICON_ROUTE_PREFIX',
  'LEGACY_ICON_ROUTE_PREFIX',
  'FALLBACK_ICON_FOLDER',
  'IconManifestError',
  'color_to_icon_folder',
  'format_icon_url',
  'icon_assets_root',
  'icon_filename',
  'icon_folder_hint',
  'icon_manifest_path',
  'icon_svg_count',
  'icon_name_exists',
  'icon_name_from_filename',
  'icon_url_path',
  'is_local_material_icon_url',
  'manifest_icon_names',
  'require_icon_svg_path',
  'require_icon_assets_available',
  'resolve_icon_svg_path',
];
