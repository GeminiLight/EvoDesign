import { existsSync } from 'node:fs';
import { join } from 'node:path';
import type { Adapter } from '../parity/functions.test.ts';
import { FIXTURES } from '../harness/fixtures.ts';

// The recorded PNG paths point into the run's (deleted) temp output dir; every
// file the pipeline left there is kept byte-for-byte as
// fixtures/runs/<run>/artifacts/<path>. validate_png_file only inspects the
// file, so the artifact stands in for it (the final file of that path: a
// pre-crop render was later overwritten by its cropped version — both are
// valid PNGs, which is all the recorded ``None`` result says).
export function artifactPath(path: string, source: string): string {
  const run = source.startsWith('run:') ? source.slice(4) : null;
  const at = path.indexOf('/out/');
  if (!run || at < 0) return path;
  const candidate = join(FIXTURES, 'runs', run, 'artifacts', path.slice(at + '/out/'.length));
  return existsSync(candidate) ? candidate : path;
}

export const pngPathAdapter: Adapter = {
  args: (bound, vector) => [artifactPath(bound[0] as string, vector.source), ...bound.slice(1)],
  // Python returns None; the TS function returns undefined (void).
  result: (actual) => (actual === undefined ? null : actual),
  // args_after holds the recorded temp path, not the remapped fixture path.
  checkMutation: false,
};

export default {
  validate_png_file: pngPathAdapter,
} satisfies Record<string, Adapter>;
