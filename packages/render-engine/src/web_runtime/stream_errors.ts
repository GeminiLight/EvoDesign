// Ported from backend/app/services/workflow_runtime/stream_errors.py — keep in
// sync (PHASE3_PLAN.md WP29). Public SSE error contract for diagram streaming.

import { ValueError } from '../py/errors.ts';
import { getLogger } from '../py/logging.ts';
import { GenerationInputValidationError } from './canvas.ts';
import { StreamErrorPayload, type StreamErrorStage } from './event_payloads.ts';
import { BackendLLMConfigurationError } from './llm_client.ts';

const logger = getLogger('app.services.workflow_runtime.stream_errors');

export const GENERIC_GENERATION_ERROR = 'Diagram generation failed';
export const STREAM_INIT_ERROR_DETAIL = 'The streaming generation request could not start.';
export const STREAM_GENERATION_ERROR_DETAIL = 'The streaming generation request could not complete.';
export const STREAM_REWRITE_ERROR_DETAIL = 'The streaming generation result could not be processed.';

export function _stream_error_payload(
  { stage = 'init', message = GENERIC_GENERATION_ERROR, detail = STREAM_INIT_ERROR_DETAIL }:
  { stage?: StreamErrorStage; message?: string; detail?: string } = {},
): StreamErrorPayload {
  return StreamErrorPayload({ stage, message, detail });
}

/** The streaming stage that best describes a generation failure. */
export function _generation_error_stage(emitted_chunk: boolean): StreamErrorStage {
  return emitted_chunk ? 'generation' : 'init';
}

export function _generation_error_detail(emitted_chunk: boolean): string {
  return emitted_chunk ? STREAM_GENERATION_ERROR_DETAIL : STREAM_INIT_ERROR_DETAIL;
}

/** Map generation exceptions to the stable public SSE error contract. */
export function _generation_stream_error_payload(exc: unknown, emitted_chunk: boolean): StreamErrorPayload {
  const stage = _generation_error_stage(emitted_chunk);
  if (exc instanceof GenerationInputValidationError) {
    return StreamErrorPayload({ stage, message: exc.public_detail, detail: exc.public_detail });
  }
  return StreamErrorPayload({ stage, message: GENERIC_GENERATION_ERROR, detail: _generation_error_detail(emitted_chunk) });
}

/** Map rewrite exceptions to the stable public SSE error contract. */
export function _rewrite_stream_error_payload(exc: unknown): StreamErrorPayload {
  if (exc instanceof GenerationInputValidationError) {
    return StreamErrorPayload({ stage: 'rewrite', message: exc.public_detail, detail: exc.public_detail });
  }
  return StreamErrorPayload({ stage: 'rewrite', message: GENERIC_GENERATION_ERROR, detail: STREAM_REWRITE_ERROR_DETAIL });
}

/** Log generation errors with private diagnostics while preserving public SSE. */
export function _log_generation_stream_error(exc: unknown, emitted_chunk: boolean): void {
  if (exc instanceof GenerationInputValidationError) logger.warning('Streaming diagram generation rejected:', exc);
  else if (exc instanceof BackendLLMConfigurationError) logger.exception('Streaming generation backend LLM configuration is invalid');
  else if (exc instanceof ValueError) logger.exception('Streaming diagram generation failed with internal validation error');
  else if (emitted_chunk) logger.exception('Streaming diagram generation failed after streaming started');
  else logger.exception('Streaming diagram generation failed before streaming started');
}
