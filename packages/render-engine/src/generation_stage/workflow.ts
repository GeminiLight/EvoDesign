// Ported from evodesign/agentic_system/generation_stage/workflow.py — keep in sync.
// server-only (file writes, LangGraph.js sub-workflows)
//
// GeneratorWorkflow — mid-level abstraction for diagram generation.
//
// Provides a common interface for two generation strategies:
// - ``PipelineGeneratorWorkflow``: Structure → Styling → Layout (3 LLM calls)
// - ``OneShotGeneratorWorkflow``: single LLM call produces the complete scene
//
// Usage::
//
//     const generator = new PipelineGeneratorWorkflow(model);
//     const outputs = await generator.run("...", "...");
//     // outputs = {structure_instantiation, layout_instantiation, ...}
//
// Python's keyword-only parameters are positional here (MIGRATION_PLAN §2.3),
// in declaration order. ``run`` and the stage runners are async; the stage
// order is unchanged. Python imports the sub-workflow modules inside
// ``__init__``/``run``; the pipeline modules are imported statically here
// (no cycle).

import { existsSync, mkdirSync, writeFileSync } from '../py/fs.ts';
import { join } from '../py/path.ts';
import { withPyFloats } from '../py/float_marks.ts';
import type { BaseChatModel } from '@langchain/core/language_models/chat_models';
import { normalize_canvas_library } from '../canvas_runtime.ts';
import { normalize_generation_mode } from '../config/settings.ts';
import { require_generation_capability } from '../canvas_environment/capabilities.ts';
import { DEFAULT_PALETTE_KEY, RouterAgent } from './router/agent.ts';
import {
  DiagramTypeValidationError,
  normalize_diagram_type,
  normalize_supported_diagram_type,
} from '../common/diagram_types.ts';
import {
  build_diagram_context,
  build_stage_knowledge,
  get_group_containment_reference,
} from '../common/domain_knowledge_loader.ts';
import { StructureWorkflow } from './structure/workflow.ts';
import { WorkflowState as StructureState } from './structure/state.ts';
import { StylingWorkflow } from './styling/workflow.ts';
import { WorkflowState as StylingState } from './styling/state.ts';
import { LayoutWorkflow } from './layout/workflow.ts';
import { WorkflowState as LayoutState } from './layout/state.ts';
import { UnifiedGeneratorWorkflow } from './unified/workflow.ts';
import { UnifiedWorkflowState } from './unified/state.ts';
import { RuntimeError, ValueError } from '../py/errors.ts';
import { pyJsonDumps } from '../py/json.ts';
import { getLogger } from '../py/logging.ts';
import { pyRepr, pyStr, pyStrip } from '../py/str.ts';
import { isDict, pyOr, truthy } from '../py/truthy.ts';

const logger = getLogger('evodesign.agentic_system.generation_stage.workflow');

type Dict = Record<string, unknown>;

export const PIPELINE_STAGE_SEQUENCE = ['structure', 'styling', 'layout'] as const;

/**
 * Base class for diagram generation workflows.
 *
 * Subclasses produce generation outputs from text input.  The returned
 * dict keys depend on the strategy: pipeline mode returns intermediate
 * structure/styling/layout dicts; one-shot returns ``diagram_manifest`` plus
 * a Structure-shaped semantic sidecar in ``structure_instantiation``.
 */
export abstract class GeneratorWorkflow {
  /**
   * Generate diagram outputs from text.
   *
   * Returns a dict with generation outputs.  Pipeline mode returns keys
   * ``structure_instantiation``, ``structure_specification``,
   * ``styling_instantiation``, ``styling_specification``,
   * ``layout_instantiation``, ``layout_specification``.
   * One-shot mode returns ``diagram_manifest`` and ``structure_instantiation``.
   */
  abstract run(
    text_content: string,
    user_query: string,
    design_expertise?: string,
    runtime_directives?: string,
    diagram_type?: string | null,
    content_area?: string | null,
    save_dir?: string | null,
  ): Promise<Dict>;
}

