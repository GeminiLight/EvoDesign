import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import type { Adapter } from '../parity/functions.test.ts';
import { EditApplyOutcome, IterationLog, VerifierRefinerState } from '../../src/refinement_stage/state.ts';

// Model arguments are recorded as field dicts: rebuild the pydantic instances.
const model = (cls: new (data: Record<string, unknown>) => unknown): Adapter => ({
  args: (bound) => [new cls(bound[0] as Record<string, unknown>), ...bound.slice(1)],
});

// Timestamps are wall-clock: same format ⇒ same value.
const TIMESTAMP = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/;
const sameTimestamp = (actual: unknown, expected: unknown): unknown =>
  typeof actual === 'string' && TIMESTAMP.test(actual) && typeof expected === 'string' && TIMESTAMP.test(expected) ? expected : actual;

// write_refiner_report: the recorded output directories were temporary and are
// gone; write into a fresh temp dir and map the returned paths back.
let outDir: string | null = null;
let recordedDir = '';

export default {
  _outcome_to_dict: model(EditApplyOutcome),
  _edit_row_md: model(EditApplyOutcome),
  _iteration_to_dict: model(IterationLog),
  _render_iteration_md: model(IterationLog),
  _utc_timestamp: { result: (actual, vector) => sameTimestamp(actual, vector.result) },
  build_refiner_report: {
    args: (bound) => [new VerifierRefinerState(bound[0] as Record<string, unknown>), ...bound.slice(1)],
    result: (actual, vector) => {
      const report = actual as { metadata: { timestamp: unknown } };
      report.metadata.timestamp = sameTimestamp(report.metadata.timestamp, (vector.result as typeof report).metadata.timestamp);
      return report;
    },
  },
  write_refiner_report: {
    args: (bound) => {
      recordedDir = bound[1] as string;
      outDir = mkdtempSync(join(tmpdir(), 'wp22-report-'));
      return [bound[0], outDir, ...bound.slice(2)];
    },
    result: (actual) => {
      const paths = Object.fromEntries(
        Object.entries(actual as Record<string, string>).map(([key, path]) => [key, recordedDir + path.slice(outDir!.length)]),
      );
      rmSync(outDir!, { recursive: true, force: true });
      outDir = null;
      return paths;
    },
    // args_after[1] is the recorded directory; the call received the temp dir.
    checkMutation: false,
  },
} satisfies Record<string, Adapter>;
