// Ported from backend/app/schemas/diagram_generate.py — keep in sync
// (PHASE3_PLAN.md WP29). Only ``DiagramGenerateRequest`` (the body of
// POST /diagram/generate/stream) is needed by the web runtime.
//
// The backend rejects an invalid body with HTTP 422 before any SSE event is
// sent; ``validate_diagram_generate_request`` throws ``RequestValidationError``
// (carrying pydantic-shaped ``errors``) in that situation, and the web runtime
// lets it propagate from ``streamDiagram`` without emitting events.

import { ValueError } from '../py/errors.ts';
import { pyJsonDumps } from '../py/json.ts';
import { cpLen } from '../py/str.ts';
import { normalize_supported_diagram_type } from '../common/diagram_types.ts';
import { normalize_canvas_library_value, type CanvasLibrary } from './canvas.ts';

// Input caps keep one request from monopolising the LLM pipeline or memory.
export const MAX_CONTEXT_CHARS = 100_000;
export const MAX_REQUIREMENTS_CHARS = 50_000;
export const MAX_INSTRUCTION_CHARS = 10_000;
export const MAX_NODE_ID_LIST_ITEMS = 2_000;
export const MAX_NODE_ID_CHARS = 256;
export const MAX_CURRENT_SCHEMA_BYTES = 5 * 1024 * 1024;

type Dict = Record<string, any>;

export interface ValidationErrorItem {
  type: string;
  loc: (string | number)[];
  msg: string;
}

/** FastAPI's 422 for an invalid request body (``pydantic.ValidationError``). */
export class RequestValidationError extends ValueError {
  readonly status_code = 422;
  constructor(readonly errors: ValidationErrorItem[]) {
    super(`${errors.length} validation error${errors.length === 1 ? '' : 's'} for DiagramGenerateRequest\n`
      + errors.map((e) => `${e.loc.join('.')}\n  ${e.msg}`).join('\n'));
  }
}

export interface DiagramGenerateRequest {
  use_icons: boolean;
  diagram_type: string | null;
  context: string;
  requirements: string | null;
  locked_nodes: string[];
  project_id: string | null;
  base_version: number | null;
  current_schema: Dict | null;
  canvas_library: CanvasLibrary;
}

const FIELDS = ['use_icons', 'diagram_type', 'context', 'requirements', 'locked_nodes', 'project_id', 'base_version', 'current_schema', 'canvas_library'];

const has = (obj: object, key: string) => Object.prototype.hasOwnProperty.call(obj, key);
const isDict = (value: unknown): value is Dict => Boolean(value) && typeof value === 'object' && !Array.isArray(value);

/** Reject canvas schemas whose compact JSON exceeds MAX_CURRENT_SCHEMA_BYTES. */
export function _require_schema_size(value: Dict | null): Dict | null {
  if (value === null || value === undefined) return value;
  let text: string;
  try {
    text = pyJsonDumps(value, { separators: [',', ':'], ensureAscii: false });
  } catch {
    throw new ValueError('current_schema must be JSON serializable');
  }
  const size = new TextEncoder().encode(text).length;
  if (size > MAX_CURRENT_SCHEMA_BYTES) {
    throw new ValueError(`current_schema is too large (${size} bytes; limit ${MAX_CURRENT_SCHEMA_BYTES})`);
  }
  return value;
}

