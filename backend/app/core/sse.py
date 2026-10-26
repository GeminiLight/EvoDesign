"""Shared helpers for the backend's simple JSON SSE wire format."""

from __future__ import annotations

import json
import asyncio
from contextlib import suppress
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class SseEvent:
    """Parsed event/data pair for backend SSE chunks."""

    event: str
    data: dict[str, Any]


def parse_sse_event(chunk: str) -> SseEvent | None:
    """Parse a backend SSE chunk, returning None when it has no JSON object data."""
    event_name: str | None = None
    data_lines: list[str] = []

    for line in chunk.strip().splitlines():
        if line.startswith("event: "):
            event_name = line.removeprefix("event: ")
        elif line.startswith("data: "):
            data_lines.append(line.removeprefix("data: "))

    if not event_name or not data_lines:
        return None

    try:
        data = json.loads("\n".join(data_lines))
    except json.JSONDecodeError:
        return None

    if not isinstance(data, dict):
        return None

    return SseEvent(event=event_name, data=data)


def format_sse_event(event_name: str, data: Mapping[str, Any]) -> str:
    """Serialize a JSON object payload using the backend SSE wire format."""
    return f"event: {event_name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def with_sse_keepalive(source: AsyncIterator[str], interval: float = 15) -> AsyncIterator[str]:
    """Keep long model calls connected without inventing progress events."""
    iterator = source.__aiter__()
    pending = None
    try:
        while True:
            if pending is None:
                pending = asyncio.create_task(anext(iterator))
            done, _ = await asyncio.wait({pending}, timeout=interval)
            if not done:
                yield ": keepalive\n\n"
                continue
            try:
                chunk = pending.result()
            except StopAsyncIteration:
                return
            pending = None
            yield chunk
    finally:
        if pending is not None:
            pending.cancel()
            with suppress(asyncio.CancelledError, StopAsyncIteration):
                await pending
        close = getattr(iterator, "aclose", None)
        if close is not None:
            await close()
