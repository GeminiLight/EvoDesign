// Ported from evodesign/agentic_system/refinement_stage/__main__.py — keep in sync.
// server-only (CLI: argv, stdout, file paths)
//
// CLI for the iterative refiner.
//
// Usage (TS):
//     npx tsx src/refinement_stage/__main__.ts \
//         --manifest path/to/diagram_manifest.json \
//         --image    path/to/rendered_diagram.png \
//         [--canvas-library excalidraw] \
//         [--structure path/to/structure_instantiation.json] \
//         [--layout path/to/layout_instantiation.json] \
//         [--verifier-report path/to/verifier_report.json] \
//         [--output-dir path] \
//         [--max-iterations 3] \
//         [--no-rerender] \
//         [--markdown] \
//         [--verbose]
//
// ``argparse`` is replaced by a small parser for exactly these options (same
// approach as verification_stage/__main__.ts): ``--opt value``,
// ``--opt=value``, unambiguous prefixes, ``-h/--help``, ``choices``,
// ``type=int``; errors print usage to stderr and raise ``SystemExit(2)``.
// ``main(argv)`` is async (the workflow is) and returns the exit code;
// ``sys.exit(main())`` runs only when this file is the process entry point.
//
// ``IterativeRefinerWorkflow`` lives in ``agentic_system/iterative_workflow``
// (WP23). Python imports it lazily inside ``main``; TS does the same with a
// dynamic import, so this module loads without it.

