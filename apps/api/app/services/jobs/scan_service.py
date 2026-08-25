"""The Scan engine (v7 ticket 07): one run of the Job Monitor across the enabled Job Boards.

CONTEXT.md (Scan) in one paragraph, which is also this module's order of operations: read the
Search Profile, decide which boards may be called at all, call those in parallel, fold what
came back into deduplicated Job Listings with their Listing Sources, reattach the Listing
Memory, rank, and write the whole result in ONE transaction. A Scan is **partial, never
failed**: each board reports its own Board Status and the other boards' results stand.

Four rules run through everything below and are worth stating once:

1. **At most one Scan at a time**, enforced by an in-process ``asyncio.Lock`` in ``ScanRunner``
   -- not by a database read. The app is single-user and local, so the lock is the whole truth;
   ``jobs_repo.start_scan``'s docstring says the same from the other side. A second caller gets
   ``ScanAlreadyRunning`` carrying the Scan that holds it (the router turns that into the 409).
2. **A board never aborts the Scan.** An adapter reports ``blocked``/``error`` by contract, and
   an adapter that raises anyway is caught here and recorded as ``error`` for its own board.
   Items are consumed even from a non-``ok`` board (ticket 04 decision 3: a partially refused
   board returns what it did find).
3. **The list IS the last Scan** (CONTEXT.md: Job Listing), so ``job_listings`` is truncated
   and rewritten wholesale. The one guard on that is spelled out at ``_produced_evidence``.
4. **Time is injected, never read twice.** One instant (``now``) stamps the whole Scan: every
   recency score, every Repost comparison and every ``last_seen_at``. Datetimes coming back out
   of SQLite are naive and are read as UTC (``domain.recency.as_utc``).

Not in this ticket: the Fit Score. ``fit_score`` is whatever the Listing Memory already holds
(0 for a job never scored), ``fit_estimated`` is False -- nothing here estimates anything -- and
``visibility_score`` is the recency term alone, on the 0-100 scale of the contract. Ticket 08
adds the keyword pass, the LLM pass and the real weighted blend.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy.engine import Engine
from sqlmodel import Session

from app import config as config_module
from app.db.tables import JobListing, JobScan, ListingMemory, ListingSource, SearchProfile
from app.domain.listing_identity import identity_key
from app.domain.locale import DEFAULT_LOCALE, detect_locale
from app.domain.recency import as_utc, recency_score
from app.domain.schemas import BoardQuery, BoardResult, RawPosting
from app.repositories import jobs_repo
from app.services.jobboards.base import JobBoardProvider
from app.services.jobboards.provider_registry import BOARD_SPECS, BoardProviderRegistry
from app.services.secret_redaction import redact_secrets

logger = logging.getLogger(__name__)


# --- Applicant Band ordering ------------------------------------------------------------------

# Bands from least to most crowded. ``unknown`` is deliberately NOT in this tuple: it is not a
# point on the scale, it is the absence of one, and every rule below treats it as such --
# CONTEXT.md (Applicant Band): "unknown never excludes a listing from the user's maximum-
# applicants filter, it only scores neutrally".
BAND_ORDER: tuple[str, ...] = ("<10", "<25", "<50", "<100", "100+")
UNKNOWN_BAND = "unknown"

# How far back a board is asked to look, as a multiple of the user's scan interval, so two
# consecutive Scans OVERLAP and nothing published between them falls through the gap.
HOURS_OLD_OVERLAP_FACTOR = 2
# ...and never a narrower window than a day, so a 1h interval still surfaces yesterday's
# postings on the first Scan after the app has been closed for a while.
HOURS_OLD_FLOOR = 24
# The interval assumed when the user has scheduling switched off: an Immediate Scan still has
# to ask the boards for SOMETHING.
HOURS_OLD_WHEN_OFF = 24

# How many Scans back the "when did this board last answer" walk may look (see
# ``jobs_repo.list_recent_scans``).
BOARD_HISTORY_SCANS = 200

_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_WS_RE = re.compile(r"\s+")
_MAX_MESSAGE_CHARS = 200


class ScanAlreadyRunning(RuntimeError):
    """A Scan was requested while one is already running (CONTEXT.md: at most one Scan at a
    time). Carries the current Scan so the router can answer 409 with it rather than with a
    bare message -- ``scan`` is detached from its Session (already loaded, safe to read) and is
    ``None`` only in the window where the running Scan's row has not been committed yet."""

    def __init__(self, scan: JobScan | None = None) -> None:
        self.scan = scan
        self.scan_id = getattr(scan, "id", None)
        super().__init__(
            "a Scan is already running"
            + (f" (id={self.scan_id})" if self.scan_id is not None else "")
        )


