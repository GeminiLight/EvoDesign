// Ported from evodesign/agentic_system/common/node_icons.py — keep in sync.
//
// Portable node icons: trusted assets, explicit ownership and content geometry.
//
// ``icon_svg`` uses ``xml.etree.ElementTree`` in Python. There is no XML
// library in the browser-safe runtime, so this file carries a small
// ElementTree-compatible parser/serializer (``_EtElement``, ``_etFromstring``,
// ``_etTostring``) that reproduces ``ET.fromstring`` + ``ET.tostring(root,
// encoding="unicode")`` for the bundled icons: expat namespace resolution,
// attribute insertion order, ``xmlns`` declarations first, `` />`` for empty
// elements, and ElementTree's escaping rules.

import { copyF, isF, markF } from '../py/float_marks.ts';
import { readAssetJson } from '../py/assets.ts';
import { pyGet, pyGetItem, pyItems, pySetdefault, type PyMapping } from '../py/dict.ts';
import { pyEq, pyIn, pyNe } from '../py/eq.ts';
import { PyTypeError, ValueError } from '../py/errors.ts';
import { sha256Hex, utf8Encode } from '../py/hash.ts';
import { cos, sin, sqrt } from '../py/math.ts';
import { pyFloatParse, pyInt } from '../py/number.ts';
import { pyMax, pyMaxN, pyMinN } from '../py/sort.ts';
import { isDict, isStr, pyOr, truthy } from '../py/truthy.ts';

type Dict = Record<string, any>;

export const ICON_SIZE = 26;
export const ICON_PADDING = 16;
export const ICON_GAP = 10;
export const ICON_KEY = 'evoDesignIcon';
// Architecture design-system cards lay out their own icon, title and sublabel.
export const CARD_KEY = 'evoDesignCard';
// Junction dots on shared connector trunks: decoration, never a node.
export const JUNCTION_KEY = 'evoDesignJunction';
// Zone backgrounds, zone labels and diagram titles: decoration, never a node.
export const DECORATION_KEY = 'evoDesignDecoration';

let _bundledIconsCache: Record<string, string> | null = null;

/** ``@lru_cache(maxsize=1)``: the same dict object on every call. */
export function bundled_icons(): Record<string, string> {
  if (_bundledIconsCache === null) {
    _bundledIconsCache = readAssetJson('common/assets/material_icons.json') as Record<string, string>;
  }
  return _bundledIconsCache;
}
/** ``bundled_icons.cache_clear()`` */
bundled_icons.cache_clear = (): void => {
  _bundledIconsCache = null;
};

// ---------------------------------------------------------------------------
// Minimal xml.etree.ElementTree (fromstring / iter / get / set / tostring)
// ---------------------------------------------------------------------------

const SVG_NS = 'http://www.w3.org/2000/svg';
const XML_NS = 'http://www.w3.org/XML/1998/namespace';

/** ``xml.etree.ElementTree._namespace_map`` after ``register_namespace("", SVG_NS)``. */
const _etNamespaceMap = new Map<string, string>([
  [XML_NS, 'xml'],
  ['http://www.w3.org/1999/xhtml', 'html'],
  ['http://www.w3.org/1999/02/22-rdf-syntax-ns#', 'rdf'],
  ['http://schemas.xmlsoap.org/wsdl/', 'wsdl'],
  ['http://www.w3.org/2001/XMLSchema', 'xs'],
  ['http://www.w3.org/2001/XMLSchema-instance', 'xsi'],
  ['http://purl.org/dc/elements/1.1/', 'dc'],
  [SVG_NS, ''],
]);

class _EtElement {
  tag: string;
  attrib = new Map<string, string>();
  text: string | null = null;
  tail: string | null = null;
  children: _EtElement[] = [];

  constructor(tag: string) {
    this.tag = tag;
  }

  get(key: string): string | null {
    return this.attrib.has(key) ? this.attrib.get(key)! : null;
  }

  set(key: string, value: string): void {
    this.attrib.set(key, value);
  }

  /** ``Element.iter()`` — document order, self first. */
  *iter(): Generator<_EtElement> {
    yield this;
    for (const child of this.children) yield* child.iter();
  }
}

