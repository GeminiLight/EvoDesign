import { EDIT_PROMPT } from '../../../../shared/diagram-prompts.mjs';
import type { DiagramRequest, DiagramResponse, DiagramLocalEditRequest, DiagramLocalEditResponse, StreamResultEvent } from '../../types/api';
import type { StreamCallbacks, StreamOptions } from '../apiDiagramService';
import { dispatchDiagramStreamEvent, diagramResponseFromStream } from '../apiDiagramService';
import { resolveNodeIcons } from '../projectPreferences';
import { callBrowserModel, loadModelConfig, parseModelJson } from './modelConfig';
import { reflowEditedText } from './scene';
import { runPipelineWorker } from './pipelineClient';
import { openModelSettings } from './runtime';

function model() {
  const config = loadModelConfig();
  if (!config.model.trim()) { openModelSettings(); throw new Error('Configure your API base URL, model and API key in Model settings, then try again.'); }
  return config;
}

export async function generateBrowserDiagram(request: DiagramRequest, requirements: string, callbacks: StreamCallbacks = {}, options: StreamOptions = {}): Promise<DiagramResponse> {
  if (request.metadata?.canvasLibrary === 'tldraw') throw new Error('The browser edition generates Excalidraw diagrams. Choose Excalidraw in workspace settings.');
  let current: Record<string, unknown> | null = null;
  if (request.metadata?.currentSchema) current = JSON.parse(request.metadata.currentSchema);
  const config = model();
  const result = await runPipelineWorker({
    context: request.prompt, requirements, diagram_type: request.diagramType === 'automated' ? null : request.diagramType,
    use_icons: resolveNodeIcons(request), locked_nodes: request.lockedNodes ?? [],
    current_schema: current, project_id: null, canvas_library: 'excalidraw',
  }, config, (name, payload) => dispatchDiagramStreamEvent(name, payload, callbacks), options.signal);
  const response = diagramResponseFromStream(result as unknown as StreamResultEvent, request, 'excalidraw');
  if (config.supportsVision === false) {
    const message = 'Visual review skipped: this model is configured for text only. Diagram checks still ran.';
    response.warnings = [...(response.warnings ?? []), message];
    if (response.generationReport) response.generationReport.refinement.reason = message;
  }
  return response;
}

const PATCH_FIELDS = new Set(['text', 'originalText', 'strokeColor', 'backgroundColor', 'strokeStyle', 'fontSize', 'x', 'y', 'width', 'height', 'strokeWidth', 'opacity']);
export function sanitizeEdit(value: unknown, request: DiagramLocalEditRequest): Record<string, unknown> {
  const answer = value && typeof value === 'object' ? value as Record<string, unknown> : {};
  const existing = (Array.isArray(request.current_schema.elements) ? request.current_schema.elements : []) as Record<string, unknown>[];
  const allowed = new Set(request.selected_node_ids);
  for (const e of existing) if (allowed.has(String(e.containerId))) allowed.add(String(e.id));
  const byId = new Map(existing.map(e => [String(e.id), e]));
  const elements = (Array.isArray(answer.elements) ? answer.elements : []).flatMap(raw => {
    if (!raw || typeof raw !== 'object' || !allowed.has(raw.id) || !byId.has(raw.id)) return [];
    const patch: Record<string, unknown> = { id: raw.id };
    for (const [k, v] of Object.entries(raw)) {
      if (!PATCH_FIELDS.has(k)) continue;
      if (['strokeColor', 'backgroundColor'].includes(k) && typeof v === 'string' && /^(#[\da-f]{6}|transparent)$/i.test(v)) patch[k] = v;
      else if (k === 'strokeStyle' && (v === 'solid' || v === 'dashed')) patch[k] = v;
      else if (['text', 'originalText'].includes(k) && byId.get(raw.id)?.type === 'text' && typeof v === 'string') patch[k] = v.slice(0, 1000);
      else if (typeof v === 'number' && Number.isFinite(v)) {
        if (['x', 'y'].includes(k) && Math.abs(v) <= 100_000) patch[k] = v;
        if (['width', 'height'].includes(k) && v >= 8 && v <= 5000) patch[k] = v;
        if (k === 'fontSize' && v >= 10 && v <= 80) patch[k] = v;
        if (k === 'strokeWidth' && v >= 0.5 && v <= 8) patch[k] = v;
        if (k === 'opacity' && v >= 0 && v <= 100) patch[k] = v;
      }
    }
    if (typeof patch.text === 'string') patch.originalText = patch.text;
    return Object.keys(patch).length > 1 ? [patch] : [];
  });
  const deleted_ids = Array.isArray(answer.deleted_ids) ? answer.deleted_ids.filter(id => typeof id === 'string' && allowed.has(id) && byId.has(id)) : [];
  if (!elements.length && !deleted_ids.length) throw new Error('No applicable edit was returned. Select the relevant object and describe a text, color, size or position change.');
  return { elements, deleted_ids };
}

export async function editBrowserDiagram(request: DiagramLocalEditRequest): Promise<DiagramLocalEditResponse> {
  if (request.canvas_library !== 'excalidraw') throw new Error('Browser model edits currently support Excalidraw.');
  const elements = (Array.isArray(request.current_schema.elements) ? request.current_schema.elements : []) as Record<string, unknown>[];
  const selected = new Set(request.selected_node_ids);
  const scope = elements.filter(e => selected.has(String(e.id)) || selected.has(String(e.containerId)));
  if (!scope.length) throw new Error('Select at least one existing object to edit.');
  const answer = await callBrowserModel(model(), EDIT_PROMPT,
    JSON.stringify({ instruction: request.instruction, selected: scope.map(({ customData: _custom, ...e }) => { void _custom; return e; }) }), undefined, 8192, undefined, 'edit');
  const modified = await reflowEditedText(request.current_schema, sanitizeEdit(parseModelJson(answer), request));
  return { request_id: crypto.randomUUID(), modified_nodes: modified, operation_type: 'update', summary: 'Selected objects updated.' };
}
