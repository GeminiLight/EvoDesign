// Ported from evodesign/agentic_system/main.py — keep in sync.
// server-only (CLI, file I/O, environment)
//
// Main entry point for Text2Diagram workflow CLI.
//
// Usage:
//     npx tsx src/agentic_system/main.ts --example 1
//     npx tsx src/agentic_system/main.ts --start 1 --end 10
//     npx tsx src/agentic_system/main.ts --all
//
// TS notes:
// * ``argparse`` is replaced by a small parser that supports exactly the
//   options below (``--opt value``, ``--opt=value``, unique-prefix
//   abbreviations, ``nargs='+'``, ``choices``, ``type=int``, mutually
//   exclusive groups, ``SUPPRESS`` defaults). Help text is simplified.
// * ``parse_arguments(argv)`` takes the argument list (Python reads
//   ``sys.argv[1:]``); ``main(argv)`` is async and returns the exit code.
// * ``runRecordedPipeline`` is the entry used by ``tools/parity-runs.ts``
//   (PHASE2_PLAN appendix E); it mirrors ``tools/record_runs.py worker()``.

import { homedir, mkdirSync, readFileSync, statSync, writeFileSync } from '../py/fs.ts';
import { join } from '../py/path.ts';
import { withPyFloats } from '../py/float_marks.ts';
import { fileURLToPath } from 'node:url';
import type { BaseChatModel } from '@langchain/core/language_models/chat_models';

import { ensure_env_loaded } from '../utils/env_loader.ts';

import { LLMFactory, set_chat_model_factory, type ChatModelFactory } from '../core/llm_factory.ts';
import { canonical_method_name, get_experiment_id, get_evodesign_output_dir } from '../core/experiment.ts';
import { DEFAULT_TEST_DATASET, EXAMPLES_DIR, safe_join_under, safe_path_segment } from '../utils/path_manager.ts';
import { AgenticSystemConfig, get_variant_preset, list_variant_presets } from './config.ts';
import { Text2DiagramWorkflow, user_memory_hooks, _USER_MEMORY_IMPORT_ERROR } from './workflow.ts';
import { ModelConfig } from '../config/model_loader.ts';
import { AppSettings, _ENV_OVERRIDES } from '../config/settings.ts';
import { MAX_REFINER_ITERATIONS } from '../refinement_stage/state.ts';

import { KeyError, RuntimeError, ValueError } from '../py/errors.ts';
import { clearEnv } from '../py/env.ts';
import { pyJsonDumps } from '../py/json.ts';
import { pyJsonLoadsExact } from '../py/json_decoder.ts';
import { getLogger } from '../py/logging.ts';
import { pyGet } from '../py/dict.ts';
import { cpLen, pyRepr, pyStr, pyStrip } from '../py/str.ts';
import { isDict, isInt, isStr, truthy } from '../py/truthy.ts';

ensure_env_loaded();

const logger = getLogger('evodesign.agentic_system.main');

type Dict = Record<string, any>;

/**
 * Module globals that Python callers and tests replace at run time
 * (``monkeypatch.setattr(main, "EXAMPLES_DIR", ...)``). Python looks these
 * names up in the module namespace on every call; TS imports are read-only
 * bindings, so the functions below read them through this object.
 */
export const _globals = {
  EXAMPLES_DIR,
  DEFAULT_TEST_DATASET,
  get_experiment_id,
  get_evodesign_output_dir,
};

/** Raised when generation completes but the verifier quality gate fails. */
export class VerificationQualityError extends RuntimeError {
  static pythonModule = 'evodesign.agentic_system.main';
}

/** ``SystemExit(code)`` raised by the argument parser. */
export class SystemExit extends Error {
  constructor(readonly code: number) {
    super(`SystemExit: ${code}`);
    this.name = 'SystemExit';
  }
}

// ── CLI Parsing ─────────────────────────────────────────────────────────

/** ``argparse.Namespace``: SUPPRESS-ed options are absent until given. */
export type Namespace = Record<string, any>;

interface OptionSpec {
  flags: string[];
  dest: string;
  action: 'store' | 'store_true' | 'store_false';
  type?: (raw: string) => unknown;
  typeName?: string;
  choices?: readonly unknown[];
  nargs?: '+';
  /** ``undefined`` = argparse.SUPPRESS */
  default?: unknown;
  suppress?: boolean;
  group?: string;
}

/** ``int(raw)`` as argparse ``type=int`` sees it. */
function _int_type(raw: string): number {
  const text = raw.trim();
  if (!/^[-+]?\d+(_\d+)*$/.test(text)) throw new ValueError(`invalid literal for int() with base 10: ${pyRepr(raw)}`);
  return Number(text.replace(/_/g, ''));
}

