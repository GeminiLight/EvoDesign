// Ported from evodesign/canvas_environment/editing.py — keep in sync.
//
// Deterministic, scoped edits to an Excalidraw scene.
//
// ``dict[str, dict]`` element indexes (``by_id``, ``old``/``new``) are ``Map``s:
// element ids may look like integers, and a plain object would reorder them
// (MIGRATION_PLAN.md §4) — the order of ``changed`` follows ``by_id``.
// ``_card_companions`` / ``_place_card_label`` also accept a plain object
// (the shape their parity vectors carry).

import { pyEq, pyNe } from '../py/eq.ts';
import { KeyError, ValueError } from '../py/errors.ts';
import { pyIsupper, cpChars, cpLen, pyStr } from '../py/str.ts';
import { cpCompare, pySorted } from '../py/sort.ts';
import { isDict, truthy } from '../py/truthy.ts';
import { east_asian_width } from '../py/unicodedata.ts';
import { excalidraw_element_defaults } from './scene.ts';

type Dict = Record<string, unknown>;
type Elements = Map<string, Dict> | Record<string, Dict>;

export class EditError extends ValueError {
  code: string;

  constructor(code: string, message: string) {
    super(message);
    this.code = code;
    this.name = 'EditError';
  }
}

/** ``elements.get(key, default)`` for a Map or a plain object. */
function _lookup(elements: Elements, key: unknown, defaultValue: unknown = null): unknown {
  if (elements instanceof Map) return elements.has(key as string) ? elements.get(key as string) : defaultValue;
  if (typeof key === 'string' && Object.prototype.hasOwnProperty.call(elements, key)) return elements[key];
  return defaultValue;
}

/** ``d.get(key, default)`` on an element-like dict. */
function _get(d: unknown, key: string, defaultValue: unknown = null): unknown {
  if (!isDict(d)) return defaultValue;
  return Object.prototype.hasOwnProperty.call(d, key) ? d[key] : defaultValue;
}

/** ``d[key]`` (KeyError when missing). */
function _item(d: Dict, key: string): unknown {
  if (!Object.prototype.hasOwnProperty.call(d, key)) throw new KeyError(`'${key}'`);
  return d[key];
}

/** ``(x or {})`` for dict-valued fields. */
function _orDict(value: unknown): Dict {
  return (truthy(value) ? value : {}) as Dict;
}

/** ``(x or [])`` for list-valued fields. */
function _orList(value: unknown): Dict[] {
  return (truthy(value) ? value : []) as Dict[];
}

export function _card_companions(elements: Elements, eid: string): Set<string> {
  const card = _get(_orDict(_get(_lookup(elements, eid, {}), 'customData')), 'evoDesignCard');
  if (!isDict(card)) {
    return new Set();
  }
  const result = new Set<string>();
  for (const [key, marker] of [['iconId', 'evoDesignIcon'], ['sublabelId', 'evoDesignCardPart']] as const) {
    const part_id = _get(card, key);
    const part = typeof part_id === 'string' ? _lookup(elements, part_id, {}) : {};
    const owner = _get(_orDict(_get(part, 'customData')), marker);
    if (isDict(owner) && _get(owner, 'hostId') === eid) {
      result.add(part_id as string);
    }
  }
  return result;
}