class _EtParseError extends ValueError {}

const _XML_ENTITIES: Record<string, string> = { lt: '<', gt: '>', amp: '&', quot: '"', apos: "'" };

function _etDecodeEntities(text: string): string {
  return text.replace(/&(#x[0-9a-fA-F]+|#[0-9]+|[A-Za-z_][\w.-]*);?/g, (match, body: string) => {
    if (!match.endsWith(';')) throw new _EtParseError('not well-formed (invalid token)');
    if (body.startsWith('#x')) return String.fromCodePoint(parseInt(body.slice(2), 16));
    if (body.startsWith('#')) return String.fromCodePoint(parseInt(body.slice(1), 10));
    if (!(body in _XML_ENTITIES)) throw new _EtParseError(`undefined entity &${body};`);
    return _XML_ENTITIES[body];
  });
}

/** ``ET.fromstring(text)`` (expat + TreeBuilder; comments and PIs dropped). */
function _etFromstring(source: string): _EtElement {
  const text = source.replace(/\r\n?/g, '\n');
  let pos = 0;
  let root: _EtElement | null = null;
  const stack: { element: _EtElement; scope: Map<string, string> }[] = [];
  let lastClosed: _EtElement | null = null;
  let data = '';

  const flush = () => {
    if (!data) return;
    if (lastClosed) lastClosed.tail = (lastClosed.tail ?? '') + data;
    else if (stack.length) {
      const top = stack[stack.length - 1].element;
      top.text = (top.text ?? '') + data;
    } else if (data.trim()) throw new _EtParseError('syntax error');
    data = '';
  };

  const resolve = (qname: string, scope: Map<string, string>, isAttribute: boolean): string => {
    const colon = qname.indexOf(':');
    if (colon < 0) {
      if (isAttribute) return qname;
      const uri = scope.get('');
      return uri ? `{${uri}}${qname}` : qname;
    }
    const prefix = qname.slice(0, colon);
    const local = qname.slice(colon + 1);
    const uri = prefix === 'xml' ? XML_NS : scope.get(prefix);
    if (uri === undefined) throw new _EtParseError('unbound prefix');
    return `{${uri}}${local}`;
  };

  while (pos < text.length) {
    const lt = text.indexOf('<', pos);
    if (lt < 0) {
      data += _etDecodeEntities(text.slice(pos));
      pos = text.length;
      break;
    }
    if (lt > pos) data += _etDecodeEntities(text.slice(pos, lt));
    if (text.startsWith('<!--', lt)) {
      const end = text.indexOf('-->', lt + 4);
      if (end < 0) throw new _EtParseError('unclosed token');
      pos = end + 3;
      continue;
    }
    if (text.startsWith('<![CDATA[', lt)) {
      const end = text.indexOf(']]>', lt + 9);
      if (end < 0) throw new _EtParseError('unclosed CDATA section');
      data += text.slice(lt + 9, end);
      pos = end + 3;
      continue;
    }
    if (text.startsWith('<?', lt)) {
      const end = text.indexOf('?>', lt + 2);
      if (end < 0) throw new _EtParseError('unclosed token');
      pos = end + 2;
      continue;
    }
    if (text.startsWith('<!', lt)) {
      const end = text.indexOf('>', lt + 2);
      if (end < 0) throw new _EtParseError('unclosed token');
      pos = end + 1;
      continue;
    }
    if (text.startsWith('</', lt)) {
      const end = text.indexOf('>', lt + 2);
      if (end < 0) throw new _EtParseError('unclosed token');
      const name = text.slice(lt + 2, end).trim();
      const top = stack.pop();
      if (!top) throw new _EtParseError('not well-formed (invalid token)');
      if (resolve(name, top.scope, false) !== top.element.tag) throw new _EtParseError('mismatched tag');
      flush();
      lastClosed = top.element;
      pos = end + 1;
      continue;
    }
    // Start tag.
    const tagMatch = /^<([A-Za-z_][\w.:-]*)/.exec(text.slice(lt));
    if (!tagMatch) throw new _EtParseError('not well-formed (invalid token)');
    const rawName = tagMatch[1];
    pos = lt + tagMatch[0].length;
    const rawAttrs: [string, string][] = [];
    let selfClosing = false;
    for (;;) {
      const ws = /^\s*/.exec(text.slice(pos))![0];
      pos += ws.length;
      if (text.startsWith('/>', pos)) {
        selfClosing = true;
        pos += 2;
        break;
      }
      if (text.startsWith('>', pos)) {
        pos += 1;
        break;
      }
      const attrMatch = /^([A-Za-z_][\w.:-]*)\s*=\s*("([^"<]*)"|'([^'<]*)')/.exec(text.slice(pos));
      if (!attrMatch || !ws) throw new _EtParseError('not well-formed (invalid token)');
      const rawValue = attrMatch[3] ?? attrMatch[4];
      // Attribute-value normalisation: literal whitespace characters become spaces.
      rawAttrs.push([attrMatch[1], _etDecodeEntities(rawValue.replace(/[\t\n]/g, ' '))]);
      pos += attrMatch[0].length;
    }
    const parentScope = stack.length ? stack[stack.length - 1].scope : new Map<string, string>();
    const scope = new Map(parentScope);
    for (const [name, value] of rawAttrs) {
      if (name === 'xmlns') scope.set('', value);
      else if (name.startsWith('xmlns:')) scope.set(name.slice(6), value);
    }
    flush();
    const element = new _EtElement(resolve(rawName, scope, false));
    for (const [name, value] of rawAttrs) {
      if (name === 'xmlns' || name.startsWith('xmlns:')) continue;
      const key = resolve(name, scope, true);
      if (element.attrib.has(key)) throw new _EtParseError('duplicate attribute');
      element.attrib.set(key, value);
    }
    if (stack.length) stack[stack.length - 1].element.children.push(element);
    else if (root) throw new _EtParseError('junk after document element');
    else root = element;
    lastClosed = null;
    if (selfClosing) lastClosed = element;
    else stack.push({ element, scope });
  }
  flush();
  if (!root || stack.length) throw new _EtParseError('no element found');
  return root;
}

