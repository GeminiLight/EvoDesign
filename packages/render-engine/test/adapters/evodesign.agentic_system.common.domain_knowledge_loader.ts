import { existsSync } from 'node:fs';
import { join } from 'node:path';
import type { Adapter } from '../parity/functions.test.ts';
import { PACKAGE_ROOT } from '../harness/fixtures.ts';
import { relativeAssetPath } from '../../src/py/assets.ts';

const colorfulPorted = existsSync(join(PACKAGE_ROOT, 'src/generation_stage/styling/colorful.ts'));

export default {
  // Python passes an absolute Path; the port reads assets by their path
  // relative to evodesign/agentic_system (py/assets.ts).
  _read_optional_text: { args: (bound) => [relativeAssetPath(bound[0] as string), ...bound.slice(1)], checkMutation: false },
  // Delegates to generation_stage/styling/colorful (WP16); replayed as soon as that port exists.
  ...(colorfulPorted ? {} : { get_selected_palette: { skip: 'needs generation_stage/styling/colorful.ts (WP16, not ported yet)' } }),
} satisfies Record<string, Adapter>;