/** Persist one stage's output to disk. */
export function _save_stage_output(
  save_dir: string,
  stage_name: string,
  artifact_name: string,
  instantiation: unknown,
  specification: unknown = null,
): Record<string, string> {
  const stage_dir = join(save_dir, stage_name);
  mkdirSync(stage_dir, { recursive: true });
  const paths: Record<string, string> = {};

  if (instantiation !== null && instantiation !== undefined) {
    const instantiation_path = join(stage_dir, `${artifact_name}_instantiation.json`);
    writeFileSync(instantiation_path, pyJsonDumps(withPyFloats(instantiation), { indent: 2, ensureAscii: false }), 'utf-8');
    paths[`${artifact_name}_instantiation_path`] = instantiation_path;
  }

  if (specification !== null && specification !== undefined) {
    const specification_path = join(stage_dir, `${artifact_name}_specification.json`);
    writeFileSync(specification_path, pyJsonDumps(withPyFloats(specification), { indent: 2, ensureAscii: false }), 'utf-8');
    paths[`${artifact_name}_specification_path`] = specification_path;
  }

  return paths;
}

/** Mutable state for an observable Structure -> Styling -> Layout run. (dataclass) */
export class PipelineGenerationRun {
  text_content: string;
  user_query: string;
  design_expertise: string;
  runtime_directives: string;
  content_area: string | null;
  effective_diagram_type: string | null;
  palette_key: string;
  artifact_paths: Record<string, string>;
  structure_state: StructureState | null;
  styling_state: StylingState | null;
  layout_state: LayoutState | null;
  structure_instantiation: unknown;
  structure_specification: unknown;
  styling_instantiation: unknown;
  styling_specification: unknown;
  layout_instantiation: unknown;
  layout_specification: unknown;

  constructor(
    text_content: string,
    user_query: string,
    design_expertise = '',
    runtime_directives = '',
    content_area: string | null = null,
    effective_diagram_type: string | null = null,
    palette_key: string = DEFAULT_PALETTE_KEY,
    artifact_paths: Record<string, string> | null = null,
    structure_state: StructureState | null = null,
    styling_state: StylingState | null = null,
    layout_state: LayoutState | null = null,
    structure_instantiation: unknown = null,
    structure_specification: unknown = null,
    styling_instantiation: unknown = null,
    styling_specification: unknown = null,
    layout_instantiation: unknown = null,
    layout_specification: unknown = null,
  ) {
    this.text_content = text_content;
    this.user_query = user_query;
    this.design_expertise = design_expertise;
    this.runtime_directives = runtime_directives;
    this.content_area = content_area;
    this.effective_diagram_type = effective_diagram_type;
    this.palette_key = palette_key;
    this.artifact_paths = artifact_paths ?? {};
    this.structure_state = structure_state;
    this.styling_state = styling_state;
    this.layout_state = layout_state;
    this.structure_instantiation = structure_instantiation;
    this.structure_specification = structure_specification;
    this.styling_instantiation = styling_instantiation;
    this.styling_specification = styling_specification;
    this.layout_instantiation = layout_instantiation;
    this.layout_specification = layout_specification;
  }
}

/** ``raise ValueError(str(exc)) from exc`` */
function _value_error_from(exc: Error): ValueError {
  const error = new ValueError(exc.message);
  (error as { cause?: unknown }).cause = exc;
  return error;
}

/** ``getattr(obj, name, None)`` */
function getattr(obj: unknown, name: string): unknown {
  if (obj === null || obj === undefined || typeof obj !== 'object') return null;
  const value = (obj as Dict)[name];
  return value === undefined ? null : value;
}

/**
 * Multi-stage generation: Structure → Styling → Layout.
 *
 * Wraps the three sub-workflows and threads state between them.
 */
export class PipelineGeneratorWorkflow extends GeneratorWorkflow {
  structure: StructureWorkflow;
  styling: StylingWorkflow;
  layout: LayoutWorkflow;
  canvas_library: string;
  full_domain_knowledge: boolean;
  _router: RouterAgent | null;

  constructor(
    model: BaseChatModel,
    canvas_library = 'excalidraw',
    use_icons = false,
    router_model: BaseChatModel | null = null,
    full_domain_knowledge = true,
  ) {
    super();
    this.structure = new StructureWorkflow(model);
    this.styling = new StylingWorkflow(model, use_icons);
    this.layout = new LayoutWorkflow(model);
    this.canvas_library = normalize_canvas_library(canvas_library);
    this.full_domain_knowledge = full_domain_knowledge;

    // Router uses a cheap/fast model for classification
    this._router = null;
    if (router_model !== null && router_model !== undefined) {
      this._router = new RouterAgent(router_model);
    }
  }