function _etEscapeCdata(text: string): string {
  return text.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
}

function _etEscapeAttrib(text: string): string {
  return text
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll('\r', '&#13;')
    .replaceAll('\n', '&#10;')
    .replaceAll('\t', '&#09;');
}

/** ``ET.tostring(root, encoding="unicode")`` (``short_empty_elements=True``). */
function _etTostring(root: _EtElement): string {
  // ElementTree._namespaces: qualified names and the namespaces to declare.
  const qnames = new Map<string, string>();
  const namespaces = new Map<string, string>();
  let generated = 0;
  const addQname = (qname: string) => {
    if (qnames.has(qname)) return;
    if (qname.startsWith('{')) {
      const close = qname.indexOf('}');
      const uri = qname.slice(1, close);
      const local = qname.slice(close + 1);
      let prefix = _etNamespaceMap.get(uri);
      if (prefix === undefined) {
        prefix = `ns${generated}`;
        generated += 1;
      }
      if (prefix !== 'xml') namespaces.set(uri, prefix);
      qnames.set(qname, prefix ? `${prefix}:${local}` : local);
    } else {
      qnames.set(qname, qname);
    }
  };
  for (const element of root.iter()) {
    addQname(element.tag);
    for (const key of element.attrib.keys()) addQname(key);
  }

  const out: string[] = [];
  const serialize = (element: _EtElement, declare: Map<string, string> | null) => {
    const tag = qnames.get(element.tag)!;
    out.push(`<${tag}`);
    if (declare && declare.size) {
      const sorted = [...declare.entries()].sort((a, b) => (a[1] < b[1] ? -1 : a[1] > b[1] ? 1 : 0));
      for (const [uri, prefix] of sorted) {
        out.push(` xmlns${prefix ? `:${prefix}` : ''}="${_etEscapeAttrib(uri)}"`);
      }
    }
    for (const [key, value] of element.attrib) out.push(` ${qnames.get(key)}="${_etEscapeAttrib(value)}"`);
    if (element.text || element.children.length) {
      out.push('>');
      if (element.text) out.push(_etEscapeCdata(element.text));
      for (const child of element.children) serialize(child, null);
      out.push(`</${tag}>`);
    } else {
      out.push(' />');
    }
    if (element.tail) out.push(_etEscapeCdata(element.tail));
  };
  serialize(root, namespaces);
  return out.join('');
}