function _option_specs(): OptionSpec[] {
  return [
    { flags: ['--example'], dest: 'example', action: 'store', type: _int_type, typeName: 'int', default: null },
    { flags: ['--all'], dest: 'all', action: 'store_true', default: false },
    { flags: ['--mode'], dest: 'mode', action: 'store', choices: ['multiagent', 'oneshot'], suppress: true },
    { flags: ['--no-save-intermediate'], dest: 'no_save_intermediate', action: 'store_true', default: false },
    { flags: ['--enable-refiner'], dest: 'enable_refiner', action: 'store_true', suppress: true },
    { flags: ['--refiner-iterations'], dest: 'refiner_iterations', action: 'store', type: _int_type, typeName: 'int', default: 3 },

    // Verification
    { flags: ['--enable-verifier'], dest: 'enable_verifier', action: 'store_true', default: true },
    { flags: ['--no-verifier'], dest: 'enable_verifier', action: 'store_false', default: true },
    { flags: ['--verification-only'], dest: 'verification_only', action: 'store_true', default: false },
    { flags: ['--critic'], dest: 'enable_critic', action: 'store_true', default: true, group: 'critic' },
    { flags: ['--no-critic'], dest: 'enable_critic', action: 'store_false', default: true, group: 'critic' },

    { flags: ['--model'], dest: 'model', action: 'store', default: null },

    // Tool toggles
    { flags: ['--use-icons'], dest: 'use_icons', action: 'store_true', suppress: true },
    { flags: ['--no-icons'], dest: 'use_icons', action: 'store_false', suppress: true },
    { flags: ['--canvas-library'], dest: 'canvas_library', action: 'store', choices: ['excalidraw', 'tldraw'], suppress: true },

    // Provider
    { flags: ['--model-config'], dest: 'model_config', action: 'store', default: null },
    { flags: ['--settings'], dest: 'settings', action: 'store', default: null },
    { flags: ['--role'], dest: 'role', action: 'store', default: 'generator' },
    { flags: ['--dataset-path'], dest: 'dataset_path', action: 'store', default: null },
    { flags: ['--start'], dest: 'start', action: 'store', type: _int_type, typeName: 'int', default: null },
    { flags: ['--end'], dest: 'end', action: 'store', type: _int_type, typeName: 'int', default: null },
    { flags: ['--ids'], dest: 'ids', action: 'store', nargs: '+', default: null },
    { flags: ['--tag'], dest: 'tag', action: 'store', default: null },
    {
      flags: ['--variant'], dest: 'variant', action: 'store', type: canonical_method_name, typeName: 'canonical_method_name',
      choices: list_variant_presets(), default: null,
    },

    // User Memory
    { flags: ['--learn-from-edit'], dest: 'learn_from_edit', action: 'store_true', default: false },
    { flags: ['--enable-user-memory'], dest: 'enable_user_memory', action: 'store_true', default: false },
    { flags: ['--user-id'], dest: 'user_id', action: 'store', default: 'default_user' },
    { flags: ['--session-id'], dest: 'session_id', action: 'store', default: null },
    { flags: ['--memory-db-path'], dest: 'memory_db_path', action: 'store', default: null },

    // Design Memory (evolved design knowledge injected into generation)
    { flags: ['--design-memory'], dest: 'enable_design_memory', action: 'store_true', default: true, group: 'design_memory' },
    { flags: ['--no-design-memory'], dest: 'enable_design_memory', action: 'store_false', default: true, group: 'design_memory' },
    { flags: ['--design-memory-db-path'], dest: 'design_memory_db_path', action: 'store', default: null },

    // Learn-from-edit mode
    { flags: ['--task-json'], dest: 'task_json', action: 'store', default: null },
    { flags: ['--model-manifest'], dest: 'model_manifest', action: 'store', default: null },
    { flags: ['--model-image'], dest: 'model_image', action: 'store', default: null },
    { flags: ['--user-manifest'], dest: 'user_manifest', action: 'store', default: null },
    { flags: ['--user-image'], dest: 'user_image', action: 'store', default: null },
  ];
}

const PROG = 'main.py';

function _parser_error(message: string): never {
  process.stderr.write(`usage: ${PROG} [-h] [options]\n${PROG}: error: ${message}\n`);
  throw new SystemExit(2);
}

function _looks_like_negative_number(arg: string): boolean {
  return /^-\d+$|^-\d*\.\d+$/.test(arg);
}