import { realpathSync } from 'node:fs';
import { existsSync, readFileSync } from '../py/fs.ts';
import { basename, dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { VALID_CANVAS_LIBRARIES, normalize_canvas_library } from '../canvas_runtime.ts';
import { pyGet } from '../py/dict.ts';
import { ValueError } from '../py/errors.ts';
import { pyJsonLoadsExact } from '../py/json_decoder.ts';
import { getLogger } from '../py/logging.ts';
import { pyLower, pyRepr, pyStr } from '../py/str.ts';
import { isDict, truthy } from '../py/truthy.ts';
import { ensure_env_loaded } from '../utils/env_loader.ts';

const logger = getLogger('evodesign.agentic_system.refinement_stage.__main__');
export const SUPPORTED_CLI_CANVAS_LIBRARIES = ['excalidraw'] as const;

export function _load_environment(): boolean {
  try {
    ensure_env_loaded();
    return true;
  } catch (exc) {
    logger.error(`Could not load EvoDesign environment variables: ${(exc as Error)?.message ?? pyStr(exc)}`);
    return false;
  }
}

// ---------------------------------------------------------------- argparse

/** ``SystemExit(code)`` raised by the argument parser. */
export class SystemExit extends Error {
  constructor(readonly code: number) {
    super(`SystemExit: ${code}`);
    this.name = 'SystemExit';
  }
}

/** ``argparse.Namespace`` of this CLI. */
export interface RefinerCliArgs {
  manifest: string;
  image: string;
  canvas_library: string | null;
  structure: string | null;
  layout: string | null;
  verifier_report: string | null;
  output_dir: string | null;
  max_iterations: number;
  no_rerender: boolean;
  markdown: boolean;
  verbose: boolean;
}

interface OptionSpec {
  flag: string;
  dest: keyof RefinerCliArgs;
  kind: 'value' | 'int' | 'flag';
  required?: boolean;
  choices?: readonly string[];
  help: string;
}

const PROG = 'evodesign.agentic_system.refinement_stage';
const DESCRIPTION = 'Verifier-driven Excalidraw diagram refiner. Runs deterministic '
  + 'fixers and a single VLM call per iteration, re-renders the PNG, '
  + 'and loops until findings converge or max_iterations exhausted.';

const OPTIONS: OptionSpec[] = [
  { flag: '--manifest', dest: 'manifest', kind: 'value', required: true, help: 'Path to diagram_manifest.json (the post-arrow Excalidraw scene).' },
  { flag: '--image', dest: 'image', kind: 'value', required: true, help: 'Path to rendered_diagram.png (sent to the VLM, never read by Claude).' },
  {
    flag: '--canvas-library', dest: 'canvas_library', kind: 'value', choices: VALID_CANVAS_LIBRARIES,
    help: 'Canvas manifest type. The iterative refiner currently supports '
      + 'Excalidraw only; TLDraw manifests are rejected at the CLI boundary.',
  },
  { flag: '--structure', dest: 'structure', kind: 'value', help: 'Optional path to structure_instantiation.json. Enables chart-type-aware fixers.' },
  {
    flag: '--layout', dest: 'layout', kind: 'value',
    help: 'Optional path to layout_instantiation.json. When omitted the '
      + 'layout_audit check does NOT run (it needs layout input, and no '
      + 'fixer can synthesise one), and refiner_report.json records it '
      + 'under skipped_objective_checks.',
  },
  {
    flag: '--verifier-report', dest: 'verifier_report', kind: 'value',
    help: 'Path to a pre-existing verifier_report.json (containing the '
      + 'subjective critique). Defaults to <manifest_dir>/verifier_report.json.',
  },
  { flag: '--output-dir', dest: 'output_dir', kind: 'value', help: "Where to write refined manifest / image / report. Defaults to manifest's parent." },
  { flag: '--max-iterations', dest: 'max_iterations', kind: 'int', help: 'Max refinement iterations.' },
  { flag: '--no-rerender', dest: 'no_rerender', kind: 'flag', help: 'Skip PNG re-render between iterations (faster; LLM sees the original image).' },
  { flag: '--markdown', dest: 'markdown', kind: 'flag', help: 'Also write refiner_report.md.' },
  { flag: '--verbose', dest: 'verbose', kind: 'flag', help: 'Verbose logging (INFO level).' },
];

const USAGE = `usage: ${PROG} [-h] --manifest MANIFEST --image IMAGE [--canvas-library {${VALID_CANVAS_LIBRARIES.join(',')}}] `
  + '[--structure STRUCTURE] [--layout LAYOUT] [--verifier-report VERIFIER_REPORT] [--output-dir OUTPUT_DIR] '
  + '[--max-iterations MAX_ITERATIONS] [--no-rerender] [--markdown] [--verbose]';

function _parser_error(message: string): never {
  process.stderr.write(`${USAGE}\n${PROG}: error: ${message}\n`);
  throw new SystemExit(2);
}

function _find_option(flag: string): OptionSpec {
  const exact = OPTIONS.find((option) => option.flag === flag);
  if (exact) return exact;
  // argparse allow_abbrev: a unique prefix selects the option.
  const matches = OPTIONS.filter((option) => option.flag.startsWith(flag));
  if (matches.length === 1) return matches[0];
  if (matches.length > 1) {
    _parser_error(`ambiguous option: ${flag} could match ${matches.map((option) => option.flag).join(', ')}`);
  }
  _parser_error(`unrecognized arguments: ${flag}`);
}

/** ``int(text)`` as argparse ``type=int`` (Python int literal rules for base 10). */
function _parse_int(text: string, flag: string): number {
  if (!/^\s*[-+]?\d+(_\d+)*\s*$/.test(text)) {
    _parser_error(`argument ${flag}: invalid int value: ${pyRepr(text)}`);
  }
  return Number(text.replace(/_/g, '').trim());
}

export function _parse_args(argv: string[] | null = null): RefinerCliArgs {
  const args = argv ?? process.argv.slice(2);
  const parsed: RefinerCliArgs = {
    manifest: null as unknown as string,
    image: null as unknown as string,
    canvas_library: null,
    structure: null,
    layout: null,
    verifier_report: null,
    output_dir: null,
    max_iterations: 3,
    no_rerender: false,
    markdown: false,
    verbose: false,
  };
  const seen = new Set<string>();
  for (let i = 0; i < args.length; i++) {
    const token = args[i];
    if (token === '-h' || token === '--help') {
      const lines = [USAGE, '', DESCRIPTION, '', 'options:', '  -h, --help            show this help message and exit'];
      for (const option of OPTIONS) lines.push(`  ${option.flag}${option.kind !== 'flag' ? ` ${option.dest.toUpperCase()}` : ''}\n                        ${option.help}`);
      process.stdout.write(`${lines.join('\n')}\n`);
      throw new SystemExit(0);
    }
    if (!token.startsWith('--')) {
      _parser_error(`unrecognized arguments: ${token}`);
    }
    const eq = token.indexOf('=');
    const flag = eq >= 0 ? token.slice(0, eq) : token;
    const option = _find_option(flag);
    if (option.kind === 'flag') {
      if (eq >= 0) _parser_error(`argument ${option.flag}: ignored explicit argument '${token.slice(eq + 1)}'`);
      (parsed[option.dest] as boolean) = true;
    } else {
      let value: string;
      if (eq >= 0) {
        value = token.slice(eq + 1);
      } else {
        const next = args[i + 1];
        if (next === undefined || (next.startsWith('-') && next.length > 1 && !/^-\d/.test(next))) {
          _parser_error(`argument ${option.flag}: expected one argument`);
        }
        value = next;
        i += 1;
      }
      if (option.kind === 'int') {
        (parsed[option.dest] as number) = _parse_int(value, option.flag);
      } else {
        if (option.choices && !option.choices.includes(value)) {
          _parser_error(`argument ${option.flag}: invalid choice: '${value}' (choose from ${option.choices.map((c) => `'${c}'`).join(', ')})`);
        }
        (parsed[option.dest] as string) = value;
      }
    }
    seen.add(option.flag);
  }
  const missing = OPTIONS.filter((option) => option.required && !seen.has(option.flag)).map((option) => option.flag);
  if (missing.length) {
    _parser_error(`the following arguments are required: ${missing.join(', ')}`);
  }
  return parsed;
}

// ---------------------------------------------------------------- canvas library

/** Infer obvious canvas manifests without forcing the input to exist. */
export function _infer_canvas_library_from_manifest(manifest_path: string): string {
  if (!existsSync(manifest_path)) {
    return 'excalidraw';
  }
  let data: unknown;
  try {
    data = pyJsonLoadsExact(readFileSync(manifest_path, 'utf-8'));
  } catch (error) {
    // except (OSError, json.JSONDecodeError)
    const isOSError = typeof (error as { code?: unknown })?.code === 'string';
    if (isOSError || (error as Error)?.name === 'JSONDecodeError') {
      return 'excalidraw';
    }
    throw error;
  }
  if (!isDict(data)) {
    return 'excalidraw';
  }

  const type = pyGet(data, 'type');
  const manifest_type = pyLower(truthy(type) ? pyStr(type) : '');
  if (manifest_type.startsWith('excalidraw')) {
    return 'excalidraw';
  }
  if (manifest_type.startsWith('tldraw')) {
    return 'tldraw';
  }
  if ('document' in data || 'store' in data || 'schema' in data) {
    return 'tldraw';
  }
  return 'excalidraw';
}

export function _resolve_canvas_library(args: RefinerCliArgs, manifest_path: string): string {
  const canvas_library = truthy(args.canvas_library)
    ? normalize_canvas_library(args.canvas_library)
    : _infer_canvas_library_from_manifest(manifest_path);
  if (!(SUPPORTED_CLI_CANVAS_LIBRARIES as readonly string[]).includes(canvas_library)) {
    const supported = SUPPORTED_CLI_CANVAS_LIBRARIES.join(', ');
    throw new ValueError(
      'IterativeRefinerWorkflow currently supports Excalidraw manifests '
      + `only; got canvas_library=${pyRepr(canvas_library)}. Supported: ${supported}.`,
    );
  }
  return canvas_library;
}

// ---------------------------------------------------------------- main

/** ``str(Path(p).resolve())`` (non-strict: symlinks resolved on the existing prefix). */
function _resolve_path(path: string): string {
  const absolute = resolve(path);
  let head = absolute;
  const tail: string[] = [];
  while (!existsSync(head)) {
    const parent = dirname(head);
    if (parent === head) return absolute;
    tail.unshift(basename(head));
    head = parent;
  }
  return join(realpathSync(head), ...tail);
}

interface IterativeRefinerWorkflowLike {
  run(...args: unknown[]): Promise<{
    status: string;
    current_iteration: number;
    max_iterations: number;
    converged: boolean;
    termination_reason: string | null;
    skipped_objective_checks: string[];
    refined_manifest_path: string | null;
    refined_image_path: string | null;
    refiner_report_path: string | null;
    iteration_logs: Array<{
      iteration: number;
      findings_before: Record<string, number>;
      findings_after: Record<string, number>;
      deterministic_edits: unknown[];
      llm_edits: unknown[];
      rerender_ok: boolean;
    }>;
    errors: string[];
  }>;
}

/** ``from evodesign.agentic_system.iterative_workflow import IterativeRefinerWorkflow`` (WP23). */
async function _import_iterative_workflow(): Promise<new () => IterativeRefinerWorkflowLike> {
  const mod = (await import(/* @vite-ignore */ new URL('../agentic_system/iterative_workflow.ts', import.meta.url).href)) as {
    IterativeRefinerWorkflow: new () => IterativeRefinerWorkflowLike;
  };
  return mod.IterativeRefinerWorkflow;
}

export async function main(argv: string[] | null = null): Promise<number> {
  const args = _parse_args(argv);

  // logging.basicConfig(level=INFO if args.verbose else WARNING): the TS
  // logging shim is a no-op.
  if (!_load_environment()) {
    return 2;
  }

  const IterativeRefinerWorkflow = await _import_iterative_workflow();

  const manifest_file = _resolve_path(args.manifest);
  let canvas_library: string;
  try {
    canvas_library = _resolve_canvas_library(args, manifest_file);
  } catch (exc) {
    if (!(exc instanceof ValueError)) throw exc;
    logger.error(exc.message);
    process.stderr.write(`Error: ${exc.message}\n`);
    return 2;
  }

  const manifest_path = manifest_file;
  const image_path = _resolve_path(args.image);
  const structure_path = truthy(args.structure) ? _resolve_path(args.structure!) : null;
  const layout_path = truthy(args.layout) ? _resolve_path(args.layout!) : null;
  const verifier_report_path = truthy(args.verifier_report) ? _resolve_path(args.verifier_report!) : null;
  const output_dir = truthy(args.output_dir) ? _resolve_path(args.output_dir!) : null;

  const workflow = new IterativeRefinerWorkflow();
  // run(manifest_path, image_path, *, verifier_report_path, design_constraints,
  //     structure_path, layout_path, output_dir, canvas_library, max_iterations,
  //     skip_rerender_between_iterations, skip_checks, emit_markdown):
  // keyword-only parameters become positional in declaration order.
  const state = await workflow.run(
    manifest_path,
    image_path,
    verifier_report_path,
    undefined, // design_constraints (default "")
    structure_path,
    layout_path,
    output_dir,
    canvas_library,
    args.max_iterations,
    args.no_rerender,
    undefined, // skip_checks (default None)
    args.markdown,
  );

  const print = (line = '') => process.stdout.write(`${line}\n`);
  print('='.repeat(70));
  print(`Verifier-Refiner — status: ${state.status}`);
  print(`Manifest:   ${manifest_path}`);
  print(`Image:      ${image_path}`);
  print(`Iterations: ${pyStr(state.current_iteration)}/${pyStr(state.max_iterations)}`
    + ` (converged=${pyStr(state.converged)})`);
  if (truthy(state.termination_reason)) {
    print(`Termination: ${state.termination_reason}`);
  }
  if (truthy(state.skipped_objective_checks)) {
    print('Objective checks NOT run:');
    for (const skipped of state.skipped_objective_checks) {
      print(`  - ${skipped}`);
    }
  }
  if (truthy(state.refined_manifest_path)) {
    print(`Refined manifest: ${state.refined_manifest_path}`);
  }
  if (truthy(state.refined_image_path)) {
    print(`Refined image:    ${state.refined_image_path}`);
  }
  if (truthy(state.refiner_report_path)) {
    print(`Report:           ${state.refiner_report_path}`);
  }

  if (truthy(state.iteration_logs)) {
    print();
    print('Per-iteration findings (severity counts):');
    for (const log of state.iteration_logs) {
      const before = Object.entries(log.findings_before).map(([k, v]) => `${k}=${pyStr(v)}`).join(', ');
      const after = Object.entries(log.findings_after).map(([k, v]) => `${k}=${pyStr(v)}`).join(', ');
      print(
        `  iter ${pyStr(log.iteration)}: `
        + `det=${log.deterministic_edits.length} `
        + `llm=${log.llm_edits.length} `
        + `render_ok=${pyStr(log.rerender_ok)}`,
      );
      print(`           before: ${before}`);
      print(`           after:  ${after}`);
    }
  }

  if (truthy(state.errors)) {
    print();
    print('Errors:');
    for (const err of state.errors) {
      print(`  - ${err}`);
    }
  }

  print('='.repeat(70));
  return state.status === 'reported' && state.converged ? 0 : 1;
}


// ``if __name__ == "__main__": sys.exit(main())``
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().then(
    (code) => process.exit(code),
    (error) => {
      if (error instanceof SystemExit) process.exit(error.code);
      throw error;
    },
  );
}
