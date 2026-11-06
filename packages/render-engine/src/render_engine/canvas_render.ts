// Ported from evodesign/agentic_system/render_engine/canvas_render.py — keep in sync.
// server-only (subprocess / browser rendering, file system)
//
// Unified Canvas Rendering Module.
//
// Python renders by running ``npx tsx tool_services/scripts/render-excalidraw.ts``
// as a subprocess (stdin = scene JSON). The TS port keeps the same command
// line and the same ``subprocess.run`` contract (``CompletedProcess`` with
// return code, stdout, stderr; ``TimeoutExpired``), but when the command is
// the default Excalidraw renderer it runs that script's logic **in process**
// with Node playwright against the same renderer page (``_run_excalidraw_cli``
// is a line-by-line port of render-excalidraw.ts + its renderContract /
// renderDefaults helpers). Any other command (TLDraw, a custom ``runner`` or
// ``script_path``) is spawned exactly like Python does.
//
// Everything that launches the renderer is async (``render``, ``render_canvas``);
// call order is unchanged. ``smart_crop`` (post-process) stays synchronous.

import { latin1Decode, utf8Decode, utf8EncodeLossy } from '../py/bytes.ts';
import { cwd, existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from '../py/fs.ts';
import { dirname, isAbsolute, join, resolve } from '../py/path.ts';
import { getPlatform } from '../py/platform.ts';
import { getPngRenderer } from './png_renderer.ts';
import { normalize_canvas_library } from '../canvas_runtime.ts';
import { getEnv } from '../py/env.ts';
import { PyTypeError, RuntimeError, ValueError } from '../py/errors.ts';
import { pyJsonDumps } from '../py/json.ts';
import { cpLen, cpSlice, floatRepr, pyRepr, pyStrip } from '../py/str.ts';
import { isDict, isList } from '../py/truthy.ts';
import { AGENTIC_SYSTEM_DIR } from '../utils/path_manager.ts';
import { smart_crop as _smart_crop_tool } from './shared/image_cropper.ts';
import { validate_png_file } from './shared/png_validation.ts';

type Dict = Record<string, unknown>;
export type SnapshotDict = Dict;
export type SceneDict = Dict;
export type DataDict = SnapshotDict | SceneDict;

/** ``try: from .shared.image_cropper import smart_crop except ImportError: smart_crop = None`` */
export let smart_crop: { invoke(input: Dict): string } | null = _smart_crop_tool as unknown as { invoke(input: Dict): string };

/** Test hook: replace the module-level ``smart_crop`` (Python tests monkeypatch it). */
export function _set_smart_crop(tool: { invoke(input: Dict): string } | null): void {
  smart_crop = tool;
}

export const DEFAULT_RENDER_TIMEOUT_MS = 60_000;
export const SUBPROCESS_TIMEOUT_GRACE_SECONDS = 5.0;
export const MAX_RENDERER_VIEWPORT_WIDTH = 8_000;
export const MAX_RENDERER_VIEWPORT_HEIGHT = 8_000;
export const MAX_RENDER_TIMEOUT_MS = 300_000;
export const MAX_RENDER_MARGIN = 1_000;
export const MAX_EXCALIDRAW_RENDER_SCALE = 4.0;
export const LOCAL_RENDERER_HOSTS = new Set(['localhost', '127.0.0.1', '::1', '0.0.0.0']);

/** Python's directory of this module (``Path(__file__).resolve().parent``). */
const _MODULE_DIR = join(AGENTIC_SYSTEM_DIR, 'render_engine');

/** ``FileNotFoundError`` */
export class FileNotFoundError extends Error {
  constructor(message = '') {
    super(message);
    this.name = 'FileNotFoundError';
  }
}

/** Python builtin ``TimeoutError``. */
export class PyTimeoutError extends Error {
  constructor(message = '') {
    super(message);
    this.name = 'TimeoutError';
  }
}

/** ``subprocess.CompletedProcess[bytes]`` */
export interface CompletedProcess {
  args: string[];
  returncode: number;
  stdout: Uint8Array | null;
  stderr: Uint8Array | null;
}

/** ``subprocess.TimeoutExpired`` */
export class TimeoutExpired extends Error {
  constructor(public cmd: string[], public timeout: number, public output: Uint8Array | null = null, public stderr: Uint8Array | null = null) {
    super(`Command '${cmd.join(' ')}' timed out after ${timeout} seconds`);
    this.name = 'TimeoutExpired';
  }
}

export function _decode_process_output(value: unknown): string {
  if (value === null || value === undefined) {
    return '';
  }
  if (value instanceof Uint8Array) {
    return utf8Decode(value);
  }
  return String(value);
}

export function _tail(text: string, limit = 1200): string {
  text = pyStrip(text);
  if (cpLen(text) <= limit) {
    return text;
  }
  return cpSlice(text, -limit);
}

export function _subprocess_timeout_seconds(timeout_ms: number | null): number {
  const effective_timeout_ms = timeout_ms !== null && timeout_ms !== undefined ? timeout_ms : DEFAULT_RENDER_TIMEOUT_MS;
  return Math.max(1.0, (Math.trunc(effective_timeout_ms) / 1000.0) + SUBPROCESS_TIMEOUT_GRACE_SECONDS);
}

function _isPyInt(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value);
}

