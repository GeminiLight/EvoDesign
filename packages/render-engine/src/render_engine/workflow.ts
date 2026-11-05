// Ported from evodesign/agentic_system/render_engine/workflow.py — keep in sync.
//
// Excalidraw path only (MIGRATION_PLAN.md §1): the tldraw nodes and the
// langgraph compilation are out of scope. The graph is always the sequential
// chain (Python's ``_SequentialGraph``), which is what langgraph runs too.
//
// Contract with tools/parity-stages.ts:
//   createWorkflowState(input) and excalidrawNodes(): [nodeName, (state) => state][]

import { pyDeepcopy } from '../py/float_marks.ts';
import { ensure_no_integer_like_semantic_ids } from '../common/semantic_ids.ts';
import { RuntimeError, ValueError } from '../py/errors.ts';
import { getLogger } from '../py/logging.ts';
import { truthy } from '../py/truthy.ts';
import { add_icon_urls } from './shared/icon_url_adder.ts';
import { audit_excalidraw_manifest, audit_layout_instantiation } from './shared/render_audit.ts';
import { InstantiationToExcalidrawConverter } from './excalidraw/converter.ts';
import { fit_shape_sizes_to_text } from './excalidraw/shape_size_fitter.ts';
import { add_excalidraw_arrows_to_manifest } from './excalidraw/arrow_adder.ts';
import { normalize_architecture_style } from './excalidraw/architecture_style_normalizer.ts';
import { fit_excalidraw_groups_to_children } from './excalidraw/group_fitter.ts';
import { preserve_group_alignment_intent } from './excalidraw/group_alignment_normalizer.ts';
import { compact_architecture_layout } from './excalidraw/layered_layout_compactor.ts';
import { compact_concept_map_layout } from './excalidraw/radial_concept_compactor.ts';
import { apply_architecture_design_system } from './excalidraw/architecture_design_system.ts';
import { apply_design_theme } from './excalidraw/design_theme.ts';
import { is_enabled as _zorder_repair_enabled, repair_zorder } from './excalidraw/zorder_repair.ts';
import { validate_excalidraw_manifest } from './excalidraw/validator.ts';
import { WorkflowState } from './state.ts';
import { ALIGN_GROUPS, ARROW, CONVERT, FIT_GROUPS, SIZE_FIT, VALIDATE, ZORDER_REPAIR } from './stages.ts';

type Dict = Record<string, unknown>;
export type WorkflowNode = (state: WorkflowState) => WorkflowState;

const logger = getLogger('evodesign.agentic_system.render_engine.workflow');

/** Fail the render workflow on semantic losses that later validators miss. */
export function _raise_on_blocking_render_audit(report: unknown, canvas_library: string): void {
  const issues = (report as { issues?: unknown } | null)?.issues;
  if (!Array.isArray(issues)) {
    return;
  }
  const blocking = issues.filter((issue) => (issue as { category?: unknown } | null)?.category === 'arrow_coverage');
  if (!blocking.length) {
    return;
  }
  const details = blocking.map((issue) => String((issue as { message?: unknown }).message ?? issue)).join('\n');
  throw new RuntimeError(
    `${canvas_library} render audit failed: structure edges were not `
    + `faithfully rendered.\n${details}`,
  );
}

/** Runs a linear chain of nodes in order; used when langgraph is absent. */
export class _SequentialGraph {
  private _nodes: WorkflowNode[];

  constructor(nodes: [string, WorkflowNode][]) {
    this._nodes = nodes.map(([, node]) => node);
  }

  invoke(state: WorkflowState): WorkflowState {
    for (const node of this._nodes) {
      state = node(state);
    }
    return state;
  }
}

/** Compile ``[(name, node), ...]`` as a chain (always sequential in TS). */
export function _linear_graph(nodes: [string, WorkflowNode][], _sequential = false): _SequentialGraph {
  return new _SequentialGraph(nodes);
}

/** Sequential workflow that converts styling data, adds arrows and validates (Excalidraw only). */
export class RenderWorkflow {
  canvas_library: string;
  graph: _SequentialGraph;