/** ``DiagramGenerateRequest.model_validate(body)`` */
export function validate_diagram_generate_request(body: unknown): DiagramGenerateRequest {
  const errors: ValidationErrorItem[] = [];
  const error = (loc: string, type: string, msg: string) => errors.push({ type, loc: ['body', loc], msg });
  if (!isDict(body)) {
    throw new RequestValidationError([{ type: 'model_type', loc: ['body'], msg: 'Input should be a valid dictionary or object to extract fields from' }]);
  }
  for (const key of Object.keys(body)) {
    if (!FIELDS.includes(key)) error(key, 'extra_forbidden', 'Extra inputs are not permitted');
  }
  const optionalStr = (key: string, max: number | null): string | null => {
    const value = body[key];
    if (value === null || value === undefined) return null;
    if (typeof value !== 'string') { error(key, 'string_type', 'Input should be a valid string'); return null; }
    if (max !== null && cpLen(value) > max) error(key, 'string_too_long', `String should have at most ${max} characters`);
    return value;
  };

  let use_icons = true;
  if (has(body, 'use_icons')) {
    if (typeof body.use_icons !== 'boolean') error('use_icons', 'bool_type', 'Input should be a valid boolean');
    else use_icons = body.use_icons;
  }

  let diagram_type: string | null = null;
  if (body.diagram_type !== null && body.diagram_type !== undefined && body.diagram_type !== 'automated') {
    try {
      diagram_type = normalize_supported_diagram_type(body.diagram_type);
    } catch (exc) {
      if (!(exc instanceof ValueError)) throw exc;
      error('diagram_type', 'value_error', `Value error, ${exc.message}`);
    }
  }

  let context = '';
  if (!has(body, 'context')) error('context', 'missing', 'Field required');
  else if (typeof body.context !== 'string') error('context', 'string_type', 'Input should be a valid string');
  else context = optionalStr('context', MAX_CONTEXT_CHARS) ?? '';

  const requirements = optionalStr('requirements', MAX_REQUIREMENTS_CHARS);

  let locked_nodes: string[] = [];
  if (has(body, 'locked_nodes')) {
    if (!Array.isArray(body.locked_nodes)) error('locked_nodes', 'list_type', 'Input should be a valid list');
    else {
      if (body.locked_nodes.length > MAX_NODE_ID_LIST_ITEMS) {
        error('locked_nodes', 'too_long', `List should have at most ${MAX_NODE_ID_LIST_ITEMS} items after validation, not ${body.locked_nodes.length}`);
      }
      body.locked_nodes.forEach((item: unknown, index: number) => {
        if (typeof item !== 'string') errors.push({ type: 'string_type', loc: ['body', 'locked_nodes', index], msg: 'Input should be a valid string' });
        else if (cpLen(item) > MAX_NODE_ID_CHARS) {
          errors.push({ type: 'string_too_long', loc: ['body', 'locked_nodes', index], msg: `String should have at most ${MAX_NODE_ID_CHARS} characters` });
        }
      });
      locked_nodes = [...body.locked_nodes];
    }
  }

  const project_id = optionalStr('project_id', null);

  let base_version: number | null = null;
  if (body.base_version !== null && body.base_version !== undefined) {
    if (typeof body.base_version !== 'number' || !Number.isInteger(body.base_version)) error('base_version', 'int_type', 'Input should be a valid integer');
    else if (body.base_version < 1) error('base_version', 'greater_than_equal', 'Input should be greater than or equal to 1');
    else base_version = body.base_version;
  }

  let current_schema: Dict | null = null;
  if (body.current_schema !== null && body.current_schema !== undefined) {
    if (!isDict(body.current_schema)) error('current_schema', 'dict_type', 'Input should be a valid dictionary');
    else {
      try {
        current_schema = _require_schema_size(body.current_schema);
      } catch (exc) {
        if (!(exc instanceof ValueError)) throw exc;
        error('current_schema', 'value_error', `Value error, ${exc.message}`);
      }
    }
  }

  let canvas_library: CanvasLibrary = 'excalidraw';
  if (!has(body, 'canvas_library')) error('canvas_library', 'missing', 'Field required');
  else {
    try {
      canvas_library = normalize_canvas_library_value(body.canvas_library);
    } catch (exc) {
      if (!(exc instanceof ValueError)) throw exc;
      error('canvas_library', 'value_error', `Value error, ${exc.message}`);
    }
  }

  if (errors.length) throw new RequestValidationError(errors);

  // @model_validator(mode="after") require_project_version
  if (!has(body, 'use_icons')) {
    if (canvas_library !== 'excalidraw') {
      use_icons = false;
    } else {
      const elements = (current_schema || {}).elements;
      if (Array.isArray(elements)) {
        const live = elements.filter((e) => isDict(e) && !e.isDeleted);
        if (live.length) {
          use_icons = live.some((e: Dict) => e.type === 'image' && isDict(e.customData) && Boolean(e.customData.evoDesignIcon));
        }
      }
    }
  }
  if (project_id && !project_id.startsWith('guest_') && base_version === null) {
    throw new RequestValidationError([{
      type: 'value_error', loc: ['body'], msg: 'Value error, base_version is required when generating into an existing project',
    }]);
  }

  return { use_icons, diagram_type, context, requirements, locked_nodes, project_id, base_version, current_schema, canvas_library };
}
