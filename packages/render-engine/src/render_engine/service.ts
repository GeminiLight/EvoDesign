// Ported from evodesign/agentic_system/render_engine/service.py — keep in sync.
// server-only (file system, renderer)
//
// Shared render service — layout+structure → manifest JSON + PNG.
//
// Wraps RenderWorkflow (LangGraph pipeline) + render_canvas into a single
// callable. Used by both the main orchestrator (Phase 2) and the refiner
// (re-render between iterations).
//
// RenderWorkflow note: Python's ``RenderWorkflow.run`` invokes a compiled
// LangGraph ``StateGraph(WorkflowState)`` (one node per stage, linear edges).
// The phase-1 TS ``RenderWorkflow`` (src/render_engine/workflow.ts) runs the
// same node functions synchronously without LangGraph (it must stay usable by
// the synchronous stage-parity tools). ``_run_render_workflow`` below runs
// those very node functions through a LangGraph.js graph with the same node
// names and pydantic-style state handling (each node receives
// ``WorkflowState(**channel_values)``: dict/list fields shallow-copied), so the
// per-node snapshots and the copy semantics match Python.

import { mkdirSync, mkdtempSync, tmpdir, writeFileSync } from '../py/fs.ts';
import { dirname, join } from '../py/path.ts';
import { withPyFloats } from '../py/float_marks.ts';
import { pyDeepcopy } from '../py/float_marks.ts';
import {
  CANVAS_DEFAULT_VIEWPORT_HEIGHT,
  CANVAS_DEFAULT_VIEWPORT_WIDTH,
  RenderPngResult,
  RenderResult,
  normalize_canvas_library,
} from '../canvas_runtime.ts';
import { PydanticStateGraph, type WorkflowStateClass } from '../common/base_workflow.ts';
import { ensure_no_integer_like_semantic_ids } from '../common/semantic_ids.ts';
import { RuntimeError } from '../py/errors.ts';
import { pyJsonDumps } from '../py/json.ts';
import { getLogger } from '../py/logging.ts';
import { isDict, truthy } from '../py/truthy.ts';
import { render_canvas } from './canvas_render.ts';
import { validate_png_file } from './shared/png_validation.ts';
import { WorkflowState as RenderWorkflowState } from './state.ts';
import { RenderWorkflow } from './workflow.ts';

const logger = getLogger('evodesign.agentic_system.render_engine.service');

type Dict = Record<string, unknown>;

export function _ensure_valid_png(path: string, context: string): void {
  validate_png_file(path, context);
}

// ---------------------------------------------------------------------------
// RenderWorkflow.run through LangGraph.js (see header)
// ---------------------------------------------------------------------------

/** ``evodesign.agentic_system.render_engine.state.WorkflowState`` fields, in declaration order. */
const _RENDER_STATE_FIELDS: Record<string, 'any' | 'dict' | 'list_of_dict'> = {
  current_stage: 'any',
  canvas_library: 'any',
  text_content: 'any',
  user_query: 'any',
  stage_knowledge: 'any',
  design_expertise: 'any',
  runtime_directives: 'any',
  diagram_type: 'any',
  content_area: 'any',
  conversation_history: 'list_of_dict',
  structure_instantiation: 'dict',
  layout_instantiation: 'dict',
  layout_specification: 'dict',
  design_constraints: 'any',
  validation_report: 'dict',
  diagram_manifest: 'dict',
  manifest_without_arrows: 'dict',
  render_stdout: 'any',
  render_stderr: 'any',
};

/** Pydantic re-validation copies containers: ``Dict[...]`` → new dict, ``List[Dict]`` → new list of new dicts. */
function _revalidate(values: Dict): Dict {
  const out: Dict = {};
  for (const [key, value] of Object.entries(values)) {
    const kind = _RENDER_STATE_FIELDS[key];
    if (kind === 'dict' && isDict(value)) out[key] = { ...value };
    else if (kind === 'list_of_dict' && Array.isArray(value)) out[key] = value.map((item) => (isDict(item) ? { ...item } : item));
    else out[key] = value;
  }
  return out;
}

/** The render ``WorkflowState`` as a pydantic-like model class for ``PydanticStateGraph``. */
class _RenderGraphState extends RenderWorkflowState {
  static model_fields: Record<string, unknown> = Object.fromEntries(Object.keys(_RENDER_STATE_FIELDS).map((name) => [name, {}]));
  static pythonName = 'evodesign.agentic_system.render_engine.state.WorkflowState';

  constructor(data: Dict = {}) {
    super(_revalidate(data));
  }
}

/** ``_linear_graph(nodes)`` with langgraph: entry point, linear edges, END. */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function _linear_state_graph(nodes: [string, (state: RenderWorkflowState) => RenderWorkflowState][]): any {
  const workflow = new PydanticStateGraph(_RenderGraphState as unknown as WorkflowStateClass);
  for (const [name, node] of nodes) {
    workflow.addNode(name, node);
  }
  workflow.addEdge('__start__', nodes[0][0]);
  for (let i = 0; i + 1 < nodes.length; i += 1) {
    workflow.addEdge(nodes[i][0], nodes[i + 1][0]);
  }
  workflow.addEdge(nodes[nodes.length - 1][0], '__end__');
  return workflow.compile();
}