  constructor(canvas_library: string | null = null, sequential = false) {
    if (canvas_library === null) {
      canvas_library = 'excalidraw';
    }
    const canvas = String(canvas_library).trim().toLowerCase();
    if (canvas !== 'excalidraw') {
      // tldraw is out of scope for the TS port (MIGRATION_PLAN.md §1).
      throw new ValueError(`Unsupported canvas_library in the TS port: '${canvas_library}'.`);
    }
    this.canvas_library = canvas;
    this.graph = _linear_graph(this._excalidraw_nodes(), sequential);
  }

  // ==================================================================
  // Excalidraw workflow
  // ==================================================================
  _excalidraw_nodes(): [string, WorkflowNode][] {
    return [
      ['excalidraw_add_icon_urls', (s) => this._run_excalidraw_icon_url_adder(s)],
      ['excalidraw_convert', (s) => this._run_excalidraw_converter(s)],
      ['excalidraw_size_fit', (s) => this._run_excalidraw_size_fit(s)],
      ['excalidraw_fit_groups', (s) => this._run_excalidraw_group_fitter(s)],
      ['excalidraw_align_groups', (s) => this._run_excalidraw_group_alignment(s)],
      ['excalidraw_arrows', (s) => this._run_excalidraw_arrow_adder(s)],
      ['excalidraw_arch_design_system', (s) => this._run_excalidraw_arch_design_system(s)],
      ['excalidraw_zorder_repair', (s) => this._run_excalidraw_zorder_repair(s)],
      ['excalidraw_validate', (s) => this._run_excalidraw_validator(s)],
    ];
  }

  /** Add icon URLs to styling_instantiation before Excalidraw conversion. */
  _run_excalidraw_icon_url_adder(state: WorkflowState): WorkflowState {
    const updated_layout = add_icon_urls(state.layout_instantiation);
    state.layout_instantiation = updated_layout as Dict;
    logger.info('[RenderWorkflow/Excalidraw] Icon URLs added to layout_instantiation');
    return state;
  }

  /** Convert positioned styling JSON into an Excalidraw manifest. */
  _run_excalidraw_converter(state: WorkflowState): WorkflowState {
    audit_layout_instantiation(state.layout_instantiation, state.structure_instantiation);
    const converter = new InstantiationToExcalidrawConverter(state.layout_instantiation, state.structure_instantiation);
    const manifest = converter.convert();
    state.update_stage(CONVERT, { manifest });
    logger.info('[RenderWorkflow/Excalidraw] Manifest (no arrows) generated in memory');
    return state;
  }

  /** Enforce shape.width/height >= bound-text bbox (plus shape-type padding). */
  _run_excalidraw_size_fit(state: WorkflowState): WorkflowState {
    const fitted_manifest = fit_shape_sizes_to_text(state.diagram_manifest as Dict);
    state.update_stage(SIZE_FIT, { manifest: fitted_manifest });
    logger.info('[RenderWorkflow/Excalidraw] Shape sizes fitted to bound text');
    return state;
  }

  /** Enrich Excalidraw manifest with arrows from structure_instantiation. */
  _run_excalidraw_arrow_adder(state: WorkflowState): WorkflowState {
    const base_manifest = truthy(state.diagram_manifest) ? state.diagram_manifest : state.manifest_without_arrows;
    let enriched_manifest = add_excalidraw_arrows_to_manifest(base_manifest as Dict, state.structure_instantiation);
    enriched_manifest = normalize_architecture_style(
      enriched_manifest,
      state.structure_instantiation,
      state.layout_instantiation,
    );
    state.update_stage(ARROW, { manifest: enriched_manifest });
    const report = audit_excalidraw_manifest(enriched_manifest, state.structure_instantiation);
    _raise_on_blocking_render_audit(report, 'Excalidraw');
    logger.info('[RenderWorkflow/Excalidraw] Manifest enriched with arrows in memory');
    return state;
  }

  /** Fit group backgrounds in Excalidraw manifest to wrap children. */
  _run_excalidraw_group_fitter(state: WorkflowState): WorkflowState {
    logger.info('[RenderWorkflow/Excalidraw] Fitting group frames to children');
    const fitted_manifest = fit_excalidraw_groups_to_children(
      state.diagram_manifest as Dict,
      state.structure_instantiation,
      20,
    );
    state.update_stage(FIT_GROUPS, { manifest: fitted_manifest });
    logger.info('[RenderWorkflow/Excalidraw] Group frames fitted successfully');
    return state;
  }