export function _place_card_label(host: Dict, title: Dict, elements: Elements): void {
  const card = _get(_orDict(_get(host, 'customData')), 'evoDesignCard');
  if (!isDict(card) || pyNe(_get(card, 'titleId'), _item(title, 'id'))) {
    return;
  }
  const companions = _card_companions(elements, _item(host, 'id') as string);
  const icon_id = _get(card, 'iconId');
  const subtitle_id = _get(card, 'sublabelId');
  const left = 22 + (typeof icon_id === 'string' && companions.has(icon_id) ? 52 : 0);
  const available = Math.max(1, (_item(host, 'width') as number) - left - 22);
  const lines: string[] = [];
  const fontSize = _get(title, 'fontSize', 20) as number;
  for (const paragraph of (_item(title, 'originalText') as string).split('\n')) {
    let line = '';
    let width = 0.0;
    for (const char of cpChars(paragraph)) {
      const ea = east_asian_width(char);
      const advance = fontSize * (ea === 'W' || ea === 'F' ? 1
        : pyIsupper(char) ? 0.66 : char === ' ' ? 0.3 : 0.55);
      if (line && width + advance > available) {
        lines.push(line);
        line = '';
        width = 0.0;
      }
      line = line + char;
      width = width + advance;
    }
    lines.push(line);
  }
  const height = lines.length * fontSize * (_get(title, 'lineHeight', 1.25) as number);
  const subtitle = (typeof subtitle_id === 'string' && companions.has(subtitle_id)
    ? _lookup(elements, subtitle_id, {}) : {}) as Dict;
  const sub_height = !truthy(_get(subtitle, 'isDeleted')) ? (_get(subtitle, 'height', 0) as number) : 0;
  const top = (_item(host, 'y') as number)
    + ((_item(host, 'height') as number) - height - (truthy(sub_height) ? sub_height + 6 : 0)) / 2;
  Object.assign(title, { text: lines.join('\n'), x: (_item(host, 'x') as number) + left, y: top, width: available, height });
  if (truthy(sub_height)) {
    Object.assign(subtitle, { x: (_item(host, 'x') as number) + left, y: top + height + 6 });
  }
}

/** ``{e['id']: e for e in elements if not e.get('isDeleted')}`` */
function _live_index(scene: Dict): Map<string, Dict> {
  const out = new Map<string, Dict>();
  for (const e of (_get(scene, 'elements', []) as Dict[])) {
    if (!truthy(_get(e, 'isDeleted'))) out.set(_item(e, 'id') as string, e);
  }
  return out;
}

/** Protect locked shapes, their labels and image data at a write boundary. */
export function assert_preserves_locks(before: Dict, after: Dict): void {
  const old = _live_index(before);
  const neu = _live_index(after);
  const locked = new Set<string>();
  for (const [eid, element] of old) if (truthy(_get(element, 'locked'))) locked.add(eid);
  for (const eid of [...locked]) {
    for (const binding of _orList(_get(old.get(eid), 'boundElements'))) {
      if (_get(binding, 'type') === 'text') locked.add(_item(binding, 'id') as string);
    }
    for (const [key, element] of old) if (pyEq(_get(element, 'containerId'), eid)) locked.add(key);
    for (const part of _card_companions(old, eid)) locked.add(part);
  }
  for (const eid of locked) {
    if (pyNe(old.get(eid) ?? null, neu.get(eid) ?? null)) {
      throw new EditError('locked_element', 'The candidate changes a locked element or its label');
    }
    const file_id = _get(old.get(eid) ?? {}, 'fileId');
    if (truthy(file_id) && pyNe(_get(_orDict(_get(before, 'files')), file_id as string), _get(_orDict(_get(after, 'files')), file_id as string))) {
      throw new EditError('locked_element', 'The candidate changes a locked image');
    }
  }
}

function _isNumber(value: unknown): value is number {
  return typeof value === 'number';
}

/** ``max(a, b)`` — the first argument wins ties, like Python. */
function _max(a: number, b: number): number {
  return b > a ? b : a;
}

/** ``min(a, b)`` */
function _min(a: number, b: number): number {
  return b < a ? b : a;
}

const _HEX6 = /^#[0-9a-fA-F]{6}$/;