export function _validate_positive_int(name: string, value: number | null, max_value: number | null = null): number | null {
  if (value === null || value === undefined) {
    return null;
  }
  if (typeof value === 'boolean' || !_isPyInt(value)) {
    throw new ValueError(`${name} must be a positive integer; got ${pyRepr(value)}.`);
  }
  if (value <= 0) {
    throw new ValueError(`${name} must be a positive integer; got ${pyRepr(value)}.`);
  }
  if (max_value !== null && max_value !== undefined && value > max_value) {
    throw new ValueError(`${name} must be <= ${max_value}; got ${pyRepr(value)}.`);
  }
  return value;
}

export function _validate_non_negative_int(name: string, value: number | null, max_value: number | null = null): number | null {
  if (value === null || value === undefined) {
    return null;
  }
  if (typeof value === 'boolean' || !_isPyInt(value)) {
    throw new ValueError(`${name} must be a non-negative integer; got ${pyRepr(value)}.`);
  }
  if (value < 0) {
    throw new ValueError(`${name} must be a non-negative integer; got ${pyRepr(value)}.`);
  }
  if (max_value !== null && max_value !== undefined && value > max_value) {
    throw new ValueError(`${name} must be <= ${max_value}; got ${pyRepr(value)}.`);
  }
  return value;
}

export function _validate_positive_number(name: string, value: number | null, max_value: number | null = null): number | null {
  if (value === null || value === undefined) {
    return null;
  }
  if (typeof value === 'boolean' || typeof value !== 'number') {
    throw new ValueError(`${name} must be a positive number; got ${pyRepr(value)}.`);
  }
  const numeric = value;
  if (numeric <= 0 || numeric !== numeric || numeric === Infinity || numeric === -Infinity) {
    throw new ValueError(`${name} must be a positive finite number; got ${pyRepr(value)}.`);
  }
  if (max_value !== null && max_value !== undefined && numeric > max_value) {
    throw new ValueError(`${name} must be <= ${floatRepr(max_value)}; got ${pyRepr(value)}.`);
  }
  return numeric;
}

export function _normalize_pathname(pathname: string): string {
  if (pathname === '/') {
    return pathname;
  }
  return pathname.replace(/\/+$/, '');
}

/** The parts of ``urllib.parse.urlparse(url)`` this module reads. */
export function _urlparse(url: string): { scheme: string; netloc: string; path: string; hostname: string | null } {
  let rest = url;
  let scheme = '';
  const colon = rest.indexOf(':');
  if (colon > 0 && /^[A-Za-z][A-Za-z0-9+\-.]*$/.test(rest.slice(0, colon))) {
    scheme = rest.slice(0, colon).toLowerCase();
    rest = rest.slice(colon + 1);
  }
  let netloc = '';
  if (rest.startsWith('//')) {
    let end = rest.length;
    for (const ch of '/?#') {
      const at = rest.indexOf(ch, 2);
      if (at >= 0) end = Math.min(end, at);
    }
    netloc = rest.slice(2, end);
    rest = rest.slice(end);
  }
  const hash = rest.indexOf('#');
  if (hash >= 0) rest = rest.slice(0, hash);
  const query = rest.indexOf('?');
  if (query >= 0) rest = rest.slice(0, query);
  // urlparse splits ";params" off the last path segment.
  let path = rest;
  const slash = path.lastIndexOf('/');
  const semi = slash >= 0 ? path.indexOf(';', slash) : path.indexOf(';');
  if (semi >= 0) path = path.slice(0, semi);
  // hostname: drop userinfo and port, unwrap "[v6]", lower-case; '' → None
  let hostinfo = netloc.slice(netloc.lastIndexOf('@') + 1);
  let hostname: string;
  if (hostinfo.startsWith('[')) {
    const close = hostinfo.indexOf(']');
    hostname = close >= 0 ? hostinfo.slice(1, close) : hostinfo.slice(1);
  } else {
    const portAt = hostinfo.indexOf(':');
    if (portAt >= 0) hostinfo = hostinfo.slice(0, portAt);
    hostname = hostinfo;
  }
  if (hostname.includes('%')) hostname = hostname.slice(0, hostname.indexOf('%'));
  return { scheme, netloc, path, hostname: hostname ? hostname.toLowerCase() : null };
}

