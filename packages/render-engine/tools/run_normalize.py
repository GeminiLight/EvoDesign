"""Normalization rules for end-to-end run fixtures (fixtures/runs/<run>/).

A recorded run must be byte-identical when recorded twice, and the TS replay
compares against the same normalized form, so every value that legitimately
changes between two executions is rewritten by these rules — and nothing else.
The TS side (tools/parity-runs.ts) imports the same rules from
``run_normalize.json`` (written next to this file by ``write_rules()``).

Rules, applied to every string (JSON values, JSON object keys are left alone,
text artifacts line by line) in this order:

1. ``<OUT>``  the run's output directory (and its realpath) — the pipeline is
   pointed at a fresh temporary directory per execution.
2. ``<REPO>`` the repository root.
3. ``<TMP>``  the system temp directory (``tempfile.gettempdir()`` and its
   realpath, ``/tmp``); random ``tempfile`` suffixes after the known prefixes
   ``evodesign_``, ``evodesign-render-`` and ``tmp`` become ``XXXXXXXX``.
4. ``<TIMESTAMP>`` ISO-8601 timestamps (``2026-11-04T10:00:00Z``,
   with optional fraction and offset).
5. ``<UUID>`` RFC-4122 UUIDs (langchain message/run ids).

Rules applied to JSON object members by key (whatever the nesting):

6. ``duration_ms`` → 0, ``elapsed_seconds`` → 0 (wall-clock durations).

Binary artifacts (PNG) are not rewritten; they are compared by sha256 and, when
the bytes differ, by decoded RGBA pixels (see PHASE2_PLAN.md appendix).
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import tempfile
from typing import Any, List, Tuple

REPO = pathlib.Path(__file__).resolve().parents[3]

TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?")
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
TEMP_SUFFIX_RE = re.compile(r"(<TMP>/(?:evodesign_|evodesign-render-|tmp))[A-Za-z0-9_]{8}")
VOLATILE_KEYS = {"duration_ms": 0, "elapsed_seconds": 0}


class Normalizer:
    def __init__(self, out_dir: str | os.PathLike[str]) -> None:
        pairs: List[Tuple[str, str]] = []

        def add(path: str, token: str) -> None:
            for variant in {str(path).rstrip("/"), os.path.realpath(str(path)).rstrip("/")}:
                if variant and (variant, token) not in pairs:
                    pairs.append((variant, token))

        add(str(out_dir), "<OUT>")
        add(str(REPO), "<REPO>")
        add(tempfile.gettempdir(), "<TMP>")
        add("/tmp", "<TMP>")
        # Longest first so a nested path wins over its parent.
        self.pairs = sorted(pairs, key=lambda item: -len(item[0]))

    def text(self, value: str) -> str:
        for path, token in self.pairs:
            if path in value:
                value = value.replace(path, token)
        value = TEMP_SUFFIX_RE.sub(r"\1XXXXXXXX", value)
        value = TIMESTAMP_RE.sub("<TIMESTAMP>", value)
        value = UUID_RE.sub("<UUID>", value)
        return value

    def value(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, list):
            return [self.value(item) for item in value]
        if isinstance(value, dict):
            return {
                key: (VOLATILE_KEYS[key] if key in VOLATILE_KEYS and isinstance(item, (int, float)) and not isinstance(item, bool)
                      else self.value(item))
                for key, item in value.items()
            }
        return value


def rules() -> dict:
    """Machine-readable rules for the TS side."""
    return {
        "tokens": ["<OUT>", "<REPO>", "<TMP>"],
        "temp_suffix": TEMP_SUFFIX_RE.pattern,
        "timestamp": TIMESTAMP_RE.pattern,
        "uuid": UUID_RE.pattern,
        "volatile_keys": VOLATILE_KEYS,
    }


def write_rules(path: pathlib.Path) -> None:
    path.write_text(json.dumps(rules(), indent=1) + "\n", encoding="utf-8")
