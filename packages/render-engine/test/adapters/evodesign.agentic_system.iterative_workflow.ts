import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';
import { join } from 'node:path';
import type { Adapter } from '../parity/functions.test.ts';
import { FIXTURES, bindArguments, signatureOf, type Vector } from '../harness/fixtures.ts';
import { pyJsonLoadsExact } from '../../src/py/json_decoder.ts';
import { Finding } from '../../src/verification_stage/checks/finding.ts';
import { EditApplyOutcome, EditOp, IterationLog, VerifierRefinerState } from '../../src/refinement_stage/state.ts';

// WP23 adapters for iterative_workflow.
//
// * Pydantic arguments (VerifierRefinerState, IterationLog, EditApplyOutcome,
//   EditOp, Finding) are recorded as field dicts; they are rebuilt into the TS
//   model classes. The TS objects keep exactly the model fields as own
//   properties, so args_after still compares field by field.
// * Paths recorded inside a run point into the deleted temporary run
//   directory (<tmp>/evodesign-run-XXXXXXXX/out/...). Functions that read
//   files get them rewritten to fixtures/runs/<run>/artifacts (normalized
//   copies, "<OUT>" for the run dir) and the result mapped back.
// * Async nodes (they render through the port-3001 renderer and/or call the
//   model) cannot run under the synchronous harness: skipped, covered by
//   `npm run parity:runs` (every run_iteration / finalize snapshot).

type Dict = Record<string, any>;

const MODULE = 'evodesign.agentic_system.iterative_workflow';
const RUN_OUT = /([^\s"'<>]*\/evodesign-run-[A-Za-z0-9_]+)\/out(?=\/|$)/;

interface Mapping { run: string; runDir: string; artifacts: string }
const mappings = new WeakMap<Vector, Mapping>();

function mapStrings(value: unknown, fn: (text: string) => string): unknown {
  if (typeof value === 'string') return fn(value);
  if (Array.isArray(value)) return value.map((item) => mapStrings(item, fn));
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, mapStrings(item, fn)]));
  }
  return value;
}

function mappingFor(vector: Vector, args: unknown[]): Mapping | null {
  const run = vector.source.startsWith('run:') ? vector.source.slice(4) : null;
  const match = RUN_OUT.exec(JSON.stringify(args) ?? '');
  if (!run || !match) return null;
  const mapping = { run, runDir: match[1], artifacts: join(FIXTURES, 'runs', run, 'artifacts') };
  mappings.set(vector, mapping);
  return mapping;
}

function mapIn(value: unknown, mapping: Mapping | null): unknown {
  if (!mapping) return value;
  return mapStrings(value, (text) => text.split(`${mapping.runDir}/out`).join(mapping.artifacts));
}

function mapOut(value: unknown, vector: Vector): unknown {
  const plain = JSON.parse(JSON.stringify(value ?? null));
  const mapping = mappings.get(vector);
  const mapped = mapStrings(plain, (text) => (mapping
    ? text.split(mapping.artifacts).join(`${mapping.runDir}/out`).split('<OUT>').join(mapping.runDir)
    : text));
  return mapping ? denormalize(vector.result, mapped) : mapped;
}

// The artifact copies are normalized (tools/run_normalize.py): ISO timestamps
// became "<TIMESTAMP>" and duration_ms / elapsed_seconds became 0. Where the
// loaded copy holds such a placeholder, take the recorded value.
const ISO = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?$/;
function denormalize(expected: unknown, actual: unknown, key = ''): unknown {
  if (actual === '<TIMESTAMP>' && typeof expected === 'string' && ISO.test(expected)) return expected;
  if ((key === 'duration_ms' || key === 'elapsed_seconds') && actual === 0 && typeof expected === 'number') return expected;
  if (Array.isArray(actual) && Array.isArray(expected)) return actual.map((item, i) => denormalize(expected[i], item));
  if (actual && typeof actual === 'object' && expected && typeof expected === 'object' && !Array.isArray(actual)) {
    return Object.fromEntries(Object.entries(actual).map(([k, v]) => [k, denormalize((expected as Dict)[k], v, k)]));
  }
  return actual;
}

const state = (value: unknown) => new VerifierRefinerState(value as Dict);
const log = (value: unknown) => (value instanceof IterationLog ? value : new IterationLog(value as Dict));
const finding = (value: unknown) => (value instanceof Finding ? value : new Finding(value as never));
const outcome = (value: unknown) => (value instanceof EditApplyOutcome ? value : new EditApplyOutcome(value as Dict));
const edit = (value: unknown) => (value instanceof EditOp ? value : new EditOp(value as Dict));