export function _validate_renderer_url(url: string | null, expected_pathname: string): string | null {
  if (url === null || url === undefined) {
    return null;
  }
  const parsed = _urlparse(url);
  if (parsed.scheme !== 'http' && parsed.scheme !== 'https') {
    throw new ValueError('Renderer URL must use http or https.');
  }
  if (parsed.hostname === null || !LOCAL_RENDERER_HOSTS.has(parsed.hostname)) {
    throw new ValueError('Renderer URL must point to a local host.');
  }
  if (_normalize_pathname(parsed.path) !== _normalize_pathname(expected_pathname)) {
    throw new ValueError(`Renderer URL must point to ${expected_pathname}.`);
  }
  return url;
}

export interface RenderOptions {
  viewport_width: number | null;
  viewport_height: number | null;
  timeout_ms: number | null;
  margin: number | null;
  render_scale: number | null;
}

export function _validate_render_options(
  viewport_width: number | null,
  viewport_height: number | null,
  timeout_ms: number | null,
  margin: number | null,
  render_scale: number | null,
): RenderOptions {
  return {
    viewport_width: _validate_positive_int('viewport_width', viewport_width, MAX_RENDERER_VIEWPORT_WIDTH),
    viewport_height: _validate_positive_int('viewport_height', viewport_height, MAX_RENDERER_VIEWPORT_HEIGHT),
    timeout_ms: _validate_positive_int('timeout_ms', timeout_ms, MAX_RENDER_TIMEOUT_MS),
    margin: _validate_non_negative_int('margin', margin, MAX_RENDER_MARGIN),
    render_scale: _validate_positive_number('render_scale', render_scale, MAX_EXCALIDRAW_RENDER_SCALE),
  };
}

/** Fail fast when a renderer reports success without a usable image. */
export function _ensure_rendered_output(output_file: string, completed: CompletedProcess, phase: string): void {
  let validation_error: Error;
  try {
    validate_png_file(output_file, `Render after ${phase}`);
    return;
  } catch (exc) {
    if (!(exc instanceof RuntimeError)) throw exc;
    validation_error = exc;
  }

  const stdout = _tail(_decode_process_output(completed.stdout));
  const stderr = _tail(_decode_process_output(completed.stderr));
  let problem: string;
  if (!existsSync(output_file)) {
    problem = 'did not create output file';
  } else if (statSync(output_file).size <= 0) {
    problem = 'created an empty output file';
  } else {
    problem = 'created an unusable output file';
  }
  throw new RuntimeError(
    `Render ${problem} after ${phase}: ${output_file}; `
    + `stdout_tail=${pyRepr(stdout)}; stderr_tail=${pyRepr(stderr)}; `
    + `validation_error=${validation_error.message}`,
  );
}

// ---------------------------------------------------------------------------
// subprocess.run replacement
// ---------------------------------------------------------------------------

export interface RunOptions {
  input: Uint8Array;
  cwd: string;
  /** seconds */
  timeout: number;
}

/** Spawn ``cmd`` like ``subprocess.run(cmd, input=..., stdout=PIPE, stderr=PIPE, check=False, cwd=..., timeout=...)``. */
async function _spawn(cmd: string[], options: RunOptions): Promise<CompletedProcess> {
  const spawn = getPlatform().spawn;
  if (!spawn) throw new Error(`Cannot run subprocess on this platform: ${cmd.join(' ')}`);
  const result = await spawn(cmd, { input: options.input, cwd: options.cwd, timeoutSeconds: options.timeout });
  if (result.timedOut) throw new TimeoutExpired(cmd, options.timeout, result.stdout, result.stderr);
  return { args: cmd, returncode: result.returncode, stdout: result.stdout, stderr: result.stderr };
}

