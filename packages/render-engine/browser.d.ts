import type { RuntimeFS } from './dist/fs.js';
import type { BaseChatModel } from '@langchain/core/language_models/chat_models';
export { MemoryFS } from './dist/fs.js';
export type { RuntimeFS, MemoryFSOptions, ReadOnlyProvider } from './dist/fs.js';
export function installBrowserRuntime(): import('./dist/fs.js').MemoryFS;
export interface PngRenderOptions { url: string; viewportWidth: number; viewportHeight: number; timeoutMs: number; exportScale: number; margin: number }
export interface PngRenderRequest { scene: Record<string, unknown>; options: PngRenderOptions; signal?: AbortSignal }
export interface PngRenderResult { png: Uint8Array; width: number; height: number; warnings: string[]; renderer: string }
export interface PngRenderer { readonly name: string; render(request: PngRenderRequest): Promise<PngRenderResult> }
export interface BrowserModel { model: string; baseUrl: string; apiKey: string; reasoningEffort?: 'low' | 'medium' | 'high' }
export interface BrowserRunOptions {
  chatModelFactory?: (params: Record<string, unknown>, role: string | null) => BaseChatModel | Promise<BaseChatModel>;
  onEvent?: (name: string, payload: Record<string, unknown>) => void;
  settings?: Record<string, unknown>;
  engine?: Record<string, unknown>;
  fs?: RuntimeFS;
  env?: Record<string, string>;
  rendererUrl?: string;
  resultsDir?: string;
  requestId?: string;
  renderer?: PngRenderer;
  signal?: AbortSignal;
  fetch?: typeof fetch;
  modelStreaming?: boolean;
}
export type StreamDiagramOptions = Omit<BrowserRunOptions, 'fetch' | 'modelStreaming'>;
export function runBrowserDiagram(request: unknown, model: BrowserModel, options?: BrowserRunOptions): Promise<Record<string, unknown> | null>;
export function streamDiagram(request: unknown, options?: BrowserRunOptions): Promise<Record<string, unknown> | null>;