/** Parse command line arguments. */
export function parse_arguments(argv: string[] = process.argv.slice(2)): Namespace {
  const specs = _option_specs();
  const ns: Namespace = {};
  for (const spec of specs) {
    if (!spec.suppress && !(spec.dest in ns)) ns[spec.dest] = spec.default;
  }
  const flagMap = new Map<string, OptionSpec>();
  for (const spec of specs) for (const flag of spec.flags) flagMap.set(flag, spec);
  const seenGroups = new Map<string, string>();

  const resolveFlag = (name: string): OptionSpec => {
    const exact = flagMap.get(name);
    if (exact) return exact;
    const matches = [...flagMap.keys()].filter((flag) => flag.startsWith(name));
    if (matches.length === 1) return flagMap.get(matches[0])!;
    if (matches.length > 1) {
      _parser_error(`ambiguous option: ${name} could match ${matches.join(', ')}`);
    }
    _parser_error(`unrecognized arguments: ${name}`);
  };

  const convert = (spec: OptionSpec, raw: string): unknown => {
    let value: unknown = raw;
    if (spec.type) {
      try {
        value = spec.type(raw);
      } catch {
        _parser_error(`argument ${spec.flags.join('/')}: invalid ${spec.typeName} value: ${pyRepr(raw)}`);
      }
    }
    if (spec.choices && !spec.choices.includes(value)) {
      _parser_error(
        `argument ${spec.flags.join('/')}: invalid choice: ${pyRepr(value)} (choose from ${spec.choices.map((c) => pyRepr(c)).join(', ')})`,
      );
    }
    return value;
  };

  const positionals: string[] = [];
  let i = 0;
  while (i < argv.length) {
    const arg = argv[i];
    if (arg === '-h' || arg === '--help') {
      process.stdout.write(`usage: ${PROG} [-h] [options]\n\nRun Text2Diagram workflow on dataset examples\n`);
      throw new SystemExit(0);
    }
    if (arg === '--') {
      positionals.push(...argv.slice(i + 1));
      break;
    }
    if (!arg.startsWith('--') || arg === '-') {
      positionals.push(arg);
      i += 1;
      continue;
    }
    let name = arg;
    let inline: string | null = null;
    const eq = arg.indexOf('=');
    if (eq >= 0) {
      name = arg.slice(0, eq);
      inline = arg.slice(eq + 1);
    }
    const spec = resolveFlag(name);
    if (spec.group) {
      const previous = seenGroups.get(spec.group);
      const flag = spec.flags[0];
      if (previous !== undefined && previous !== flag) {
        _parser_error(`argument ${flag}: not allowed with argument ${previous}`);
      }
      seenGroups.set(spec.group, flag);
    }
    i += 1;
    if (spec.action === 'store_true' || spec.action === 'store_false') {
      if (inline !== null) _parser_error(`argument ${spec.flags.join('/')}: ignored explicit argument ${pyRepr(inline)}`);
      ns[spec.dest] = spec.action === 'store_true';
      continue;
    }
    if (spec.nargs === '+') {
      const values: unknown[] = [];
      if (inline !== null) values.push(convert(spec, inline));
      while (i < argv.length && (!argv[i].startsWith('-') || argv[i] === '-' || _looks_like_negative_number(argv[i]))) {
        if (argv[i] === '--') break;
        values.push(convert(spec, argv[i]));
        i += 1;
      }
      if (!values.length) _parser_error(`argument ${spec.flags.join('/')}: expected at least one argument`);
      ns[spec.dest] = values;
      continue;
    }
    let raw: string;
    if (inline !== null) {
      raw = inline;
    } else {
      if (i >= argv.length || (argv[i].startsWith('-') && !_looks_like_negative_number(argv[i]) && argv[i] !== '-')) {
        _parser_error(`argument ${spec.flags.join('/')}: expected one argument`);
      }
      raw = argv[i];
      i += 1;
    }
    ns[spec.dest] = convert(spec, raw);
  }
  if (positionals.length) _parser_error(`unrecognized arguments: ${positionals.join(' ')}`);
  return ns;
}

function hasattr(args: Namespace, name: string): boolean {
  return Object.prototype.hasOwnProperty.call(args, name);
}

/** ``getattr(args, name, default)`` */
function getattr(obj: unknown, name: string, defaultValue: unknown = null): unknown {
  if (obj === null || obj === undefined) return defaultValue;
  const value = (obj as Dict)[name];
  return value === undefined ? defaultValue : value;
}

/** Build AgenticSystemConfig from parsed CLI arguments. */
export function build_config(args: Namespace): AgenticSystemConfig {
  if (truthy(args.model_config)) {
    ModelConfig.init(args.model_config);
  }

  if (truthy(args.settings)) {
    AppSettings.init(args.settings);
  }

  // Resolution order:
  //   CLI flags > explicitly selected variant preset > settings.yaml defaults.
  // When --variant is omitted, keep "evodesign" only as the output-path
  // variant name; do not let its preset shadow settings.yaml.
  const variant = args.variant || 'evodesign';
  const preset: Dict = truthy(args.variant) ? get_variant_preset(args.variant) : {};

  const settings = AppSettings.get_default();
  const settings_mode = settings.generation_mode;
  const settings_canvas = settings.canvas_library;
  const settings_enable_refiner = settings.generation_enable_refiner;
  const settings_use_icons = settings.generation_use_icons;
  const settings_full_domain_knowledge = settings.full_domain_knowledge;

  const resolve_arg = (name: string, setting_default: unknown): any => {
    if (hasattr(args, name)) {
      return args[name];
    }
    return Object.prototype.hasOwnProperty.call(preset, name) ? preset[name] : setting_default;
  };

  return new AgenticSystemConfig({
    role: args.role,
    model_override: args.model,
    mode: resolve_arg('mode', settings_mode),
    save_intermediate: !args.no_save_intermediate,
    tag: args.tag,
    variant,
    enable_refiner: resolve_arg('enable_refiner', settings_enable_refiner),
    refiner_iterations: args.refiner_iterations,
    enable_verifier: args.enable_verifier,
    verification_only: args.verification_only,
    enable_critic: args.enable_critic,
    use_icons: resolve_arg('use_icons', settings_use_icons),
    canvas_library: resolve_arg('canvas_library', settings_canvas),
    full_domain_knowledge: settings_full_domain_knowledge,
    enable_user_memory: args.enable_user_memory,
    user_id: args.user_id,
    session_id: args.session_id,
    memory_db_path: args.memory_db_path,
    // getattr keeps programmatic arg namespaces that predate these flags
    // working, and falls back to the AgenticSystemConfig default.
    enable_design_memory: getattr(args, 'enable_design_memory', true) as boolean,
    design_memory_db_path: getattr(args, 'design_memory_db_path', null) as string | null,
    learn_from_edit: args.learn_from_edit,
    task_json: args.task_json,
    model_manifest: args.model_manifest,
    model_image: args.model_image,
    user_manifest: args.user_manifest,
    user_image: args.user_image,
  });
}

// ── Validation ──────────────────────────────────────────────────────────