  /** Preserve equal-width/equal-height group intent from layout output. */
  _run_excalidraw_group_alignment(state: WorkflowState): WorkflowState {
    let aligned_manifest = preserve_group_alignment_intent(
      state.diagram_manifest as Dict,
      state.layout_instantiation,
    );
    aligned_manifest = compact_architecture_layout(aligned_manifest, state.structure_instantiation);
    aligned_manifest = compact_concept_map_layout(aligned_manifest, state.structure_instantiation);
    state.update_stage(ALIGN_GROUPS, { manifest: aligned_manifest });
    logger.info('[RenderWorkflow/Excalidraw] Group alignment intent preserved');
    return state;
  }

  /** Apply the architecture design system, or the shared theme to other types. */
  _run_excalidraw_arch_design_system(state: WorkflowState): WorkflowState {
    let designed: unknown = apply_architecture_design_system(
      state.diagram_manifest as Dict,
      state.structure_instantiation,
      state.layout_instantiation,
      state.layout_specification,
      state.design_constraints,
    );
    if (designed === state.diagram_manifest) {
      designed = apply_design_theme(
        state.diagram_manifest,
        state.structure_instantiation,
        state.layout_instantiation,
        state.design_constraints,
      );
    }
    if (designed !== state.diagram_manifest) {
      state.update_stage(ARROW, { manifest: designed });
    }
    return state;
  }

  /** Reassign fractional indices by layer band so group frames never occlude their children. */
  _run_excalidraw_zorder_repair(state: WorkflowState): WorkflowState {
    if (!_zorder_repair_enabled()) {
      logger.info(
        '[RenderWorkflow/Excalidraw] zorder_repair disabled via '
        + 'EVODESIGN_RENDER_FIX_ZORDER; skipping.',
      );
      return state;
    }
    const repaired_manifest = repair_zorder(state.diagram_manifest as Dict);
    state.update_stage(ZORDER_REPAIR, { manifest: repaired_manifest });
    return state;
  }

  /** Validate Excalidraw manifest structure. */
  _run_excalidraw_validator(state: WorkflowState): WorkflowState {
    logger.info('[RenderWorkflow/Excalidraw] Validating manifest structure');
    const report = validate_excalidraw_manifest(state.diagram_manifest as Dict);
    state.update_stage(VALIDATE, report);
    if (!truthy(report.is_valid ?? false)) {
      const errors = ((report.errors ?? []) as unknown[]).map(String).join('\n');
      throw new ValueError(`Excalidraw manifest validation failed:\n${errors}`);
    }
    return state;
  }

  /** Run all stages and return the completed state. */
  run(state: WorkflowState): WorkflowState {
    logger.info(`Starting render workflow (canvas_library=${this.canvas_library})...`);
    ensure_no_integer_like_semantic_ids(state.structure_instantiation, state.layout_instantiation);
    const result = this.graph.invoke(state);
    logger.info('Render workflow finished.');
    return result;
  }
}

// ----------------------------------------------------------------------
// TS-only entry points (contract with tools/parity-stages.ts and tools/render.ts)
// ----------------------------------------------------------------------

/** ``WorkflowState(**input, canvas_library="excalidraw")`` */
export function createWorkflowState(input: Dict): WorkflowState {
  return new WorkflowState({ ...input, canvas_library: 'excalidraw' });
}

/** ``RenderWorkflow(canvas_library="excalidraw")._excalidraw_nodes()`` */
export function excalidrawNodes(): [string, WorkflowNode][] {
  return new RenderWorkflow('excalidraw')._excalidraw_nodes();
}

/** Run every Excalidraw node and return the final ``diagram_manifest``. */
export function renderExcalidrawManifest(input: Dict): Dict {
  const state = new RenderWorkflow('excalidraw').run(createWorkflowState(pyDeepcopy(input)));
  return state.diagram_manifest as Dict;
}