  /** Resolve router-derived context shared by every pipeline stage. */
  async resolve_generation_context(
    text_content: string,
    user_query: string,
    diagram_type: string | null = null,
  ): Promise<[string | null, string]> {
    let palette_key: string = DEFAULT_PALETTE_KEY;
    let effective_diagram_type: string | null = diagram_type;

    if (this._router !== null && !truthy(effective_diagram_type)) {
      logger.info('[PipelineGenerator] Running RouterAgent...');
      const router_result = await this._router.run(text_content, user_query);
      palette_key = Object.prototype.hasOwnProperty.call(router_result, 'palette_key') ? router_result.palette_key : '';
      if (!truthy(effective_diagram_type)) {
        effective_diagram_type = Object.prototype.hasOwnProperty.call(router_result, 'diagram_type') ? router_result.diagram_type : null;
      }
      logger.info(
        `[PipelineGenerator] Router: diagram_type=${pyStr(effective_diagram_type)}, palette_key=${pyStr(palette_key)}`,
      );
    }

    if (truthy(effective_diagram_type)) {
      try {
        effective_diagram_type = normalize_supported_diagram_type(
          effective_diagram_type,
          'diagram_type',
        );
      } catch (exc) {
        if (exc instanceof DiagramTypeValidationError) {
          throw _value_error_from(exc);
        }
        throw exc;
      }
    }

    return [effective_diagram_type, palette_key];
  }

  /** Build the stage_knowledge block for a pipeline stage. */
  build_stage_context(
    stage_name: string,
    diagram_type: string | null,
  ): string {
    let stage_knowledge = build_stage_knowledge(
      diagram_type,
      stage_name,
      this.full_domain_knowledge,
    );
    const diagram_context = build_diagram_context(diagram_type);
    if (diagram_context) {
      stage_knowledge = pyStrip(`${diagram_context}\n\n${stage_knowledge}`);
    }
    if (stage_name === 'Structure' && diagram_type === 'architecture') {
      const group_ref = get_group_containment_reference();
      if (group_ref) {
        stage_knowledge += `\n\n=== GROUP & CONTAINMENT REFERENCE ===\n${group_ref}`;
      }
    }
    return stage_knowledge;
  }

  static _resolve_downstream_diagram_type(
    resolved_diagram_type: string | null,
    structure_instantiation: unknown,
  ): string | null {
    let structure_chart_type: string | null = null;
    if (isDict(structure_instantiation)) {
      const raw_chart_type = Object.prototype.hasOwnProperty.call(structure_instantiation, 'chart_type')
        ? structure_instantiation.chart_type
        : null;
      if (typeof raw_chart_type === 'string' && pyStrip(raw_chart_type)) {
        structure_chart_type = raw_chart_type;
      }
    }

    let normalized_resolved: string;
    let normalized_structure: string;
    try {
      normalized_resolved = truthy(resolved_diagram_type)
        ? normalize_supported_diagram_type(resolved_diagram_type)
        : '';
      normalized_structure = structure_chart_type
        ? normalize_supported_diagram_type(structure_chart_type, 'chart_type')
        : '';
    } catch (exc) {
      if (exc instanceof DiagramTypeValidationError) {
        throw _value_error_from(exc);
      }
      throw exc;
    }

    if (normalized_resolved && normalized_structure) {
      if (normalized_resolved !== normalized_structure) {
        throw new ValueError(
          'Structure chart_type conflicts with resolved diagram_type: '
          + `${pyRepr(structure_chart_type)} vs ${pyRepr(resolved_diagram_type)}.`,
        );
      }
      return normalized_structure;
    }

    return pyOr(pyOr(normalized_structure, normalized_resolved), normalize_diagram_type(resolved_diagram_type));
  }

  static _record_stage_artifacts(
    artifact_paths: Record<string, string>,
    save_dir: string | null,
    stage_name: string,
    artifact_name: string,
    instantiation: unknown,
    specification: unknown,
  ): void {
    if (!save_dir) {
      return;
    }
    Object.assign(
      artifact_paths,
      _save_stage_output(
        save_dir,
        stage_name,
        artifact_name,
        instantiation,
        specification,
      ),
    );
  }

  static _raise_if_stage_failed(stage_name: string, stage_state: unknown): void {
    const status = getattr(stage_state, 'status');
    const errors = (pyOr(getattr(stage_state, 'errors'), [])) as unknown[];

    if (status === 'failed' || truthy(errors)) {
      const error_message = pyOr(
        errors.map((error) => pyStr(error)).join('; '), 'no error details',
      );
      throw new RuntimeError(
        `Pipeline generation ${stage_name} stage failed: ${error_message}`,
      );
    }
  }

