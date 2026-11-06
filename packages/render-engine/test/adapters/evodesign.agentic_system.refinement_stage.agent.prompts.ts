import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import type { Adapter } from '../parity/functions.test.ts';
import { FIXTURES, bindArguments, signatureOf } from '../harness/fixtures.ts';
import { pyJsonLoadsExact } from '../../src/py/json_decoder.ts';

// The prompt prints Python floats as ``190.0`` / ``score=7.0``. JSON.parse in
// the shared decoder drops the int/float distinction, so the arguments are
// re-read from the raw vector line with the CPython-compatible decoder, which
// records integral floats in ``PY_FLOAT_MARKS`` (the same thing the TS
// pipeline gets when it loads verifier_report.json with ``pyJsonLoadsExact``).
// These vectors carry no special encodings (no __tuple__/__model__), so the
// raw values are the decoded values.
const MODULE = 'evodesign.agentic_system.refinement_stage.agent.prompts';

function rawArgs(func: string): Adapter['args'] {
  return (_bound, vector) => {
    const lines = readFileSync(join(FIXTURES, 'functions', MODULE, `${func}.jsonl`), 'utf-8').split('\n').filter(Boolean);
    const raw = pyJsonLoadsExact(lines[vector.line - 1]) as { args: unknown[]; kwargs: Record<string, unknown> };
    return bindArguments(signatureOf(MODULE, func)!, { ...vector, args: raw.args, kwargs: raw.kwargs });
  };
}

export default {
  build_refiner_user_prompt: { args: rawArgs('build_refiner_user_prompt') },
} satisfies Record<string, Adapter>;
