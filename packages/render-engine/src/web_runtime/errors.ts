// Ported from backend/app/services/workflow_runtime/errors.py — keep in sync
// (PHASE3_PLAN.md WP29). Sanitized workflow error contracts for streaming
// generation.

import { RuntimeError } from '../py/errors.ts';
import { RefineErrorPayload, StreamErrorPayload } from './event_payloads.ts';

export const PUBLIC_STAGE_ERROR_MESSAGE = 'Diagram generation failed';
export const PUBLIC_STAGE_ERROR_DETAIL = 'The diagram generation stage failed.';
export const PUBLIC_REFINER_ERROR_MESSAGE = 'Refiner failed';
export const PUBLIC_REFINER_ERROR_DETAIL = 'Auto-refinement could not complete.';
export const PUBLIC_REFINER_DEGRADED_MESSAGE = 'Auto-refinement failed; using base diagram.';
export const PUBLIC_REFINER_NOT_NEEDED_MESSAGE = 'No auto-refinement needed.';
export const PUBLIC_REFINER_UNSUPPORTED_CANVAS_MESSAGE = 'Auto-refinement is currently available for Excalidraw only.';
export const PUBLIC_REFINER_START_MESSAGE = 'Refiner Agent is fixing visual issues...';
export const PUBLIC_REFINER_COMPLETE_MESSAGE = 'Refining complete';
export const PUBLIC_REFINER_DISABLED_MESSAGE = 'Automatic refinement is disabled in server settings';
export const REFINER_FAILURE_VERIFICATION = 'verification';
export const REFINER_FAILURE_EXECUTION = 'execution';
export const REFINER_FAILURE_ARTIFACT = 'artifact';
export const REFINER_STAGE_INDEX = 7;
export const REFINER_TOTAL_STAGES = 9;

/** ``type(exc).__name__`` */
export function errorTypeName(exc: unknown): string {
  if (exc instanceof Error) return exc.constructor?.name || exc.name || 'Error';
  return typeof exc;
}

/** Sanitized failure metadata for a streaming workflow stage. */
export class WorkflowStageFailure {
  constructor(readonly request_id: string, readonly stage: string, readonly error_type: string) {}

  /** The client-safe SSE error payload. */
  public_payload(): StreamErrorPayload {
    return StreamErrorPayload({ stage: this.stage, message: PUBLIC_STAGE_ERROR_MESSAGE, detail: PUBLIC_STAGE_ERROR_DETAIL });
  }

  log_context(): Record<string, string> {
    return { request_id: this.request_id, stage: this.stage, error_type: this.error_type };
  }
}

/** Internal refiner failure with a sanitized phase for diagnostics. */
export class RefinerPipelineError extends RuntimeError {
  readonly phase: string;
  /** ``__cause__`` */
  cause_exc: unknown = null;

  constructor({ phase, reason }: { phase: string; reason: string }) {
    super(reason);
    this.phase = phase;
  }
}

/** Refiner completed its call but reported a failed terminal status. */
export class RefinerExecutionStatusError extends RefinerPipelineError {}

/** Refiner produced incomplete or unusable output artifacts. */
export class RefinerArtifactError extends RefinerPipelineError {}

/** Sanitized failure metadata for the optional refinement pipeline. */
export class RefinerFailure {
  constructor(readonly request_id: string, readonly phase: string, readonly error_type: string) {}

  public_payload(): RefineErrorPayload {
    return _refine_error_payload();
  }

  log_context(): Record<string, string> {
    return { request_id: this.request_id, stage: 'refining', phase: this.phase, error_type: this.error_type };
  }
}

export function _stage_failure({ request_id, stage, exc }: { request_id: string; stage: string; exc: unknown }): WorkflowStageFailure {
  return new WorkflowStageFailure(request_id, stage, errorTypeName(exc));
}

export function _refine_error_payload(): RefineErrorPayload {
  return RefineErrorPayload({ message: PUBLIC_REFINER_ERROR_MESSAGE, detail: PUBLIC_REFINER_ERROR_DETAIL });
}

export function _refiner_failure({ request_id, exc }: { request_id: string; exc: unknown }): RefinerFailure {
  const cause = (exc instanceof RefinerPipelineError && exc.cause_exc) || exc;
  const phase = exc instanceof RefinerPipelineError ? exc.phase : REFINER_FAILURE_EXECUTION;
  return new RefinerFailure(request_id, phase, errorTypeName(cause));
}

export function _wrap_refiner_error({ phase, reason, exc }: { phase: string; reason: string; exc: unknown }): RefinerPipelineError {
  const error = new RefinerPipelineError({ phase, reason });
  error.cause_exc = exc;
  return error;
}