function _base64Encode(bytes: Uint8Array): string {
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
  let out = '';
  for (let i = 0; i < bytes.length; i += 3) {
    const b0 = bytes[i];
    const b1 = i + 1 < bytes.length ? bytes[i + 1] : 0;
    const b2 = i + 2 < bytes.length ? bytes[i + 2] : 0;
    const triple = (b0 << 16) | (b1 << 8) | b2;
    out += alphabet[(triple >> 18) & 63] + alphabet[(triple >> 12) & 63];
    out += i + 1 < bytes.length ? alphabet[(triple >> 6) & 63] : '=';
    out += i + 2 < bytes.length ? alphabet[triple & 63] : '=';
  }
  return out;
}

// ---------------------------------------------------------------------------

/** Tint only a trusted, packaged icon; never parse arbitrary remote SVG. */
export function icon_svg(name: string, color: string): string {
  const candidate = pyOr(color as unknown, '');
  if (!isStr(candidate)) throw new PyTypeError('expected string or bytes-like object');
  color = /^#[0-9a-fA-F]{6}$/.test(candidate) ? color : '#475569';
  const root = _etFromstring(pyGetItem(bundled_icons(), name));
  // Excalidraw's SVG importer requires an unprefixed <svg> root.
  // (ET.register_namespace("", SVG_NS) is baked into _etNamespaceMap.)
  root.set('fill', color);
  for (const element of root.iter()) {
    for (const attr of ['fill', 'stroke']) {
      const value = element.get(attr);
      if (truthy(value) && !(value === 'none' || value === 'transparent')) {
        element.set(attr, color);
      }
    }
  }
  return _etTostring(root);
}

export function icon_file(name: string, color: string): Dict {
  const svg = icon_svg(name, color);
  return {
    id: sha256Hex(svg).slice(0, 20),
    mimeType: 'image/svg+xml',
    dataURL: 'data:image/svg+xml;base64,' + _base64Encode(utf8Encode(svg)),
    created: 1, lastRetrieved: 1,
  };
}

function _hostTypes(value: unknown): boolean {
  return value === 'rectangle' || value === 'ellipse';
}

/** Groups survive native duplication; IDs also support ungrouped/legacy scenes. */
export function icon_owner(icon: Dict, elements: Dict[], id_map: PyMapping | null = null): Dict | null {
  const data = pyOr(pyGet(pyOr(pyGet(icon, 'customData'), {}), ICON_KEY), {}) as Dict;
  const groups = pyOr(pyGet(icon, 'groupIds'), []) as unknown[];
  const hosts = elements.filter((e) => _hostTypes(pyGet(e, 'type')) && !truthy(pyGet(e, 'is_group')));
  // The innermost group is the node+label+icon group. Native duplication
  // rewrites group IDs but cannot rewrite arbitrary customData host IDs.
  if (truthy(groups)) {
    const matches = hosts.filter((e) => pyIn(groups[0], pyOr(pyGet(e, 'groupIds'), [])));
    if (matches.length === 1) {
      return matches[0];
    }
  }
  let host_id = pyGet(data, 'hostId');
  if (!truthy(host_id) && truthy(id_map)) {
    const found = pyItems(id_map!).find(([k, v]) => pyEq(v, pyGet(icon, 'id')) && (k as string).endsWith(':icon'));
    const key = found ? (found[0] as string) : null;
    host_id = key ? pyGet(id_map!, key.slice(0, -5)) : null;
  }
  return hosts.find((e) => pyEq(pyGet(e, 'id'), host_id)) ?? null;
}