/**
 * ``subprocess`` stand-in. ``run`` executes the default Excalidraw renderer
 * command in process (``_run_excalidraw_cli``) and spawns anything else.
 * Replaceable for tests (Python tests monkeypatch ``canvas_render.subprocess.run``).
 */
export const subprocess = {
  async run(cmd: string[], options: RunOptions): Promise<CompletedProcess> {
    const inProcess = _in_process_excalidraw_argv(cmd);
    if (inProcess === null) {
      return _spawn(cmd, options);
    }
    let timer: ReturnType<typeof setTimeout> | null = null;
    const stdout: string[] = [];
    const stderr: string[] = [];
    const work = _run_excalidraw_cli(inProcess, utf8Decode(options.input), stdout, stderr);
    const timeout = new Promise<'timeout'>((resolveTimeout) => {
      timer = setTimeout(() => resolveTimeout('timeout'), options.timeout * 1000);
      (timer as { unref?: () => void }).unref?.();
    });
    const winner = await Promise.race([work, timeout]);
    if (timer) clearTimeout(timer);
    if (winner === 'timeout') {
      work.catch(() => {});
      throw new TimeoutExpired(cmd, options.timeout, utf8EncodeLossy(stdout.join('')), utf8EncodeLossy(stderr.join('')));
    }
    return {
      args: cmd,
      returncode: winner,
      stdout: utf8EncodeLossy(stdout.join('')),
      stderr: utf8EncodeLossy(stderr.join('')),
    };
  },
};

/** The CLI arguments when ``cmd`` is ``npx tsx <render-excalidraw.ts> ...`` (the default runner + script). */
function _in_process_excalidraw_argv(cmd: string[]): string[] | null {
  const script = resolve(_MODULE_DIR, '../tool_services/scripts/render-excalidraw.ts');
  if (cmd.length >= 3 && cmd[0] === 'npx' && cmd[1] === 'tsx' && resolve(cmd[2]) === script) {
    return cmd.slice(3);
  }
  return null;
}

// ---------------------------------------------------------------------------
// In-process port of tool_services/scripts/render-excalidraw.ts
// (+ src/lib/renderDefaults.ts, src/lib/renderContract.ts)
// ---------------------------------------------------------------------------

const _CLI_DEFAULT_RENDERER_VIEWPORT = { width: 4000, height: 4000 } as const;
const _CLI_DEFAULT_RENDER_TIMEOUT_MS = 60000;
const _CLI_DEFAULT_RENDER_MARGIN = 40;
const _CLI_DEFAULT_EXCALIDRAW_EXPORT_SCALE = 4;
const _CLI_MAX_RENDERER_VIEWPORT = { width: 8000, height: 8000 } as const;
const _CLI_MAX_RENDER_TIMEOUT_MS = 300000;
const _CLI_MAX_RENDER_MARGIN = 1000;
const _CLI_MAX_EXCALIDRAW_EXPORT_SCALE = 4;
const _CLI_LOCAL_RENDERER_HOSTS = new Set(['localhost', '127.0.0.1', '::1', '[::1]', '0.0.0.0']);
const _CLI_RENDERER_PATH = '/renderers/excalidraw';

interface _CliOptions {
  scenePath: string | null;
  outputPath: string;
  url: string;
  viewportWidth: number;
  viewportHeight: number;
  timeoutMs: number;
  exportScale: number;
  margin: number;
}

function _cli_assert_bounded_number(value: number, field: string, min: number, max: number): number {
  if (!Number.isFinite(value)) {
    throw new Error(`${field} must be a finite number`);
  }
  if (value < min || value > max) {
    throw new Error(`${field} must be between ${min} and ${max}`);
  }
  return value;
}

function _cli_validate_renderer_url(url: string, expectedPathname: string): string {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    throw new Error('Renderer URL is invalid');
  }
  if (!['http:', 'https:'].includes(parsed.protocol)) {
    throw new Error('Renderer URL must use http or https');
  }
  if (!_CLI_LOCAL_RENDERER_HOSTS.has(parsed.hostname)) {
    throw new Error('Renderer URL must point to a local host');
  }
  const normalize = (p: string) => (p === '/' ? p : p.replace(/\/+$/, ''));
  if (normalize(parsed.pathname) !== normalize(expectedPathname)) {
    throw new Error(`Renderer URL must point to ${expectedPathname}`);
  }
  return parsed.toString();
}

