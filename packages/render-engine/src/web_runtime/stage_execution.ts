// Ported from backend/app/services/workflow_runtime/stage_execution.py — keep
// in sync (PHASE3_PLAN.md WP29).

import { getLogger } from '../py/logging.ts';
import { WorkflowStageFailure, _stage_failure } from './errors.ts';
import { isCancellation } from './cancel.ts';

const default_logger = getLogger('app.services.workflow_runtime.stage_execution');

/** Result of executing one streaming workflow stage. */
export class StageRunResult {
  constructor(readonly duration_ms: number, readonly failure: WorkflowStageFailure | null = null) {}

  get succeeded(): boolean {
    return this.failure === null;
  }
}

/** ``time.monotonic()`` in seconds. */
export function monotonic(): number {
  const perf = (globalThis as { performance?: { now(): number } }).performance;
  return (perf ? perf.now() : Date.now()) / 1000;
}

/** Run one streaming stage and convert engine failures to safe metadata. */
export async function run_streaming_stage(
  { request_id, stage, handler }: { request_id: string; stage: string; handler: () => Promise<void>; stage_logger?: unknown },
): Promise<StageRunResult> {
  const t0 = monotonic();
  try {
    await handler();
  } catch (stage_exc) {
    // ``except Exception``: cancellation (CancelledError is a BaseException) propagates.
    if (isCancellation(stage_exc)) throw stage_exc;
    const failure = _stage_failure({ request_id, stage, exc: stage_exc });
    default_logger.error('Streaming workflow stage failed', failure.log_context());
    return new StageRunResult(0, failure);
  }
  return new StageRunResult(Math.trunc((monotonic() - t0) * 1000));
}
