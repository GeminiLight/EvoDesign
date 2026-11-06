// Browser-platform checks (PHASE3_PLAN.md WP27).
//
//  1. Bundle each orchestration entry with esbuild (platform=browser, so the
//     ``browser`` export condition picks src/py/platform_browser.ts for
//     ``#platform``) and report every Node built-in module the bundle would
//     need (``fs``, ``node:fs``, ``zlib`` …, from our code or a dependency).
//  2. Grep ``src/`` for ``node:*`` imports outside the allowed places:
//     ``src/node/``, ``__main__.ts`` files, and the command-line part of
//     ``src/agentic_system/main.ts`` (its ``node:url`` import for the
//     ``import.meta.url === argv[1]`` check).
//
// Usage: npm run check:browser [-- --entry <path>]...   (exit 1 on any finding)
// Until WP31 adds src/browser.ts the entries are the orchestration modules.

import { readFileSync, readdirSync, statSync } from 'node:fs';
import { builtinModules } from 'node:module';
import { join, relative } from 'node:path';
import * as esbuild from 'esbuild';
import { PACKAGE_ROOT } from '../test/harness/fixtures.ts';

const DEFAULT_ENTRIES = [
  'src/agentic_system/workflow.ts',
  'src/agentic_system/iterative_workflow.ts',
  'src/generation_stage/workflow.ts',
  'src/verification_stage/workflow.ts',
  'src/render_engine/workflow.ts',
  'src/render_engine/service.ts',
];

/** ``node:*`` imports allowed only here (relative to the package root). */
const ALLOWED_NODE_IMPORTS: { file: RegExp; modules?: string[] }[] = [
  { file: /^src\/node\// },
  { file: /(^|\/)__main__\.ts$/ },
  { file: /^src\/agentic_system\/main\.ts$/, modules: ['node:url'] },
];

const argv = process.argv.slice(2);
const entryArgs = argv.flatMap((arg, i) => (arg === '--entry' && argv[i + 1] ? [argv[i + 1]] : []));
const entries = entryArgs.length ? entryArgs : DEFAULT_ENTRIES;

const builtins = new Set(builtinModules.flatMap((name) => [name, `node:${name}`]));
const isBuiltin = (path: string) => path.startsWith('node:') || builtins.has(path) || builtins.has(path.split('/')[0]);

let failures = 0;

for (const entry of entries) {
  const hits = new Map<string, Set<string>>();
  const plugin: esbuild.Plugin = {
    name: 'node-builtins',
    setup(build) {
      build.onResolve({ filter: /.*/ }, (args) => {
        if (!isBuiltin(args.path)) return undefined;
        const importer = relative(PACKAGE_ROOT, args.importer);
        if (!hits.has(args.path)) hits.set(args.path, new Set());
        hits.get(args.path)!.add(importer);
        return { path: args.path, external: true };
      });
    },
  };
  let bytes = 0;
  let errors: string[] = [];
  try {
    const result = await esbuild.build({
      absWorkingDir: PACKAGE_ROOT,
      entryPoints: [entry],
      bundle: true,
      platform: 'browser',
      format: 'esm',
      target: 'es2022',
      write: false,
      logLevel: 'silent',
      plugins: [plugin],
    });
    bytes = result.outputFiles[0]?.contents.length ?? 0;
  } catch (error) {
    errors = ((error as { errors?: esbuild.Message[] }).errors ?? []).map((m) => `${m.text} @ ${m.location?.file ?? '?'}`);
    if (!errors.length) errors = [String(error)];
  }
  const ok = hits.size === 0 && errors.length === 0;
  if (!ok) failures += 1;
  console.log(`${ok ? 'OK  ' : 'FAIL'} ${entry}  node builtins: ${hits.size}${bytes ? `  bundle ${(bytes / 1024).toFixed(0)} KiB` : ''}`);
  for (const [name, importers] of hits) console.log(`       ${name} <- ${[...importers].slice(0, 5).join(', ')}`);
  for (const error of errors.slice(0, 10)) console.log(`       build error: ${error}`);
}

// ── node:* import grep ────────────────────────────────────────────────────
const IMPORT_RE = /(?:^|[\s;])(?:import|export)\b[^'"]*?from\s*['"](node:[^'"]+)['"]|import\(\s*['"](node:[^'"]+)['"]\s*\)|^\s*import\s*['"](node:[^'"]+)['"]/gm;

const walk = (dir: string): string[] => readdirSync(dir).flatMap((name) => {
  const path = join(dir, name);
  return statSync(path).isDirectory() ? walk(path) : path.endsWith('.ts') ? [path] : [];
});

const violations: string[] = [];
for (const file of walk(join(PACKAGE_ROOT, 'src'))) {
  const rel = relative(PACKAGE_ROOT, file);
  const text = readFileSync(file, 'utf-8');
  for (const match of text.matchAll(IMPORT_RE)) {
    const module = match[1] ?? match[2] ?? match[3];
    const allowed = ALLOWED_NODE_IMPORTS.some((rule) => rule.file.test(rel) && (!rule.modules || rule.modules.includes(module)));
    if (!allowed) {
      const line = text.slice(0, match.index).split('\n').length;
      violations.push(`${rel}:${line} ${module}`);
    }
  }
}
console.log(`\nnode:* imports outside the allowed places: ${violations.length}`);
for (const violation of violations) console.log(`  ${violation}`);
if (violations.length) failures += 1;

console.log(failures ? `\n${failures} check(s) failed.` : '\nAll browser-platform checks passed.');
process.exitCode = failures ? 1 : 0;