function _cli_parse_args(argv: string[]): { options: _CliOptions; helpRequested: boolean } {
  const options: _CliOptions = {
    scenePath: null,
    outputPath: 'excalidraw.png',
    url: getEnv('EXCALIDRAW_RENDER_URL') ?? 'http://localhost:3000/renderers/excalidraw',
    viewportWidth: _CLI_DEFAULT_RENDERER_VIEWPORT.width,
    viewportHeight: _CLI_DEFAULT_RENDERER_VIEWPORT.height,
    timeoutMs: _CLI_DEFAULT_RENDER_TIMEOUT_MS,
    exportScale: Number.parseFloat(getEnv('EXCALIDRAW_EXPORT_SCALE') ?? String(_CLI_DEFAULT_EXCALIDRAW_EXPORT_SCALE)),
    margin: _CLI_DEFAULT_RENDER_MARGIN,
  };
  let helpRequested = false;
  const need = (i: number, flag: string) => {
    const value = argv[i];
    if (!value) throw new Error(`Missing value for ${flag}`);
    return value;
  };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    switch (arg) {
      case '--scene': {
        const value = need(++i, '--scene');
        options.scenePath = value === '-' ? null : value;
        break;
      }
      case '--output':
        options.outputPath = need(++i, '--output');
        break;
      case '--url':
        options.url = need(++i, '--url');
        break;
      case '--width':
        options.viewportWidth = Number.parseInt(need(++i, '--width'), 10);
        break;
      case '--height':
        options.viewportHeight = Number.parseInt(need(++i, '--height'), 10);
        break;
      case '--scale':
        options.exportScale = Number.parseFloat(need(++i, '--scale'));
        break;
      case '--margin':
        options.margin = Number.parseInt(need(++i, '--margin'), 10);
        break;
      case '--timeout':
        options.timeoutMs = Number.parseInt(need(++i, '--timeout'), 10);
        break;
      case '-h':
      case '--help':
        helpRequested = true;
        break;
      default:
        if (arg.startsWith('--')) {
          throw new Error(`Unknown option: ${arg}`);
        }
        if (!options.scenePath) {
          options.scenePath = arg === '-' ? null : arg;
        } else {
          throw new Error(`Unexpected positional argument: ${arg}`);
        }
    }
  }
  return { options, helpRequested };
}

function _cli_validate_options(options: _CliOptions): void {
  options.url = _cli_validate_renderer_url(options.url, _CLI_RENDERER_PATH);
  _cli_assert_bounded_number(options.viewportWidth, 'viewport width', 1, _CLI_MAX_RENDERER_VIEWPORT.width);
  _cli_assert_bounded_number(options.viewportHeight, 'viewport height', 1, _CLI_MAX_RENDERER_VIEWPORT.height);
  _cli_assert_bounded_number(options.timeoutMs, 'timeout', 1, _CLI_MAX_RENDER_TIMEOUT_MS);
  _cli_assert_bounded_number(options.margin, 'margin', 0, _CLI_MAX_RENDER_MARGIN);
  _cli_assert_bounded_number(options.exportScale, 'scale', 0.01, _CLI_MAX_EXCALIDRAW_EXPORT_SCALE);
}

function _cli_normalize_scene(scene: unknown): Dict {
  if (Array.isArray(scene)) {
    return { elements: scene };
  }
  if (scene && typeof scene === 'object') {
    if (!('elements' in (scene as Dict))) {
      throw new Error('Scene JSON must include an "elements" field.');
    }
    return scene as Dict;
  }
  throw new Error('Scene JSON must be a list of elements or an object with "elements".');
}

/**
 * ``render-excalidraw.ts`` page driver. An installed ``PngRenderer``
 * (png_renderer.ts, WP28) takes precedence; otherwise the platform hook
 * renders (playwright under Node, src/node/excalidraw_page.ts).
 */