@dataclass(frozen=True)
class BoardOutcome:
    """How one board fared, in the shape ``job_scans.board_statuses`` stores."""

    board: str
    status: str  # BoardStatus: 'ok' | 'blocked' | 'error' | 'skipped'
    message: str | None = None
    # Postings this board contributed BEFORE dedup -- the number that explains a partial Scan
    # ("Indeed: 40, LinkedIn: bloqueado"), which the deduplicated total cannot.
    count: int = 0

    def as_dict(self) -> dict:
        return {"status": self.status, "message": self.message, "count": self.count}


@dataclass(frozen=True)
class ScanOutcome:
    """What ``run_scan`` returns to its caller (the router, the scheduler, a test)."""

    scan_id: int
    trigger: str
    started_at: datetime
    finished_at: datetime
    listings_found: int
    listings_scored: int
    board_statuses: dict[str, dict]
    # False when every enabled board was ``skipped`` (or none was enabled): the previous list
    # was left standing rather than wiped -- see ``_produced_evidence``.
    listings_replaced: bool = True


@dataclass
class _Group:
    """One Job Listing under construction: the postings that share an ``identity_key``."""

    key: str
    title: str
    company: str
    location: str | None = None
    is_remote: bool = False
    description: str = ""
    date_posted: datetime | None = None
    band: str = UNKNOWN_BAND
    sources: list[ListingSource] = field(default_factory=list)
    _seen_urls: set[tuple[str, str]] = field(default_factory=set)


@dataclass(frozen=True)
class _ScanPlan:
    """Everything decided from the Search Profile before a single board is called."""

    query: BoardQuery
    to_call: tuple[JobBoardProvider, ...]
    skipped: tuple[BoardOutcome, ...]
    max_band: str | None


# --- Message hygiene ---------------------------------------------------------------------------


def _safe_message(text: str, *, fallback: str) -> str:
    """A Board Status message fit to render verbatim.

    Same treatment (and same reason) as ``jobspy_board._safe_message``: the contract says this
    string is shown to the user as-is, so no raw exception repr, no URL, no secret, bounded
    length. Reimplemented here rather than imported from an adapter because this is the path
    for an adapter that MISBEHAVED -- borrowing a private helper from the module that produced
    the failure is the wrong direction of dependency for the engine's own safety net.
    """
    cleaned = _WS_RE.sub(" ", _URL_RE.sub("[url]", text or "")).strip()
    cleaned = redact_secrets(cleaned)
    if not cleaned:
        return fallback
    if len(cleaned) > _MAX_MESSAGE_CHARS:
        cleaned = cleaned[: _MAX_MESSAGE_CHARS - 1].rstrip() + "…"
    return cleaned


# --- Planning ------------------------------------------------------------------------------------


def hours_old_for(interval_hours: int | None) -> int:
    """How far back to ask the boards to look, from the user's scan interval.

    Deliberately WIDER than the interval (``HOURS_OLD_OVERLAP_FACTOR``): asking for exactly the
    interval would mean a posting published one minute after a Scan started, and indexed by the
    board one minute after the next Scan's window opened, is never seen by either. Re-seeing a
    posting costs nothing -- dedup and the Listing Memory absorb it -- while missing one is
    invisible and permanent.
    """
    base = interval_hours or HOURS_OLD_WHEN_OFF
    return max(HOURS_OLD_FLOOR, base * HOURS_OLD_OVERLAP_FACTOR)


