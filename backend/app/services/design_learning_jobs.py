"""Private, durable post-delivery learning jobs, without another service.

Jobs contain no credentials. File locks prevent duplicate workers; completed
jobs also serve as the status record when an older snapshot is reopened.
"""
from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import time
from typing import Any
from weakref import WeakKeyDictionary

from loguru import logger

_TASKS: set[asyncio.Task] = set()
_ACTIVE: set[str] = set()
_LIMITS: WeakKeyDictionary = WeakKeyDictionary()


def _write(path: Path, value: Any) -> None:
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as output:
        os.chmod(temporary, 0o600)
        json.dump(value, output, ensure_ascii=False)
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(path)


def private_memory_path(root: str, user_id: str) -> Path:
    return Path(root) / hashlib.sha256(user_id.encode()).hexdigest()[:24]


def read_status(memory_path: str | Path, job_id: str) -> dict[str, Any] | None:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", job_id):
        return None
    path = Path(memory_path) / ".learning" / job_id / "status.json"
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _execute(directory: Path, *, model: Any = None, retriever: Any = None,
             learner: Any = None) -> None:
    with (directory / "worker.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        status = json.loads((directory / "status.json").read_text())
        if status["status"] not in {"queued", "running"}:
            return
        job = json.loads((directory / "job.json").read_text())
        started = time.monotonic()
        _write(directory / "status.json", {**status, "status": "running"})
        try:
            if learner is None:
                from evo_diagram.design_memory.web_memory import learn_verified_refinement
                learner = learn_verified_refinement
            if retriever is None:
                from evo_diagram.agentic_system.workflow import _load_design_memory_retriever
                retriever, error = _load_design_memory_retriever(job["memory_path"], job["embedding_model"])
                if retriever is None:
                    raise RuntimeError(error or "Design memory unavailable")
            if model is None:
                from app.services.llm_client import create_backend_llm
                model = create_backend_llm()
            result = learner(retriever=retriever, model=model,
                             report_path=str(directory / "report.json"), **job["inputs"])
        except Exception:
            logger.exception("Post-delivery design learning failed for {}", directory.name)
            result = {"status": "unavailable", "saved_count": 0}
        _write(directory / "status.json", {**result, "job_id": directory.name,
                                             "duration_ms": int((time.monotonic() - started) * 1000)})


def _start(directory: Path, **kwargs: Any) -> None:
    key = str(directory)
    if key in _ACTIVE:
        return
    _ACTIVE.add(key)

    async def work() -> None:
        try:
            loop = asyncio.get_running_loop()
            limit = _LIMITS.setdefault(loop, asyncio.Semaphore(2))
            async with limit:
                await asyncio.to_thread(_execute, directory, **kwargs)
        except Exception:
            logger.exception("Could not process design learning job {}", directory.name)
        finally:
            _ACTIVE.discard(key)

    task = asyncio.create_task(work())
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)


def enqueue_learning(*, memory_path: str, embedding_model: str, report_path: str,
                     request_id: str, diagram_type: str, before: dict, after: dict,
                     model: Any, retriever: Any, learner: Any) -> dict[str, Any]:
    from evo_diagram.agentic_system.quality_policy import verified_learning_gain
    if not verified_learning_gain(before, after):
        return {"status": "skipped", "saved_count": 0, "reason": "no_verified_gain"}
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", request_id):
        raise ValueError("Invalid internal request ID")
    directory = Path(memory_path) / ".learning" / request_id
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    status = {"status": "queued", "saved_count": 0, "job_id": request_id}
    # Copy inputs before the request's temporary artifacts can be removed.
    _write(directory / "report.json", json.loads(Path(report_path).read_text()))
    _write(directory / "job.json", {
        "memory_path": str(Path(memory_path).resolve()), "embedding_model": embedding_model,
        "inputs": {"request_id": request_id, "diagram_type": diagram_type,
                   "before": before, "after": after},
    })
    _write(directory / "status.json", status)
    _start(directory, model=model, retriever=retriever, learner=learner)
    return status


def resume_learning(root: str) -> None:
    for status_path in Path(root).glob("*/.learning/*/status.json"):
        try:
            status = json.loads(status_path.read_text())
            if status.get("status") in {"queued", "running"}:
                _start(status_path.parent)
        except (OSError, ValueError):
            logger.warning("Skipping unreadable design learning job {}", status_path.parent.name)


async def wait_for_learning() -> None:
    """Drain accepted work for shutdown and deterministic integration tests."""
    if _TASKS:
        await asyncio.gather(*list(_TASKS), return_exceptions=True)