/** Validate config + CLI args combination. */
export function validate_config(config: AgenticSystemConfig, args: Namespace): null {
  if (config.learn_from_edit) {
    const required = ['task_json', 'model_manifest', 'model_image', 'user_manifest', 'user_image'];
    const missing = required
      .filter((f) => !truthy((config as unknown as Dict)[f]))
      .map((f) => `--${f.replace(/_/g, '-')}`);
    if (missing.length) {
      throw new ValueError(`--learn-from-edit requires: ${missing.join(', ')}`);
    }
    return null;
  }

  const refiner_iterations = getattr(config, 'refiner_iterations', null) as number | null;
  if (refiner_iterations !== null && !(refiner_iterations >= 1 && refiner_iterations <= MAX_REFINER_ITERATIONS)) {
    throw new ValueError(`--refiner-iterations must be between 1 and ${MAX_REFINER_ITERATIONS}`);
  }

  const mode_count = [
    args.example !== null && args.example !== undefined,
    (args.start !== null && args.start !== undefined) || (args.end !== null && args.end !== undefined),
    args.ids !== null && args.ids !== undefined,
    truthy(getattr(args, 'all', false)),
  ].filter(Boolean).length;
  if (mode_count === 0) {
    throw new ValueError('Must specify one of: --example, --start/--end, --ids, or --all');
  }
  if (mode_count > 1) {
    throw new ValueError('Cannot combine --example, --start/--end, --ids, and --all.');
  }
  if ((args.start !== null && args.start !== undefined) || (args.end !== null && args.end !== undefined)) {
    if (args.start === null || args.start === undefined || args.end === null || args.end === undefined) {
      throw new ValueError('Both --start and --end must be specified together');
    }
    if (args.start < 1 || args.end < 1) {
      throw new ValueError('--start and --end must be >= 1');
    }
    if (args.start > args.end) {
      throw new ValueError('--start must be <= --end');
    }
  }
  return null;
}

// ── Dataset ─────────────────────────────────────────────────────────────

/** ``Path(p).expanduser()`` */
function _expanduser(path: string): string {
  if (path === '~' || path.startsWith('~/')) return homedir() + path.slice(1);
  return path;
}

/** Python ``FileNotFoundError`` (``OSError`` subclass). */
export class FileNotFoundError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'FileNotFoundError';
  }
}

/** Load dataset from path (default: test dataset). */
export function load_dataset(dataset_path: string | null): [unknown[], string] {
  const path = truthy(dataset_path) ? _expanduser(dataset_path!) : _globals.DEFAULT_TEST_DATASET;
  let is_file = false;
  try {
    is_file = statSync(path).isFile();
  } catch {
    is_file = false;
  }
  if (!is_file) {
    throw new FileNotFoundError(`Input file not found: ${path}. Training/test datasets are released separately. Pass --dataset-path examples/diagrams/quickstart.json to try the included example.`);
  }
  const dataset = pyJsonLoadsExact(readFileSync(path, 'utf-8')) as unknown[];
  return [dataset, path];
}

/** Determine which examples to process based on CLI args. */
export function determine_items(dataset: unknown[], args: Namespace): [number, Dict][] {
  let items: [number, Dict][] = [];

  if (args.ids !== null && args.ids !== undefined) {
    const id_to_item = new Map<unknown, [number, Dict]>();
    dataset.forEach((item, i) => id_to_item.set(pyGet(item, 'id', ''), [i + 1, item as Dict]));
    const not_found: unknown[] = [];
    for (const data_id of args.ids as unknown[]) {
      if (id_to_item.has(data_id)) {
        items.push(id_to_item.get(data_id)!);
      } else {
        not_found.push(data_id);
      }
    }
    if (not_found.length) {
      throw new ValueError(`Data IDs not found in dataset: ${pyRepr(not_found)}`);
    }
  } else if (args.example !== null && args.example !== undefined) {
    const index = args.example - 1;
    if (index < 0 || index >= dataset.length) {
      throw new ValueError(`Invalid example index: ${args.example}. Valid range: 1-${dataset.length}`);
    }
    items = [[args.example, dataset[index] as Dict]];
  } else if (truthy(getattr(args, 'all', false))) {
    items = dataset.map((item, i) => [i + 1, item as Dict]);
  } else {
    if (args.end > dataset.length) {
      throw new ValueError(`--end (${args.end}) exceeds dataset size (${dataset.length})`);
    }
    for (let num = args.start; num <= args.end; num += 1) items.push([num, dataset[num - 1] as Dict]);
  }

  return items;
}

// ── Model ───────────────────────────────────────────────────────────────

/**
 * Initialize LLM model from models.yaml or environment variables.
 *
 * Returns (model, model_name) tuple.
 */
export async function initialize_model(config: AgenticSystemConfig): Promise<[BaseChatModel, string]> {
  const overrides = { max_tokens: 16384 };

  const model_config = ModelConfig.get_default();
  let model: BaseChatModel;
  let resolved_name: string;
  if (truthy(config.model_override)) {
    if (!model_config.has_model(config.model_override!)) {
      const available = model_config.list_models().join(', ');
      throw new ValueError(
        `Unknown model alias ${pyRepr(config.model_override)}. `
        + 'Declare it under models in the active models.yaml or use one '
        + `of: ${available}.`,
      );
    }
    const params = model_config.get_named_model_config(config.model_override!, overrides);
    model = await LLMFactory.create_kw(params);
    resolved_name = config.model_override!;
  } else {
    model = await LLMFactory.create_for_role(config.role, overrides);

    // Resolve actual model name from provider config
    try {
      const roles = model_config.list_roles();
      resolved_name = Object.prototype.hasOwnProperty.call(roles, config.role) ? roles[config.role] : 'unknown';
    } catch {
      resolved_name = 'unknown';
    }
  }

  logger.info(`Model initialized (role=${config.role}, model=${resolved_name})`);
  return [model, resolved_name];
}