async function _cli_render(options: _CliOptions, scene: unknown, stderr: string[]): Promise<Uint8Array> {
  const renderer = getPngRenderer();
  if (renderer) {
    const result = await renderer.render({
      scene: _cli_normalize_scene(scene),
      options: {
        url: options.url,
        viewportWidth: options.viewportWidth,
        viewportHeight: options.viewportHeight,
        timeoutMs: options.timeoutMs,
        exportScale: options.exportScale,
        margin: options.margin,
      },
    });
    if (result.warnings.length > 0) {
      stderr.push('[render-excalidraw] Browser console emitted errors:\n');
      for (const entry of result.warnings) stderr.push(`  ${entry}\n`);
    }
    return result.png;
  }
  const render = getPlatform().renderExcalidrawPage;
  if (!render) throw new Error('No in-process Excalidraw renderer on this platform (install one with setPngRenderer).');
  return render(options, scene, _cli_normalize_scene, stderr);
}

/** ``main()`` of render-excalidraw.ts with ``argv``/stdin given; returns the exit code. */
export async function _run_excalidraw_cli(argv: string[], stdinText: string, stdout: string[], stderr: string[]): Promise<number> {
  try {
    const { options, helpRequested } = _cli_parse_args(argv);
    if (helpRequested) {
      stdout.push('Usage: render-excalidraw.ts [options]\n');
      return 0;
    }
    _cli_validate_options(options);
    const scene = options.scenePath === null
      ? JSON.parse(stdinText)
      : JSON.parse(readFileSync(options.scenePath!, 'utf-8'));
    const buffer = await _cli_render(options, scene, stderr);
    if (options.outputPath === '-') {
      stdout.push(latin1Decode(buffer));
      return 0;
    }
    const parent = dirname(options.outputPath);
    if (parent && parent !== '.') {
      mkdirSync(parent, { recursive: true });
    }
    writeFileSync(options.outputPath, buffer);
    return 0;
  } catch (error) {
    if (error instanceof Error) {
      stderr.push(`[render-excalidraw] ${error.message}\n`);
    } else {
      stderr.push(`[render-excalidraw] Unexpected error. ${String(error)}\n`);
    }
    return 1;
  }
}

// ---------------------------------------------------------------------------
// Renderers
// ---------------------------------------------------------------------------

/** Abstract base class for Canvas renders (Tldraw, Excalidraw, etc.). */
export abstract class CanvasRenderBase {
  script_path: string;
  default_runner: string[];
  renderer_path: string;

  constructor(script_path: string, default_runner: string[] | null = null, renderer_path = '') {
    this.script_path = script_path;
    this.default_runner = default_runner && default_runner.length ? default_runner : ['npx', 'tsx'];
    this.renderer_path = renderer_path;
  }

  _resolve_script_path(override_path: string | null, working_dir: string | null): string {
    const script_target = override_path || this.script_path;
    const base_dir = working_dir ? resolve(working_dir) : _MODULE_DIR;
    let candidate = script_target;
    if (!isAbsolute(candidate)) {
      candidate = resolve(base_dir, candidate);
    }

    // With a PngRenderer installed the default Excalidraw script runs in
    // process, so it need not exist on the (possibly in-memory) file system.
    if (!existsSync(candidate) && !(getPngRenderer() && _in_process_excalidraw_argv([...this.default_runner, candidate]) !== null)) {
      throw new FileNotFoundError(`Renderer script not found at: ${candidate}`);
    }

    return candidate;
  }

