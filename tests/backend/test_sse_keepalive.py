import asyncio

import pytest

from app.core.sse import with_sse_keepalive


@pytest.mark.asyncio
async def test_heartbeat_preserves_pending_work_and_result():
    release = asyncio.Event()
    calls = []
    async def source():
        calls.append("started")
        await release.wait()
        yield "event: result\ndata: {}\n\n"
    stream = with_sse_keepalive(source(), interval=0.001)
    assert await anext(stream) == ": keepalive\n\n"
    release.set()
    assert await anext(stream) == "event: result\ndata: {}\n\n"
    with pytest.raises(StopAsyncIteration):
        await anext(stream)
    assert calls == ["started"]


@pytest.mark.asyncio
async def test_disconnect_cancels_and_closes_source():
    closed = asyncio.Event()
    async def source():
        try:
            await asyncio.Event().wait()
            yield "never"
        finally:
            closed.set()
    stream = with_sse_keepalive(source(), interval=0.001)
    assert await anext(stream) == ": keepalive\n\n"
    await stream.aclose()
    assert closed.is_set()