  _run_structure_stage(
    text_content: string,
    user_query: string,
    design_expertise = '',
    runtime_directives = '',
    diagram_type: string | null = null,
    content_area: string | null = null,
  ): Promise<StructureState> {
    logger.info('[PipelineGenerator] Running StructureWorkflow...');
    const stage_knowledge = this.build_stage_context('Structure', diagram_type);
    const state = new StructureState({
      text_content,
      user_query,
      canvas_library: this.canvas_library,
      stage_knowledge,
      design_expertise,
      runtime_directives,
      diagram_type,
      content_area,
    });
    return this.structure.run(state);
  }

  _run_styling_stage(
    text_content: string,
    user_query: string,
    structure_state: StructureState,
    structure_instantiation: unknown,
    structure_specification: unknown,
    design_expertise: string,
    runtime_directives: string,
    diagram_type: string | null,
    content_area: string | null,
    palette_key: string,
  ): Promise<StylingState> {
    logger.info('[PipelineGenerator] Running StylingWorkflow...');
    const stage_knowledge = this.build_stage_context('Styling', diagram_type);
    const state = new StylingState({
      text_content,
      user_query,
      canvas_library: this.canvas_library,
      structure_instantiation,
      structure_specification,
      stage_knowledge,
      design_expertise,
      runtime_directives,
      diagram_type,
      content_area,
      conversation_history: [...structure_state.conversation_history],
      palette_key,
    });
    return this.styling.run(state);
  }

  _run_layout_stage(
    text_content: string,
    user_query: string,
    styling_state: StylingState,
    structure_instantiation: unknown,
    structure_specification: unknown,
    styling_instantiation: unknown,
    styling_specification: unknown,
    design_expertise: string,
    runtime_directives: string,
    diagram_type: string | null,
    content_area: string | null,
  ): Promise<LayoutState> {
    logger.info('[PipelineGenerator] Running LayoutWorkflow...');
    const stage_knowledge = this.build_stage_context('Layout', diagram_type);
    const state = new LayoutState({
      text_content,
      user_query,
      structure_instantiation,
      styling_instantiation,
      structure_specification,
      styling_specification,
      stage_knowledge,
      design_expertise,
      runtime_directives,
      diagram_type,
      content_area,
      canvas_library: this.canvas_library,
      conversation_history: [...styling_state.conversation_history],
    });
    return this.layout.run(state);
  }

  /** Initialize a pipeline run that can be advanced one stage at a time. */
  async begin_pipeline_run(
    text_content: string,
    user_query: string,
    design_expertise = '',
    runtime_directives = '',
    diagram_type: string | null = null,
    content_area: string | null = null,
  ): Promise<PipelineGenerationRun> {
    const [effective_diagram_type, palette_key] = await this.resolve_generation_context(
      text_content,
      user_query,
      diagram_type,
    );
    return new PipelineGenerationRun(
      text_content,
      user_query,
      design_expertise,
      runtime_directives,
      content_area,
      effective_diagram_type,
      palette_key,
    );
  }