  /**
   * Render ``data`` to a PNG at ``output_path``.
   *
   * ``render_scale`` sets the renderer export scale in image pixels per
   * manifest unit (Excalidraw only; TLDraw rejects it). ``crop=False``
   * skips the post-render smart crop and keeps the renderer's full
   * exported canvas. ``render_scale=1.0`` together with ``crop=False``
   * is the **analysis render** mode used for VLM refinement/verification
   * input. The defaults reproduce the historical product render exactly.
   */
  async render(
    data: DataDict,
    output_path = 'output.png',
    script_path: string | null = null,
    runner: string[] | null = null,
    url: string | null = null,
    viewport_width: number | null = null,
    viewport_height: number | null = null,
    timeout_ms: number | null = null,
    margin: number | null = null,
    render_scale: number | null = null,
    crop = true,
    working_dir: string | null = null,
    ensure_ascii = false,
    capture_output = false,
  ): Promise<Record<string, string>> {
    this._validate_data(data);
    const options = _validate_render_options(viewport_width, viewport_height, timeout_ms, margin, render_scale);
    viewport_width = options.viewport_width;
    viewport_height = options.viewport_height;
    timeout_ms = options.timeout_ms;
    margin = options.margin;
    render_scale = options.render_scale;
    url = this.renderer_path ? _validate_renderer_url(url, this.renderer_path) : url;

    // Path Resolution
    const script = this._resolve_script_path(script_path, working_dir);
    const workdir = working_dir ? resolve(working_dir) : dirname(dirname(script));

    let output_file = output_path;
    if (!isAbsolute(output_file)) {
      output_file = join(cwd(), output_file);
    }
    mkdirSync(dirname(output_file), { recursive: true });

    // CLI Build
    let cmd = [...(runner && runner.length ? runner : this.default_runner), script];
    cmd = this._append_cli_args(cmd, output_file, url, viewport_width, viewport_height, timeout_ms, margin, render_scale);

    // Execution
    const payload = pyJsonDumps(data, { ensureAscii: ensure_ascii });
    const python_timeout = _subprocess_timeout_seconds(timeout_ms);
    let completed: CompletedProcess;
    try {
      completed = await subprocess.run(cmd, { input: utf8EncodeLossy(payload), cwd: workdir, timeout: python_timeout });
    } catch (exc) {
      if (!(exc instanceof TimeoutExpired)) throw exc;
      const stdout = _tail(_decode_process_output(exc.output));
      const stderr = _tail(_decode_process_output(exc.stderr));
      throw new PyTimeoutError(
        'Render subprocess timed out '
        + `after ${python_timeout.toFixed(1)}s; cwd=${workdir}; `
        + `command=${cmd.join(' ')}; stdout_tail=${pyRepr(stdout)}; `
        + `stderr_tail=${pyRepr(stderr)}`,
      );
    }

    if (completed.returncode !== 0) {
      const stderr = pyStrip(_decode_process_output(completed.stderr));
      throw new RuntimeError(`Render failed (code ${completed.returncode}): ${stderr}`);
    }

    _ensure_rendered_output(output_file, completed, 'subprocess');

    const result: Record<string, string> = { output_path: output_file };
    if (capture_output) {
      result.stdout = _decode_process_output(completed.stdout);
      result.stderr = _decode_process_output(completed.stderr);
    }

    if (crop) {
      this._post_process(output_file);
    }
    _ensure_rendered_output(output_file, completed, 'post-process');

    return result;
  }

  /** Validate input data structure. */
  abstract _validate_data(data: DataDict): void;

  /** Append renderer-specific CLI arguments. */
  abstract _append_cli_args(
    base_cmd: string[],
    output_file: string,
    url: string | null,
    width: number | null,
    height: number | null,
    timeout: number | null,
    margin: number | null,
    render_scale: number | null,
  ): string[];

  /**
   * Optional post-processing (e.g. smart crop).
   *
   * Skipped entirely when ``render()`` is called with ``crop=False``.
   */
  _post_process(_output_file: string): void {}
}

/** ``str(int(x))`` */
function _int_str(value: number): string {
  return String(Math.trunc(value));
}

export class TldrawRender extends CanvasRenderBase {
  constructor() {
    super('../tool_services/scripts/render-tldraw.ts', null, '/renderers/tldraw');
  }

  _validate_data(data: DataDict): void {
    if (!isDict(data) || !('document' in data)) {
      throw new ValueError("Tldraw manifest must include a top-level 'document' key.");
    }
  }

  _append_cli_args(cmd: string[], output_file: string, url: string | null, width: number | null, height: number | null, timeout: number | null, margin: number | null, render_scale: number | null): string[] {
    if (render_scale !== null && render_scale !== undefined) {
      throw new ValueError('render_scale is not supported by the TLDraw renderer.');
    }
    cmd.push('--snapshot', '-', '--output', output_file);
    if (url) {
      cmd.push('--url', url);
    }
    if (width !== null && width !== undefined) {
      cmd.push('--width', _int_str(width));
    }
    if (height !== null && height !== undefined) {
      cmd.push('--height', _int_str(height));
    }
    if (timeout !== null && timeout !== undefined) {
      cmd.push('--timeout', _int_str(timeout));
    }
    if (margin !== null && margin !== undefined) {
      cmd.push('--margin', _int_str(margin));
    }
    return cmd;
  }

  override _post_process(output_file: string): void {
    if (smart_crop) {
      smart_crop.invoke({
        image_path: output_file,
        output_path: output_file,
        padding: 0,
        canvas_engine: 'tldraw',
      });
    }
  }
}

export class ExcalidrawRender extends CanvasRenderBase {
  constructor() {
    super('../tool_services/scripts/render-excalidraw.ts', null, '/renderers/excalidraw');
  }

