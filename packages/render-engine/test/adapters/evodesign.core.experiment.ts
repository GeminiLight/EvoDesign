import type { Adapter } from '../parity/functions.test.ts';
import type { Vector } from '../harness/fixtures.ts';
import { setEnv } from '../../src/py/env.ts';
import { AppSettings } from '../../src/config/settings.ts';
import { _set_project_root, get_project_root } from '../../src/core/experiment.ts';

// The pytest vectors ran under monkeypatched EVO_EXPERIMENT_ID / settings /
// _PROJECT_ROOT. Each vector's expected outcome names the value that was in
// effect (the id inside the error message, or the last path segment of the
// result), so the adapter re-creates that environment before the call.
const REPO_ROOT = get_project_root();
const realSettings = AppSettings.get_default();

function fakeSettings(experimentId: string): AppSettings {
  const fake = Object.create(AppSettings.prototype) as AppSettings;
  fake._path = realSettings._path;
  fake._raw = { experiment: { id: experimentId } };
  return fake;
}

function environmentFor(vector: Vector): void {
  setEnv('EVO_EXPERIMENT_ID', null);
  AppSettings._instance = realSettings;
  _set_project_root(REPO_ROOT);
  const message = vector.message ?? '';
  const fromMessage = /from (EVO_EXPERIMENT_ID|settings\.yaml experiment\.id): .*'([^']*)'\.$/.exec(message);
  if (fromMessage) {
    if (fromMessage[1] === 'EVO_EXPERIMENT_ID') setEnv('EVO_EXPERIMENT_ID', fromMessage[2]);
    else AppSettings._instance = fakeSettings(fromMessage[2]);
    return;
  }
  const result = typeof vector.result === 'string' ? vector.result : null;
  if (result === null) return;
  const marker = '/experiments/';
  const at = result.indexOf(marker);
  if (at >= 0) {
    _set_project_root(result.slice(0, at));
    setEnv('EVO_EXPERIMENT_ID', result.slice(at + marker.length).split('/')[0]);
  } else {
    setEnv('EVO_EXPERIMENT_ID', result);
  }
}

const withEnvironment: Adapter = {
  args: (bound, vector) => {
    environmentFor(vector);
    return bound;
  },
};

export default {
  get_project_root: { args: (bound, vector) => { environmentFor({ ...vector, result: null }); return bound; } },
  get_experiment_id: withEnvironment,
  get_experiment_root: withEnvironment,
  get_evodesign_output_dir: withEnvironment,
  ensure_experiment_dirs: withEnvironment,
} satisfies Record<string, Adapter>;