def last_ok_by_board(session: Session, *, limit: int = BOARD_HISTORY_SCANS) -> dict[str, datetime]:
    """When each board last ANSWERED us (Board Status ``ok``), newest first.

    Only ``ok`` arms a board's minimum interval, and that asymmetry is the product behavior the
    BoardStatusBar promises: "X bloqueou; tentamos no próximo Scan". A refusal or a breakage is
    not a successful call, so it must not buy the board six hours of silence -- while a call
    that did return data is exactly what Remotive's four-per-day terms are counting.

    The timestamp is the Scan's ``finished_at`` (falling back to ``started_at`` for a Scan that
    never closed): the call happened somewhere inside that window and the later edge is the
    conservative choice against a rate limit.
    """
    latest: dict[str, datetime] = {}
    for scan in jobs_repo.list_recent_scans(session, limit=limit):
        statuses = jobs_repo.get_board_statuses(scan)
        when = as_utc(scan.finished_at or scan.started_at)
        if when is None:
            continue
        for board, report in statuses.items():
            if board in latest:
                continue
            if isinstance(report, dict) and report.get("status") == "ok":
                latest[board] = when
    return latest


def _plan(
    session: Session,
    row: SearchProfile,
    registry: BoardProviderRegistry,
    *,
    now: datetime,
) -> _ScanPlan:
    interval = row.interval_hours
    query = BoardQuery(
        roles=jobs_repo.get_roles(row),
        locations=jobs_repo.get_locations(row),
        remote=row.remote,  # type: ignore[arg-type]
        hours_old=hours_old_for(interval),
        results_wanted=config_module.scan_results_wanted(),
    )
    last_ok = last_ok_by_board(session)
    to_call: list[JobBoardProvider] = []
    skipped: list[BoardOutcome] = []
    # ``providers_for`` returns catalog order and silently drops an enabled id with no adapter,
    # so a Search Profile saved while a board existed keeps working after that board is retired.
    for provider in registry.providers_for(jobs_repo.get_boards(row)):
        minimum = max(1, int(getattr(provider, "min_interval_hours", 1) or 1))
        previous = last_ok.get(provider.id)
        if previous is None:
            to_call.append(provider)
            continue
        elapsed = now - previous
        if elapsed >= timedelta(hours=minimum):
            to_call.append(provider)
            continue
        skipped.append(
            BoardOutcome(
                board=provider.id,
                status="skipped",
                message=_skipped_message(minimum, elapsed),
                count=0,
            )
        )
    return _ScanPlan(
        query=query,
        to_call=tuple(to_call),
        skipped=tuple(skipped),
        max_band=row.max_applicant_band,
    )


def _skipped_message(minimum_hours: int, elapsed: timedelta) -> str:
    """pt-BR, like every other Board Status message (ticket 05 decision 12): the string is
    rendered verbatim in a product UI that is in Portuguese."""
    hours = elapsed.total_seconds() / 3600.0
    seen = f"{hours:.1f}h".replace(".0h", "h")
    return (
        f"Intervalo mínimo do portal ({minimum_hours}h) ainda não decorrido "
        f"— última resposta há {seen}."
    )


# --- Calling the boards ---------------------------------------------------------------------------


async def _call_boards(
    providers: Sequence[JobBoardProvider], query: BoardQuery
) -> list[tuple[JobBoardProvider, BoardOutcome, list[RawPosting]]]:
    """Every board, at once, with no board able to sink another.

    ``return_exceptions=True`` is the mechanism for rule 2 of the module docstring: a provider
    that raises (a bug, an unhandled timeout) resolves to the exception object instead of
    cancelling its siblings mid-flight, and becomes an ``error`` for its own board only.
    """
    if not providers:
        return []
    results = await asyncio.gather(
        *(provider.search(query) for provider in providers), return_exceptions=True
    )
    out: list[tuple[JobBoardProvider, BoardOutcome, list[RawPosting]]] = []
    for provider, result in zip(providers, results):
        out.append(_outcome_for(provider, result))
    return out