/** Add/replace a trusted icon on an existing node; preserve all source text. */
export function set_node_icon(manifest: Dict, host_id: string, name: string): boolean {
  const elements = pyOr(pyGet(manifest, 'elements'), []) as Dict[];
  const host = elements.find((e) => pyEq(pyGet(e, 'id'), host_id)) ?? null;
  if (!pyIn(name, bundled_icons())) {
    throw new ValueError('Icon must be a bundled Material icon name.');
  }
  if (!truthy(host) || !_hostTypes(pyGet(host, 'type'))
      || truthy(pyGet(host, 'isDeleted')) || truthy(pyGet(host, 'is_group')) || truthy(pyGet(host, 'locked'))) {
    throw new ValueError('Icon host must be an unlocked visible rectangle or ellipse node.');
  }
  const texts = elements.filter((e) => pyGet(e, 'type') === 'text' && pyEq(pyGet(e, 'containerId'), host_id) && !truthy(pyGet(e, 'isDeleted')));
  if (!texts.length) {
    throw new ValueError('Icon host must retain a bound node label.');
  }
  const existing = elements.find((e) => pyGet(e, 'type') === 'image' && !truthy(pyGet(e, 'isDeleted'))
    && truthy(pyGet(pyOr(pyGet(e, 'customData'), {}), ICON_KEY))
    && icon_owner(e, elements) === host) ?? null;
  if (truthy(existing)) {
    const iconData = pyGetItem(pyGetItem(existing!, 'customData') as Dict, ICON_KEY) as Dict;
    if (pyEq(pyGet(iconData, 'name'), name)) {
      return false;
    }
    iconData.name = name;
  } else {
    const icon_id = sha256Hex('refined-icon:' + host_id).slice(0, 20);
    if (elements.some((e) => pyEq(pyGet(e, 'id'), icon_id))) {
      throw new ValueError('Icon ID already exists; refusing to overwrite an element.');
    }
    const group_id = 'icon-group-' + icon_id;
    const groups = [group_id, ..._iterate(pyGet(host, 'groupIds', []))];
    host!.groupIds = groups;
    for (const text of texts) {
      text.groupIds = [...groups];
    }
    elements.push({
      id: icon_id, type: 'image', x: pyGetItem(host!, 'x'), y: pyGetItem(host!, 'y'),
      width: ICON_SIZE, height: ICON_SIZE, angle: 0,
      strokeColor: 'transparent', backgroundColor: 'transparent',
      fillStyle: 'solid', strokeWidth: 1, strokeStyle: 'solid',
      roughness: 0, opacity: 100, groupIds: groups,
      frameId: pyGet(host, 'frameId'), roundness: null,
      index: (pyMax(elements.map((e) => pyOr(pyGet(e, 'index'), 'a0')), undefined, 'a0') as string) + 'V',
      seed: 1, version: 1, versionNonce: 1, updated: 1,
      isDeleted: false, boundElements: [], link: null, locked: false,
      status: 'saved', scale: [1, 1], crop: null,
      customData: { [ICON_KEY]: { hostId: host_id, name } },
    });
    copyF(host, 'x', elements[elements.length - 1], 'x');
    copyF(host, 'y', elements[elements.length - 1], 'y');
  }
  sync_node_icons(manifest, host_id);
  host!.version = pyInt(pyGet(host, 'version', 1) as number) + 1;
  markF(host, 'version', false);
  return true;
}

function _iterate(value: unknown): unknown[] {
  if (Array.isArray(value)) return value;
  if (typeof value === 'string') return [...value];
  if (value instanceof Set || value instanceof Map) return [...value.keys()];
  if (isDict(value)) return Object.keys(value);
  throw new PyTypeError('object is not iterable');
}

