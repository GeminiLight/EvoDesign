// Ported from evodesign/agentic_system/generation_stage/unified/transport_journal.py — keep in sync.
// server-only (writes transport evidence files with node:fs)
//
// Record authored native output when a provider stream fails mid-generation.
//
// ``langchain_core.callbacks.BaseCallbackHandler`` → the LangChain.js
// ``BaseCallbackHandler``; ``on_chat_model_start`` / ``on_llm_new_token`` /
// ``on_llm_end`` / ``on_llm_error`` → ``handleChatModelStart`` /
// ``handleLLMNewToken`` / ``handleLLMEnd`` / ``handleLLMError`` (each delegates
// to the Python-named method). Python runs handlers synchronously inside the
// model call, so ``last_output`` is set before the caller's ``except`` runs;
// LangChain.js may run handlers in the background, so this handler sets
// ``awaitHandlers`` (``_awaitHandler: true``) to keep that ordering.

import { mkdirSync, writeFileSync } from '../../py/fs.ts';
import { join } from '../../py/path.ts';
import { BaseCallbackHandler } from '@langchain/core/callbacks/base';
import type { Serialized } from '@langchain/core/load/serializable';
import type { BaseMessage } from '@langchain/core/messages';
import type { LLMResult } from '@langchain/core/outputs';
import { pyJsonDumps } from '../../py/json.ts';
import { getLogger } from '../../py/logging.ts';
import { pyRound } from '../../py/number.ts';
import { cpLen, pyStr } from '../../py/str.ts';
import { isDict, isList, isStr } from '../../py/truthy.ts';

const logger = getLogger('evodesign.agentic_system.generation_stage.unified.transport_journal');

/** ``time.monotonic()`` */
function monotonic(): number {
  return performance.now() / 1000;
}

/** ``f"{x:.1f}"`` */
function fmt1(x: number): string {
  return x.toFixed(1);
}

/** ``f"{type(error).__name__}: {error}"`` */
export function _error_label(error: unknown): string {
  const name = (error as { constructor?: { name?: string } } | null)?.constructor?.name;
  const label = typeof name === 'string' && name && name !== 'Object' ? name : ((error as { name?: string })?.name ?? 'Exception');
  const text = error instanceof Error ? error.message : pyStr(error);
  return `${label}: ${text}`;
}

export function _authored_text(value: unknown): string {
  if (isStr(value)) {
    return value;
  }
  if (isList(value)) {
    return value.map((item) => _authored_text(item)).join('');
  }
  if (isDict(value) && (value.type === 'text' || value.type === 'output_text')) {
    const text = Object.prototype.hasOwnProperty.call(value, 'text') ? value.text : null;
    return isStr(text) ? text : '';
  }
  return '';
}

interface ActiveRun {
  started: number;
  chunks: string[];
}

/** Keep transport evidence separate from scene-validation candidates. */
export class NativeStreamJournal extends BaseCallbackHandler {
  name = 'NativeStreamJournal';
  directory: string | null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  attempts: Record<string, any>[];
  active: Map<string, ActiveRun>;
  last_output: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  continuations: Record<string, any>[];

  constructor() {
    super({ _awaitHandler: true });
    this.directory = null;
    this.attempts = [];
    this.active = new Map();
    this.last_output = '';
    this.continuations = [];
  }

  configure(directory: string | null, new_scene: boolean): void {
    if (new_scene || directory !== this.directory) {
      this.attempts.length = 0;
      this.active.clear();
      this.continuations.length = 0;
      this.last_output = '';
    }
    this.directory = directory;
  }

  // ── Python-named hooks ──────────────────────────────────────────────

  on_chat_model_start(_serialized: unknown, _messages: unknown, run_id: unknown): void {
    this.active.set(pyStr(run_id), { started: monotonic(), chunks: [] });
  }

  on_llm_new_token(token: unknown, run_id: unknown): void {
    const current = this.active.get(pyStr(run_id));
    const text = _authored_text(token);
    if (current === undefined || !text) {
      return;
    }
    if (!current.chunks.length) {
      logger.info('[NativeStream] First authored output after %ss', fmt1(monotonic() - current.started));
    }
    current.chunks.push(text);
  }

  on_llm_end(response: unknown, run_id: unknown): void {
    const current = this.active.get(pyStr(run_id));
    if (current !== undefined && !current.chunks.length) {
      const generations = ((response as { generations?: unknown } | null)?.generations ?? []) as unknown[][];
      if (generations.length && generations[0] && generations[0].length) {
        const text = _authored_text((generations[0][0] as { text?: unknown })?.text ?? '');
        if (text) {
          current.chunks.push(text);
        }
      }
    }
    this._finish(pyStr(run_id), 'complete');
  }

  on_llm_error(error: unknown, run_id: unknown): void {
    this._finish(pyStr(run_id), 'failed', _error_label(error));
  }

  _finish(run_id: string, status: string, error: string | null = null): void {
    const current = this.active.get(run_id);
    this.active.delete(run_id);
    if (current === undefined) {
      return;
    }
    const output = current.chunks.join('');
    this.last_output = output;
    const attempt = this.attempts.length + 1;
    const output_name = `attempt_${String(attempt).padStart(2, '0')}_output.txt`;
    const entry = {
      attempt,
      status,
      elapsed_seconds: pyRound(monotonic() - current.started, 2),
      authored_characters: cpLen(output),
      text_chunks: current.chunks.length,
      output_path: output_name,
      error,
    };
    this.attempts.push(entry);
    if (this.directory !== null) {
      mkdirSync(this.directory, { recursive: true });
      writeFileSync(join(this.directory, output_name), output, 'utf-8');
      writeFileSync(
        join(this.directory, 'transport_attempts.json'),
        pyJsonDumps({ attempts: this.attempts }, { ensureAscii: false, indent: 2 }),
        'utf-8',
      );
    }
    logger.info('[NativeStream] %s after %ss; captured %d authored characters',
      status, fmt1(entry.elapsed_seconds), cpLen(output));
  }

  // ── LangChain.js callback interface ─────────────────────────────────

  override handleChatModelStart(llm: Serialized, messages: BaseMessage[][], runId: string): void {
    this.on_chat_model_start(llm, messages, runId);
  }

  override handleLLMNewToken(token: string, _idx: unknown, runId: string): void {
    this.on_llm_new_token(token, runId);
  }

  override handleLLMEnd(output: LLMResult, runId: string): void {
    this.on_llm_end(output, runId);
  }

  override handleLLMError(err: Error, runId: string): void {
    this.on_llm_error(err, runId);
  }
}

export const __all__ = ['NativeStreamJournal'];
