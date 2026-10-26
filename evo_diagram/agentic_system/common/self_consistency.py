"""Self-consistency sampling for high-stakes agent decisions.

Single-shot LLM calls for pipeline-critical choices (e.g. `chart_type`)
create a single point of failure: if the model's first sample is off, the
entire downstream pipeline inherits the bad commitment and compounds it.
Self-consistency (Wang et al., 2022) mitigates this by drawing N independent
samples and voting on a small set of discrete keys; for `chart_type`
specifically, N=3 with majority vote removes most single-shot flips with no
change to the rest of the pipeline.

Scope
-----
This module is intentionally narrow:

- Only the **vote_key** field (default ``chart_type``) gets majority vote.
  Other fields (``nodes``, ``edges``, ``groups``, ``specification``) are
  taken verbatim from the first canonical sample matching the majority vote.
  No per-field ensemble is attempted because that would be nonsensical for
  coordinates / ids.
- Defaults are **off** at the caller level. The caller (e.g.
  ``StructureAgent``) reads an env flag and only invokes
  ``sample_and_vote`` when ``N >= 2``. When ``N == 1`` the caller should
  keep its existing single-shot path — do not route through here.
- All N samples run concurrently via a thread pool; if some samples raise
  or return invalid JSON, surviving samples still vote (unless every sample
  failed, which re-raises).

Thread-safety note
------------------
Assumes the ``invoke_fn`` callable is safe to call from multiple threads
simultaneously — which holds for LangChain's ``Runnable`` family (the
underlying httpx client is thread-safe). If you pass a non-reentrant
callable, wrap it with a lock first.
"""

from __future__ import annotations

import logging
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

_Unwrapped = Tuple[Optional[Dict[str, Any]], Any]
MAX_SELF_CONSISTENCY_SAMPLES = 9


def sample_and_vote(
    invoke_fn: Callable[[Dict[str, Any]], Any],
    input_dict: Dict[str, Any],
    n_samples: int = 3,
    vote_key: str = "chart_type",
    unwrap_fn: Optional[Callable[[Any], _Unwrapped]] = None,
) -> _Unwrapped:
    """Draw ``n_samples`` concurrent samples from ``invoke_fn`` and return the
    (specification, instantiation) pair whose instantiation's ``vote_key``
    matches the majority vote.

    Parameters
    ----------
    invoke_fn:
        Callable taking ``input_dict`` and returning a single raw agent
        output (whatever ``BaseAgent.invoke`` returns).
    input_dict:
        Kwargs passed to ``invoke_fn`` for every sample; identical each call
        so sample variation comes from LLM sampling alone.
    n_samples:
        How many parallel samples to draw. Must be >= 1; when 1 this
        function simply unwraps a single call and voting is trivial.
    vote_key:
        Field inside each ``instantiation`` dict whose value is voted on.
        Defaults to ``"chart_type"``, the only key currently wired for
        self-consistency in the Structure stage.
    unwrap_fn:
        Callable that turns a raw agent output into
        ``(specification, instantiation)``. Defaults to the canonical
        ``common.spec_utils.unwrap_agent_output`` (imported lazily so this
        module can be used in test contexts without pulling the full agent
        stack).

    Returns
    -------
    (specification, instantiation):
        From the first surviving sample whose instantiation carries the
        majority value of ``vote_key``. Non-voted fields are **not**
        ensembled across samples — they come from this single winning
        sample only, so coordinates / ids / labels stay internally
        consistent.

    Raises
    ------
    RuntimeError:
        If every sample raised before any canonical output could be unwrapped.
    """
    if n_samples < 1:
        raise ValueError(f"n_samples must be >= 1, got {n_samples}")
    if n_samples > MAX_SELF_CONSISTENCY_SAMPLES:
        raise ValueError(
            f"n_samples must be <= {MAX_SELF_CONSISTENCY_SAMPLES}, got {n_samples}"
        )

    if unwrap_fn is None:
        from evo_diagram.agentic_system.common.spec_utils import unwrap_agent_output
        unwrap_fn = unwrap_agent_output

    samples: list[_Unwrapped] = []

    # Concurrent fan-out. If an individual sample raises, we swallow and move
    # on so majority vote is still meaningful.
    with ThreadPoolExecutor(max_workers=n_samples) as pool:
        futures = [pool.submit(invoke_fn, input_dict) for _ in range(n_samples)]
        for idx, fut in enumerate(futures):
            try:
                raw = fut.result()
                spec, inst = unwrap_fn(raw)
                samples.append((spec, inst))
            except Exception as exc:  # noqa: BLE001 — surface over logs, not crash
                logger.warning(
                    "sample_and_vote: sample %d/%d raised %s: %s",
                    idx + 1, n_samples, type(exc).__name__, exc,
                )

    usable = [
        (spec, inst)
        for spec, inst in samples
        if isinstance(inst, dict) and inst.get(vote_key) is not None
    ]

    if not usable:
        if samples:
            logger.warning(
                "sample_and_vote: no sample carried vote_key=%r; "
                "falling back to first sample (%d samples drew, voteless)",
                vote_key, len(samples),
            )
            return samples[0]
        raise RuntimeError(
            f"sample_and_vote: all {n_samples} samples failed; no usable output."
        )

    votes = Counter(inst[vote_key] for _, inst in usable)
    majority_value, majority_count = votes.most_common(1)[0]
    logger.info(
        "sample_and_vote: vote_key=%r majority=%r (%d/%d) full_tally=%s",
        vote_key, majority_value, majority_count, len(usable), dict(votes),
    )

    # Return the first usable sample agreeing with the majority — preserves
    # internal consistency of non-voted fields (they all come from one run).
    for spec, inst in usable:
        if inst.get(vote_key) == majority_value:
            return spec, inst

    # Defensive fallback — should be unreachable.
    return usable[0]


__all__ = ["sample_and_vote"]
