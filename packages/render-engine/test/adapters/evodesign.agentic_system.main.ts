import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import type { Adapter } from '../parity/functions.test.ts';
import { FIXTURES, type Vector } from '../harness/fixtures.ts';
import { _globals } from '../../src/agentic_system/main.ts';

// WP23 adapters for agentic_system.main.
//
// * get_output_dir / get_output_failure_dir: the pytest calls ran with
//   monkeypatched module globals (EXAMPLES_DIR → <pytest tmp>/examples;
//   get_experiment_id / get_evodesign_output_dir → a tmp tree). main.ts reads
//   those names through ``_globals`` (TS imports are read-only); the adapter
//   sets them from the recorded result for the duration of the call.
// * load_dataset: the run vectors read <run tmp>/dataset.json, deleted after
//   recording. record_runs.py wrote it as json.dumps([item], indent=2,
//   ensure_ascii=False); the adapter recreates it from fixtures/runs/<run>/
//   input.json in a fresh temp dir and maps the returned path back.
// * initialize_model / initialize_router_model / process_example / main are
//   async (model creation, the whole pipeline): skipped, covered by
//   npm run parity:runs (models are created through the cassette factory,
//   process_example's return value is compared as the run result).

type Dict = Record<string, any>;

const original = { ..._globals };
const restoreGlobals = () => Object.assign(_globals, original);

function patchGlobals(vector: Vector): void {
  restoreGlobals();
  const result = typeof vector.result === 'string' ? vector.result : '';
  const examples = result.indexOf('/examples/');
  if (examples >= 0) {
    _globals.EXAMPLES_DIR = result.slice(0, examples + '/examples'.length);
    return;
  }
  const outputs = /^(.*)\/([^/]+)\/outputs\//.exec(result);
  if (outputs) {
    const [, root, expId] = outputs;
    _globals.get_experiment_id = () => expId;
    _globals.get_evodesign_output_dir = (variant: string, model_id: string, exp_id: string | null = null) => join(root, String(exp_id), 'outputs', variant, model_id);
  }
}

const outputDirAdapter: Adapter = {
  args: (bound, vector) => {
    patchGlobals(vector);
    return bound;
  },
  result: (actual) => {
    restoreGlobals();
    return actual;
  },
};

let datasetRoot: string | null = null;
const datasetMap = new WeakMap<Vector, { from: string; to: string }>();

function loadDatasetArgs(bound: unknown[], vector: Vector): unknown[] {
  const run = vector.source.startsWith('run:') ? vector.source.slice(4) : null;
  const from = String(bound[0] ?? '');
  if (!run || !from) return bound;
  const input = JSON.parse(readFileSync(join(FIXTURES, 'runs', run, 'input.json'), 'utf-8')) as { item: Dict };
  datasetRoot ??= mkdtempSync(join(tmpdir(), 'wp23-load-dataset-'));
  const to = join(datasetRoot, `${run}.json`);
  writeFileSync(to, JSON.stringify([input.item], null, 2), 'utf-8');
  datasetMap.set(vector, { from, to });
  return [to, ...bound.slice(1)];
}

function loadDatasetResult(actual: unknown, vector: Vector): unknown {
  const mapping = datasetMap.get(vector);
  if (!mapping || !Array.isArray(actual)) return actual;
  return [actual[0], actual[1] === mapping.to ? mapping.from : actual[1]];
}

const ASYNC = 'async; covered by npm run parity:runs';

export default {
  get_output_dir: outputDirAdapter,
  get_output_failure_dir: outputDirAdapter,
  load_dataset: { args: loadDatasetArgs, result: loadDatasetResult, checkMutation: false },
  initialize_model: { skip: `${ASYNC} (every model is created through the cassette chatModelFactory; the cassette checks model params per call)` },
  initialize_router_model: { skip: `${ASYNC} (router model creation; the cassette checks model params per call)` },
  process_example: { skip: `${ASYNC} (process_example() return value is the compared run result)` },
  main: { skip: 'async; the recorded pytest calls monkeypatch parse_arguments/build_config/process_example/... with lambdas that cannot be replayed' },
} satisfies Record<string, Adapter>;