def _outcome_for(
    provider: JobBoardProvider, result: object
) -> tuple[JobBoardProvider, BoardOutcome, list[RawPosting]]:
    if isinstance(result, BaseException):
        message = _safe_message(
            f"{type(result).__name__}: {result}", fallback="O portal falhou de forma inesperada."
        )
        logger.warning(
            "job scan board failed: board=%s status=error message=%s", provider.id, message
        )
        return provider, BoardOutcome(provider.id, "error", message, 0), []
    if not isinstance(result, BoardResult):
        message = _safe_message(
            f"adapter returned {type(result).__name__}", fallback="Resposta inválida do portal."
        )
        logger.warning(
            "job scan board returned a non-BoardResult: board=%s type=%s",
            provider.id,
            type(result).__name__,
        )
        return provider, BoardOutcome(provider.id, "error", message, 0), []
    # Items are taken regardless of status: a board that was refused partway through still
    # returns what it managed to collect (ticket 04 decision 3), and throwing that away would
    # make a partial refusal worse than a total one.
    items = list(result.items)
    outcome = BoardOutcome(
        board=provider.id,
        status=result.status,
        message=result.message,
        count=len(items),
    )
    logger.info(
        "job scan board done: board=%s status=%s count=%d%s",
        outcome.board,
        outcome.status,
        outcome.count,
        f" message={outcome.message}" if outcome.message else "",
    )
    return provider, outcome, items


# --- Dedup: RawPosting -> Job Listing + Listing Sources ---------------------------------------


def _smaller_band(current: str, incoming: str | None) -> str:
    """The SMALLEST known band across a listing's sources -- judge a job by its least crowded
    posting, since that is the queue the user would actually join. ``unknown`` loses to any
    known band and only survives when nothing knew anything (``None``, which means "this board
    has no such concept", is the same as ``unknown`` here)."""
    candidate = incoming or UNKNOWN_BAND
    if candidate not in BAND_ORDER:
        return current
    if current not in BAND_ORDER:
        return candidate
    return candidate if BAND_ORDER.index(candidate) < BAND_ORDER.index(current) else current


def _newer(current: datetime | None, incoming: datetime | None) -> datetime | None:
    """The NEWEST date across a listing's sources. One board indexing a posting a day late must
    not make the job look a day older than it is -- and the same choice keeps Repost detection
    honest, since the freshest evidence is what "reappeared with a newer date" is about."""
    a, b = as_utc(current), as_utc(incoming)
    if a is None:
        return b
    if b is None:
        return a
    return max(a, b)


