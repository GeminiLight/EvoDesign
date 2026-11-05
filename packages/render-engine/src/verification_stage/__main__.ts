// Ported from evodesign/agentic_system/verification_stage/__main__.py — keep in sync.
// server-only (CLI: argv, stdout, file paths)
//
// CLI entry point for the verifier workflow.
//
// Usage (TS):
//     npx tsx src/verification_stage/__main__.ts \
//         --manifest path/to/diagram_manifest.json \
//         --image    path/to/rendered_diagram.png \
//         [--canvas-library excalidraw|tldraw] \
//         [--structure path/to/structure_instantiation.json] \
//         [--layout path/to/layout_instantiation.json] \
//         [--source-text "original input text"] \
//         [--output-dir path] \
//         [--no-critic] \
//         [--markdown]
//
// ``argparse`` is replaced by a small parser for exactly these options
// (``--opt value``, ``--opt=value``, unambiguous prefixes, ``-h/--help``;
// errors print usage to stderr and exit with status 2, like argparse).
// ``main(argv)`` is async and returns the exit code; ``sys.exit(main())``
// runs only when this file is the process entry point.

import { existsSync, realpathSync } from 'node:fs';
import { basename, dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { CanvasEnvironmentConfig } from '../canvas_environment/config.ts';
import { VALID_CANVAS_LIBRARIES, normalize_canvas_library } from '../canvas_runtime.ts';
import { ensure_env_loaded } from '../utils/env_loader.ts';
import { pyFormatFixed, pyStr, pyStrip } from '../py/str.ts';
import { truthy } from '../py/truthy.ts';
import { VerifierWorkflow } from './workflow.ts';

// Ensure .env is loaded before LLM client construction.
try {
  ensure_env_loaded();
} catch {
  // The verifier should still work without the env loader (e.g. when env
  // vars are exported in the shell). Fall through silently.
}

/** Resolve verifier canvas with CLI > settings/env > Excalidraw fallback. */
export function _resolve_canvas_library(explicit_value: string | null): string {
  if (truthy(explicit_value)) {
    return normalize_canvas_library(explicit_value);
  }

  try {
    return CanvasEnvironmentConfig.from_settings().normalized_canvas_library();
  } catch (error) {
    if ((error as Error)?.name === 'FileNotFoundError' || (error as { code?: unknown })?.code === 'ENOENT') {
      return 'excalidraw';
    }
    throw error;
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

export interface VerifierCliArgs {
  manifest: string;
  image: string;
  canvas_library: string | null;
  structure: string | null;
  layout: string | null;
  output_dir: string | null;
  source_text: string | null;
  no_critic: boolean;
  skip_checks: string | null;
  markdown: boolean;
  verbose: boolean;
}

interface OptionSpec {
  flag: string;
  dest: keyof VerifierCliArgs;
  kind: 'value' | 'flag';
  required?: boolean;
  choices?: readonly string[];
  help: string;
}

const PROG = 'evodesign.agentic_system.verification_stage';
const DESCRIPTION = 'Run objective + subjective verification on an EvoDesign render. '
  + 'Objective checks read the manifest JSON. Subjective critique is '
  + 'performed by a remote VLM that receives the PNG via the soxio API.';

const OPTIONS: OptionSpec[] = [
  { flag: '--manifest', dest: 'manifest', kind: 'value', required: true, help: 'Path to diagram_manifest.json (the rendered canvas scene).' },
  { flag: '--image', dest: 'image', kind: 'value', required: true, help: 'Path to rendered_diagram.png (sent to the VLM, never read by Claude).' },
  {
    flag: '--canvas-library', dest: 'canvas_library', kind: 'value', choices: VALID_CANVAS_LIBRARIES,
    help: 'Canvas backend used to validate the manifest schema. Defaults to settings.yaml / CANVAS_LIBRARY.',
  },
  {
    flag: '--structure', dest: 'structure', kind: 'value',
    help: 'Optional path to structure_instantiation.json. Enables chart-type-aware checks (e.g. swimlane lane membership) and feeds chart_type to the VLM.',
  },
  {
    flag: '--layout', dest: 'layout', kind: 'value',
    help: 'Optional path to layout_instantiation.json. Enables layout-aware objective checks without relying on a structure-path-relative fallback.',
  },
  { flag: '--output-dir', dest: 'output_dir', kind: 'value', help: "Where to write verifier_report.json. Defaults to the manifest's parent directory." },
  {
    flag: '--source-text', dest: 'source_text', kind: 'value',
    help: 'Original input text that the diagram was generated from. Passed to the VLM critic for context-aware evaluation.',
  },
  { flag: '--no-critic', dest: 'no_critic', kind: 'flag', help: 'Skip the VLM critic call (only run objective checks).' },
  {
    flag: '--skip-checks', dest: 'skip_checks', kind: 'value',
    help: "Comma-separated list of check categories to skip. Matches against the check function's category prefix. "
      + 'Available: schema, render_audit, layout_audit, binding, containment/group_bbox, containment/swimlane_lane, '
      + 'collision/node_overlap, collision/edge_crossing, collision/out_of_canvas.',
  },
  { flag: '--markdown', dest: 'markdown', kind: 'flag', help: 'Also write a verifier_report.md alongside the JSON report.' },
  { flag: '--verbose', dest: 'verbose', kind: 'flag', help: 'Verbose logging (INFO level).' },
];

const USAGE = `usage: ${PROG} [-h] --manifest MANIFEST --image IMAGE [--canvas-library {${VALID_CANVAS_LIBRARIES.join(',')}}] `
  + '[--structure STRUCTURE] [--layout LAYOUT] [--output-dir OUTPUT_DIR] [--source-text SOURCE_TEXT] '
  + '[--no-critic] [--skip-checks SKIP_CHECKS] [--markdown] [--verbose]';

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

export function _parse_args(argv: string[] | null = null): VerifierCliArgs {
  const args = argv ?? process.argv.slice(2);
  const parsed: VerifierCliArgs = {
    manifest: null as unknown as string,
    image: null as unknown as string,
    canvas_library: null,
    structure: null,
    layout: null,
    output_dir: null,
    source_text: null,
    no_critic: false,
    skip_checks: null,
    markdown: false,
    verbose: false,
  };
  const seen = new Set<string>();
  for (let i = 0; i < args.length; i++) {
    const token = args[i];
    if (token === '-h' || token === '--help') {
      const lines = [USAGE, '', DESCRIPTION, '', 'options:', '  -h, --help            show this help message and exit'];
      for (const option of OPTIONS) lines.push(`  ${option.flag}${option.kind === 'value' ? ` ${option.dest.toUpperCase()}` : ''}\n                        ${option.help}`);
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
      if (option.choices && !option.choices.includes(value)) {
        _parser_error(`argument ${option.flag}: invalid choice: '${value}' (choose from ${option.choices.map((c) => `'${c}'`).join(', ')})`);
      }
      (parsed[option.dest] as string) = value;
    }
    seen.add(option.flag);
  }
  const missing = OPTIONS.filter((option) => option.required && !seen.has(option.flag)).map((option) => option.flag);
  if (missing.length) {
    _parser_error(`the following arguments are required: ${missing.join(', ')}`);
  }
  return parsed;
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

export async function main(argv: string[] | null = null): Promise<number> {
  const args = _parse_args(argv);

  // logging.basicConfig(level=INFO if args.verbose else WARNING): the TS
  // logging shim is a no-op.

  const manifest_path = _resolve_path(args.manifest);
  const image_path = _resolve_path(args.image);
  const structure_path = truthy(args.structure) ? _resolve_path(args.structure!) : null;
  const layout_path = truthy(args.layout) ? _resolve_path(args.layout!) : null;
  const output_dir = truthy(args.output_dir) ? _resolve_path(args.output_dir!) : null;
  const skip_checks = truthy(args.skip_checks)
    ? args.skip_checks!.split(',').map((c) => pyStrip(c)).filter((c) => c)
    : [];
  const canvas_library = _resolve_canvas_library(args.canvas_library);

  const workflow = new VerifierWorkflow();
  const state = await workflow.run(
    manifest_path,
    image_path,
    canvas_library,
    structure_path,
    layout_path,
    args.source_text,
    undefined,
    output_dir,
    args.no_critic,
    skip_checks,
    args.markdown,
  );

  // Console summary (don't dump full report — the JSON is the source of truth).
  const print = (line = '') => process.stdout.write(`${line}\n`);
  print('='.repeat(70));
  print(`Verifier — status: ${state.status}`);
  print(`Manifest: ${manifest_path}`);
  print(`Image:    ${image_path}`);
  if (truthy(state.report_path)) {
    print(`Report:   ${state.report_path}`);
  }
  const summary: Record<string, unknown> = truthy(state.objective_summary) ? state.objective_summary : {};
  print(
    'Objective: '
    + ['critical', 'major', 'minor', 'info', 'total']
      .map((k) => `${k}=${pyStr(summary[k] ?? 0)}`)
      .join(', '),
  );
  if (state.critique !== null && state.critique !== undefined) {
    const c = state.critique;
    print(
      `Subjective: structure=${pyFormatFixed(c.structure.score, 1)} `
      + `styling=${pyFormatFixed(c.styling.score, 1)} `
      + `layout=${pyFormatFixed(c.layout.score, 1)} `
      + `overall=${pyFormatFixed(c.overall_score, 1)}`,
    );
    if (truthy(c.summary)) {
      print(`  Summary: ${c.summary}`);
    }
  } else if (args.no_critic) {
    print('Subjective: (skipped)');
  } else {
    print('Subjective: (failed — see errors)');
  }

  if (truthy(state.errors)) {
    print('\nErrors:');
    for (const err of state.errors) {
      print(`  - ${err}`);
    }
  }

  print('='.repeat(70));
  return state.cli_exit_code;
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
