// Parity adapter for render_engine.excalidraw.arrow_routing.passes (WP07).
import type { Adapter } from '../parity/functions.test.ts';
import { pyEq } from '../../src/py/eq.ts';

type Dict = Record<string, unknown>;

/**
 * In Python ``elements_by_id`` maps every generated element id to the same
 * dict object that sits in ``arrow_elems`` (arrow_adder builds it from
 * ``new_arrows``), so committing a reroute also moves the ``elements_by_id``
 * entry. JSON fixtures lose that aliasing; put it back for entries that are
 * structurally equal to the arrow with the same id.
 */
function realiasElementsById(bound: unknown[]): unknown[] {
  const args = [...bound];
  const arrows = args[0] as Dict[];
  const byId = args[2] as Dict;
  if (Array.isArray(arrows) && byId && typeof byId === 'object') {
    for (const arrow of arrows) {
      const key = String(arrow.id);
      if (Object.prototype.hasOwnProperty.call(byId, key) && pyEq(byId[key], arrow)) byId[key] = arrow;
    }
  }
  return args;
}

export default {
  _reduce_crossings: { args: realiasElementsById },
  _route_concept_corridors: { args: realiasElementsById },
} satisfies Record<string, Adapter>;
