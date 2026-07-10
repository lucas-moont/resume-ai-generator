"""SSE framing and heartbeat polling for the streaming endpoints -- extracted from
app/main.py (B3).

``run_with_heartbeat`` replaces 3 near-identical inline copies of the same
task+heartbeat+timeout polling loop (the profile-PDF extraction call in generate/stream, and
the main LLM call in each of generate/stream and refine/stream).

Bug fix vs. the original inline loops: ``while not task.done(): await
asyncio.sleep(heartbeat_seconds)`` always slept a FULL heartbeat interval at least once, even
for an instant response -- a task can never be ``.done()`` on the very first check right
after ``asyncio.create_task(...)`` (it has not had a chance to run yet), so the loop body
(sleep, then re-check) always ran at least one full iteration. In production
(heartbeat_seconds=5) this meant every streamed generate/refine call paid a minimum ~5s tax
beyond actual LLM latency. This version waits ON the task itself
(``asyncio.wait({task}, timeout=heartbeat_seconds)``), which returns as soon as the task
finishes OR the interval elapses, whichever comes first -- an instant task now yields zero
heartbeat ticks and returns immediately.
"""

import asyncio
import json
from collections.abc import AsyncIterator, Callable


def sse(event: str, data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


async def run_with_heartbeat(
    task: asyncio.Task,
    *,
    heartbeat_seconds: float,
    timeout_seconds: float,
    tick: Callable[[float], str],
    on_timeout: Callable[[float], str],
) -> AsyncIterator[tuple[bool, str]]:
    """Poll ``task``, yielding ``(is_timeout, sse_frame)`` pairs until it settles.

    - Every full ``heartbeat_seconds`` interval that ``task`` is still pending, yields
      ``(False, tick(elapsed))`` so the caller can forward a progress frame to the client.
    - If accumulated ``elapsed`` reaches ``timeout_seconds``, cancels ``task``, yields exactly
      one ``(True, on_timeout(elapsed))``, and returns. The caller must stop at that point
      without reading ``task.result()`` (the task was cancelled).
    - On success the generator yields nothing further and simply returns; the caller reads
      ``task.result()`` on the same task object it passed in (mirroring the historical
      ``raw = await task`` at the end of the inline loops, including re-raising whatever
      exception the task raised, if any).
    """
    elapsed = 0
    while True:
        done, _pending = await asyncio.wait({task}, timeout=heartbeat_seconds)
        if task in done:
            return
        elapsed += heartbeat_seconds
        if elapsed >= timeout_seconds:
            task.cancel()
            yield True, on_timeout(elapsed)
            return
        yield False, tick(elapsed)