def group_postings(
    found: Iterable[tuple[str, RawPosting]],
) -> list[_Group]:
    """Fold ``(board_id, posting)`` pairs into one group per ``identity_key`` (CONTEXT.md: Job
    Listing -- "deduplicated across boards by normalized company + normalized title").

    Which posting wins which field, and why:

    * ``title``/``company`` -- the FIRST posting's, i.e. the first board in catalog order. They
      are the same job by definition here; picking a winner deterministically matters more than
      which spelling wins.
    * ``description`` -- the LONGEST. Boards truncate differently, and this text is what the
      Fit pass reads and what a One-click Resume is generated from, so more of it is strictly
      better. A board that returns none simply never wins.
    * ``date_posted`` -- the newest; ``applicant_band`` -- the smallest known (see above).
    * ``location`` -- the first non-empty; ``is_remote`` -- true if ANY board says so, because
      a board that omits the flag is silent, not negative.

    Every posting still becomes a Listing Source: a Job Listing always keeps every source link.
    Two postings from the same board with the same URL collapse (the same job answering two of
    that board's queries), which the adapters already do internally -- this is the backstop.
    """
    groups: dict[str, _Group] = {}
    for board, posting in found:
        title = (posting.title or "").strip()
        url = (posting.url or "").strip()
        if not title or not url:
            # Not a job: an adapter should already have dropped it (ticket 04 decision 9),
            # and a row with no title has no identity worth remembering.
            continue
        company = (posting.company or "").strip()
        key = identity_key(company, title)
        group = groups.get(key)
        if group is None:
            group = _Group(key=key, title=title, company=company)
            groups[key] = group
        group.location = group.location or (posting.location or None)
        group.is_remote = group.is_remote or bool(posting.is_remote)
        description = posting.description or ""
        if len(description) > len(group.description):
            group.description = description
        group.date_posted = _newer(group.date_posted, posting.date_posted)
        group.band = _smaller_band(group.band, posting.applicant_band)
        if (board, url) in group._seen_urls:
            continue
        group._seen_urls.add((board, url))
        group.sources.append(
            ListingSource(
                listing_id=0,  # replace_listings owns the linkage
                board=board,
                url=url,
                date_posted=as_utc(posting.date_posted),
                applicant_band=posting.applicant_band or UNKNOWN_BAND,
            )
        )
    return list(groups.values())


# --- Memory, filtering and ranking -------------------------------------------------------------


def description_hash(description: str) -> str:
    """sha256 of a posting's description -- what ``listing_memory.fit_description_hash`` stores,
    so a Repost whose text was rewritten can be told from the same text coming back."""
    return hashlib.sha256((description or "").encode("utf-8")).hexdigest()


def is_repost(memory: ListingMemory | None, date_posted: datetime | None) -> bool:
    """Whether this is a Repost (CONTEXT.md: Repost -- "already known, reappears with a newer
    ``date_posted``"). Boards do not flag reposts, so this comparison is the only detection.

    The baseline is ``last_seen_at``: a date newer than the last time the Monitor looked means
    the job was (re)published AFTER we already had it, which is precisely a fresh queue for the
    applicant. A job with no memory is not a Repost, it is new; a posting with no date cannot
    be shown to be newer than anything, so it is not one either.
    """
    if memory is None:
        return False
    posted = as_utc(date_posted)
    if posted is None:
        return False
    seen = as_utc(memory.last_seen_at)
    return seen is not None and posted > seen


def passes_band_cap(band: str, max_band: str | None) -> bool:
    """The user's maximum-applicants filter. ``None`` is "qualquer"; ``unknown`` ALWAYS passes
    (CONTEXT.md: an absent number is not evidence of a crowd), and a band the contract does not
    know passes too rather than silently hiding a job."""
    if max_band is None:
        return True
    if band not in BAND_ORDER or max_band not in BAND_ORDER:
        return True
    return BAND_ORDER.index(band) <= BAND_ORDER.index(max_band)


def _build_listing(
    group: _Group, memory: ListingMemory | None, *, now: datetime
) -> tuple[JobListing, bool]:
    """One ``job_listings`` row from a group plus whatever the Listing Memory remembers."""
    repost = is_repost(memory, group.date_posted)
    recency = recency_score(group.date_posted, now)
    listing = JobListing(
        scan_id=0,  # replace_listings owns it
        identity_key=group.key,
        title=group.title,
        company=group.company,
        location=group.location,
        is_remote=group.is_remote,
        description=group.description,
        description_word_count=len(group.description.split()),
        date_posted=as_utc(group.date_posted),
        is_repost=repost,
        applicant_band=group.band,
        # Reattached, never recomputed here: the LLM's number if this identity was ever scored,
        # 0 otherwise. ``fit_estimated`` is False in BOTH cases because nothing in this ticket
        # estimates a Fit -- claiming an estimate exists would be a fake precision. Ticket 08
        # introduces the keyword pass that legitimately sets it True.
        fit_score=(memory.fit_score if memory is not None and memory.fit_score is not None else 0),
        fit_estimated=False,
        # Provisional: the recency term alone, on the contract's 0-100 scale. Ticket 08 replaces
        # this with 100 * (0.55*fit + 0.25*recency + 0.20*competition).
        visibility_score=round(100.0 * recency, 2),
        locale=detect_locale(group.description) or DEFAULT_LOCALE,
    )
    return listing, repost


