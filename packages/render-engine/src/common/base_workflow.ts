// Ported from evodesign/agentic_system/common/base_workflow.py — keep in sync.
// server-only (LangGraph.js uses AsyncLocalStorage)
//
// Base workflow class providing a unified run() template for all Generation workflows.
//
// ``langgraph.graph.StateGraph(PydanticModel)`` → ``PydanticStateGraph``: a
// LangGraph.js ``StateGraph`` with one last-value channel per model field.
// Like Python LangGraph with a pydantic schema, every node (and every
// conditional-edge path function) receives the state re-validated into an
// instance of the model class (``Model(**channel_values)``), and may return
// that instance (all fields become updates) or a partial dict. Node names,
// edges and conditional edges are added with the LangGraph.js API
// (``addNode``/``addEdge``/``addConditionalEdges``, ``START``/``END``).
//
// Subclass note: TS runs ``_build_workflow()`` inside ``super()``, before the
// subclass constructor body. Python subclasses that set attributes before
// ``super().__init__`` must set them in an overridden ``_build_workflow`` or
// only use them from node bodies (which run later, in ``run``).

import { Annotation, StateGraph } from '@langchain/langgraph';
import { NotImplementedError } from '../py/errors.ts';
import { getLogger } from '../py/logging.ts';
import { isDict } from '../py/truthy.ts';
import type { WorkflowStateBase } from './workflow_state_base.ts';

const logger = getLogger('evodesign.agentic_system.common.base_workflow');
void logger;

/** A ``WorkflowStateBase`` subclass (the pydantic model class). */
export interface WorkflowStateClass<S extends WorkflowStateBase = WorkflowStateBase> {
  new (data?: Record<string, unknown>): S;
  model_fields: Record<string, unknown>;
  pythonName: string;
  name: string;
}

type AnyFn = (...args: unknown[]) => unknown;

/** One ``Annotation<unknown>()`` (LastValue channel) per model field. */
export function stateAnnotation(cls: WorkflowStateClass) {
  const channels: Record<string, ReturnType<typeof Annotation<unknown>>> = {};
  for (const name of Object.keys(cls.model_fields)) channels[name] = Annotation<unknown>();
  return Annotation.Root(channels);
}

function coerceState(cls: WorkflowStateClass, values: unknown): unknown {
  if (values instanceof cls) return values;
  if (isDict(values)) return new cls(values);
  return values;
}

function named<T extends AnyFn>(fn: T, name: string): T {
  Object.defineProperty(fn, 'name', { value: name, configurable: true });
  return fn;
}

/** ``StateGraph(workflow_state_cls)`` with pydantic-style state coercion. */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export class PydanticStateGraph extends (StateGraph as any) {
  readonly pythonName: string;
  readonly _state_cls: WorkflowStateClass;

  constructor(workflow_state_cls: WorkflowStateClass) {
    super(stateAnnotation(workflow_state_cls));
    this._state_cls = workflow_state_cls;
    this.pythonName = workflow_state_cls.pythonName;
  }

  private _wrapAction(action: unknown): unknown {
    if (typeof action !== 'function') return action;
    const cls = this._state_cls;
    const fn = action as AnyFn;
    return named((state: unknown, config: unknown) => fn(coerceState(cls, state), config), fn.name);
  }

  addNode(...args: unknown[]): this {
    const wrap = (action: unknown) => this._wrapAction(action);
    if (typeof args[0] === 'string') return super.addNode(args[0], wrap(args[1]), ...args.slice(2));
    if (Array.isArray(args[0])) {
      return super.addNode((args[0] as [string, unknown, ...unknown[]][]).map(([key, action, ...rest]) => [key, wrap(action), ...rest]), ...args.slice(1));
    }
    if (args[0] && typeof args[0] === 'object') {
      return super.addNode(Object.fromEntries(Object.entries(args[0] as Record<string, unknown>).map(([key, action]) => [key, wrap(action)])), ...args.slice(1));
    }
    return super.addNode(...args);
  }

  addConditionalEdges(source: unknown, path?: unknown, pathMap?: unknown): this {
    if (typeof source === 'object' && source !== null) {
      const options = { ...(source as Record<string, unknown>) };
      options.path = this._wrapAction(options.path);
      return super.addConditionalEdges(options);
    }
    return super.addConditionalEdges(source, this._wrapAction(path), pathMap);
  }
}

/**
 * Unified workflow execution template.
 *
 * Subclasses implement ``_build_workflow()`` to define their LangGraph
 * nodes and edges. The base class handles graph compilation, invocation,
 * and dict-to-State conversion.
 *
 * Override ``_validate_inputs(state)`` to add input validation (default is
 * a no-op).
 */
export class BaseWorkflow<S extends WorkflowStateBase = WorkflowStateBase> {
  _workflow_state_cls: WorkflowStateClass<S>;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  workflow: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  graph: any;

  constructor(workflow_state_cls: WorkflowStateClass<S>) {
    this._workflow_state_cls = workflow_state_cls;
    this.workflow = new PydanticStateGraph(workflow_state_cls as WorkflowStateClass);
    this.graph = this._build_workflow();
  }

  // ------------------------------------------------------------------
  // Extension points for subclasses
  // ------------------------------------------------------------------

  /** Build and compile the LangGraph StateGraph. Must be implemented by every subclass. */
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  _build_workflow(): any {
    throw new NotImplementedError();
  }

  /**
   * Optional input validation. Override to enforce required fields.
   * Raise ``ValueError`` on missing inputs.
   */
  _validate_inputs(_state: S): void {}

  // ------------------------------------------------------------------
  // Template method
  // ------------------------------------------------------------------

  /** Execute the compiled graph and return the result as a ``WorkflowStateBase`` instance. */
  async run(state: S): Promise<S> {
    this._validate_inputs(state);
    const result_dict = await this.graph.invoke(state);
    if (isDict(result_dict)) {
      return new this._workflow_state_cls(result_dict);
    }
    return result_dict as S;
  }
}
