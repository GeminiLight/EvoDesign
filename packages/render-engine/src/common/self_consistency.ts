// Ported from evodesign/agentic_system/common/self_consistency.py — keep in sync.
//
// Self-consistency sampling for high-stakes agent decisions.
//
// Single-shot LLM calls for pipeline-critical choices (e.g. ``chart_type``)
// create a single point of failure. Self-consistency (Wang et al., 2022) draws
// N independent samples and votes on a small set of discrete keys.
//
// Scope: only the **vote_key** field (default ``chart_type``) gets majority
// vote; other fields are taken verbatim from the first sample matching the
// majority. Defaults are **off** at the caller level (N == 1 keeps the
// single-shot path).
//
// Concurrency: Python fans the N calls out on a thread pool and copies the
// contextvars into each worker; here all N ``invoke_fn`` promises are started
// in order inside the caller's async context (AsyncLocalStorage carries the
// run budget into them) and awaited in order. Per-sample failures are
// swallowed so surviving samples still vote.

import { RuntimeError, ValueError } from '../py/errors.ts';
import { pyEq } from '../py/eq.ts';
import { getLogger } from '../py/logging.ts';
import { pyRepr } from '../py/str.ts';
import { isDict } from '../py/truthy.ts';
import { unwrap_agent_output } from './spec_utils.ts';

const logger = getLogger('evodesign.agentic_system.common.self_consistency');

export type _Unwrapped = [Record<string, unknown> | null, unknown];
export const MAX_SELF_CONSISTENCY_SAMPLES = 9;

/**
 * Draw ``n_samples`` concurrent samples from ``invoke_fn`` and return the
 * (specification, instantiation) pair whose instantiation's ``vote_key``
 * matches the majority vote.
 *
 * @throws RuntimeError if every sample raised before any canonical output could be unwrapped.
 */
export async function sample_and_vote(
  invoke_fn: (input_dict: Record<string, unknown>) => unknown,
  input_dict: Record<string, unknown>,
  n_samples = 3,
  vote_key = 'chart_type',
  unwrap_fn: ((raw: unknown) => _Unwrapped) | null = null,
): Promise<_Unwrapped> {
  if (n_samples < 1) {
    throw new ValueError(`n_samples must be >= 1, got ${n_samples}`);
  }
  if (n_samples > MAX_SELF_CONSISTENCY_SAMPLES) {
    throw new ValueError(`n_samples must be <= ${MAX_SELF_CONSISTENCY_SAMPLES}, got ${n_samples}`);
  }

  const unwrap = unwrap_fn ?? (unwrap_agent_output as unknown as (raw: unknown) => _Unwrapped);

  const samples: _Unwrapped[] = [];

  // Concurrent fan-out. If an individual sample raises, we swallow and move
  // on so majority vote is still meaningful.
  const futures: Promise<unknown>[] = [];
  for (let i = 0; i < n_samples; i += 1) {
    futures.push(Promise.resolve().then(() => invoke_fn(input_dict)));
  }
  // Mark rejections handled up front: they are inspected in order below.
  futures.forEach((future) => future.catch(() => undefined));
  for (let idx = 0; idx < futures.length; idx += 1) {
    try {
      const raw = await futures[idx];
      const [spec, inst] = unwrap(raw);
      samples.push([spec, inst]);
    } catch (exc) {
      logger.warning(
        'sample_and_vote: sample %d/%d raised %s: %s',
        idx + 1, n_samples, (exc as Error)?.name ?? typeof exc, (exc as Error)?.message ?? exc,
      );
    }
  }

  const usable = samples.filter(([, inst]) => isDict(inst) && inst[vote_key] !== undefined && inst[vote_key] !== null);

  if (!usable.length) {
    if (samples.length) {
      logger.warning(
        'sample_and_vote: no sample carried vote_key=%r; falling back to first sample (%d samples drew, voteless)',
        vote_key, samples.length,
      );
      return samples[0];
    }
    throw new RuntimeError(`sample_and_vote: all ${n_samples} samples failed; no usable output.`);
  }

  // Counter(...).most_common(1): highest count, ties → first seen.
  const votes: [unknown, number][] = [];
  for (const [, inst] of usable) {
    const value = (inst as Record<string, unknown>)[vote_key];
    const slot = votes.find(([seen]) => pyEq(seen, value));
    if (slot) slot[1] += 1;
    else votes.push([value, 1]);
  }
  let [majority_value, majority_count] = votes[0];
  for (const [value, count] of votes) {
    if (count > majority_count) {
      majority_value = value;
      majority_count = count;
    }
  }
  logger.info(
    'sample_and_vote: vote_key=%r majority=%r (%d/%d) full_tally=%s',
    vote_key, pyRepr(majority_value), majority_count, usable.length, votes,
  );

  // Return the first usable sample agreeing with the majority — preserves
  // internal consistency of non-voted fields (they all come from one run).
  for (const [spec, inst] of usable) {
    if (pyEq((inst as Record<string, unknown>)[vote_key], majority_value)) {
      return [spec, inst];
    }
  }

  // Defensive fallback — should be unreachable.
  return usable[0];
}

export const __all__ = ['sample_and_vote'];
