"""The scheduled Scan loop (v7 ticket 07): one ``asyncio`` task, started by the app's lifespan
next to the Source Document reaper, that runs a Scan at the user's chosen interval.

No new dependency and no scheduler library -- the spec is explicit about that. The loop's whole
design is one decision: **it never sleeps on a remembered interval, it re-reads the Search
Profile every turn**. Same philosophy as the Runtime Config (CONTEXT.md): a value the user
changes in the UI takes effect on the next loop, with no process restart. Concretely, the task
wakes every ``config.scan_check_interval_seconds()`` (60s by default) and each time asks two
questions of the database:

* is scheduling on? ``search_profile.interval_hours`` of ``None`` is OFF -- and so is having no
  Search Profile row at all, which is the state a fresh install is in. Off means "keep waking
  up and re-checking", never "exit", so switching it back on does not need a restart either.
* is a Scan due? ``interval_hours`` after the last Scan STARTED. Reading that from
  ``job_scans`` rather than from a timer in memory is what makes the schedule survive a restart
  (a 24h interval does not become "24h from every boot") and what keeps an Immediate Scan from
  being immediately followed by a scheduled one.

Failure policy, in one line: nothing a Scan does may kill this task. An exception is logged and
the loop sleeps on; a Scan already running (the user clicked "Buscar agora" a moment ago) is not
even an error, just a turn skipped. Only cancellation ends the loop, and it ends it cleanly --
``stop`` awaits the task so shutdown never races a half-written Scan transaction.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from sqlalchemy.engine import Engine
from sqlmodel import Session

from app import config as config_module
from app.domain.recency import as_utc
from app.repositories import jobs_repo
from app.services.jobboards.provider_registry import BoardProviderRegistry
from app.services.jobs import scan_service
from app.services.jobs.scan_service import ScanAlreadyRunning, ScanOutcome

logger = logging.getLogger(__name__)

# Where the scheduler is parked on the FastAPI app, mirroring ``app.state.db_engine``.
STATE_ATTR = "scan_scheduler"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ScanScheduler:
    """The background loop. Constructed directly by tests (no env gate, no ``app``); production
    goes through ``start(app)`` below.

    Every collaborator is injectable for the same reason the reaper's clock is: a test must be
    able to drive several turns of this loop without real time passing and without a real board
    ever being reached.
    """

    def __init__(
        self,
        engine: Engine,
        registry: BoardProviderRegistry,
        *,
        run_scan: Callable[..., Awaitable[ScanOutcome | None]] | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        clock: Callable[[], datetime] = _utcnow,
        check_interval_seconds: float | None = None,
    ) -> None:
        self._engine = engine
        self._registry = registry
        self._run_scan = run_scan or scan_service.run_scan
        self._sleep = sleep or asyncio.sleep
        self._clock = clock
        self._check_interval_override = check_interval_seconds
        self._task: asyncio.Task | None = None

    # --- lifecycle ---------------------------------------------------------------------------

    @property
    def task(self) -> asyncio.Task | None:
        return self._task

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> asyncio.Task:
        """Create the loop task. Idempotent: calling it twice returns the same task rather than
        running two schedulers against one database."""
        if self._task is not None and not self._task.done():
            return self._task
        self._task = asyncio.create_task(self.run_forever(), name="job-scan-scheduler")
        return self._task

    async def stop(self) -> None:
        """Cancel the loop and WAIT for it. Awaiting is the point: without it, shutdown could
        return while a Scan transaction is still mid-flight against an engine the lifespan is
        about to drop."""
        task, self._task = self._task, None
        if task is None or task.done():
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    # --- the loop ----------------------------------------------------------------------------

    def check_interval_seconds(self) -> float:
        """Read at CALL time, like every other config accessor, so the env var can change the
        granularity without a restart."""
        if self._check_interval_override is not None:
            return float(self._check_interval_override)
        return float(config_module.scan_check_interval_seconds())

    async def run_forever(self) -> None:
        """One turn per wake-up, forever, until cancelled."""
        logger.info("job scan scheduler started")
        try:
            while True:
                await self.tick()
        except asyncio.CancelledError:
            logger.info("job scan scheduler stopped")
            raise

    async def tick(self) -> None:
        """One turn: re-read the interval, run a Scan if one is due, then sleep.

        Public and awaitable on its own so a test can step the loop deterministically instead
        of racing a task.
        """
        try:
            interval_hours, due_in_seconds = self._next_wait()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("job scan scheduler could not read the Search Profile")
            await self._sleep(self.check_interval_seconds())
            return

        if interval_hours is None:
            # Off (or no Search Profile at all). Keep waking up: switching it on must not need
            # a restart.
            await self._sleep(self.check_interval_seconds())
            return

        if due_in_seconds > 0:
            await self._sleep(min(self.check_interval_seconds(), due_in_seconds))
            return

        await self._run_once(interval_hours)

    async def _run_once(self, interval_hours: int) -> None:
        try:
            outcome = await self._run_scan(
                self._engine, self._registry, "scheduled", clock=self._clock
            )
        except asyncio.CancelledError:
            raise
        except ScanAlreadyRunning as e:
            # Not an error: the user asked for an Immediate Scan seconds ago. Wait it out.
            logger.info(
                "scheduled Scan skipped: a Scan is already running (id=%s)", e.scan_id
            )
            await self._sleep(self.check_interval_seconds())
            return
        except Exception:
            # A board, an adapter or the database misbehaved. The Scan engine already closed
            # its own row; this task must survive to try again on the next interval.
            logger.exception("scheduled Scan failed")
            await self._sleep(self.check_interval_seconds())
            return
        if outcome is None:
            # No Search Profile row -- the interval we read a moment ago came from one, so this
            # is the narrow window where it was deleted mid-turn. Nothing to do but wait.
            logger.info("scheduled Scan did not run: no Search Profile")
            await self._sleep(self.check_interval_seconds())
            return
        logger.info(
            "scheduled Scan done: id=%d listings=%d (next in %dh)",
            outcome.scan_id,
            outcome.listings_found,
            interval_hours,
        )

    def _next_wait(self) -> tuple[int | None, float]:
        """``(interval_hours, seconds_until_due)``.

        ``interval_hours`` is ``None`` when scheduling is off -- including when the user has
        never saved a Search Profile, since a scheduler that scanned seven boards before the
        user opened the form would be reaching the network on their behalf unasked (the same
        reason ``search_profile_service`` refuses to persist defaults on a GET).

        Due-ness is measured from the last Scan's ``started_at``, whatever triggered it: an
        Immediate Scan resets the clock, because "scan every 6 hours" is about how often the
        boards are called, not about who asked.
        """
        with Session(self._engine) as session:
            row = jobs_repo.get_search_profile(session)
            interval_hours = row.interval_hours if row is not None else None
            if interval_hours is None:
                return None, 0.0
            latest = jobs_repo.get_latest_scan(session)
            last_started = as_utc(latest.started_at) if latest is not None else None
        if last_started is None:
            return interval_hours, 0.0  # never scanned: due immediately
        elapsed = (self._clock() - last_started).total_seconds()
        return interval_hours, max(0.0, interval_hours * 3600.0 - elapsed)


# --- Lifespan wiring -------------------------------------------------------------------------


def start(app, **kwargs: object) -> ScanScheduler | None:
    """Start the scheduler on the FastAPI app (called from ``main.py``'s lifespan).

    Returns ``None`` -- having started nothing -- when ``SCAN_SCHEDULER_ENABLED`` is off. That
    switch is not the product's off button (an interval of "off" in the Search Profile is);
    it exists so the test suite, which drives ``lifespan`` directly in two integration tests,
    never spawns a task that would reach real Job Boards. See ``config.scan_scheduler_enabled``.
    """
    if not config_module.scan_scheduler_enabled():
        logger.info("job scan scheduler disabled (SCAN_SCHEDULER_ENABLED)")
        return None
    engine = kwargs.pop("engine", None) or getattr(app.state, "db_engine", None)
    if engine is None:  # pragma: no cover - the lifespan always sets it first
        logger.warning("job scan scheduler not started: no database engine on app.state")
        return None
    registry = kwargs.pop("registry", None)
    if registry is None:
        # Imported here, not at module scope: this is the one call in the app that constructs
        # the network-reaching adapters, and the Scan engine's own tests must never pull them
        # in as a side effect of importing the scheduler.
        from app.services.jobboards.default_registry import build_default_registry

        registry = build_default_registry()
    scheduler = ScanScheduler(engine, registry, **kwargs)  # type: ignore[arg-type]
    scheduler.start()
    setattr(app.state, STATE_ATTR, scheduler)
    return scheduler


async def stop(app) -> None:
    """Cancel and await the scheduler, if one was started. Safe to call unconditionally."""
    scheduler = getattr(app.state, STATE_ATTR, None)
    if scheduler is None:
        return
    await scheduler.stop()
    setattr(app.state, STATE_ATTR, None)