  /** Advance one pipeline stage and record canonical artifacts. */
  async run_pipeline_stage(
    run_state: PipelineGenerationRun,
    stage_name: string,
    save_dir: string | null = null,
  ): Promise<void> {
    if (stage_name === 'structure') {
      const structure_state = await this._run_structure_stage(
        run_state.text_content,
        run_state.user_query,
        run_state.design_expertise,
        run_state.runtime_directives,
        run_state.effective_diagram_type,
        run_state.content_area,
      );
      PipelineGeneratorWorkflow._raise_if_stage_failed('structure', structure_state);
      run_state.structure_state = structure_state;
      run_state.structure_instantiation = structure_state.structure_instantiation;
      run_state.structure_specification = structure_state.structure_specification;
      run_state.effective_diagram_type = PipelineGeneratorWorkflow._resolve_downstream_diagram_type(
        run_state.effective_diagram_type,
        run_state.structure_instantiation,
      );
      PipelineGeneratorWorkflow._record_stage_artifacts(
        run_state.artifact_paths,
        save_dir,
        '1_structure',
        'structure',
        run_state.structure_instantiation,
        run_state.structure_specification,
      );
      return;
    }

    if (stage_name === 'styling') {
      if (run_state.structure_state === null) {
        throw new RuntimeError('Structure stage must run before styling.');
      }
      const styling_state = await this._run_styling_stage(
        run_state.text_content,
        run_state.user_query,
        run_state.structure_state,
        run_state.structure_instantiation,
        run_state.structure_specification,
        run_state.design_expertise,
        run_state.runtime_directives,
        run_state.effective_diagram_type,
        run_state.content_area,
        run_state.palette_key,
      );
      PipelineGeneratorWorkflow._raise_if_stage_failed('styling', styling_state);
      run_state.styling_state = styling_state;
      run_state.styling_instantiation = styling_state.styling_instantiation;
      run_state.styling_specification = styling_state.styling_specification;
      PipelineGeneratorWorkflow._record_stage_artifacts(
        run_state.artifact_paths,
        save_dir,
        '2_styling',
        'styling',
        run_state.styling_instantiation,
        run_state.styling_specification,
      );
      return;
    }

    if (stage_name === 'layout') {
      if (run_state.styling_state === null) {
        throw new RuntimeError('Styling stage must run before layout.');
      }
      const layout_state = await this._run_layout_stage(
        run_state.text_content,
        run_state.user_query,
        run_state.styling_state,
        run_state.structure_instantiation,
        run_state.structure_specification,
        run_state.styling_instantiation,
        run_state.styling_specification,
        run_state.design_expertise,
        run_state.runtime_directives,
        run_state.effective_diagram_type,
        run_state.content_area,
      );
      PipelineGeneratorWorkflow._raise_if_stage_failed('layout', layout_state);
      run_state.layout_state = layout_state;
      run_state.layout_instantiation = layout_state.layout_instantiation;
      run_state.layout_specification = layout_state.layout_specification;
      PipelineGeneratorWorkflow._record_stage_artifacts(
        run_state.artifact_paths,
        save_dir,
        '3_layout',
        'layout',
        run_state.layout_instantiation,
        run_state.layout_specification,
      );
      return;
    }

    throw new ValueError(`Unknown pipeline generation stage: ${stage_name}`);
  }

  /** Return the canonical pipeline output dict for a completed run. */
  static pipeline_outputs(run_state: PipelineGenerationRun): Dict {
    return {
      structure_instantiation: run_state.structure_instantiation,
      structure_specification: run_state.structure_specification,
      styling_instantiation: run_state.styling_instantiation,
      styling_specification: run_state.styling_specification,
      layout_instantiation: run_state.layout_instantiation,
      layout_specification: run_state.layout_specification,
      artifact_paths: { ...run_state.artifact_paths },
    };
  }

  async run(
    text_content: string,
    user_query: string,
    design_expertise = '',
    runtime_directives = '',
    diagram_type: string | null = null,
    content_area: string | null = null,
    save_dir: string | null = null,
  ): Promise<Dict> {
    const run_state = await this.begin_pipeline_run(
      text_content,
      user_query,
      design_expertise,
      runtime_directives,
      diagram_type,
      content_area,
    );

    for (const stage_name of PIPELINE_STAGE_SEQUENCE) {
      await this.run_pipeline_stage(run_state, stage_name, save_dir);
    }

    return PipelineGeneratorWorkflow.pipeline_outputs(run_state);
  }
}

/**
 * Single-shot generation: one LLM call produces the complete scene.
 *
 * Optionally runs a lightweight RouterAgent first to classify diagram_type
 * and palette_key, then injects those into the UnifiedGenerator so it
 * receives the same type-specific knowledge (diagram context, stage rules,
 * palette) that the pipeline mode enjoys.
 */
export class OneShotGeneratorWorkflow extends GeneratorWorkflow {
  canvas_library: string;
  unified: UnifiedGeneratorWorkflow;
  _router: RouterAgent | null;

  constructor(
    model: BaseChatModel,
    canvas_library = 'excalidraw',
    router_model: BaseChatModel | null = null,
    full_domain_knowledge = true,
  ) {
    super();
    canvas_library = normalize_canvas_library(canvas_library);
    require_generation_capability(canvas_library, 'oneshot');
    this.canvas_library = canvas_library;
    this.unified = new UnifiedGeneratorWorkflow(
      model,
      full_domain_knowledge,
    );

    this._router = null;
    if (router_model !== null && router_model !== undefined) {
      this._router = new RouterAgent(router_model);
    }
  }