export function _sync_design_cards(elements: Dict[], host_id: string | null): null {
  const by_id = new Map<unknown, Dict>();
  for (const e of elements) by_id.set(pyGet(e, 'id'), e);
  for (const host of elements) {
    const card = pyGet(pyOr(pyGet(host, 'customData'), {}), CARD_KEY);
    if (!isDict(card) || truthy(pyGet(host, 'locked')) || (truthy(host_id) && pyNe(pyGet(host, 'id'), host_id))) {
      continue;
    }
    const part = (key: string): Dict | null => {
      const eid = pyGet(card, key);
      return isStr(eid) ? (by_id.has(eid) ? by_id.get(eid)! : null) : null;
    };

    const title = part('titleId');
    if (!truthy(title) || pyNe(pyGet(title, 'containerId'), pyGet(host, 'id')) || truthy(pyGet(title, 'isDeleted'))) {
      continue;
    }
    let icon = part('iconId');
    if (truthy(icon) && (pyNe(pyGet(pyOr(pyGet(pyOr(pyGet(icon, 'customData'), {}), ICON_KEY), {}), 'hostId'), pyGetItem(host, 'id')) || truthy(pyGet(icon, 'isDeleted')))) {
      icon = null;
    }
    let subtitle = part('sublabelId');
    if (truthy(subtitle) && (pyNe(pyGet(pyOr(pyGet(pyOr(pyGet(subtitle, 'customData'), {}), 'evoDesignCardPart'), {}), 'hostId'), pyGetItem(host, 'id')) || truthy(pyGet(subtitle, 'isDeleted')))) {
      subtitle = null;
    }
    const left = 22 + (truthy(icon) ? 52 : 0);
    _requireKeys(host, ['x', 'y', 'width', 'height']);
    const top = host.y + (host.height - title!.height - (truthy(subtitle) ? subtitle!.height + 6 : 0)) / 2;

    const place = (part: Dict, x: number, y: number, width: number, height: number, width_f: boolean, height_f: boolean): void => {
      const angle = pyGet(host, 'angle', 0) as number;
      const dx = x + width / 2 - host.x - host.width / 2;
      const dy = y + height / 2 - host.y - host.height / 2;
      const patch: Dict = {
        x: host.x + host.width / 2 + dx * cos(angle) - dy * sin(angle) - width / 2,
        y: host.y + host.height / 2 + dx * sin(angle) + dy * cos(angle) - height / 2,
        width, height, angle,
      };
      if (truthy(pyGet(host, 'isDeleted'))) {
        patch.isDeleted = true;
      }
      if (Object.entries(patch).some(([key, value]) => pyNe(pyGet(part, key), value))) {
        Object.assign(part, patch);
        markF(part, 'x', true); // ``... - width/2``
        markF(part, 'y', true);
        markF(part, 'width', width_f);
        markF(part, 'height', height_f);
        copyF(host, 'angle', part, 'angle');
        part.version = pyInt(pyGet(part, 'version', 1) as number) + 1;
      }
    };

    place(title!, host.x + left, top, pyMaxN(1, host.width - left - 22), title!.height,
      host.width - left - 22 > 1 && isF(host, 'width'), isF(title, 'height'));
    if (truthy(subtitle)) {
      place(subtitle!, host.x + left, top + title!.height + 6, subtitle!.width, subtitle!.height,
        isF(subtitle, 'width'), isF(subtitle, 'height'));
    }
    if (truthy(icon)) {
      place(icon!, host.x + 22, host.y + (host.height - 36) / 2, 36, 36, false, false);
    }
  }
  return null;
}

function _requireKeys(element: Dict, keys: string[]): void {
  for (const key of keys) pyGetItem(element, key);
}

/**
 * Keep generated icons and labels attached after geometry/style edits.
 *
 * Imported ordinary images are deliberately untouched. Existing icon metadata
 * or a canonical semantic companion ID is required; geometry is not ownership.
 */
