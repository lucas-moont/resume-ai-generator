import asyncio
import time
import unittest

from app.services.streaming import run_with_heartbeat, sse


class SseFramingTests(unittest.TestCase):
    def test_formats_event_and_json_data(self) -> None:
        frame = sse("stage", {"step": "calling_ai", "progress": 60})
        self.assertEqual(frame, 'event: stage\ndata: {"step": "calling_ai", "progress": 60}\n\n')


class RunWithHeartbeatTests(unittest.IsolatedAsyncioTestCase):
    async def test_instant_task_completes_with_no_ticks_and_no_tax(self) -> None:
        """The bug this replaces: the old inline loop always slept one full heartbeat
        interval before its first completion check, even for a task that was already done.
        A large heartbeat_seconds here (5s) would make that regression obvious in the
        wall-clock assertion below; with the fix, an instant task returns in well under it."""

        async def instant() -> str:
            return "raw-result"

        task = asyncio.create_task(instant())
        started = time.monotonic()
        frames = [frame async for frame in run_with_heartbeat(
            task,
            heartbeat_seconds=5,
            timeout_seconds=900,
            tick=lambda elapsed: sse("stage", {"message": f"tick {elapsed}"}),
            on_timeout=lambda elapsed: sse("error", {"message": "timeout"}),
        )]
        elapsed_wall = time.monotonic() - started

        self.assertEqual(frames, [])
        self.assertLess(elapsed_wall, 1.0)
        self.assertEqual(task.result(), "raw-result")

    async def test_yields_a_tick_per_heartbeat_while_pending(self) -> None:
        async def slow() -> str:
            await asyncio.sleep(0.05)
            return "raw-result"

        task = asyncio.create_task(slow())
        frames = [frame async for frame in run_with_heartbeat(
            task,
            heartbeat_seconds=0.01,
            timeout_seconds=10,
            tick=lambda elapsed: sse("stage", {"message": f"tick {elapsed}"}),
            on_timeout=lambda elapsed: sse("error", {"message": "timeout"}),
        )]

        self.assertGreaterEqual(len(frames), 1)
        self.assertTrue(all(is_timeout is False for is_timeout, _ in frames))
        self.assertTrue(all("tick" in frame for _, frame in frames))
        self.assertEqual(task.result(), "raw-result")

    async def test_times_out_cancels_task_and_yields_a_single_error_frame(self) -> None:
        async def never_finishes() -> str:
            await asyncio.sleep(1000)
            return "unreachable"

        task = asyncio.create_task(never_finishes())
        frames = [frame async for frame in run_with_heartbeat(
            task,
            heartbeat_seconds=0.01,
            timeout_seconds=0.03,
            tick=lambda elapsed: sse("stage", {"message": f"tick {elapsed}"}),
            on_timeout=lambda elapsed: sse("error", {"message": f"timed out after {elapsed}"}),
        )]

        timeouts = [is_timeout for is_timeout, _ in frames]
        self.assertEqual(timeouts.count(True), 1)
        self.assertEqual(timeouts[-1], True)
        self.assertTrue(frames[-1][1].startswith("event: error"))
        # Give the event loop a beat to actually process the requested cancellation.
        await asyncio.sleep(0)
        self.assertTrue(task.cancelled() or task.cancelling() > 0)


if __name__ == "__main__":
    unittest.main()
