// Parity adapter for render_engine.excalidraw.shape_size_fitter (WP04).
//
// In Python, the shapes passed to _translate_related / _resolve_container_overlaps
// are the very same objects stored in ``by_id`` (fit_shape_sizes_to_text builds
// by_id from the element list), so translating a shape also moves its by_id
// entry. JSON fixtures lose that aliasing: every argument is decoded into a
// separate copy. The adapter restores it: a by_id entry whose id matches a
// shape argument and is structurally equal to it is replaced by that shape
// object. Nothing is skipped.
import type { Adapter } from '../parity/functions.test.ts';
import { pyEq } from '../../src/py/eq.ts';

type Dict = Record<string, unknown>;

function alias(shapes: Dict[], byId: Dict): void {
  for (const shape of shapes) {
    const id = shape?.id;
    if (typeof id === 'string' && Object.prototype.hasOwnProperty.call(byId, id) && pyEq(byId[id], shape)) {
      byId[id] = shape;
    }
  }
}

export default {
  // (shape, dx, dy, by_id, shape_to_text, shape_to_icon)
  _translate_related: {
    args: (bound) => {
      alias([bound[0] as Dict], bound[3] as Dict);
      return bound;
    },
  },
  // (candidates, original_dims, by_id, shape_to_text, shape_to_icon, gap)
  _resolve_container_overlaps: {
    args: (bound) => {
      alias(bound[0] as Dict[], bound[2] as Dict);
      return bound;
    },
  },
} satisfies Record<string, Adapter>;