/** Re-read the raw vector line with the CPython decoder (keeps ``1.0`` vs ``1``). */
function rawArgs(func: string): Adapter['args'] {
  return (_bound, vector) => {
    const lines = readFileSync(join(FIXTURES, 'functions', MODULE, `${func}.jsonl`), 'utf-8').split('\n').filter(Boolean);
    const raw = pyJsonLoadsExact(lines[vector.line - 1]) as { args: unknown[]; kwargs: Record<string, unknown> };
    return bindArguments(signatureOf(MODULE, func)!, { ...vector, args: raw.args, kwargs: raw.kwargs });
  };
}

const ASYNC = 'async (renders through the port-3001 renderer and/or calls the model); the synchronous harness cannot await it — covered by npm run parity:runs node snapshots';

const nullResult = (actual: unknown) => (actual === undefined ? null : actual);

// pytest test_prepared_work_rejects_changed_input: the first calls read
// scene.json, then the test overwrites the file with '{"elements": []}' (what
// the leftover pytest directory still holds). For the calls made before the
// change, the original fixture content (identical to the sibling test's
// scene.json) is put back for the duration of the call, then restored.
const restore = new WeakMap<Vector, () => void>();
function swapOriginalScene(manifestPath: string, vector: Vector, beforeChange: boolean): void {
  if (vector.source !== 'pytest' || !beforeChange || !manifestPath.includes('/test_prepared_work_rejects_cha0/') || !existsSync(manifestPath)) return;
  const current = readFileSync(manifestPath);
  const sibling = join(dirname(dirname(manifestPath)), 'test_preparation_does_not_call0', 'scene.json');
  if (current.toString('utf-8') !== '{"elements": []}' || !existsSync(sibling)) return;
  writeFileSync(manifestPath, readFileSync(sibling));
  restore.set(vector, () => writeFileSync(manifestPath, current));
}
// Result of the post-change _input_fingerprint call (vector line 4).
const CHANGED_INPUT_FINGERPRINT = 'cf0b081d1b33786e574fd82e1ce9e097bf7a6080c326c4afe9abb5dd1b2d3e46';
const restored = (actual: unknown, vector: Vector) => {
  restore.get(vector)?.();
  return actual;
};

export default {
  _input_fingerprint: {
    args: (bound, vector) => {
      swapOriginalScene(String((bound[0] as Dict)?.manifest_path ?? ''), vector, vector.result !== CHANGED_INPUT_FINGERPRINT);
      return bound;
    },
    result: restored,
  },
  _findings_to_dicts: { args: ([findings]) => [(findings as unknown[]).map(finding)] },
  _outcome_to_prompt_dict: { args: ([o]) => [outcome(o)] },
  _iter_log_to_prompt_dict: { args: ([l]) => [log(l)] },
  _apply_edit_batch: {
    // (state, edits, *, log, target_attr, log_prefix)
    args: ([s, edits, l, ...rest]) => [state(s), (edits as unknown[]).map(edit), log(l), ...rest],
  },
  _refresh_edited_geometry: {
    // (state, outcomes, *, log)
    args: ([s, outcomes, l]) => [state(s), (outcomes as unknown[]).map(outcome), log(l)],
  },
  _repair_derived_geometry: {
    // (state, *, log, touched_ids, geometry_refreshed=False)
    args: ([s, l, ...rest]) => [state(s), log(l), ...rest],
    result: nullResult,
  },
  _mark_convergence: {
    // (state, *, log, findings_after_iter, edits_applied, iteration)
    args: ([s, l, findings, ...rest]) => [state(s), log(l), (findings as unknown[]).map(finding), ...rest],
    result: nullResult,
  },
  _manifest_fingerprint: {
    // json.dumps prints Python floats as ``120.0``: keep that distinction.
    args: rawArgs('_manifest_fingerprint'),
  },
  _load_json: {
    args: (bound, vector) => mapIn(bound, mappingFor(vector, bound)) as unknown[],
    result: (actual, vector) => mapOut(actual, vector),
    checkMutation: false,
  },
  _node_load_inputs: {
    args: (bound, vector) => {
      const mapping = mappingFor(vector, bound);
      const elements = ((vector.result as Dict)?.manifest as Dict)?.elements;
      swapOriginalScene(String((bound[0] as Dict)?.manifest_path ?? ''), vector, Array.isArray(elements) && elements.length > 0);
      return [state(mapIn(bound[0], mapping)), ...bound.slice(1)];
    },
    result: (actual, vector) => mapOut(restored(actual, vector), vector),
    checkMutation: false,
  },
  _prepare_iteration: { skip: ASYNC },
  _run_one_iteration: { skip: ASYNC },
  _refresh_image_for_llm: { skip: ASYNC },
  _rerender_iteration_image: { skip: ASYNC },
  _node_finalize: { skip: ASYNC },
} satisfies Record<string, Adapter>;
