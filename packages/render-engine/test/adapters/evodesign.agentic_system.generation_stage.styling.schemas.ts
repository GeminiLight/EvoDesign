import type { Adapter } from '../parity/functions.test.ts';

// Python validators return None; the TS ports are ``void`` (undefined).
const noneResult: Adapter = { result: (actual) => (actual === undefined ? null : actual) };

export default {
  _reject_layout_owned_fields: noneResult,
  _require_hex_color: noneResult,
  _require_tldraw_color: noneResult,
  _validate_edge_entry: noneResult,
  _validate_icon_entry: noneResult,
  _validate_required_coverage: noneResult,
  _validate_shape_entry: noneResult,
  _validate_title_entry: noneResult,
} satisfies Record<string, Adapter>;