export function sync_node_icons(manifest: Dict, host_id: string | null = null): null {
  const elements = pyOr(pyGet(manifest, 'elements'), []) as Dict[];
  _sync_design_cards(elements, host_id);
  const id_map = pyOr(pyGet(pyOr(pyGet(manifest, '_meta'), {}), 'id_map'), {}) as PyMapping;
  const legacy_ids = pyItems(id_map).filter(([k]) => (k as string).endsWith(':icon')).map(([, v]) => v);
  for (const icon of elements) {
    if (pyGet(icon, 'type') !== 'image' || truthy(pyGet(icon, 'isDeleted'))) {
      continue;
    }
    const data = pyGet(pyOr(pyGet(icon, 'customData'), {}), ICON_KEY) as Dict | null;
    if (!truthy(data) && !pyIn(pyGet(icon, 'id'), legacy_ids)) {
      continue;
    }
    const host = icon_owner(icon, elements, id_map);
    if (!truthy(host) || (truthy(host_id) && pyNe(pyGet(host, 'id'), host_id))) {
      continue;
    }
    if (!truthy(pyGet(host, 'isDeleted')) && truthy(pyGet(pyOr(pyGet(host, 'customData'), {}), CARD_KEY))) {
      continue;
    }
    const before_icon: Dict = { ...icon };
    if (truthy(pyGet(host, 'isDeleted'))) {
      icon.isDeleted = true;
    } else {
      const h0 = host!;
      const text = elements.find((e) => pyGet(e, 'type') === 'text'
        && pyEq(pyGet(e, 'containerId'), pyGetItem(h0, 'id')) && !truthy(pyGet(e, 'isDeleted'))) ?? null;
      const size = pyMinN(ICON_SIZE, pyMaxN(12.0, pyFloatParse(pyGetItem(h0, 'height')) - 16));
      // max(12.0, float(...)) is a float; min(ICON_SIZE, ...) keeps the int ICON_SIZE unless the float is smaller.
      const size_f = pyMaxN(12.0, pyFloatParse(pyGetItem(h0, 'height')) - 16) < ICON_SIZE;
      // An ellipse's bounding box is not its usable content area. Fit
      // icon + label inside its central inscribed rectangle.
      const inset_scale = pyGet(h0, 'type') === 'ellipse' ? sqrt(2) : 1;
      if (truthy(text)) {
        h0.width = pyMaxN(pyFloatParse(pyGetItem(h0, 'width')), inset_scale * (2 * ICON_PADDING + size + ICON_GAP + pyFloatParse(pyGetItem(text!, 'width'))));
        h0.height = pyMaxN(pyFloatParse(pyGetItem(h0, 'height')), inset_scale * (pyFloatParse(pyGetItem(text!, 'height')) + 16), inset_scale * (size + 16));
        markF(h0, 'width', true); // max(float(...), inset_scale*(... + float(...)))
        markF(h0, 'height', true);
      }
      const x = pyFloatParse(pyGetItem(h0, 'x'));
      const y = pyFloatParse(pyGetItem(h0, 'y'));
      const w = pyFloatParse(pyGetItem(h0, 'width'));
      const h = pyFloatParse(pyGetItem(h0, 'height'));
      const angle = pyFloatParse(pyGet(h0, 'angle', 0) as number);
      const place = (element: Dict, center_x: number, center_y: number, width: number, height: number, size_is_f: boolean): void => {
        const dx = center_x - (x + w / 2);
        const dy = center_y - (y + h / 2);
        const cx = x + w / 2 + dx * cos(angle) - dy * sin(angle);
        const cy = y + h / 2 + dx * sin(angle) + dy * cos(angle);
        Object.assign(element, { x: cx - width / 2, y: cy - height / 2, width, height, angle });
        markF(element, 'x', true);
        markF(element, 'y', true);
        markF(element, 'width', size_is_f);
        markF(element, 'height', size_is_f);
        markF(element, 'angle', true); // float(host.get("angle", 0))
      };
      const padding = ICON_PADDING + w * (1 - 1 / inset_scale) / 2;
      place(icon, x + padding + size / 2, y + h / 2, size, size, size_f);
      if (truthy(text)) {
        const before_text: Dict = { ...text };
        const left = x + padding + size + ICON_GAP;
        const right = x + w - padding;
        place(text!, (left + right) / 2, y + h / 2, pyFloatParse(pyGetItem(text!, 'width')), pyFloatParse(pyGetItem(text!, 'height')), true);
        if (pyNe(text, before_text)) {
          text!.version = pyInt(pyGet(text, 'version', 1) as number) + 1;
        }
      }
      if (truthy(data)) {
        icon.customData = { ...(pyGet(icon, 'customData', {}) as Dict), [ICON_KEY]: { ...data, hostId: pyGetItem(h0, 'id') } };
        if (pyIn(pyGet(data, 'name'), bundled_icons())) {
          const asset = icon_file(data!.name, pyGet(h0, 'strokeColor', '#475569') as string);
          (pySetdefault(manifest, 'files', {}) as Dict)[asset.id] = asset;
          icon.fileId = asset.id;
        }
      }
    }
    if (pyNe(icon, before_icon)) {
      icon.version = pyInt(pyGet(icon, 'version', 1) as number) + 1;
    }
  }
  return null;
}
