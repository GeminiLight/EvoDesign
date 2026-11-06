// Ported from evodesign/agentic_system/verification_stage/checks/node_icons.py — keep in sync.
//
// Check generated node companions, without treating ordinary images as icons.

import { ICON_KEY, icon_owner } from '../../common/node_icons.ts';
import { pyGet, pyGetItem } from '../../py/dict.ts';
import { cos, sin } from '../../py/math.ts';
import { pyFloatParse } from '../../py/number.ts';
import { pyStr } from '../../py/str.ts';
import { isDict, truthy } from '../../py/truthy.ts';
import { Finding } from './finding.ts';

type Dict = Record<string, any>;

function _or<T>(value: unknown, fallback: T): any {
  return truthy(value) ? value : fallback;
}

export function check_node_icons(manifest: Dict, canvas_library: string): Finding[] {
  if (canvas_library !== 'excalidraw') {
    return [];
  }
  const elements = _or(pyGet(manifest, 'elements'), []) as Dict[];
  const findings: Finding[] = [];
  for (const icon of elements) {
    if (pyGet(icon, 'type') !== 'image' || truthy(pyGet(icon, 'isDeleted')) || !truthy(pyGet(_or(pyGet(icon, 'customData'), {}), ICON_KEY))) {
      continue;
    }
    const report = (category: string, message: string): void => {
      findings.push(new Finding({ category: `icon/${category}`, severity: 'major', message, element_id: pyGetItem(icon, 'id') as string }));
    };
    const host = icon_owner(icon, elements);
    if (!truthy(host) || truthy(pyGet(host, 'isDeleted'))) {
      report('missing_host', 'Generated icon has no active host node.');
      continue;
    }
    const h = host!;
    const asset = pyGet(_or(pyGet(manifest, 'files'), {}), pyGet(icon, 'fileId'));
    if (!isDict(asset) || !pyStr(pyGet(asset, 'dataURL', '')).startsWith('data:image/')) {
      report('missing_asset', 'Generated icon must have an embedded image asset for portable exports.');
    }
    const angle = pyFloatParse(pyGet(h, 'angle', 0) as number);
    const local_box = (element: Dict): [number, number, number, number] => {
      const dx = pyGetItem(element, 'x') + pyGetItem(element, 'width') / 2 - (pyGetItem(h, 'x') + pyGetItem(h, 'width') / 2);
      const dy = pyGetItem(element, 'y') + pyGetItem(element, 'height') / 2 - (pyGetItem(h, 'y') + pyGetItem(h, 'height') / 2);
      const cx = pyGetItem(h, 'width') / 2 + dx * cos(angle) + dy * sin(angle);
      const cy = pyGetItem(h, 'height') / 2 - dx * sin(angle) + dy * cos(angle);
      return [cx - pyGetItem(element, 'width') / 2, cy - pyGetItem(element, 'height') / 2, pyGetItem(element, 'width'), pyGetItem(element, 'height')];
    };
    const [x, y, w, hh] = local_box(icon);
    const hw = pyGetItem(h, 'width') as number;
    const hh_ = pyGetItem(h, 'height') as number;
    if (x < -1 || y < -1 || x + w > hw + 1 || y + hh > hh_ + 1) {
      report('outside_host', 'Generated icon extends outside its host node.');
    } else if (pyGet(h, 'type') === 'ellipse' && hw > 0 && hh_ > 0) {
      let outside = false;
      for (const cx of [x, x + w]) {
        for (const cy of [y, y + hh]) {
          if (((cx - hw / 2) / (hw / 2)) ** 2 + ((cy - hh_ / 2) / (hh_ / 2)) ** 2 > 1.01) {
            outside = true;
            break;
          }
        }
        if (outside) break;
      }
      if (outside) {
        report('outside_host', 'Generated icon extends beyond its elliptical host boundary.');
      }
    }
    for (const text of elements) {
      if (pyGet(text, 'type') !== 'text' || pyGet(text, 'containerId') !== pyGetItem(h, 'id') || truthy(pyGet(text, 'isDeleted'))) {
        continue;
      }
      const [tx, ty, tw, th] = local_box(text);
      if (Math.min(x + w, tx + tw) - Math.max(x, tx) > 1 && Math.min(y + hh, ty + th) - Math.max(y, ty) > 1) {
        report('text_overlap', 'Generated icon overlaps its node label; restore separate icon and text areas.');
      }
    }
  }
  return findings;
}
