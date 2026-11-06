/** Browser/Node entry for the backend's observable generation pipeline.
 * One run per runtime: workers provide isolation for all engine singletons.
 */
import { getFS, setFS, type RuntimeFS } from '../py/fs.ts';
import { getEnv, setEnv, clearEnv } from '../py/env.ts';
import { ModelConfig } from '../config/model_loader.ts';
import { AppSettings } from '../config/settings.ts';
import { get_chat_model_factory, set_chat_model_factory, type ChatModelFactory } from '../core/llm_factory.ts';
import { withPngRenderer, type PngRenderer } from '../render_engine/png_renderer.ts';
import { validate_diagram_generate_request } from './diagram_generate.ts';
import { resolveWebSettings, type WebSettings } from './settings.ts';
import { create_backend_llm } from './llm_client.ts';
import { EvoDesignWorkflowEnginePort, withEngineOverrides } from './workflow_engine_port.ts';
import { _cleanup_stream_dir, _request_scoped_stream_dir, _save_json } from './artifacts.ts';
import { build_design_constraints, quality_status, quality_summary, refinement_rejection } from './quality.ts';
import { CONNECTOR_COLLECTION_KEYS, NODE_COLLECTION_KEYS, count_schema_collection } from './diagram_schema_inspection.ts';
import { StreamResultPayload } from './event_payloads.ts';
import { STREAMING_STAGES, stage_start_payload, stage_complete_payload, refine_completed_completion,
  refine_unresolved_completion, refine_failed_completion, refine_skipped_completion, refiner_skipped_payload } from './events.ts';
import { _StreamingArtifacts, _build_runtime_directives, _run_generation_stage, _run_render_stage,
  _run_stream_verification, _run_final_stream_verification, _verification_should_run, _verification_quality_passed } from './stream_pipeline.ts';
import { _prepare_iterative_refiner, _run_iterative_refiner, _should_run_refiner } from './refiner.ts';
import { RefinerPipelineError, REFINER_FAILURE_VERIFICATION, REFINER_FAILURE_ARTIFACT, _refiner_failure,
  _stage_failure, PUBLIC_REFINER_START_MESSAGE, PUBLIC_REFINER_COMPLETE_MESSAGE } from './errors.ts';
import { _generation_stream_error_payload } from './stream_errors.ts';
import { monotonic, run_streaming_stage } from './stage_execution.ts';
import { throwIfAborted, isCancellation } from './cancel.ts';

type Dict = Record<string, any>;
export interface StreamDiagramOptions {
  chatModelFactory?: ChatModelFactory;
  onEvent?: (name: string, payload: Dict) => void;
  settings?: Partial<WebSettings> & Dict;
  engine?: Dict;
  env?: Record<string, string>;
  rendererUrl?: string;
  resultsDir?: string;
  renderer?: PngRenderer;
  fs?: RuntimeFS;
  signal?: AbortSignal;
  requestId?: string;
}

let running = false;

export async function streamDiagram(body: unknown, options: StreamDiagramOptions = {}): Promise<Dict | null> {
  const request = validate_diagram_generate_request(body);
  // The current browser surface only has an Excalidraw editor.
  if (request.canvas_library !== 'excalidraw') throw new Error('Browser generation supports Excalidraw only.');
  if (running) throw new Error('A diagram pipeline is already running in this runtime.');
  throwIfAborted(options.signal);
  running = true;
  const previousFS = getFS();
  const previousFactory = get_chat_model_factory();
  const previousSettings = AppSettings._instance;
  const previousModels = ModelConfig._instance;
  const env = { ...options.env, ...(options.rendererUrl ? { EXCALIDRAW_RENDER_URL: options.rendererUrl } : {}) };
  const savedEnv = new Map(Object.keys(env).map((key) => [key, getEnv(key)]));
  let emitted = false;
  const emit = (name: string, payload: object) => {
    throwIfAborted(options.signal);
    options.onEvent?.(name, payload as Dict);
    emitted = true;
  };
  try {
    if (options.fs) setFS(options.fs);
    if (options.chatModelFactory) set_chat_model_factory(options.chatModelFactory);
    for (const [key, value] of Object.entries(env)) setEnv(key, value);
    AppSettings._instance = null;
    ModelConfig._instance = null;
    const settings = resolveWebSettings(options.settings);
    settings.results_dir = options.resultsDir ?? settings.results_dir;
    return await withPngRenderer(options.renderer ?? null, async () => {
      try {
        const model = await create_backend_llm(settings);
        return await execute(request, settings, model, options, emit);
      } catch (error) {
        if (isCancellation(error) || options.signal?.aborted) {
          throwIfAborted(options.signal);
          throw error;
        }
        emit('error', _generation_stream_error_payload(error, emitted));
        return null;
      }
    });
  } finally {
    setFS(previousFS);
    set_chat_model_factory(previousFactory);
    AppSettings._instance = previousSettings;
    ModelConfig._instance = previousModels;
    for (const [key, value] of savedEnv) {
      clearEnv(key);
      // Restore the observable value, including an explicit unset override.
      if (getEnv(key) !== value) setEnv(key, value);
    }
    running = false;
  }
}