  override async render(data: DataDict, ...args: Parameters<CanvasRenderBase['render']> extends [unknown, ...infer R] ? R : never): Promise<Record<string, string>> {
    // Strip _meta for Excalidraw to match previous behavior and avoid potential renderer issues
    if (isDict(data) && '_meta' in data) {
      // Shallow copy to avoid mutating original state
      data = Object.fromEntries(Object.entries(data).filter(([k]) => k !== '_meta'));
    }
    return super.render(data, ...args);
  }

  _validate_data(data: DataDict): void {
    if (!isDict(data) || !('elements' in data) || !isList(data.elements ?? null)) {
      throw new ValueError("Excalidraw manifest must include an 'elements' list.");
    }
  }

  _append_cli_args(cmd: string[], output_file: string, url: string | null, width: number | null, height: number | null, timeout: number | null, margin: number | null, render_scale: number | null): string[] {
    cmd.push('--scene', '-', '--output', output_file);
    if (url) {
      cmd.push('--url', url);
    }
    if (width !== null && width !== undefined) {
      cmd.push('--width', _int_str(width));
    }
    if (height !== null && height !== undefined) {
      cmd.push('--height', _int_str(height));
    }
    if (timeout !== null && timeout !== undefined) {
      cmd.push('--timeout', _int_str(timeout));
    }
    if (margin !== null && margin !== undefined) {
      cmd.push('--margin', _int_str(margin));
    }
    if (render_scale !== null && render_scale !== undefined) {
      cmd.push('--scale', floatRepr(render_scale));
    }
    return cmd;
  }

  /** Apply smart crop to remove white space and watermarks from Excalidraw renders. */
  override _post_process(output_file: string): void {
    if (smart_crop) {
      smart_crop.invoke({
        image_path: output_file,
        output_path: output_file,
        padding: 60,
        canvas_engine: 'excalidraw',
      });
    }
  }
}

export function get_renderer(canvas_library: string): CanvasRenderBase {
  canvas_library = normalize_canvas_library(canvas_library);
  if (canvas_library === 'tldraw') {
    return new TldrawRender();
  } else if (canvas_library === 'excalidraw') {
    return new ExcalidrawRender();
  } else {
    throw new ValueError(`Unknown canvas library: ${canvas_library}`);
  }
}

/** Keyword arguments ``render_canvas(**kwargs)`` forwards to ``CanvasRenderBase.render``. */
export interface RenderKwargs {
  script_path?: string | null;
  runner?: string[] | null;
  url?: string | null;
  viewport_width?: number | null;
  viewport_height?: number | null;
  timeout_ms?: number | null;
  margin?: number | null;
  render_scale?: number | null;
  crop?: boolean;
  working_dir?: string | null;
  ensure_ascii?: boolean;
  capture_output?: boolean;
}

const _RENDER_KWARGS = [
  'script_path', 'runner', 'url', 'viewport_width', 'viewport_height', 'timeout_ms',
  'margin', 'render_scale', 'crop', 'working_dir', 'ensure_ascii', 'capture_output',
] as const;

/** Unified entry point for rendering diagram data. */
export async function render_canvas(
  data: Dict | unknown[],
  output_path = 'output.png',
  canvas_library = 'excalidraw',
  kwargs: RenderKwargs = {},
): Promise<Record<string, string>> {
  canvas_library = normalize_canvas_library(canvas_library);

  // Pre-normalization for Excalidraw lists
  if (canvas_library === 'excalidraw' && Array.isArray(data)) {
    data = { elements: data };
  }

  const renderer = get_renderer(canvas_library);
  for (const key of Object.keys(kwargs)) {
    if (!(_RENDER_KWARGS as readonly string[]).includes(key)) {
      throw new PyTypeError(`render() got an unexpected keyword argument '${key}'`);
    }
  }
  const kw = kwargs as Record<string, unknown>;
  const arg = <T>(key: string): T => (kw[key] === undefined ? undefined : kw[key]) as T;
  return renderer.render(
    data as DataDict,
    output_path,
    arg('script_path'),
    arg('runner'),
    arg('url'),
    arg('viewport_width'),
    arg('viewport_height'),
    arg('timeout_ms'),
    arg('margin'),
    arg('render_scale'),
    arg('crop'),
    arg('working_dir'),
    arg('ensure_ascii'),
    arg('capture_output'),
  );
}
