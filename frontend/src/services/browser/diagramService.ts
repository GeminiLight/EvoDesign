import { PLAN_PROMPT, EDIT_PROMPT } from '../../../../shared/diagram-prompts.mjs';
import type { DiagramRequest, DiagramResponse, DiagramLocalEditRequest, DiagramLocalEditResponse, StreamStage } from '../../types/api';
import type { StreamCallbacks, StreamOptions } from '../apiDiagramService';
import { nodeIconNames } from '../../utils/nodeIcons';
import { callBrowserModel, loadModelConfig, parseModelJson } from './modelConfig';
import { normalizePlan, preservesContent, type DiagramPlan } from './diagramPlan';
import { preserveLockedElements, repairSceneBindings, reflowEditedText, renderPlan } from './scene';
import { openModelSettings } from './runtime';



function model() {
  const config = loadModelConfig();
  if (!config.model.trim()) { openModelSettings(); throw new Error('Configure your API base URL, model and API key in Model settings, then try again.'); }
  return config;
}

export async function generateBrowserDiagram(request: DiagramRequest, requirements: string, callbacks: StreamCallbacks = {}, options: StreamOptions = {}): Promise<DiagramResponse> {
  if (request.metadata?.canvasLibrary === 'tldraw') throw new Error('The browser edition generates Excalidraw diagrams. Choose Excalidraw in workspace settings.');
  const config = model(); const started = performance.now();
  const timings: Partial<Record<StreamStage, number>> = {};
  const stage = async <T>(name: StreamStage, index: number, run: () => Promise<T>): Promise<T> => {
    options.signal?.throwIfAborted();
    callbacks.onStageStart?.({ stage: name, stage_index: index, total_stages: config.refine ? 3 : 2, message: name });
    const start = performance.now();
    let result: T;
    try { result = await run(); }
    finally { timings[name] = performance.now() - start; }
    options.signal?.throwIfAborted();
    callbacks.onStageComplete?.({ stage: name, stage_index: index, total_stages: config.refine ? 3 : 2, message: name, duration_ms: timings[name]! });
    return result;
  };
  let current: Record<string, unknown> | null = null;
  if (request.metadata?.currentSchema) { try { current = JSON.parse(request.metadata.currentSchema); } catch { /* Initial creation has no current scene. */ } }
  const context = Array.isArray(current?.elements) ? current.elements.filter(e => e && !e.isDeleted && e.type !== 'image').map(e => ({ id: e.id, type: e.type, text: e.text, x: e.x, y: e.y, containerId: e.containerId, startBinding: e.startBinding, endBinding: e.endBinding })) : [];
  const icons = request.useIcons ?? request.metadata?.useIcons === 'true';
  // Legend/layout flags belong to the full renderer; the browser schema has no legend object.
  const { includeLegend: _legend, autoLayout: _layout, preferOrthogonal: _orthogonal, ...constraints } = request.constraints || {};
  void _legend; void _layout; void _orthogonal;
  const prompt = `${requirements}\nRequested style: ${request.style}. User constraints: ${JSON.stringify(constraints)}. Do not add placeholder legend nodes.\n${icons ? `Use a small relevant icon when appropriate. Allowed icon names: ${nodeIconNames.join(', ')}.` : 'Icons disabled: omit all icons.'}\n${context.length ? `Existing editable diagram context: ${JSON.stringify(context)}. Preserve existing IDs when revising a node. Locked IDs: ${JSON.stringify(request.lockedNodes || [])}.` : ''}\nUser content:\n${request.prompt}`;
  let plan = await stage('structure', 1, async () => normalizePlan(parseModelJson(await callBrowserModel(config, PLAN_PROMPT, prompt, options.signal, 8192, callbacks.onProviderWait))));
  let review = 'skipped'; let changed = 0; let reviewReason: string | undefined;
  if (config.refine) {
    try {
      const candidate = await stage('refining', 2, async () => {
        const answer = await callBrowserModel(config, PLAN_PROMPT, `Review this diagram against the user's request. Correct missing content, ambiguous labels and incorrect branches. Keep every existing node ID and connection; do not simplify away details. Return a complete corrected plan in the same schema. This is a semantic review, not an image review.\n${prompt}\nPlan:\n${JSON.stringify(plan)}`, options.signal, 8192, callbacks.onProviderWait);
        return normalizePlan(parseModelJson(answer));
      });
      if (preservesContent(plan, candidate)) {
        changed = countChanges(plan, candidate); plan = candidate; review = 'completed';
      } else { review = 'reverted'; reviewReason = 'The review removed or reordered required content. The original diagram was retained.'; }
    } catch (error) {
      if (options.signal?.aborted) throw error;
      review = 'failed';
      reviewReason = error instanceof Error ? error.message : 'Review failed.';
      callbacks.onRefineError?.({ message: 'Model review unavailable; the initial diagram was retained.', detail: reviewReason });
    }
  }
  callbacks.onRefineComplete?.({ status: review === 'completed' ? 'completed' : review === 'skipped' ? 'skipped' : 'failed', fixes_applied: changed,
    message: review === 'completed' ? 'Semantic model review completed.' : 'The original diagram was retained.' });
  const scene = await stage('layout', config.refine ? 3 : 2, async () => repairSceneBindings(preserveLockedElements(await renderPlan(plan, icons), current, request.lockedNodes || [])));
  return {
    requestId: request.id, diagramId: `diagram_${crypto.randomUUID()}`, excalidrawPayload: JSON.stringify(scene), rawSchemaBlob: scene,
    summary: plan.title, previewImage: '', generatedAt: new Date().toISOString(),
    generationReport: { browserEdition: true, memory: { status: 'local', retrievedCount: 0 }, refinement: { status: review, fixesApplied: changed, reason: reviewReason },
      learning: { status: 'disabled', savedCount: 0 }, qualityStatus: 'unverified', timings, durationMs: performance.now() - started },
  };
}

function countChanges(a: DiagramPlan, b: DiagramPlan): number {
  return b.nodes.filter(n => JSON.stringify(n) !== JSON.stringify(a.nodes.find(v => v.id === n.id))).length
    + b.edges.filter((e, i) => JSON.stringify(e) !== JSON.stringify(a.edges[i])).length;
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