# --- The runner --------------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ScanRunner:
    """Owns the single-flight lock. One instance per process (``default_runner`` below); a test
    builds its own so two tests can never contend for the same lock."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._current_scan_id: int | None = None

    @property
    def is_running(self) -> bool:
        return self._lock.locked()

    @property
    def current_scan_id(self) -> int | None:
        return self._current_scan_id

    async def run(
        self,
        engine: Engine,
        registry: BoardProviderRegistry,
        trigger: str = "scheduled",
        *,
        now: datetime | None = None,
        clock: Callable[[], datetime] = _utcnow,
    ) -> ScanOutcome | None:
        """Run one Scan, or raise ``ScanAlreadyRunning``. ``None`` means there was nothing to
        search for (no Search Profile saved) -- no Scan row is written in that case.

        The ``locked()`` check and the acquire that follows are not a race in this codebase:
        ``asyncio.Lock.acquire`` takes an uncontended lock without suspending, so no other task
        can interleave between them on the one event loop this app runs.
        """
        if self._lock.locked():
            raise ScanAlreadyRunning(self._load_running_scan(engine))
        await self._lock.acquire()
        try:
            return await self._run(engine, registry, trigger, now=now, clock=clock)
        finally:
            self._current_scan_id = None
            self._lock.release()

    def _load_running_scan(self, engine: Engine) -> JobScan | None:
        try:
            with Session(engine) as session:
                row = jobs_repo.get_running_scan(session)
                if row is not None:
                    session.expunge(row)  # read after the Session closes
                return row
        except Exception:  # pragma: no cover - a 409 must not depend on a second DB read
            logger.exception("could not load the running Scan for the ScanAlreadyRunning body")
            return None

    async def _run(
        self,
        engine: Engine,
        registry: BoardProviderRegistry,
        trigger: str,
        *,
        now: datetime | None,
        clock: Callable[[], datetime],
    ) -> ScanOutcome | None:
        instant = as_utc(now) or as_utc(clock())
        assert instant is not None  # as_utc only returns None for a None input

        # Phase 1 -- plan, and open the ``running`` row in its OWN transaction. The spec's
        # "single transaction" is the RESULT write (phase 3); committing the scan row up front
        # is what makes GET /scans/current pollable and gives the 409 something to carry.
        with Session(engine) as session:
            profile_row = jobs_repo.get_search_profile(session)
            if profile_row is None:
                logger.info(
                    "job scan not run: no Search Profile saved (trigger=%s)", trigger
                )
                return None
            plan = _plan(session, profile_row, registry, now=instant)
            scan = jobs_repo.start_scan(session, trigger=trigger)
            # The Scan's own timestamps come from the Scan's instant, not from a second read of
            # the clock inside the repository. Production cannot tell the difference (``now``
            # was read microseconds earlier), but it is what makes ``skipped`` -- which is
            # decided by comparing THIS instant against a previous Scan's ``finished_at`` --
            # answer to the injected clock instead of to the wall clock in a test.
            scan.started_at = instant
            session.add(scan)
            scan_id = int(scan.id or 0)
            started_at = instant
            session.commit()
        self._current_scan_id = scan_id
        logger.info(
            "job scan started: id=%d trigger=%s boards=%s skipped=%s hours_old=%d",
            scan_id,
            trigger,
            ",".join(p.id for p in plan.to_call) or "-",
            ",".join(o.board for o in plan.skipped) or "-",
            plan.query.hours_old,
        )

        outcomes: dict[str, BoardOutcome] = {o.board: o for o in plan.skipped}
        try:
            # Phase 2 -- the network. No DB session is held open across it.
            called = await _call_boards(plan.to_call, plan.query)
            found: list[tuple[str, RawPosting]] = []
            for provider, outcome, items in called:
                outcomes[provider.id] = outcome
                found.extend((provider.id, posting) for posting in items)

            # Phase 3 -- one transaction for the whole result.
            return self._write(
                engine,
                scan_id=scan_id,
                trigger=trigger,
                started_at=started_at,
                found=found,
                outcomes=outcomes,
                any_called=bool(called),
                max_band=plan.max_band,
                now=instant,
                clock=clock,
            )
        except Exception:
            # The Scan row must not be left ``running`` forever -- a stale one would block
            # every later Immediate Scan through GET /scans/current. finish_scan is documented
            # as safe to call here; the listings are untouched, so the previous list stands.
            logger.exception("job scan failed: id=%d trigger=%s", scan_id, trigger)
            self._close_failed(engine, scan_id, outcomes)
            raise

    def _write(
        self,
        engine: Engine,
        *,
        scan_id: int,
        trigger: str,
        started_at: datetime,
        found: Sequence[tuple[str, RawPosting]],
        outcomes: dict[str, BoardOutcome],
        any_called: bool,
        max_band: str | None,
        now: datetime,
        clock: Callable[[], datetime] = _utcnow,
    ) -> ScanOutcome:
        finished_clock = clock
        groups = group_postings(found)
        with Session(engine) as session:
            memories = jobs_repo.get_memories(session, [g.key for g in groups])
            pairs: list[tuple[JobListing, Sequence[ListingSource]]] = []
            hidden = 0
            for group in groups:
                memory = memories.get(group.key)
                listing, repost = _build_listing(group, memory, now=now)
                # Every job the Scan SAW updates its memory, including the ones the user will
                # not see: ``last_seen_at`` is a fact about the Monitor having found the job,
                # independent of whether a filter hides it -- and it is the baseline the next
                # Repost detection compares against.
                self._remember(session, group, memory, repost=repost, now=now)
                if memory is not None and memory.status == "dismissed":
                    hidden += 1
                    continue
                if not passes_band_cap(listing.applicant_band, max_band):
                    hidden += 1
                    continue
                pairs.append((listing, group.sources))

            replaced = _produced_evidence(outcomes.values()) if any_called else False
            if replaced:
                jobs_repo.replace_listings(session, scan_id=scan_id, listings=pairs)
                listings_found = len(pairs)
            else:
                # Nothing was called, or nothing answered: keep the previous list rather than
                # wiping the user's Job Monitor on the strength of a rate limit. The Board
                # Statuses below say why the list did not move.
                listings_found = len(jobs_repo.list_listings(session))

            scan = jobs_repo.get_scan(session, scan_id)
            assert scan is not None  # written and committed by phase 1
            board_statuses = _ordered_statuses(outcomes)
            jobs_repo.finish_scan(
                session,
                scan,
                board_statuses=board_statuses,
                listings_found=listings_found,
                listings_scored=0,  # ticket 08 scores; this ticket scores nothing
            )
            # ``finished_at`` is read from the clock rather than reused from ``now``, so a Scan
            # that took two minutes says so; ``finish_scan``'s own default is overridden for the
            # same reason ``started_at`` above is.
            finished_at = as_utc(finished_clock()) or now
            scan.finished_at = finished_at
            session.add(scan)
            session.commit()

        logger.info(
            "job scan finished: id=%d trigger=%s raw=%d listings=%d hidden=%d replaced=%s",
            scan_id,
            trigger,
            len(found),
            listings_found,
            hidden,
            replaced,
        )
        return ScanOutcome(
            scan_id=scan_id,
            trigger=trigger,
            started_at=started_at,
            finished_at=finished_at,
            listings_found=listings_found,
            listings_scored=0,
            board_statuses=board_statuses,
            listings_replaced=replaced,
        )

    def _remember(
        self,
        session: Session,
        group: _Group,
        memory: ListingMemory | None,
        *,
        repost: bool,
        now: datetime,
    ) -> None:
        """Reattach-and-bump. ``status`` is never written by a Scan for an identity that
        already has one (``upsert_memory`` reads ``None`` as "leave alone"), so a ``dismissed``
        job stays dismissed and an ``applied`` one stays applied; a brand-new identity gets
        ``new`` from the repository's own default.

        The one thing a Scan DOES clear: a Repost whose description was rewritten invalidates
        the stored Fit, because that number was computed for different text. The same text
        coming back does not -- which is exactly what ``fit_description_hash`` is for.
        """
        clear_fit = (
            repost
            and memory is not None
            and memory.fit_description_hash is not None
            and memory.fit_description_hash != description_hash(group.description)
        )
        jobs_repo.upsert_memory(
            session,
            group.key,
            fit_score=None if clear_fit else jobs_repo.KEEP,
            fit_description_hash=None if clear_fit else jobs_repo.KEEP,
            seen_at=now,
        )

    def _close_failed(
        self, engine: Engine, scan_id: int, outcomes: dict[str, BoardOutcome]
    ) -> None:
        try:
            with Session(engine) as session:
                scan = jobs_repo.get_scan(session, scan_id)
                if scan is None:  # pragma: no cover - phase 1 committed it
                    return
                jobs_repo.finish_scan(
                    session,
                    scan,
                    board_statuses=_ordered_statuses(outcomes),
                    listings_found=0,
                    listings_scored=0,
                )
                session.commit()
        except Exception:  # pragma: no cover - never mask the original failure
            logger.exception("could not close the failed Scan id=%d", scan_id)


def _produced_evidence(outcomes: Iterable[BoardOutcome]) -> bool:
    """Whether this Scan learned anything about the job market, as opposed to only about the
    boards.

    The list IS the last Scan, so it is normally replaced wholesale -- but "every board we
    called was blocked" is evidence about LinkedIn's rate limiter, not evidence that the user's
    jobs disappeared, and truncating the list on it would delete the whole Job Monitor because
    of a 429. One board answering ``ok`` (or any board returning items despite being refused
    partway -- ticket 04 decision 3) is enough for the replacement to go ahead, which is what
    keeps a genuinely partial Scan behaving as the spec says it should.
    """
    return any(o.status == "ok" or o.count > 0 for o in outcomes if o.status != "skipped")


def _ordered_statuses(outcomes: dict[str, BoardOutcome]) -> dict[str, dict]:
    """The map ``job_scans.board_statuses`` stores, in catalog order so the JSON reads the same
    way the BoardStatusBar renders it."""
    ordered = {spec.id: outcomes[spec.id].as_dict() for spec in BOARD_SPECS if spec.id in outcomes}
    # A board id not in the catalog cannot normally get here (``providers_for`` filters), but
    # dropping one silently would lose a Board Status the user is owed.
    for board, outcome in outcomes.items():
        ordered.setdefault(board, outcome.as_dict())
    return ordered


# The process-wide runner. Module-level because the single-flight lock has to be shared by
# every caller in the process -- the HTTP handler for an Immediate Scan and the scheduler are
# exactly the two that must not run at the same time.
default_runner = ScanRunner()


async def run_scan(
    engine: Engine,
    registry: BoardProviderRegistry,
    trigger: str = "scheduled",
    *,
    now: datetime | None = None,
    clock: Callable[[], datetime] = _utcnow,
    runner: ScanRunner | None = None,
) -> ScanOutcome | None:
    """Run one Scan (see ``ScanRunner.run``). The module-level entry point every caller uses;
    ``runner`` is the test seam for an isolated lock."""
    return await (runner or default_runner).run(
        engine, registry, trigger, now=now, clock=clock
    )