/** Initialize the required Router classifier model. */
export async function initialize_router_model(): Promise<BaseChatModel> {
  const model_config = ModelConfig.get_default();
  const roles = model_config.list_roles();
  if (!Object.prototype.hasOwnProperty.call(roles, 'router')) {
    throw new RuntimeError(
      'Router role is required in model settings. Add roles.router to '
      + 'the active settings.yaml instead of relying on the old fast-role fallback.',
    );
  }

  let router_model: BaseChatModel;
  try {
    router_model = await LLMFactory.create_for_role('router');
  } catch (exc) {
    const error = new RuntimeError(
      'Router role is configured but the router model could not be '
      + 'initialized. Fix the router model/provider config.',
    );
    (error as { cause?: unknown }).cause = exc;
    throw error;
  }
  logger.info('Router model initialized (router role)');
  return router_model;
}

/** Return a meaningful dataset diagram_type, or None when routing is needed. */
export function _explicit_diagram_type(item: unknown): string | null {
  let value = isDict(item) ? pyGet(item, 'diagram_type') : null;
  if (!isStr(value)) {
    return null;
  }
  value = pyStrip(value);
  if (!value) {
    return null;
  }
  if (['unknown', 'general', 'auto', 'automatic'].includes((value as string).toLowerCase())) {
    return null;
  }
  return value as string;
}

export function _items_need_router(items: [number, unknown][]): boolean {
  return items.some(([, item]) => _explicit_diagram_type(item) === null);
}

// ── Output ──────────────────────────────────────────────────────────────

/** ``Path(p).parts`` for POSIX paths. */
function _path_parts(path: string): string[] {
  const parts: string[] = [];
  let rest = path;
  if (rest.startsWith('/')) {
    const lead = /^\/+/.exec(rest)![0].length;
    parts.push(lead === 2 ? '//' : '/');
    rest = rest.slice(lead);
  }
  for (const part of rest.split('/')) {
    if (part && part !== '.') parts.push(part);
  }
  return parts;
}

/** ``Path(p).stem`` */
function _path_stem(path: string): string {
  const parts = _path_parts(path);
  const name = parts.length && parts[parts.length - 1] !== '/' && parts[parts.length - 1] !== '//' ? parts[parts.length - 1] : '';
  const dot = name.lastIndexOf('.');
  return dot > 0 && dot < name.length - 1 ? name.slice(0, dot) : name;
}

/**
 * Return whether a dataset path denotes the test/eval split.
 *
 * Use path segments instead of substring matching so names such as
 * ``contest_data.json`` or ``pretest_train.json`` do not accidentally route
 * outputs into the experiment tree.
 */
export function _dataset_path_is_eval(dataset_path: string): boolean {
  const markers = new Set(['test', 'eval']);
  const parts = new Set(_path_parts(dataset_path).map((part) => part.toLowerCase()));
  return [...parts].some((part) => markers.has(part)) || markers.has(_path_stem(dataset_path).toLowerCase());
}

/** Normalize a resolved model name into one filesystem-safe segment. */
export function _safe_model_segment(model_name: string): string {
  const raw = model_name || 'default';
  return safe_path_segment(
    raw.split('/').join('_').split('\\').join('_').split(':').join('_'),
    'model name',
  );
}

/** Return the per-item directory name, honouring ``--tag``. */
export function _item_dir_name(safe_item_id: string, tag: string | null = null): string {
  if (!truthy(tag)) {
    return safe_item_id;
  }
  const safe_tag = safe_path_segment(tag, 'output tag');
  return `${safe_item_id}_${safe_tag}`;
}

/**
 * Determine output directory for an item.
 *
 * Eval mode writes to experiments/{exp_id}/outputs/evodesign/{variant}/{model}/{item_id}/
 * Non-eval mode writes to examples/{model}/{item_id}/ and applies the same
 * ``--tag`` suffix, so ablations across models/tags never overwrite each other.
 */
export function get_output_dir(
  item_id: string,
  dataset_path: string,
  model_name = 'default',
  tag: string | null = null,
  variant = 'evodesign',
): string {
  const is_eval = _dataset_path_is_eval(dataset_path);
  const safe_item_id = safe_path_segment(item_id, 'dataset item id');
  const model_id = _safe_model_segment(model_name);
  const dir_name = _item_dir_name(safe_item_id, tag);
  let output_dir: string;
  if (is_eval) {
    const exp_id = _globals.get_experiment_id();
    const output_root = _globals.get_evodesign_output_dir(variant, model_id, exp_id);
    output_dir = safe_join_under(output_root, dir_name);
  } else {
    output_dir = safe_join_under(_globals.EXAMPLES_DIR, model_id, dir_name);
  }
  mkdirSync(output_dir, { recursive: true });
  return output_dir;
}

