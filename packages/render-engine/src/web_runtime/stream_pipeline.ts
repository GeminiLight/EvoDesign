// Ported from backend/app/services/workflow_runtime/stream_pipeline.py — keep
// in sync (PHASE3_PLAN.md WP29). ``asyncio.to_thread`` calls become plain
// awaits: the ported engine is async and runs on the caller's event loop.

import { pyJsonDumps } from '../py/json.ts';
import { withPyFloats } from '../py/float_marks.ts';
import { pyStr } from '../py/str.ts';
import type { RenderManifest } from './workflow_engine_port.ts';
import {
  _final_verification_output_dir,
  _layout_instantiation_path,
  _render_output_dir,
  _structure_instantiation_path,
  _to_plain,
  _verification_output_dir,
} from './artifacts.ts';

type Dict = Record<string, any>;

/** ``getattr(obj, name, default)`` */
export function getattr(obj: unknown, name: string, defaultValue: unknown = null): any {
  if (obj === null || obj === undefined) return defaultValue;
  const value = (obj as Dict)[name];
  return value === undefined ? defaultValue : value;
}

export class _StreamingArtifacts {
  structure_state: any = null;
  styling_state: any = null;
  structure_instantiation: any = null;
  structure_specification: any = null;
  styling_instantiation: any = null;
  styling_specification: any = null;
  layout_instantiation: any = null;
  layout_specification: any = null;
  design_constraints = '';
  render_result: any = null;
  diagram_manifest: Dict | null = null;
  refined_diagram_manifest: Dict | null = null;
}

export class _VerificationResult {
  constructor(readonly verification_dir: string, readonly verifier_state: any) {}
}

/** Build runtime directives for the agentic pipeline. */
export function _build_runtime_directives(locked_nodes: string[], current_schema: Dict | null): string {
  const runtime_context = { locked_nodes, current_schema };
  const payload = pyJsonDumps(withPyFloats(runtime_context), { ensureAscii: false });
  return `=== RUNTIME DIRECTIVES (HIGHEST PRIORITY) ===\n${payload}\n\n`;
}

export function _sync_generation_artifacts(artifacts: _StreamingArtifacts, pipeline_run: unknown): void {
  artifacts.structure_state = getattr(pipeline_run, 'structure_state', null);
  artifacts.styling_state = getattr(pipeline_run, 'styling_state', null);
  artifacts.structure_instantiation = getattr(pipeline_run, 'structure_instantiation', null);
  artifacts.structure_specification = getattr(pipeline_run, 'structure_specification', null);
  artifacts.styling_instantiation = getattr(pipeline_run, 'styling_instantiation', null);
  artifacts.styling_specification = getattr(pipeline_run, 'styling_specification', null);
  artifacts.layout_instantiation = getattr(pipeline_run, 'layout_instantiation', null);
  artifacts.layout_specification = getattr(pipeline_run, 'layout_specification', null);
}

export async function _run_generation_stage(
  { workflow, pipeline_run, stage_name, save_dir, artifacts }:
  { workflow: any; pipeline_run: unknown; stage_name: string; save_dir: string; artifacts: _StreamingArtifacts },
): Promise<void> {
  await workflow.run_generation_stage(pipeline_run, stage_name, save_dir);
  _sync_generation_artifacts(artifacts, pipeline_run);
  artifacts.design_constraints = getattr(workflow, 'design_constraints', '');
}

export async function _run_render_stage(
  { render_manifest, request, save_dir, artifacts }:
  { render_manifest: RenderManifest; request: { canvas_library: string }; save_dir: string; artifacts: _StreamingArtifacts },
): Promise<void> {
  // render_manifest(layout_instantiation=…, structure_instantiation=…,
  //   layout_specification=…, design_constraints=…, canvas_library=…, output_dir=…)
  artifacts.render_result = await render_manifest(
    artifacts.layout_instantiation,
    artifacts.structure_instantiation,
    request.canvas_library,
    _render_output_dir(save_dir),
    undefined,
    undefined,
    artifacts.layout_specification,
    artifacts.design_constraints,
  );
  artifacts.diagram_manifest = _to_plain(artifacts.render_result.manifest) || {};
}

