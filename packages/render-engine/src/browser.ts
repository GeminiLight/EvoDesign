/** Browser-safe bootstrap. Install resources before importing modules which
 * load palettes and diagram types at module evaluation time. */
import { MemoryFS, setFS } from './py/fs.ts';
import { AGENTIC_SYSTEM_ROOT, setAssetProvider } from './py/assets.ts';
import { files } from './generated/browser_assets.ts';
import { getPlatform } from './py/platform.ts';
import { createOpenAIChatModel } from './models/openai_chat.ts';
import type { StreamDiagramOptions } from './web_runtime/index.ts';
export type { StreamDiagramOptions } from './web_runtime/index.ts';
export { MemoryFS } from './py/fs.ts';
export type { PngRenderer, PngRenderRequest, PngRenderResult } from './render_engine/png_renderer.ts';

export function installBrowserRuntime(): MemoryFS {
  const fs = new MemoryFS();
  const prefix = 'evodesign/agentic_system/';
  const data = new Map(Object.entries(files).filter(([path]) => path.startsWith(prefix)).map(([path, text]) => [path.slice(prefix.length), text]));
  const dirs = new Map<string, Set<string>>([['', new Set()]]);
  for (const path of data.keys()) {
    const parts = path.split('/');
    for (let i = 0; i < parts.length; i++) {
      const parent = parts.slice(0, i).join('/');
      if (!dirs.has(parent)) dirs.set(parent, new Set());
      dirs.get(parent)!.add(parts[i]);
    }
  }
  const provider = {
    readText(path: string) { if (!data.has(path)) throw new Error(`Missing bundled resource: ${path}`); return data.get(path)!; },
    exists: (path: string) => data.has(path) || dirs.has(path),
    isDir: (path: string) => dirs.has(path),
    list: (path: string) => [...(dirs.get(path) ?? [])].sort(),
  };
  setAssetProvider(provider);
  fs.mount(AGENTIC_SYSTEM_ROOT, provider);
  // Only packaged, credential-free defaults; user model settings come from the caller.
  for (const [path, text] of Object.entries(files)) {
    if (!path.startsWith('evodesign/config/defaults/')) continue;
    const target = `${getPlatform().repoRoot}/${path}`;
    fs.mkdirp(target.slice(0, target.lastIndexOf('/')));
    fs.writeText(target, text);
  }
  setFS(fs);
  return fs;
}

export async function streamDiagram(request: unknown, options: StreamDiagramOptions = {}) {
  if (!options.fs) options = { ...options, fs: installBrowserRuntime() };
  const runtime = await import('./web_runtime/index.ts');
  return runtime.streamDiagram(request, options);
}

export interface BrowserModel {
  model: string;
  baseUrl: string;
  apiKey: string;
  reasoningEffort?: 'low' | 'medium' | 'high';
}

export async function runBrowserDiagram(request: unknown, config: BrowserModel,
  options: StreamDiagramOptions & { fetch?: typeof fetch; modelStreaming?: boolean } = {}) {
  const env = { LLM_MODEL_NAME: config.model, LLM_ENDPOINT_URL: config.baseUrl, LLM_API_KEY: config.apiKey || 'browser-local', ...options.env };
  const settings = { llm_model_name: config.model, llm_api_key: config.apiKey || 'browser-local',
    llm_endpoint_url: config.baseUrl, llm_reasoning_effort: config.reasoningEffort ?? null,
    ...options.settings };
  return streamDiagram(request, { ...options, settings, env,
    chatModelFactory: options.chatModelFactory ?? ((params) => createOpenAIChatModel({ ...params, ...(options.modelStreaming === undefined ? {} : { streaming: options.modelStreaming }) }, {
      browser: true, fetch: async (input, init) => {
        options.signal?.throwIfAborted();
        const signals = [init?.signal, options.signal].filter(Boolean) as AbortSignal[];
        return (options.fetch ?? fetch)(input, { ...init,
          signal: signals.length ? AbortSignal.any(signals) : undefined,
          credentials: 'omit', redirect: 'error', referrerPolicy: 'no-referrer' });
      },
    })),
  });
}