/** Return a deterministic safe directory for failures before item dir resolution. */
export function get_output_failure_dir(
  example_num: number,
  dataset_path: string,
  model_name = 'default',
  variant = 'evodesign',
): string {
  const fallback_id = `example_${example_num}_invalid_output_path`;
  try {
    return get_output_dir(fallback_id, dataset_path, model_name, null, variant);
  } catch {
    const output_dir = safe_join_under(_globals.EXAMPLES_DIR, fallback_id);
    mkdirSync(output_dir, { recursive: true });
    return output_dir;
  }
}

// ── Processing ──────────────────────────────────────────────────────────

/** ``type(exc).__name__`` */
function _exc_type_name(exc: unknown): string {
  if (exc instanceof Error) {
    const name = exc.name || exc.constructor?.name || 'Exception';
    return name === 'PyTypeError' ? 'TypeError' : name;
  }
  return 'Exception';
}

/** ``str(exc)`` */
function _exc_str(exc: unknown): string {
  if (exc instanceof KeyError) return pyRepr(exc.message);
  if (exc instanceof Error) return exc.message;
  return pyStr(exc);
}

/**
 * ``traceback.format_exception(type(exc), exc, exc.__traceback__)``.
 *
 * ``raised=False`` is an exception object that was never raised (no
 * traceback): only the final ``module.Qualname: message`` line. A raised TS
 * error lists its JS stack frames in Python's traceback layout.
 */
function _format_exception(exc: unknown, raised: boolean): string[] {
  const name = _exc_type_name(exc);
  const module = (exc as { constructor?: { pythonModule?: string } })?.constructor?.pythonModule;
  const qualified = module && module !== 'builtins' && module !== '__main__' ? `${module}.${name}` : name;
  const message = _exc_str(exc);
  const last = message ? `${qualified}: ${message}\n` : `${qualified}\n`;
  if (!raised) return [last];
  const frames = String((exc as Error)?.stack ?? '')
    .split('\n')
    .slice(1)
    .map((line) => line.trim())
    .filter((line) => line.startsWith('at '))
    .map((line) => `  ${line}\n`);
  return ['Traceback (most recent call last):\n', ...frames, last];
}

/** Persist a per-item failure record for batch debugging. */
export function _write_failure_artifact(
  output_dir: string,
  example_num: number,
  item_id: unknown,
  exc: unknown,
  extra: Dict | null = null,
  raised = true,
): string | null {
  try {
    mkdirSync(output_dir, { recursive: true });
    const failure_path = join(output_dir, 'failure.json');
    const payload: Dict = {
      success: false,
      example_num,
      item_id,
      output_dir,
      error_type: _exc_type_name(exc),
      error: _exc_str(exc),
      traceback: _format_exception(exc, raised),
    };
    if (truthy(extra)) {
      Object.assign(payload, extra);
    }
    writeFileSync(failure_path, pyJsonDumps(withPyFloats(payload), { indent: 2, ensureAscii: false }), 'utf-8');
    return failure_path;
  } catch (write_exc) {
    logger.warning(`Could not write failure artifact for item ${pyStr(item_id)}: ${_exc_str(write_exc)}`);
    return null;
  }
}

export function _state_result_metadata(state: unknown): Dict {
  return {
    image_path: getattr(state, 'final_png_path', null),
    manifest_path: getattr(state, 'final_manifest_path', null),
    verification_status: getattr(state, 'verification_status', null),
    verification_quality_passed: getattr(state, 'verification_quality_passed', null),
    verification_cli_exit_code: getattr(state, 'verification_cli_exit_code', null),
    verification_objective_summary: getattr(state, 'verification_objective_summary', null),
    verification_errors: getattr(state, 'verification_errors', null),
    verification_report_path: getattr(state, 'verification_report_path', null),
    degraded: truthy(getattr(state, 'refiner_degraded', false)),
    refiner_status: getattr(state, 'refiner_status', null),
    user_memory_degraded: truthy(getattr(state, 'user_memory_degraded', false)),
    design_memory_enabled: truthy(getattr(state, 'design_memory_enabled', false)),
    design_memory_degraded: truthy(getattr(state, 'design_memory_degraded', false)),
    design_memory_errors: getattr(state, 'design_memory_errors', null),
    design_memory_retrieved_items: getattr(state, 'design_memory_retrieved_items', null),
  };
}

export function _verification_failure_message(state: unknown): string | null {
  const quality_passed = getattr(state, 'verification_quality_passed', null);
  const status = getattr(state, 'verification_status', null);
  const cli_exit_code = getattr(state, 'verification_cli_exit_code', null);
  const errors = getattr(state, 'verification_errors', null);

  if (quality_passed === false) {
    return 'verification did not pass' + (truthy(status) ? ` (status=${pyStr(status)})` : '');
  }
  if (status === 'failed' || status === 'error') {
    return `verification stage failed (status=${pyStr(status)})`;
  }
  if (isInt(cli_exit_code) && cli_exit_code !== 0) {
    return `verification command failed (exit_code=${cli_exit_code})`;
  }
  if (
    quality_passed === null
    && status === 'reported_with_warnings'
    && cli_exit_code === 0
  ) {
    return null;
  }
  if (truthy(errors) && quality_passed !== true) {
    return 'verification reported errors';
  }
  return null;
}

