// Ported from backend/app/services/workflow_engine_port.py — keep in sync
// (PHASE3_PLAN.md WP29). The engine primitives the streaming adapter calls.
//
// Python passes classes and calls them with keyword arguments
// (``functools.partial(Text2DiagramWorkflow, **engine)`` is the injection point
// recorded by WP26). TS constructors are positional, so ``workflow_cls`` is a
// kwargs → instance factory (``text2DiagramWorkflowFromKwargs``) and
// ``withEngineOverrides`` is the ``functools.partial`` counterpart.

import type { BaseChatModel } from '@langchain/core/language_models/chat_models';
import { PyTypeError } from '../py/errors.ts';
import { Text2DiagramWorkflow } from '../agentic_system/workflow.ts';
import { IterativeRefinerWorkflow } from '../agentic_system/iterative_workflow.ts';
import { VerifierWorkflow } from '../verification_stage/workflow.ts';
import { Severity } from '../verification_stage/checks/finding.ts';
import { render_manifest } from '../canvas_environment/rendering.ts';

type Dict = Record<string, any>;

/** ``Text2DiagramWorkflow(**kwargs)`` */
export type WorkflowFactory = (kwargs: Dict) => Text2DiagramWorkflow;

/** ``render_manifest(**kwargs)`` */
export type RenderManifest = typeof render_manifest;

/** ``prepare_web_memory(memory_path, embedding_model, seed_path)`` (design memory; not ported). */
export type PrepareDesignMemory = (memory_path: string, embedding_model: string, seed_path: string) => unknown | Promise<unknown>;

/** Engine objects required by the streaming workflow adapter. */
export interface StreamingEngineDependencies {
  workflow_cls: WorkflowFactory;
  verifier_workflow_cls: new () => VerifierWorkflow;
  iterative_refiner_workflow_cls: new () => IterativeRefinerWorkflow;
  severity_cls: unknown;
  render_manifest: RenderManifest;
  prepare_design_memory?: PrepareDesignMemory | null;
  learn_design_memory?: unknown;
}

/** Backend-facing contract for loading workflow primitives. */
export interface WorkflowEnginePort {
  load_text_workflow_cls(): WorkflowFactory;
  load_streaming_dependencies(): StreamingEngineDependencies;
}

/** Parameter names of ``Text2DiagramWorkflow.__init__`` in declaration order. */
export const TEXT2DIAGRAM_PARAMS = [
  'model', 'config', 'save_dir', 'canvas_library', 'mode', 'enable_refiner', 'always_refine', 'refiner_max_iterations',
  'enable_verifier', 'verification_only', 'enable_critic', 'use_icons', 'enable_user_memory', 'user_id', 'memory_db_path',
  'router_model', 'full_domain_knowledge', 'enable_design_memory', 'design_memory_db_path', 'design_memory_embedding_model',
  'design_memory_top_k', 'design_memory_score_threshold',
] as const;

/** ``Text2DiagramWorkflow(**kwargs)``: unknown keywords raise TypeError like Python. */
export function text2DiagramWorkflowFromKwargs(kwargs: Dict): Text2DiagramWorkflow {
  for (const key of Object.keys(kwargs)) {
    if (!(TEXT2DIAGRAM_PARAMS as readonly string[]).includes(key)) {
      throw new PyTypeError(`Text2DiagramWorkflow.__init__() got an unexpected keyword argument '${key}'`);
    }
  }
  if (!('model' in kwargs)) {
    throw new PyTypeError("Text2DiagramWorkflow.__init__() missing 1 required positional argument: 'model'");
  }
  const args = TEXT2DIAGRAM_PARAMS.map((name) => (Object.prototype.hasOwnProperty.call(kwargs, name) ? kwargs[name] : undefined));
  const Ctor = Text2DiagramWorkflow as unknown as new (...a: unknown[]) => Text2DiagramWorkflow;
  return new Ctor(...(args as [BaseChatModel, ...unknown[]]));
}

/** ``functools.partial(workflow_cls, **engine)``: later keywords override the bound ones. */
export function withEngineOverrides(workflow_cls: WorkflowFactory, engine: Dict): WorkflowFactory {
  if (!engine || !Object.keys(engine).length) return workflow_cls;
  return (kwargs: Dict) => workflow_cls({ ...engine, ...kwargs });
}

/** Production engine port backed by the ported EvoDesign engine. */
export class EvoDesignWorkflowEnginePort implements WorkflowEnginePort {
  load_text_workflow_cls(): WorkflowFactory {
    return text2DiagramWorkflowFromKwargs;
  }

  load_streaming_dependencies(): StreamingEngineDependencies {
    return {
      workflow_cls: text2DiagramWorkflowFromKwargs,
      verifier_workflow_cls: VerifierWorkflow,
      iterative_refiner_workflow_cls: IterativeRefinerWorkflow,
      severity_cls: Severity,
      render_manifest,
      // design_memory (prepare_web_memory / learn_verified_refinement) is not
      // ported; hosts may inject implementations (PHASE3_PLAN.md WP29).
      prepare_design_memory: null,
      learn_design_memory: null,
    };
  }
}
