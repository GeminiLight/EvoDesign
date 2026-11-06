// Ported from evodesign/agentic_system/render_engine/state.py — keep in sync.
//
// The pydantic model becomes a plain class whose fields are the render-relevant
// subset of WorkflowState + WorkflowStateBase (LLM-stage fields such as
// conversation_history are carried as-is but unused). Field defaults match
// Python. Pydantic validation (required structure/layout dicts, canvas_library
// normalisation) is reduced to the checks the render path relies on.

import { ValueError } from '../py/errors.ts';
import { isDict, isList } from '../py/truthy.ts';
import { CONVERT, MANIFEST_STAGES, RENDER, VALIDATE } from './stages.ts';

type Dict = Record<string, unknown>;

function _type_name(value: unknown): string {
  if (value === null || value === undefined) return 'NoneType';
  if (Array.isArray(value)) return 'list';
  if (typeof value === 'string') return 'str';
  if (typeof value === 'boolean') return 'bool';
  if (typeof value === 'number') return Number.isInteger(value) ? 'int' : 'float';
  if (isDict(value)) return 'dict';
  return typeof value;
}

export function _require_manifest(stage: string, payload: Dict): Dict {
  const manifest = payload.manifest ?? null;
  if (!isDict(manifest)) {
    throw new ValueError(
      `RenderWorkflow stage '${stage}' must return a manifest dict; `
      + `got ${_type_name(manifest)}.`,
    );
  }
  if (!isList(manifest.elements ?? null) && !isDict(manifest.document ?? null)) {
    throw new ValueError(
      `RenderWorkflow stage '${stage}' returned an invalid manifest. `
      + "Expected a top-level 'elements' list or 'document' object.",
    );
  }
  return manifest as Dict;
}

/** State container for the render workflow pipeline. */
export class WorkflowState {
  [key: string]: unknown;

  // WorkflowStateBase
  current_stage = 'init';
  canvas_library = 'excalidraw';
  text_content = '';
  user_query: string | null = null;
  stage_knowledge = '';
  design_expertise = '';
  runtime_directives = '';
  diagram_type: string | null = null;
  content_area: string | null = null;
  conversation_history: Dict[] = [];

  // WorkflowState
  structure_instantiation: Dict;
  layout_instantiation: Dict;
  layout_specification: Dict | null = null;
  design_constraints = '';

  validation_report: Dict | null = null;

  diagram_manifest: Dict | null = null;
  /** Intermediate snapshot without arrows, kept for debug or further processing. */
  manifest_without_arrows: Dict | null = null;

  render_stdout: string | null = null;
  render_stderr: string | null = null;

  constructor(fields: Dict) {
    if (!isDict(fields.structure_instantiation)) {
      throw new ValueError('structure_instantiation: Input should be a valid dictionary');
    }
    if (!isDict(fields.layout_instantiation)) {
      throw new ValueError('layout_instantiation: Input should be a valid dictionary');
    }
    this.structure_instantiation = fields.structure_instantiation as Dict;
    this.layout_instantiation = fields.layout_instantiation as Dict;
    for (const [key, value] of Object.entries(fields)) {
      if (key === 'canvas_library') {
        // evodesign.canvas_runtime.normalize_canvas_library
        const lib = String(value ?? 'None').trim().toLowerCase();
        if (lib !== 'tldraw' && lib !== 'excalidraw') {
          throw new ValueError(`Unknown canvas_library: '${String(value)}'. Use one of: tldraw, excalidraw.`);
        }
        this.canvas_library = lib;
      } else if (value !== undefined) {
        this[key] = value;
      }
    }
  }

  /** Update workflow bookkeeping after each stage finishes. */
  update_stage(stage: string, payload: Dict | null = null): void {
    payload = payload ?? {};
    this.current_stage = stage;

    if (MANIFEST_STAGES.has(stage)) {
      const manifest = _require_manifest(stage, payload);
      if (stage === CONVERT) {
        this.manifest_without_arrows = manifest;
      }
      this.diagram_manifest = manifest;
    } else if (stage === VALIDATE) {
      this.validation_report = payload;
    } else if (stage === RENDER) {
      this.render_stdout = (payload.stdout ?? null) as string | null;
      this.render_stderr = (payload.stderr ?? null) as string | null;
    } else {
      throw new ValueError(`Unknown stage name: ${stage}`);
    }
  }
}