  async run(
    text_content: string,
    user_query: string,
    design_expertise = '',
    runtime_directives = '',
    diagram_type: string | null = null,
    content_area: string | null = null,
    save_dir: string | null = null,
  ): Promise<Dict> {
    // --- Router (lightweight classification) ---
    let palette_key: string = DEFAULT_PALETTE_KEY;
    let effective_diagram_type: string | null = diagram_type;

    if (this._router !== null && !truthy(effective_diagram_type)) {
      logger.info('[OneShotGenerator] Running RouterAgent...');
      const router_result = await this._router.run(text_content, user_query);
      palette_key = Object.prototype.hasOwnProperty.call(router_result, 'palette_key') ? router_result.palette_key : '';
      if (!truthy(effective_diagram_type)) {
        effective_diagram_type = Object.prototype.hasOwnProperty.call(router_result, 'diagram_type') ? router_result.diagram_type : null;
      }
      logger.info(
        `[OneShotGenerator] Router: diagram_type=${pyStr(effective_diagram_type)}, palette_key=${pyStr(palette_key)}`,
      );
    }

    if (truthy(effective_diagram_type)) {
      try {
        effective_diagram_type = normalize_supported_diagram_type(
          effective_diagram_type,
          'diagram_type',
        );
      } catch (exc) {
        if (exc instanceof DiagramTypeValidationError) {
          throw _value_error_from(exc);
        }
        throw exc;
      }
    }

    logger.info('[OneShotGenerator] Running UnifiedGeneratorWorkflow...');
    let state = new UnifiedWorkflowState({
      text_content,
      user_query,
      design_expertise,
      runtime_directives,
      diagram_type: effective_diagram_type,
      palette_key,
      content_area,
      validation_report_path: (
        save_dir ? join(save_dir, '1_unified', 'generation_validation_attempts.json') : null
      ),
    });
    state = await this.unified.run(state);

    // Persist the manifest when save_dir is provided (parity with pipeline).
    let artifact_paths: Record<string, string>;
    if (save_dir && truthy(state.diagram_manifest)) {
      const stage_dir = join(save_dir, '1_unified');
      mkdirSync(stage_dir, { recursive: true });
      const manifest_path = join(stage_dir, 'diagram_manifest.json');
      writeFileSync(manifest_path, pyJsonDumps(withPyFloats(state.diagram_manifest), { indent: 2, ensureAscii: false }), 'utf-8');
      artifact_paths = { unified_manifest_path: manifest_path };
      if (truthy(state.validation_report_path) && existsSync(state.validation_report_path as string)) {
        artifact_paths.generation_validation_report_path = state.validation_report_path as string;
      }
      if (truthy(state.structure_instantiation)) {
        const structure_path = join(stage_dir, 'structure_instantiation.json');
        writeFileSync(
          structure_path,
          pyJsonDumps(withPyFloats(state.structure_instantiation), { indent: 2, ensureAscii: false }),
          'utf-8',
        );
        artifact_paths.structure_instantiation_path = structure_path;
      }
      if (truthy(state.raw_llm_output)) {
        const raw_path = join(stage_dir, 'raw_llm_output.txt');
        writeFileSync(raw_path, state.raw_llm_output as string, 'utf-8');
        artifact_paths.raw_llm_output_path = raw_path;
      }
    } else {
      artifact_paths = {};
    }

    return {
      structure_instantiation: state.structure_instantiation,
      diagram_manifest: state.diagram_manifest,
      artifact_paths,
    };
  }
}

/**
 * Factory: create a GeneratorWorkflow by mode name.
 *
 * mode: ``"multiagent"`` (Structure → Styling → Layout) or ``"oneshot"``
 * (single LLM call, experimental). router_model: optional cheap model for the
 * Router classifier; when ``null`` the router is skipped.
 * full_domain_knowledge: every pipeline stage receives all stage rules.
 */
export function create_generator(
  mode: string,
  model: BaseChatModel,
  canvas_library = 'excalidraw',
  use_icons = false,
  router_model: BaseChatModel | null = null,
  full_domain_knowledge = true,
): GeneratorWorkflow {
  const normalized_mode = normalize_generation_mode(mode);
  canvas_library = normalize_canvas_library(canvas_library);
  if (normalized_mode === 'multiagent') {
    return new PipelineGeneratorWorkflow(
      model,
      canvas_library,
      use_icons,
      router_model,
      full_domain_knowledge,
    );
  }
  return new OneShotGeneratorWorkflow(
    model,
    canvas_library,
    router_model,
    full_domain_knowledge,
  );
}