async function execute(request: ReturnType<typeof validate_diagram_generate_request>, settings: WebSettings,
  model: Awaited<ReturnType<typeof create_backend_llm>>, options: StreamDiagramOptions,
  emit: (name: string, payload: object) => void): Promise<Dict | null> {
  const started = monotonic();
  const request_id = options.requestId ?? `req_${globalThis.crypto.randomUUID().replaceAll('-', '').slice(0, 12)}`;
  const save_dir = _request_scoped_stream_dir(settings.results_dir, request_id);
  const engine = new EvoDesignWorkflowEnginePort().load_streaming_dependencies();
  engine.workflow_cls = withEngineOverrides(engine.workflow_cls, options.engine ?? {});
  const timings: Dict = {};
  const optimizations: Dict = {};
  const memory = { status: 'disabled', retrieved_count: 0, retrieved_items: [] };
  let refinement: Dict = { status: 'skipped', fixes_applied: 0 };
  const learning = { status: 'skipped', saved_count: 0 };
  let before: Dict = {};
  let after: Dict = {};
  const total_stages = 9;
  const user_query = request.requirements || 'Generate diagram schema';
  const runtime_directives = _build_runtime_directives(request.locked_nodes, request.current_schema);
  const runRequest = { ...request, request_id };
  const stageStart = (stage: string, stage_index: number, message: string) =>
    emit('stage_start', stage_start_payload({ stage, stage_index, total_stages, message }));
  const stageComplete = (stage: string, stage_index: number, duration_ms: number, message: string | null = null) =>
    emit('stage_complete', stage_complete_payload({ stage, stage_index, total_stages, duration_ms, message }));
  const elapsed = (t: number) => Math.trunc((monotonic() - t) * 1000);
  const failRefiner = (reason: string) => { throw new RefinerPipelineError({ phase: REFINER_FAILURE_VERIFICATION, reason }); };
  try {
    stageStart('memory', 1, 'Preparing design knowledge...');
    const workflow = engine.workflow_cls({ model, save_dir, enable_refiner: settings.auto_refine_enabled,
      refiner_max_iterations: settings.auto_refine_max_iterations, canvas_library: request.canvas_library,
      use_icons: request.use_icons, router_model: model });
    const artifacts = new _StreamingArtifacts();
    workflow.design_constraints = build_design_constraints(request.context, user_query, '', request.diagram_type, request.use_icons, request.locked_nodes);
    const pipeline_run = await workflow.begin_generation_run(request.context, user_query, '', runtime_directives, request.diagram_type);
    const routing_finished = monotonic();
    pipeline_run.design_expertise = await workflow.build_design_expertise('', pipeline_run.effective_diagram_type ?? null, null, user_query, request.context);
    optimizations.memory_retrieval_ms = elapsed(routing_finished);
    optimizations.initialization_and_routing_ms = Math.trunc((routing_finished - started) * 1000);
    optimizations.router_skipped = Boolean(request.diagram_type);
    timings.memory = elapsed(started);
    stageComplete('memory', 1, timings.memory, 'Design knowledge: 0 references loaded');
    for (const [i, [stage, message]] of STREAMING_STAGES.entries()) {
      stageStart(stage, i + 2, message);
      const outcome = await run_streaming_stage({ request_id, stage, handler: async () => {
        throwIfAborted(options.signal);
        if (stage === 'render') await _run_render_stage({ render_manifest: engine.render_manifest, request, save_dir, artifacts });
        else await _run_generation_stage({ workflow, pipeline_run, stage_name: stage, save_dir, artifacts });
        throwIfAborted(options.signal);
      } });
      if (outcome.failure) { emit('error', outcome.failure.public_payload()); return null; }
      timings[stage] = outcome.duration_ms;
      stageComplete(stage, i + 2, outcome.duration_ms);
    }
    const verification_enabled = _verification_should_run(workflow);
    const verification_started = monotonic();
    // Preparing the deterministic refiner before verification preserves the
    // backend's inputs without overlapping browser async-context stores.
    const preparation = settings.auto_refine_enabled && verification_enabled && workflow.enable_critic
      ? await _prepare_iterative_refiner({ iterative_refiner_workflow_cls: engine.iterative_refiner_workflow_cls,
        request: runRequest, save_dir, refiner_max_iterations: settings.auto_refine_max_iterations,
        artifacts, design_constraints: workflow.design_constraints }) : null;
    if (verification_enabled) stageStart('verification', 6, 'Checking diagram quality...');
    let verification;
    try {
      verification = await _run_stream_verification({ verifier_workflow_cls: engine.verifier_workflow_cls, workflow, request, save_dir, artifacts });
    } catch (error) {
      if (isCancellation(error)) throw error;
      emit('error', _stage_failure({ request_id, stage: 'verification', exc: error }).public_payload());
      return null;
    }
    if (verification_enabled) {
      before = quality_summary(verification!.verifier_state);
      after = before;
      timings.verification = elapsed(verification_started);
      stageComplete('verification', 6, timings.verification);
    }
    if (settings.auto_refine_enabled) {
      let completion = refine_completed_completion(0);
      let shouldRefine = false;
      let refineStarted = monotonic();
      let finalStarted: number | null = null;
      try {
        if (!verification) failRefiner('Refiner verification did not produce a report');
        shouldRefine = _should_run_refiner({ workflow, verifier_state: verification!.verifier_state, canvas_library: request.canvas_library });
        if (shouldRefine) {
          stageStart('refining', 7, PUBLIC_REFINER_START_MESSAGE);
          refineStarted = monotonic();
          if (preparation) optimizations.parallel_preparation_ms = preparation.duration_ms;
          const refined = await _run_iterative_refiner({ iterative_refiner_workflow_cls: engine.iterative_refiner_workflow_cls,
            request, save_dir, verification_dir: verification!.verification_dir,
            refiner_max_iterations: settings.auto_refine_max_iterations, artifacts, preparation,
            design_constraints: workflow.design_constraints });
          timings.refining = elapsed(refineStarted);
          stageComplete('refining', 7, timings.refining, PUBLIC_REFINER_COMPLETE_MESSAGE);
          if (refined.converged && refined.refined_manifest !== null) {
            if (!refined.refined_manifest_path || !refined.refined_image_path) {
              throw new RefinerPipelineError({ phase: REFINER_FAILURE_ARTIFACT, reason: 'Refiner produced an incomplete final artifact' });
            }
            stageStart('final_verification', 8, 'Checking the refined diagram...');
            finalStarted = monotonic();
            let finalVerification;
            try {
              finalVerification = await _run_final_stream_verification({ verifier_workflow_cls: engine.verifier_workflow_cls,
                workflow, request, save_dir, artifacts, manifest_path: refined.refined_manifest_path, image_path: refined.refined_image_path });
            } catch (error) {
              if (isCancellation(error)) throw error;
              failRefiner('Refined artifact final verification failed');
            }
            if (finalVerification && !_verification_quality_passed(finalVerification.verifier_state)) failRefiner('Refined artifact failed final verification');
            if (refinement_rejection(verification!.verifier_state, finalVerification!.verifier_state)) failRefiner('Refined artifact quality regressed');
            after = quality_summary(finalVerification!.verifier_state);
            timings.final_verification = elapsed(finalStarted!);
            stageComplete('final_verification', 8, timings.final_verification);
          }
          completion = refined.converged ? refine_completed_completion(refined.fixes_applied)
            : refine_unresolved_completion({ fixes_applied: refined.fixes_applied, termination_reason: refined.termination_reason });
          artifacts.refined_diagram_manifest = refined.refined_manifest;
        } else {
          completion = refine_skipped_completion();
        }
      } catch (error) {
        if (!(error instanceof RefinerPipelineError)) throw error;
        if (shouldRefine) {
          if (finalStarted !== null) timings.final_verification = elapsed(finalStarted);
          else timings.refining = elapsed(refineStarted);
        }
        completion = refine_failed_completion();
        emit('refine_error', _refiner_failure({ request_id, exc: error }).public_payload());
      }
      refinement = completion.public_payload();
      if (completion.status !== 'completed') refinement.fixes_applied = 0;
      emit('refine_complete', refinement);
    } else {
      refinement.status = 'disabled';
      emit('refiner_skipped', refiner_skipped_payload());
    }
    const schema = artifacts.refined_diagram_manifest || artifacts.diagram_manifest || {};
    const generation = { quality_status: quality_status(after), memory, refinement, learning, before, after,
      timings_ms: timings, optimizations, total_duration_ms: elapsed(started) };
    const result = StreamResultPayload({ request_id, project_id: null, snapshot_id: null, schema_blob: schema,
      thought_trace: { structure_instantiation: artifacts.structure_instantiation || {},
        styling_instantiation: artifacts.styling_instantiation || {}, layout_instantiation: artifacts.layout_instantiation || {} },
      metrics_scores: { node_count: count_schema_collection(schema, NODE_COLLECTION_KEYS),
        edge_count: count_schema_collection(schema, CONNECTOR_COLLECTION_KEYS), generation },
      summary: Array.from(request.context.trim().split(/\s+/).join(' ')).slice(0, 80).join('') || 'Generated diagram' });
    if (settings.retain_generation_artifacts) _save_json(`${save_dir}/generation_result.json`, result);
    emit('result', result);
    return result;
  } finally {
    if (!settings.retain_generation_artifacts) _cleanup_stream_dir(save_dir);
  }
}
