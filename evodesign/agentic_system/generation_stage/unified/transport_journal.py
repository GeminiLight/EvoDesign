"""Record authored native output when a provider stream fails mid-generation."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from time import monotonic
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler

logger = logging.getLogger(__name__)


def _authored_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(_authored_text(item) for item in value)
    if isinstance(value, dict) and value.get("type") in {"text", "output_text"}:
        text = value.get("text")
        return text if isinstance(text, str) else ""
    return ""


class NativeStreamJournal(BaseCallbackHandler):
    """Keep transport evidence separate from scene-validation candidates."""

    def __init__(self) -> None:
        self.directory: Path | None = None
        self.attempts: list[dict[str, Any]] = []
        self.active: dict[str, dict[str, Any]] = {}
        self.last_output = ""
        self.continuations: list[dict[str, Any]] = []

    def configure(self, directory: Path | None, *, new_scene: bool) -> None:
        if new_scene or directory != self.directory:
            self.attempts.clear()
            self.active.clear()
            self.continuations.clear()
            self.last_output = ""
        self.directory = directory

    def on_chat_model_start(self, serialized: dict, messages: list, *, run_id: Any, **kwargs: Any) -> None:
        self.active[str(run_id)] = {"started": monotonic(), "chunks": []}

    def on_llm_new_token(self, token: Any, *, run_id: Any, **kwargs: Any) -> None:
        current = self.active.get(str(run_id))
        text = _authored_text(token)
        if current is None or not text:
            return
        if not current["chunks"]:
            logger.info("[NativeStream] First authored output after %.1fs", monotonic() - current["started"])
        current["chunks"].append(text)

    def on_llm_end(self, response: Any, *, run_id: Any, **kwargs: Any) -> None:
        current = self.active.get(str(run_id))
        if current is not None and not current["chunks"]:
            generations = getattr(response, "generations", [])
            if generations and generations[0]:
                text = _authored_text(getattr(generations[0][0], "text", ""))
                if text:
                    current["chunks"].append(text)
        self._finish(str(run_id), "complete")

    def on_llm_error(self, error: BaseException, *, run_id: Any, **kwargs: Any) -> None:
        self._finish(str(run_id), "failed", f"{type(error).__name__}: {error}")

    def _finish(self, run_id: str, status: str, error: str | None = None) -> None:
        current = self.active.pop(run_id, None)
        if current is None:
            return
        output = "".join(current["chunks"])
        self.last_output = output
        attempt = len(self.attempts) + 1
        output_name = f"attempt_{attempt:02d}_output.txt"
        entry = {
            "attempt": attempt,
            "status": status,
            "elapsed_seconds": round(monotonic() - current["started"], 2),
            "authored_characters": len(output),
            "text_chunks": len(current["chunks"]),
            "output_path": output_name,
            "error": error,
        }
        self.attempts.append(entry)
        if self.directory is not None:
            self.directory.mkdir(parents=True, exist_ok=True)
            (self.directory / output_name).write_text(output, encoding="utf-8")
            (self.directory / "transport_attempts.json").write_text(
                json.dumps({"attempts": self.attempts}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        logger.info("[NativeStream] %s after %.1fs; captured %d authored characters",
                    status, entry["elapsed_seconds"], len(output))
