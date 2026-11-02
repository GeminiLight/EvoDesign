"""Deterministic, scoped edits to an Excalidraw scene."""

from __future__ import annotations

import copy
import math
import unicodedata
from typing import Any

from .scene import excalidraw_element_defaults


class EditError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _card_companions(elements: dict[str, dict], eid: str) -> set[str]:
    card = (elements.get(eid, {}).get('customData') or {}).get('evoDesignCard')
    if not isinstance(card, dict):
        return set()
    result = set()
    for key, marker in (('iconId', 'evoDesignIcon'), ('sublabelId', 'evoDesignCardPart')):
        part_id = card.get(key)
        part = elements.get(part_id, {}) if isinstance(part_id, str) else {}
        owner = (part.get('customData') or {}).get(marker)
        if isinstance(owner, dict) and owner.get('hostId') == eid:
            result.add(part_id)
    return result


def _place_card_label(host: dict, title: dict, elements: dict[str, dict]) -> None:
    card = (host.get('customData') or {}).get('evoDesignCard')
    if not isinstance(card, dict) or card.get('titleId') != title['id']:
        return
    companions = _card_companions(elements, host['id'])
    icon_id, subtitle_id = card.get('iconId'), card.get('sublabelId')
    left = 22 + (52 if isinstance(icon_id, str) and icon_id in companions else 0)
    available = max(1, host['width'] - left - 22)
    lines = []
    for paragraph in title['originalText'].split('\n'):
        line, width = '', 0.0
        for char in paragraph:
            advance = title.get('fontSize', 20) * (1 if unicodedata.east_asian_width(char) in {'W', 'F'} else
                                                   0.66 if char.isupper() else 0.3 if char == ' ' else 0.55)
            if line and width + advance > available:
                lines.append(line)
                line, width = '', 0.0
            line, width = line + char, width + advance
        lines.append(line)
    height = len(lines) * title.get('fontSize', 20) * title.get('lineHeight', 1.25)
    subtitle = elements.get(subtitle_id, {}) if isinstance(subtitle_id, str) and subtitle_id in companions else {}
    sub_height = subtitle.get('height', 0) if not subtitle.get('isDeleted') else 0
    top = host['y'] + (host['height'] - height - (sub_height + 6 if sub_height else 0)) / 2
    title.update(text='\n'.join(lines), x=host['x']+left, y=top, width=available, height=height)
    if sub_height:
        subtitle.update(x=host['x']+left, y=top+height+6)


def assert_preserves_locks(before: dict[str, Any], after: dict[str, Any]) -> None:
    """Protect locked shapes, their labels and image data at a write boundary."""
    old = {e['id']: e for e in before.get('elements', []) if not e.get('isDeleted')}
    new = {e['id']: e for e in after.get('elements', []) if not e.get('isDeleted')}
    locked = {eid for eid, element in old.items() if element.get('locked')}
    for eid in list(locked):
        locked.update(binding['id'] for binding in old[eid].get('boundElements') or []
                      if binding.get('type') == 'text')
        locked.update(key for key, element in old.items() if element.get('containerId') == eid)
        locked.update(_card_companions(old, eid))
    for eid in locked:
        if old.get(eid) != new.get(eid):
            raise EditError('locked_element', 'The candidate changes a locked element or its label')
        file_id = old.get(eid, {}).get('fileId')
        if file_id and (before.get('files') or {}).get(file_id) != (after.get('files') or {}).get(file_id):
            raise EditError('locked_element', 'The candidate changes a locked image')