/** Process a single example through the workflow. */
export async function process_example(
  example_num: number,
  item: Dict,
  model: BaseChatModel,
  config: AgenticSystemConfig,
  output_dir: string,
  router_model: BaseChatModel | null = null,
): Promise<Dict> {
  const item_id = pyGet(item, 'id', `example_${example_num}`);
  const text_content = pyGet(item, 'content', '') as string;
  const user_query = pyGet(item, 'query', '');
  const diagram_type = _explicit_diagram_type(item);
  const content_area = pyGet(item, 'content_area', 'unknown') as string | null;

  logger.info('='.repeat(80));
  logger.info(`Processing example ${example_num} (id: ${pyStr(item_id)})`);
  logger.info(`Diagram Type: ${diagram_type || 'auto'} | Content Area: ${pyStr(content_area)}`);
  if (config.enable_user_memory) {
    logger.info(`User Memory: enabled (user_id: ${config.user_id})`);
  }
  logger.info(
    `Design Memory: ${config.enable_design_memory ? 'enabled' : 'disabled'}${
      config.enable_design_memory && config.design_memory_db_path ? ` (store: ${config.design_memory_db_path})` : ''}`,
  );
  logger.info(`Content: ${[...pyStr(text_content)].slice(0, 200).join('')}${cpLen(pyStr(text_content)) > 200 ? '...' : ''}`);
  logger.info(`Query: ${pyStr(user_query)}`);
  logger.info('='.repeat(80));

  const save_dir = config.save_intermediate ? output_dir : null;

  try {
    const workflow = new Text2DiagramWorkflow(
      model, config,
      undefined, undefined, undefined, undefined, undefined, undefined, undefined,
      undefined, undefined, undefined, undefined, undefined, undefined,
      router_model,
    );
    const state = await workflow.run(
      text_content, user_query,
      undefined,
      save_dir,
      output_dir,
      undefined,
      diagram_type,
      content_area,
    );

    logger.info(`Saved rendered diagram: ${pyStr(state.final_png_path)}`);
    const metadata = _state_result_metadata(state);
    const verification_error = _verification_failure_message(state);
    if (verification_error) {
      const failure_path = _write_failure_artifact(
        output_dir,
        example_num,
        item_id,
        new VerificationQualityError(verification_error),
        metadata,
        false,
      );
      const result: Dict = {
        example_num,
        item_id,
        output_dir,
        ...metadata,
        error: verification_error,
        error_type: 'VerificationQualityError',
        success: false,
      };
      if (failure_path) {
        result.failure_path = failure_path;
      }
      return result;
    }

    return {
      example_num,
      item_id,
      output_dir,
      ...metadata,
      success: true,
    };
  } catch (e) {
    logger.error(`Error processing example ${example_num} (id: ${pyStr(item_id)}): ${_exc_str(e)}`);
    const failure_path = _write_failure_artifact(output_dir, example_num, item_id, e);
    const result: Dict = {
      example_num,
      item_id,
      error: _exc_str(e),
      error_type: _exc_type_name(e),
      success: false,
    };
    if (failure_path) {
      result.failure_path = failure_path;
    }
    return result;
  }
}

