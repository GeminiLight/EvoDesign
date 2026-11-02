/**
 * Bounded JSON request parsing shared by the tool-service route handlers.
 *
 * Route handlers must not call `request.json()` directly: it buffers an
 * unbounded body and ignores Content-Type, which lets cross-site "simple"
 * (text/plain, no-cors) POSTs reach the handlers.
 */

export class JsonRequestError extends Error {
  constructor(message: string, readonly status: number = 400) {
    super(message);
  }
}

function readPositiveIntEnv(name: string, fallback: number): number {
  const parsed = Number.parseInt(process.env[name] ?? '', 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

/** Default cap for diagram payloads (Excalidraw scenes embed icon data URLs). */
export const DEFAULT_MAX_JSON_BODY_BYTES = readPositiveIntEnv(
  'TOOL_SERVICE_MAX_BODY_BYTES',
  25 * 1024 * 1024,
);

/** Smaller cap for the layout and text-width tools. */
export const DEFAULT_MAX_TOOL_BODY_BYTES = 1024 * 1024;

export function assertJsonContentType(request: Request): void {
  const contentType = (request.headers.get('content-type') || '').toLowerCase();
  const mediaType = contentType.split(';')[0].trim();
  if (mediaType !== 'application/json') {
    throw new JsonRequestError('Content-Type must be application/json', 415);
  }
}

export async function readBoundedText(request: Request, maxBytes: number): Promise<string> {
  const declared = Number(request.headers.get('content-length'));
  if (Number.isFinite(declared) && declared > maxBytes) {
    throw new JsonRequestError(`Request body exceeds ${maxBytes} bytes`, 413);
  }
  if (!request.body) return '';

  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > maxBytes) {
      await reader.cancel().catch(() => undefined);
      throw new JsonRequestError(`Request body exceeds ${maxBytes} bytes`, 413);
    }
    chunks.push(value);
  }
  return Buffer.concat(chunks.map((chunk) => Buffer.from(chunk))).toString('utf-8');
}

/** Require application/json, cap the body size, then parse. */
export async function readJsonRequest(
  request: Request,
  maxBytes: number = DEFAULT_MAX_JSON_BODY_BYTES,
): Promise<unknown> {
  assertJsonContentType(request);
  const text = await readBoundedText(request, maxBytes);
  try {
    return JSON.parse(text);
  } catch {
    throw new JsonRequestError('Request body must be valid JSON');
  }
}
