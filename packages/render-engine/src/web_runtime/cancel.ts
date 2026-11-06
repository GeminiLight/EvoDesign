// Cancellation for the web runtime (PHASE3_PLAN.md WP29): the TS counterpart of
// the backend stopping the stream when the client disconnects
// (``_stream_client_disconnected`` → ``return``; ``asyncio.CancelledError`` is
// a BaseException, so ``except Exception`` blocks never swallow it).
//
// The pipeline itself is not interruptible mid-call; the runtime checks the
// AbortSignal between stages and events and throws ``StreamCancelledError``.

/** ``asyncio.CancelledError`` stand-in (not an ``Exception`` for the stream's handlers). */
export class StreamCancelledError extends Error {
  constructor(message = 'The diagram stream was cancelled') {
    super(message);
    this.name = 'AbortError';
  }
}

export function isCancellation(error: unknown): boolean {
  return error instanceof StreamCancelledError;
}

export function throwIfAborted(signal: AbortSignal | null | undefined): void {
  if (signal?.aborted) throw new StreamCancelledError();
}