/** ``RenderWorkflow.run(state)`` (Python: compiled LangGraph graph). */
export async function _run_render_workflow(render_wf: RenderWorkflow, state: RenderWorkflowState): Promise<RenderWorkflowState> {
  logger.info(`Starting render workflow (canvas_library=${render_wf.canvas_library})...`);
  ensure_no_integer_like_semantic_ids(state.structure_instantiation, state.layout_instantiation);
  const graph = _linear_state_graph(render_wf._excalidraw_nodes());
  const result_dict = await graph.invoke(state);
  const result = isDict(result_dict) ? new RenderWorkflowState(_revalidate(result_dict)) : (result_dict as RenderWorkflowState);
  logger.info('Render workflow finished.');
  return result;
}

/**
 * Build manifest from layout+structure, then render to PNG.
 *
 * Args:
 *     layout_instantiation: Positioned elements from layout workflow.
 *     structure_instantiation: Semantic graph from structure workflow.
 *     canvas_library: "excalidraw" or "tldraw".
 *     output_dir: Directory to write manifest JSON and PNG. If None,
 *         files are written to a unique temp directory owned by the caller.
 *     viewport_width: Render viewport width in pixels.
 *     viewport_height: Render viewport height in pixels.
 *     layout_specification: Layout agent strategy; architecture tier plans
 *         are executed by the architecture design-system tool.
 *
 * Returns:
 *     RenderResult with manifest dict, png_path, and manifest_path.
 */
export async function render_manifest(
  layout_instantiation: Dict,
  structure_instantiation: Dict,
  canvas_library = 'excalidraw',
  output_dir: string | null = null,
  viewport_width: number = CANVAS_DEFAULT_VIEWPORT_WIDTH,
  viewport_height: number = CANVAS_DEFAULT_VIEWPORT_HEIGHT,
  layout_specification: Dict | null = null,
  design_constraints = '',
): Promise<RenderResult> {
  canvas_library = normalize_canvas_library(canvas_library);

  // --- Phase 1: build manifest via RenderWorkflow ---
  const render_wf = new RenderWorkflow(canvas_library);
  let render_state = new RenderWorkflowState({
    structure_instantiation,
    layout_instantiation,
    layout_specification,
    design_constraints,
    canvas_library,
  });
  render_state = await _run_render_workflow(render_wf, render_state);

  const manifest = render_state.diagram_manifest;
  if (!truthy(manifest)) {
    throw new RuntimeError('RenderWorkflow produced no diagram_manifest');
  }

  // --- Phase 2: save manifest + render PNG ---
  if (output_dir === null || output_dir === undefined) {
    output_dir = mkdtempSync(join(tmpdir(), 'evodesign-render-'));
  }
  const out = output_dir;
  mkdirSync(out, { recursive: true });

  const manifest_path = join(out, 'diagram_manifest.json');
  const png_path = join(out, 'diagram_manifest.png');

  // Save manifest JSON
  writeFileSync(manifest_path, pyJsonDumps(withPyFloats(manifest), { indent: 2, ensureAscii: false }), 'utf-8');
  logger.info(`Manifest saved to ${manifest_path}`);

  // Save .excalidraw file for Excalidraw canvas library
  if (canvas_library === 'excalidraw') {
    const excalidraw_manifest = pyDeepcopy(manifest) as Dict;
    delete excalidraw_manifest._meta;
    Object.assign(excalidraw_manifest, { type: 'excalidraw', version: 2 });
    const excalidraw_path = join(out, 'rendered_diagram.excalidraw');
    writeFileSync(excalidraw_path, pyJsonDumps(withPyFloats(excalidraw_manifest), { indent: 2, ensureAscii: false }), 'utf-8');
  }

  // Render to PNG
  await render_canvas(manifest as Dict, png_path, canvas_library, {
    capture_output: true,
    viewport_width,
    viewport_height,
  });
  _ensure_valid_png(png_path, 'render_manifest');
  logger.info(`PNG rendered to ${png_path}`);

  return new RenderResult(manifest as Dict, png_path, manifest_path);
}

/** ``f"{type(exc).__name__}: {exc}"`` */
function _describe_exception(exc: unknown): string {
  if (exc instanceof Error) return `${exc.name}: ${exc.message}`;
  return `Exception: ${String(exc)}`;
}

/**
 * Render an existing manifest dict to PNG and preserve failure detail.
 *
 * Used by the refiner for re-rendering between iterations. Defaults
 * reproduce the product render (renderer-default export scale, smart
 * crop on); pass ``render_scale=1.0, crop=False`` for the analysis
 * render consumed by VLM stages.
 */
export async function render_png_result(
  manifest: Dict,
  output_path: string,
  canvas_library = 'excalidraw',
  viewport_width: number = CANVAS_DEFAULT_VIEWPORT_WIDTH,
  viewport_height: number = CANVAS_DEFAULT_VIEWPORT_HEIGHT,
  render_scale: number | null = null,
  crop = true,
): Promise<RenderPngResult> {
  canvas_library = normalize_canvas_library(canvas_library);
  const out = output_path;
  mkdirSync(dirname(out), { recursive: true });

  try {
    await render_canvas(manifest, out, canvas_library, {
      capture_output: true,
      viewport_width,
      viewport_height,
      render_scale,
      crop,
    });
  } catch (exc) {
    logger.warning(`render_png_result(${output_path}) failed: ${String(exc)}`);
    return new RenderPngResult(false, out, _describe_exception(exc));
  }

  try {
    _ensure_valid_png(out, 'render_png_result');
  } catch (exc) {
    if (!(exc instanceof RuntimeError)) throw exc;
    logger.warning(String(exc));
    return new RenderPngResult(false, out, _describe_exception(exc));
  }

  return new RenderPngResult(true, out);
}