export async function _run_verification(
  { verifier_workflow_cls, workflow, request, save_dir, artifacts, verification_dir = null, manifest_path = null, image_path = null }:
  {
    verifier_workflow_cls: new () => any; workflow: any; request: { context: string; canvas_library: string };
    save_dir: string; artifacts: _StreamingArtifacts; verification_dir?: string | null;
    manifest_path?: string | null; image_path?: string | null;
  },
): Promise<_VerificationResult> {
  const output_dir = verification_dir || _verification_output_dir(save_dir);
  const verifier = new verifier_workflow_cls();
  // verifier.run(manifest_path=…, image_path=…, source_text=…, design_constraints=…,
  //   canvas_library=…, structure_path=…, layout_path=…, output_dir=…,
  //   skip_critic=not workflow.enable_critic, emit_markdown=True)
  const verifier_state = await verifier.run(
    manifest_path || artifacts.render_result.manifest_path,
    image_path || artifacts.render_result.png_path,
    request.canvas_library,
    _structure_instantiation_path(save_dir),
    _layout_instantiation_path(save_dir),
    request.context,
    getattr(workflow, 'design_constraints', ''),
    output_dir,
    !workflow.enable_critic,
    null,
    true,
  );
  return new _VerificationResult(output_dir, verifier_state);
}

/** Mirror Text2DiagramWorkflow's default verifier-on behavior. */
export function _verification_should_run(workflow: unknown): boolean {
  return Boolean(getattr(workflow, 'enable_verifier', true));
}

export async function _run_stream_verification(
  args: { verifier_workflow_cls: new () => any; workflow: any; request: { context: string; canvas_library: string }; save_dir: string; artifacts: _StreamingArtifacts },
): Promise<_VerificationResult | null> {
  if (!_verification_should_run(args.workflow)) return null;
  return _run_verification(args);
}

export async function _run_final_stream_verification(
  args: {
    verifier_workflow_cls: new () => any; workflow: any; request: { context: string; canvas_library: string };
    save_dir: string; artifacts: _StreamingArtifacts; manifest_path: string; image_path: string;
  },
): Promise<_VerificationResult | null> {
  if (!_verification_should_run(args.workflow)) return null;
  return _run_verification({ ...args, verification_dir: _final_verification_output_dir(args.save_dir) });
}

/** Python ``int(x)`` for the summary counters (``int(None or 0)``). */
function pyInt(value: unknown): number {
  const n = Number(value);
  return Number.isFinite(n) ? Math.trunc(n) : 0;
}

export function _verification_quality_passed(verifier_state: unknown): boolean {
  const quality_passed = getattr(verifier_state, 'quality_passed', null);
  if (typeof quality_passed === 'boolean') return quality_passed;

  const has_blocking_errors = getattr(verifier_state, 'has_blocking_errors', null);
  if (has_blocking_errors) return false;

  const blocking_errors = getattr(verifier_state, 'blocking_errors', null);
  if (typeof blocking_errors === 'string') {
    if (blocking_errors) return false;
  } else if (Array.isArray(blocking_errors) ? blocking_errors.length : blocking_errors) {
    return false;
  }

  // Older report-like objects may only expose has_errors. Keep those
  // conservative unless they also expose explicit non-blocking semantics.
  if (getattr(verifier_state, 'has_errors', false) && has_blocking_errors === null && blocking_errors === null) return false;
  if (getattr(verifier_state, 'has_blocking_findings', false)) return false;

  const summary = getattr(verifier_state, 'objective_summary', null) || {};
  if (pyInt(summary.critical || 0) > 0) return false;
  if (pyInt(summary.major || 0) > 0) return false;

  for (const finding of getattr(verifier_state, 'objective_findings', null) || []) {
    const severity = getattr(finding, 'severity', finding);
    const name = typeof severity === 'object' ? getattr(severity, 'name', null) : null;
    const value = typeof severity === 'object' ? getattr(severity, 'value', severity) : severity;
    const labels = new Set([pyStr(value).toLowerCase(), name ? pyStr(name).toLowerCase() : '']);
    if (labels.has('critical') || labels.has('major')) return false;
  }
  return true;
}