/** ``datetime.now().strftime('%Y%m%d_%H%M%S')`` */
function _now_stamp(): string {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}_${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`;
}

/** Python ``ImportError``. */
export class ImportError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ImportError';
  }
}

/**
 * Learn user preferences from manual diagram edits.
 *
 * ``evodesign.user_memory`` is not ported; inject it through
 * ``user_memory_hooks`` (workflow.ts), otherwise this raises the same
 * ``ImportError`` Python raises when the package cannot be imported.
 */
export async function learn_from_user_edit(config: AgenticSystemConfig): Promise<Dict> {
  const session_id = config.session_id || `session_${_now_stamp()}`;

  const factory = user_memory_hooks.UserPreferenceMemorySystem;
  if (factory === null) {
    throw new ImportError(`Failed to import user_preference_memory: ${_USER_MEMORY_IMPORT_ERROR}`);
  }
  const system = factory({ user_id: config.user_id, memory_db_path: config.memory_db_path });
  if (typeof system.learn_from_edit !== 'function') {
    throw new ImportError('Failed to import user_preference_memory: learn_from_edit is not available');
  }

  const task_json = pyJsonLoadsExact(readFileSync(config.task_json!, 'utf-8'));

  logger.info(`User ID: ${config.user_id} | Session: ${session_id}`);
  logger.info(`Task: ${pyStr(config.task_json)}`);

  const result = await system.learn_from_edit({
    task_json,
    model_manifest_path: config.model_manifest,
    model_image_path: config.model_image,
    user_manifest_path: config.user_manifest,
    user_image_path: config.user_image,
    session_id,
  });

  const prefs = result.preferences;
  logger.info(`Extracted: ${pyStr(prefs.extracted)} | Filtered: ${pyStr(prefs.filtered)}`);
  return result;
}

// ── Main ────────────────────────────────────────────────────────────────

export async function main(argv: string[] = process.argv.slice(2)): Promise<number> {
  const args = parse_arguments(argv);
  const config = build_config(args);
  validate_config(config, args);

  if (config.learn_from_edit) {
    await learn_from_user_edit(config);
    return 0;
  }

  const [dataset, dataset_path] = load_dataset(args.dataset_path);
  const items = determine_items(dataset, args);

  logger.info(`Dataset: ${dataset_path} (${dataset.length} items)`);
  if (truthy(args.ids)) {
    logger.info(`Processing IDs: ${pyRepr(args.ids)}`);
  } else {
    logger.info(`Processing examples: ${pyRepr(items.map(([idx]) => idx))}`);
  }

  const [model, model_name] = await initialize_model(config);

  let router_model: BaseChatModel | null = null;
  if (_items_need_router(items)) {
    // Create a cheap model for samples that need Router classification.
    router_model = await initialize_router_model();
  } else {
    logger.info('Skipping Router model initialization; all selected items declare diagram_type.');
  }

  const success_list: Dict[] = [];
  const failure_list: Dict[] = [];
  for (const [example_num, item] of items) {
    const item_id = pyGet(item, 'id', `example_${example_num}`);
    let output_dir: string;
    try {
      output_dir = get_output_dir(
        item_id as string,
        dataset_path,
        model_name,
        config.tag,
        config.variant,
      );
    } catch (e) {
      if (!(e instanceof ValueError)) throw e;
      output_dir = get_output_failure_dir(example_num, dataset_path, model_name, config.variant);
      const failure_path = _write_failure_artifact(output_dir, example_num, item_id, e);
      const result: Dict = {
        example_num,
        item_id,
        output_dir,
        error: _exc_str(e),
        error_type: _exc_type_name(e),
        success: false,
      };
      if (failure_path) {
        result.failure_path = failure_path;
      }
      failure_list.push(result);
      logger.warning('Continuing to next example...');
      continue;
    }
    const item_router_model = _explicit_diagram_type(item) === null ? router_model : null;
    const result = await process_example(example_num, item, model, config, output_dir, item_router_model);

    if (result.success) {
      success_list.push(result);
    } else {
      failure_list.push(result);
      logger.warning('Continuing to next example...');
    }
  }

  if (items.length > 1 || failure_list.length) {
    logger.info('='.repeat(80));
    logger.info(`Summary: ${success_list.length} succeeded, ${failure_list.length} failed`);
    for (const r of failure_list) {
      logger.error(`  Failed: example ${r.example_num} (id: ${pyStr(r.item_id)}): ${[...pyStr(r.error)].slice(0, 80).join('')}`);
    }
    logger.info('='.repeat(80));
  }

  return failure_list.length ? 1 : 0;
}

// ── Recorded-run replay entry (tools/parity-runs.ts) ─────────────────────

export interface RecordedRunInput {
  run: string;
  item: Dict;
  argv: string[];
  env: Record<string, string>;
  [key: string]: unknown;
}

export interface RecordedRunOptions {
  chatModelFactory: ChatModelFactory;
  outputDir: string;
  datasetPath: string;
  argv: string[];
  env: Record<string, string>;
  rendererUrl: string;
}

/** Variables a recorded run must not inherit from the replaying process. */
function _isolated_env_names(): string[] {
  return [
    ...Object.values(_ENV_OVERRIDES),
    'EVO_LLM_RUN_MAX_CALLS',
    'EVO_LLM_RUN_DEADLINE_SECONDS',
  ];
}

/**
 * Run one recorded case the way ``tools/record_runs.py worker()`` does:
 * ``parse_arguments → build_config → validate_config → load_dataset →
 * determine_items → initialize_model / initialize_router_model →
 * process_example(…, outputDir)``, with every chat model created through
 * ``options.chatModelFactory``. The run's environment (``options.env``) is
 * applied for the duration of the call and the configuration singletons are
 * reset first (Python records each run in a fresh process).
 */
export async function runRecordedPipeline(
  _input: RecordedRunInput,
  options: RecordedRunOptions,
): Promise<Dict> {
  const saved = new Map<string, string | undefined>();
  const setVar = (name: string, value: string | undefined) => {
    if (!saved.has(name)) saved.set(name, process.env[name]);
    if (value === undefined) delete process.env[name];
    else process.env[name] = value;
    clearEnv(name);
  };
  for (const name of _isolated_env_names()) {
    if (!Object.prototype.hasOwnProperty.call(options.env, name)) setVar(name, undefined);
  }
  for (const [name, value] of Object.entries(options.env)) setVar(name, value);
  setVar('EXCALIDRAW_RENDER_URL', options.rendererUrl);

  ModelConfig._instance = null;
  ModelConfig._override_path = null;
  AppSettings._instance = null;
  AppSettings._override_path = null;
  set_chat_model_factory(options.chatModelFactory);
  try {
    const args = parse_arguments(options.argv);
    const config = build_config(args);
    validate_config(config, args);
    const [dataset] = load_dataset(args.dataset_path);
    const items = determine_items(dataset, args);
    const [model] = await initialize_model(config);
    const router_model = _items_need_router(items) ? await initialize_router_model() : null;
    if (items.length !== 1) {
      throw new ValueError(`recorded runs process exactly one item; got ${items.length}`);
    }
    const [[example_num, dataset_item]] = items;
    const item_router = _explicit_diagram_type(dataset_item) === null ? router_model : null;
    return await process_example(example_num, dataset_item, model, config, options.outputDir, item_router);
  } finally {
    set_chat_model_factory(null);
    ModelConfig._instance = null;
    AppSettings._instance = null;
    for (const [name, value] of saved) {
      if (value === undefined) delete process.env[name];
      else process.env[name] = value;
    }
  }
}

// ``if __name__ == "__main__": sys.exit(main())``
if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  main().then(
    (code) => process.exit(code),
    (error) => {
      if (error instanceof SystemExit) process.exit(error.code);
      throw error;
    },
  );
}