def apply_operations(
    scene: dict[str, Any], operations: list[dict[str, Any]],
    *, scope: list[str] | None = None, locked: list[str] = (),
) -> tuple[dict[str, Any], list[str]]:
    """Apply a batch without mutating its input or unrelated elements."""
    result = copy.deepcopy(scene)
    elements = result.setdefault('elements', [])
    if not isinstance(elements, list) or not 1 <= len(operations) <= 100:
        raise EditError('invalid_operations', 'Expected a scene and 1–100 operations')
    by_id = {e['id']: e for e in elements if isinstance(e, dict) and isinstance(e.get('id'), str)}
    if len(by_id) != len(elements):
        raise EditError('invalid_scene', 'Elements must have unique string IDs')
    before = copy.deepcopy(by_id)
    hard_locked = set(locked) | {eid for eid, e in by_id.items() if e.get('locked')}
    for eid in list(hard_locked):
        hard_locked.update(b['id'] for b in by_id.get(eid, {}).get('boundElements') or [] if b.get('type') == 'text')
        hard_locked.update(_card_companions(by_id, eid))
    permitted = None if scope is None else set(scope)

    def number(value: Any, *, positive: bool = False) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or abs(value) > 100000:
            raise EditError('invalid_geometry', 'Coordinates and dimensions must be finite and bounded')
        if positive and value <= 0:
            raise EditError('invalid_geometry', 'Dimensions must be positive')
        return value

    def get(eid: str) -> dict[str, Any]:
        if eid not in by_id or by_id[eid].get('isDeleted'):
            raise EditError('element_missing', f'Element does not exist: {eid}')
        return by_id[eid]

    def add(eid: str, kind: str, **values: Any) -> dict[str, Any]:
        if not isinstance(eid, str) or not eid or len(eid) > 128 or eid in by_id:
            raise EditError('duplicate_id', 'New elements require unique nonempty IDs')
        if permitted is not None and eid not in permitted:
            if kind != 'text' or values.get('containerId') not in permitted:
                raise EditError('scope_violation', 'Creating a standalone node or connection requires project scope')
        index = max((e.get('index') or 'a0' for e in elements), default='a0') + 'V'
        el = {**excalidraw_element_defaults(eid), 'id': eid, 'type': kind,
              'x': 0, 'y': 0, 'width': 1, 'height': 1, 'angle': 0,
              'version': 1, 'versionNonce': 1, 'index': index, 'isDeleted': False, **values}
        by_id[eid] = el
        elements.append(el)
        if permitted is not None:
            permitted.add(eid)
        return el

    def label(el: dict[str, Any]) -> dict[str, Any] | None:
        if el['type'] == 'text':
            return el
        ids = [b['id'] for b in el.get('boundElements') or [] if b.get('type') == 'text']
        return get(ids[0]) if ids else None

    def set_label(el: dict[str, Any], text: str) -> None:
        if not isinstance(text, str) or len(text) > 10000:
            raise EditError('invalid_text', 'Text must be at most 10000 characters')
        target = label(el)
        if target is None:
            tid = el['id'] + '-label'
            target = add(tid, 'text', x=el['x'] + 8, y=el['y'] + 8,
                         width=max(1, el['width'] - 16), height=max(20, el['height'] - 16),
                         containerId=el['id'], fontSize=20, fontFamily=2, lineHeight=1.25,
                         textAlign='center', verticalAlign='middle', autoResize=True)
            el['boundElements'] = [*(el.get('boundElements') or []), {'id': tid, 'type': 'text'}]
            if permitted is not None and el['id'] in permitted:
                permitted.add(tid)
        target.update(text=text, originalText=text)
        if el['type'] != 'text':
            height = target.get('fontSize', 20) * target.get('lineHeight', 1.25) * max(1, len(text.split('\n')))
            if el['type'] == 'arrow':
                width = max(40, min(300, max(map(len, text.split('\n'))) * target.get('fontSize', 20) * 0.6))
                points = el.get('points') or [[0, 0], [el['width'], el['height']]]
                target.update(width=width, height=height,
                    x=el['x']+(points[0][0]+points[-1][0])/2-width/2,
                    y=el['y']+(points[0][1]+points[-1][1])/2-height/2)
            else:
                target.update(x=el['x']+8, y=el['y']+(el['height']-height)/2,
                              width=max(1, el['width']-16), height=height)
        host = by_id.get(target.get('containerId'), {})
        _place_card_label(host, target, by_id)

    # A node's bound label is part of its semantic scope. Arrows are not:
    # moving a connected node may require explicitly including its connectors.
    if permitted is not None:
        for eid in list(permitted):
            el = get(eid)
            permitted.update(b['id'] for b in el.get('boundElements') or [] if b.get('type') == 'text')
            permitted.update(_card_companions(by_id, eid))

    for op in operations:
        fields = {
            'add_node': {'op', 'id', 'shape', 'x', 'y', 'width', 'height', 'text'},
            'connect': {'op', 'id', 'from', 'to', 'text'},
            'set_text': {'op', 'id', 'text'}, 'set_style': {'op', 'id', 'style'},
            'move_node': {'op', 'id', 'x', 'y'}, 'delete_node': {'op', 'id', 'cascade'},
        }
        kind, eid = op.get('op'), op.get('id')
        if not isinstance(kind, str) or kind not in fields or not isinstance(eid, str) or set(op) - fields[kind]:
            raise EditError('invalid_operations', 'Use supported operations, string IDs and documented properties')
        if kind == 'connect' and not all(isinstance(op.get(key), str) for key in ('from', 'to')):
            raise EditError('invalid_operations', 'Connect requires from and to IDs')
        if kind == 'add_node':
            if op.get('shape', 'rectangle') not in {'rectangle', 'ellipse', 'diamond'}:
                raise EditError('unsupported_shape', 'Unsupported node shape')
            el = add(eid, op.get('shape', 'rectangle'), x=number(op.get('x')), y=number(op.get('y')),
                     width=number(op.get('width'), positive=True), height=number(op.get('height'), positive=True))
            if 'text' in op:
                set_label(el, op['text'])
        elif kind == 'connect':
            start, end = get(op.get('from')), get(op.get('to'))
            sx, sy = start['x']+start['width']/2, start['y']+start['height']/2
            ex, ey = end['x']+end['width']/2, end['y']+end['height']/2
            dx, dy = ex-sx, ey-sy
            if abs(dx) >= abs(dy):
                direction = 1 if dx >= 0 else -1
                sx += direction*start['width']/2
                ex -= direction*end['width']/2
            else:
                direction = 1 if dy >= 0 else -1
                sy += direction*start['height']/2
                ey -= direction*end['height']/2
            el = add(eid, 'arrow', x=sx, y=sy, width=abs(ex-sx), height=abs(ey-sy),
                     points=[[0, 0], [ex-sx, ey-sy]], startArrowhead=None, endArrowhead='arrow',
                     startBinding={'elementId': start['id'], 'focus': 0, 'gap': 1},
                     endBinding={'elementId': end['id'], 'focus': 0, 'gap': 1})
            for target in (start, end):
                target['boundElements'] = [*(target.get('boundElements') or []), {'id': eid, 'type': 'arrow'}]
            if 'text' in op:
                set_label(el, op['text'])
        elif kind == 'set_text':
            set_label(get(eid), op.get('text'))
        elif kind == 'set_style':
            el = get(eid)
            keys = {'fill': 'backgroundColor', 'stroke': 'strokeColor', 'stroke_width': 'strokeWidth', 'text_color': 'strokeColor'}
            style = op.get('style')
            if not isinstance(style, dict) or not style or set(style) - keys.keys():
                raise EditError('invalid_style', 'Unsupported style properties')
            import re
            for key, value in style.items():
                if key == 'stroke_width':
                    if number(value, positive=True) > 10:
                        raise EditError('invalid_style', 'Stroke width must be at most 10')
                elif not isinstance(value, str) or not (value == 'transparent' or re.fullmatch(r'#[0-9a-fA-F]{6}', value)):
                    raise EditError('invalid_style', 'Use a six-digit hex color or transparent')
                target = label(el) if key == 'text_color' else el
                if target is None:
                    raise EditError('element_missing', 'Node has no text to style')
                target[keys[key]] = value
                if key == 'fill':
                    target['fillStyle'] = 'solid'
        elif kind == 'move_node':
            el = get(eid)
            if el['type'] in {'arrow', 'line'}:
                raise EditError('unsupported_operation', 'Move a node rather than a connector')
            dx, dy = number(op.get('x')) - el['x'], number(op.get('y')) - el['y']
            el.update(x=el['x'] + dx, y=el['y'] + dy)
            text = label(el)
            if text is not None and text is not el:
                text.update(x=text['x'] + dx, y=text['y'] + dy)
            for part_id in _card_companions(by_id, eid):
                part = by_id[part_id]
                part.update(x=part['x'] + dx, y=part['y'] + dy)
            for arrow in by_id.values():
                if arrow.get('isDeleted') or arrow.get('type') != 'arrow':
                    continue
                points = copy.deepcopy(arrow.get('points', []))
                if len(points) < 2:
                    continue
                old_center = (arrow['x']+(points[0][0]+points[-1][0])/2,
                              arrow['y']+(points[0][1]+points[-1][1])/2)
                start = (arrow.get('startBinding') or {}).get('elementId') == eid
                end = (arrow.get('endBinding') or {}).get('elementId') == eid
                if start:
                    arrow['x'] += dx; arrow['y'] += dy
                    points = [[x-dx, y-dy] for x, y in points]
                    points[0] = [0, 0]
                if end:
                    points[-1] = [points[-1][0]+dx, points[-1][1]+dy]
                if start or end:
                    arrow.update(points=points, width=max(p[0] for p in points)-min(p[0] for p in points),
                                 height=max(p[1] for p in points)-min(p[1] for p in points))
                    arrow_label = label(arrow)
                    if arrow_label:
                        arrow_label['x'] += arrow['x']+(points[0][0]+points[-1][0])/2-old_center[0]
                        arrow_label['y'] += arrow['y']+(points[0][1]+points[-1][1])/2-old_center[1]
        elif kind == 'delete_node':
            el = get(eid)
            if not isinstance(op.get('cascade'), bool):
                raise EditError('cascade_required', 'Specify cascade explicitly')
            dependents = {b['id'] for b in el.get('boundElements') or [] if b['id'] in by_id}
            dependents.update(_card_companions(by_id, eid))
            if dependents and not op['cascade']:
                raise EditError('dependent_elements', 'Element has bound text or connectors; specify cascade')
            removing = {eid} | dependents
            for rid in list(removing):
                removing.update(b['id'] for b in by_id[rid].get('boundElements') or [] if b.get('type') == 'text')
            for rid in removing:
                get(rid)['isDeleted'] = True
            for other in by_id.values():
                if other.get('boundElements'):
                    other['boundElements'] = [b for b in other['boundElements'] if b['id'] not in removing]
        else:
            raise EditError('unsupported_operation', f'Unsupported operation: {kind}')

    changed = [eid for eid, el in by_id.items() if before.get(eid) != el]
    if hard_locked.intersection(changed):
        raise EditError('locked_element', 'Edit would change a locked element')
    if permitted is not None and set(changed) - permitted:
        raise EditError('scope_violation', 'Required scope: ' + ', '.join(sorted(set(changed) - permitted)))
    for eid in changed:
        el = by_id[eid]
        el['version'] = int(before.get(eid, {}).get('version', 0)) + 1
        el['versionNonce'] = el['version']
    return result, changed