/** Apply a batch without mutating its input or unrelated elements. */
export function apply_operations(
  scene: Dict,
  operations: Dict[],
  scope: string[] | null = null,
  locked: readonly string[] = [],
): [Dict, string[]] {
  const result = structuredClone(scene);
  if (!Object.prototype.hasOwnProperty.call(result, 'elements')) result.elements = [];
  const elements = result.elements as Dict[];
  if (!Array.isArray(elements) || !(operations.length >= 1 && operations.length <= 100)) {
    throw new EditError('invalid_operations', 'Expected a scene and 1–100 operations');
  }
  const by_id = new Map<string, Dict>();
  for (const e of elements) {
    if (isDict(e) && typeof _get(e, 'id') === 'string') by_id.set(e.id as string, e);
  }
  if (by_id.size !== elements.length) {
    throw new EditError('invalid_scene', 'Elements must have unique string IDs');
  }
  const before = new Map<string, Dict>([...by_id].map(([k, v]) => [k, structuredClone(v)]));
  const hard_locked = new Set<string>(locked);
  for (const [eid, e] of by_id) if (truthy(_get(e, 'locked'))) hard_locked.add(eid);
  for (const eid of [...hard_locked]) {
    for (const b of _orList(_get(by_id.get(eid) ?? {}, 'boundElements'))) {
      if (_get(b, 'type') === 'text') hard_locked.add(_item(b, 'id') as string);
    }
    for (const part of _card_companions(by_id, eid)) hard_locked.add(part);
  }
  const permitted: Set<string> | null = scope === null || scope === undefined ? null : new Set(scope);

  const number = (value: unknown, positive = false): number => {
    if (typeof value === 'boolean' || !_isNumber(value) || !Number.isFinite(value) || Math.abs(value) > 100000) {
      throw new EditError('invalid_geometry', 'Coordinates and dimensions must be finite and bounded');
    }
    if (positive && value <= 0) {
      throw new EditError('invalid_geometry', 'Dimensions must be positive');
    }
    return value;
  };

  const get = (eid: unknown): Dict => {
    if (typeof eid !== 'string' || !by_id.has(eid) || truthy(_get(by_id.get(eid), 'isDeleted'))) {
      throw new EditError('element_missing', `Element does not exist: ${pyStr(eid)}`);
    }
    return by_id.get(eid)!;
  };

  const add = (eid: unknown, kind: string, values: Dict): Dict => {
    if (typeof eid !== 'string' || !eid || cpLen(eid) > 128 || by_id.has(eid)) {
      throw new EditError('duplicate_id', 'New elements require unique nonempty IDs');
    }
    if (permitted !== null && !permitted.has(eid)) {
      const container = _get(values, 'containerId');
      if (kind !== 'text' || !(typeof container === 'string' && permitted.has(container))) {
        throw new EditError('scope_violation', 'Creating a standalone node or connection requires project scope');
      }
    }
    let index = 'a0';
    let first = true;
    for (const e of elements) {
      const candidate = (truthy(_get(e, 'index')) ? _get(e, 'index') : 'a0') as string;
      if (first || cpCompare(candidate, index) > 0) index = candidate;
      first = false;
    }
    index += 'V';
    const el: Dict = {
      ...excalidraw_element_defaults(eid),
      id: eid,
      type: kind,
      x: 0,
      y: 0,
      width: 1,
      height: 1,
      angle: 0,
      version: 1,
      versionNonce: 1,
      index,
      isDeleted: false,
      ...values,
    };
    by_id.set(eid, el);
    elements.push(el);
    if (permitted !== null) {
      permitted.add(eid);
    }
    return el;
  };

  const label = (el: Dict): Dict | null => {
    if (_item(el, 'type') === 'text') {
      return el;
    }
    const ids = _orList(_get(el, 'boundElements')).filter((b) => _get(b, 'type') === 'text').map((b) => _item(b, 'id'));
    return ids.length ? get(ids[0]) : null;
  };

  const set_label = (el: Dict, text: unknown): void => {
    if (typeof text !== 'string' || cpLen(text) > 10000) {
      throw new EditError('invalid_text', 'Text must be at most 10000 characters');
    }
    let target = label(el);
    if (target === null) {
      // <id>-label may still be taken by a deleted or unbound label, so pick a free one.
      let tid = `${_item(el, 'id') as string}-label`;
      let suffix = 2;
      while (by_id.has(tid)) {
        tid = `${_item(el, 'id') as string}-label-${suffix}`;
        suffix += 1;
      }
      target = add(tid, 'text', {
        x: (_item(el, 'x') as number) + 8,
        y: (_item(el, 'y') as number) + 8,
        width: _max(1, (_item(el, 'width') as number) - 16),
        height: _max(20, (_item(el, 'height') as number) - 16),
        containerId: _item(el, 'id'),
        fontSize: 20,
        fontFamily: 2,
        lineHeight: 1.25,
        textAlign: 'center',
        verticalAlign: 'middle',
        autoResize: true,
      });
      el.boundElements = [..._orList(_get(el, 'boundElements')), { id: tid, type: 'text' }];
      if (permitted !== null && permitted.has(_item(el, 'id') as string)) {
        permitted.add(tid);
      }
    }
    Object.assign(target, { text, originalText: text });
    if (_item(el, 'type') !== 'text') {
      const lines = text.split('\n');
      const height = (_get(target, 'fontSize', 20) as number) * (_get(target, 'lineHeight', 1.25) as number) * _max(1, lines.length);
      if (_item(el, 'type') === 'arrow') {
        let longest = cpLen(lines[0]);
        for (const line of lines) longest = _max(longest, cpLen(line));
        const width = _max(40, _min(300, longest * (_get(target, 'fontSize', 20) as number) * 0.6));
        const points = (truthy(_get(el, 'points')) ? _get(el, 'points') : [[0, 0], [_item(el, 'width'), _item(el, 'height')]]) as number[][];
        const last = points[points.length - 1];
        Object.assign(target, {
          width,
          height,
          x: (_item(el, 'x') as number) + (points[0][0] + last[0]) / 2 - width / 2,
          y: (_item(el, 'y') as number) + (points[0][1] + last[1]) / 2 - height / 2,
        });
      } else {
        Object.assign(target, {
          x: (_item(el, 'x') as number) + 8,
          y: (_item(el, 'y') as number) + ((_item(el, 'height') as number) - height) / 2,
          width: _max(1, (_item(el, 'width') as number) - 16),
          height,
        });
      }
    }
    const containerId = _get(target, 'containerId');
    const host = (typeof containerId === 'string' && by_id.has(containerId) ? by_id.get(containerId) : {}) as Dict;
    _place_card_label(host, target, by_id);
  };

  // A node's bound label is part of its semantic scope. Arrows are not:
  // moving a connected node may require explicitly including its connectors.
  if (permitted !== null) {
    for (const eid of [...permitted]) {
      const el = get(eid);
      for (const b of _orList(_get(el, 'boundElements'))) {
        if (_get(b, 'type') === 'text') permitted.add(_item(b, 'id') as string);
      }
      for (const part of _card_companions(by_id, eid)) permitted.add(part);
    }
  }

  const fields: Record<string, Set<string>> = {
    add_node: new Set(['op', 'id', 'shape', 'x', 'y', 'width', 'height', 'text']),
    connect: new Set(['op', 'id', 'from', 'to', 'text']),
    set_text: new Set(['op', 'id', 'text']),
    set_style: new Set(['op', 'id', 'style']),
    move_node: new Set(['op', 'id', 'x', 'y']),
    delete_node: new Set(['op', 'id', 'cascade']),
  };
  for (const op of operations) {
    const kind = _get(op, 'op');
    const eid = _get(op, 'id');
    if (
      typeof kind !== 'string'
      || !Object.prototype.hasOwnProperty.call(fields, kind)
      || typeof eid !== 'string'
      || Object.keys(op).some((key) => !fields[kind].has(key))
    ) {
      throw new EditError('invalid_operations', 'Use supported operations, string IDs and documented properties');
    }
    if (kind === 'connect' && !['from', 'to'].every((key) => typeof _get(op, key) === 'string')) {
      throw new EditError('invalid_operations', 'Connect requires from and to IDs');
    }
    if (kind === 'add_node') {
      const shape = _get(op, 'shape', 'rectangle');
      if (!(shape === 'rectangle' || shape === 'ellipse' || shape === 'diamond')) {
        throw new EditError('unsupported_shape', 'Unsupported node shape');
      }
      const values = {
        x: number(_get(op, 'x')),
        y: number(_get(op, 'y')),
        width: number(_get(op, 'width'), true),
        height: number(_get(op, 'height'), true),
      };
      const el = add(eid, shape as string, values);
      if ('text' in op) {
        set_label(el, op.text);
      }
    } else if (kind === 'connect') {
      const start = get(_get(op, 'from'));
      const end = get(_get(op, 'to'));
      let sx = (_item(start, 'x') as number) + (_item(start, 'width') as number) / 2;
      let sy = (_item(start, 'y') as number) + (_item(start, 'height') as number) / 2;
      let ex = (_item(end, 'x') as number) + (_item(end, 'width') as number) / 2;
      let ey = (_item(end, 'y') as number) + (_item(end, 'height') as number) / 2;
      const dx = ex - sx;
      const dy = ey - sy;
      if (Math.abs(dx) >= Math.abs(dy)) {
        const direction = dx >= 0 ? 1 : -1;
        sx += direction * (_item(start, 'width') as number) / 2;
        ex -= direction * (_item(end, 'width') as number) / 2;
      } else {
        const direction = dy >= 0 ? 1 : -1;
        sy += direction * (_item(start, 'height') as number) / 2;
        ey -= direction * (_item(end, 'height') as number) / 2;
      }
      const el = add(eid, 'arrow', {
        x: sx,
        y: sy,
        width: Math.abs(ex - sx),
        height: Math.abs(ey - sy),
        points: [[0, 0], [ex - sx, ey - sy]],
        startArrowhead: null,
        endArrowhead: 'arrow',
        startBinding: { elementId: start.id, focus: 0, gap: 1 },
        endBinding: { elementId: end.id, focus: 0, gap: 1 },
      });
      for (const target of [start, end]) {
        target.boundElements = [..._orList(_get(target, 'boundElements')), { id: eid, type: 'arrow' }];
      }
      if ('text' in op) {
        set_label(el, op.text);
      }
    } else if (kind === 'set_text') {
      set_label(get(eid), _get(op, 'text'));
    } else if (kind === 'set_style') {
      const el = get(eid);
      const keys: Record<string, string> = { fill: 'backgroundColor', stroke: 'strokeColor', stroke_width: 'strokeWidth', text_color: 'strokeColor' };
      const style = _get(op, 'style');
      if (!isDict(style) || !truthy(style) || Object.keys(style).some((key) => !(key in keys))) {
        throw new EditError('invalid_style', 'Unsupported style properties');
      }
      for (const [key, value] of Object.entries(style)) {
        if (key === 'stroke_width') {
          if (number(value, true) > 10) {
            throw new EditError('invalid_style', 'Stroke width must be at most 10');
          }
        } else if (typeof value !== 'string' || !(value === 'transparent' || _HEX6.test(value))) {
          throw new EditError('invalid_style', 'Use a six-digit hex color or transparent');
        }
        const target = key === 'text_color' ? label(el) : el;
        if (target === null) {
          throw new EditError('element_missing', 'Node has no text to style');
        }
        target[keys[key]] = value;
        if (key === 'fill') {
          target.fillStyle = 'solid';
        }
      }
    } else if (kind === 'move_node') {
      const el = get(eid);
      if (el.type === 'arrow' || el.type === 'line') {
        throw new EditError('unsupported_operation', 'Move a node rather than a connector');
      }
      const dx = number(_get(op, 'x')) - (el.x as number);
      const dy = number(_get(op, 'y')) - (el.y as number);
      Object.assign(el, { x: (el.x as number) + dx, y: (el.y as number) + dy });
      const text = label(el);
      if (text !== null && text !== el) {
        Object.assign(text, { x: (text.x as number) + dx, y: (text.y as number) + dy });
      }
      for (const part_id of _card_companions(by_id, eid)) {
        const part = by_id.get(part_id)!;
        Object.assign(part, { x: (part.x as number) + dx, y: (part.y as number) + dy });
      }
      for (const arrow of by_id.values()) {
        if (truthy(_get(arrow, 'isDeleted')) || _get(arrow, 'type') !== 'arrow') {
          continue;
        }
        let points = structuredClone(_get(arrow, 'points', [])) as number[][];
        if (points.length < 2) {
          continue;
        }
        const old_center = [
          (arrow.x as number) + (points[0][0] + points[points.length - 1][0]) / 2,
          (arrow.y as number) + (points[0][1] + points[points.length - 1][1]) / 2,
        ];
        const start = pyEq(_get(_orDict(_get(arrow, 'startBinding')), 'elementId'), eid);
        const end = pyEq(_get(_orDict(_get(arrow, 'endBinding')), 'elementId'), eid);
        if (start) {
          arrow.x = (arrow.x as number) + dx;
          arrow.y = (arrow.y as number) + dy;
          points = points.map(([x, y]) => [x - dx, y - dy]);
          points[0] = [0, 0];
        }
        if (end) {
          const last = points[points.length - 1];
          points[points.length - 1] = [last[0] + dx, last[1] + dy];
        }
        if (start || end) {
          const xs = points.map((p) => p[0]);
          const ys = points.map((p) => p[1]);
          Object.assign(arrow, {
            points,
            width: xs.reduce(_max) - xs.reduce(_min),
            height: ys.reduce(_max) - ys.reduce(_min),
          });
          const arrow_label = label(arrow);
          if (truthy(arrow_label)) {
            const last = points[points.length - 1];
            arrow_label!.x = (arrow_label!.x as number) + ((arrow.x as number) + (points[0][0] + last[0]) / 2 - old_center[0]);
            arrow_label!.y = (arrow_label!.y as number) + ((arrow.y as number) + (points[0][1] + last[1]) / 2 - old_center[1]);
          }
        }
      }
    } else if (kind === 'delete_node') {
      const el = get(eid);
      if (typeof _get(op, 'cascade') !== 'boolean') {
        throw new EditError('cascade_required', 'Specify cascade explicitly');
      }
      const dependents = new Set<string>();
      for (const b of _orList(_get(el, 'boundElements'))) {
        const bid = _item(b, 'id');
        if (typeof bid === 'string' && by_id.has(bid)) dependents.add(bid);
      }
      for (const part of _card_companions(by_id, eid)) dependents.add(part);
      if (dependents.size && !op.cascade) {
        throw new EditError('dependent_elements', 'Element has bound text or connectors; specify cascade');
      }
      const removing = new Set<string>([eid, ...dependents]);
      for (const rid of [...removing]) {
        for (const b of _orList(_get(by_id.get(rid), 'boundElements'))) {
          if (_get(b, 'type') === 'text') removing.add(_item(b, 'id') as string);
        }
      }
      for (const rid of removing) {
        get(rid).isDeleted = true;
      }
      for (const other of by_id.values()) {
        if (truthy(_get(other, 'boundElements'))) {
          other.boundElements = (other.boundElements as Dict[]).filter((b) => !removing.has(_item(b, 'id') as string));
        }
      }
    } else {
      throw new EditError('unsupported_operation', `Unsupported operation: ${kind}`);
    }
  }

  const changed: string[] = [];
  for (const [eid, el] of by_id) {
    if (pyNe(before.get(eid) ?? null, el)) changed.push(eid);
  }
  if (changed.some((eid) => hard_locked.has(eid))) {
    throw new EditError('locked_element', 'Edit would change a locked element');
  }
  if (permitted !== null) {
    const outside = changed.filter((eid) => !permitted.has(eid));
    if (outside.length) {
      throw new EditError('scope_violation', 'Required scope: ' + pySorted(new Set(outside)).join(', '));
    }
  }
  for (const eid of changed) {
    const el = by_id.get(eid)!;
    el.version = Math.trunc(Number(_get(before.get(eid) ?? {}, 'version', 0))) + 1;
    el.versionNonce = el.version;
  }
  return [result, changed];
}
