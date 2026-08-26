"""The Job Monitor's HTTP surface (v7), prefix ``/api/jobs``.

Thin HTTP-shape adapter, like every other router here: the Search Profile's defaults,
validation and suggestion rules live in ``app/services/jobs/search_profile_service.py``, and
this module only parses, delegates, commits and maps a service error onto a status code.

Sections are ordered as the spec's Backend-6 lists them -- Search Profile, boards, and (ticket
09) scans and listings -- so the file stays readable as it grows to the full surface.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.engine import Engine
from sqlmodel import Session

from app.db.tables import JobScan
from app.domain.schemas import (
    BoardId,
    BoardListOut,
    JobListingListOut,
    JobListingOut,
    ListingStatus,
    ListingStatusUpdateIn,
    MaxApplicantBand,
    OpenInChatOut,
    ScanOut,
    SearchProfileIn,
    SearchProfileOut,
)
from app.repositories import jobs_repo
from app.routers.deps import get_session, resolve_active_profile_or_error
from app.services.errors import http_error
from app.services.jobboards.provider_registry import BoardProviderRegistry
from app.services.jobs import (
    listing_query,
    one_click_service,
    scan_presenter,
    scan_service,
    search_profile_service,
)
from app.services.profile_resolution import ProfileValidationError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/jobs")


# --- Search Profile ----------------------------------------------------------------------------


@router.get("/search-profile", response_model=SearchProfileOut)
async def get_search_profile(session: Session = Depends(get_session)) -> SearchProfileOut:
    """The saved Search Profile, or the defaults when the user has never saved one.

    Never 404s and never writes: ``updatedAt is None`` is how the response says "these are
    defaults, nothing was saved" (see the service's module docstring for why a GET must not
    persist them).
    """
    return search_profile_service.get_search_profile(session)


@router.put("/search-profile", response_model=SearchProfileOut)
async def put_search_profile(
    body: SearchProfileIn, session: Session = Depends(get_session)
) -> SearchProfileOut:
    """Replace the whole Search Profile. A PUT, not a PATCH: the form sends every field, so an
    empty list means the user emptied it rather than "unchanged"."""
    try:
        saved = search_profile_service.put_search_profile(session, body)
    except search_profile_service.SearchProfileValidationError as e:
        raise http_error(422, str(e)) from e
    session.commit()
    return saved


@router.post("/search-profile/suggest", response_model=SearchProfileOut)
async def suggest_search_profile(session: Session = Depends(get_session)) -> SearchProfileOut:
    """A Search Profile suggested from the Profile -- deterministic, no LLM, NOT saved.

    Resolves the Profile through the same read-only seam ``GET /api/profile`` uses, so "there
    is no profile yet" is the same 404 the rest of the app already answers with, rather than a
    suggestion that would pretend to be derived from data that does not exist.
    """
    resolved = resolve_active_profile_or_error(session)
    return search_profile_service.suggest_from_profile(resolved.profile)


# --- Job Boards --------------------------------------------------------------------------------


@router.get("/boards", response_model=BoardListOut)
async def list_boards() -> BoardListOut:
    """The Job Board catalog the Search Profile form renders its checkboxes from. Static: it
    needs neither a session nor a loaded adapter."""
    return search_profile_service.list_boards()


# --- Scans -------------------------------------------------------------------------------------


def build_registry() -> BoardProviderRegistry:
    """The Job Boards an Immediate Scan will call.

    Imported inside the function, exactly as ``scheduler.start`` does it and for the same
    reason: this is the one call in the HTTP layer that constructs the network-reaching
    adapters, and importing them at module scope would drag them into every test that merely
    imports a router. It is also the seam a test replaces with ``FakeJobBoard``s -- monkeypatch
    this name, not the registry module.
    """
    from app.services.jobboards.default_registry import build_default_registry

    return build_default_registry()


# Strong references to the Scan tasks in flight. ``asyncio`` only holds a WEAK reference to a
# task, so a running Scan whose only reference was a local variable in a handler can be garbage
# collected mid-flight; this set is what keeps it alive until it finishes. At most one entry in
# practice (the single-flight lock), and the done-callback empties it.
_scan_tasks: set[asyncio.Task] = set()

# How many event-loop turns the request may wait for the Scan to open its row. The Scan commits
# it BEFORE its first await (``scan_service.ScanRunner._run``, phase 1), so one turn is enough
# in practice; the bound only stops this loop from spinning forever if that ever changes.
_SCAN_START_TURNS = 100


def _interval_hours(session: Session) -> int | None:
    """The Search Profile's scan interval, or ``None`` when scheduling is off or nothing was
    ever saved. Feeds ``nextScanAt`` and nothing else."""
    row = jobs_repo.get_search_profile(session)
    return row.interval_hours if row is not None else None


def _scan_out(session: Session, scan: JobScan) -> ScanOut:
    return scan_presenter.to_scan_out(scan, interval_hours=_interval_hours(session))


def _already_running(session: Session, scan: JobScan | None) -> HTTPException:
    """The 409 for a second Immediate Scan (CONTEXT.md: at most one Scan at a time).

    The body is the CURRENT Scan, not a message: the UI's only sensible reaction to "one is
    already running" is to start polling that Scan, and making it re-fetch to find out which
    would be a round trip for something we already have in hand. ``HTTPException`` directly
    rather than ``http_error`` because that helper redacts a string body -- everything here is
    structured data this app wrote itself, and the one free-text field (a Board Status message)
    was already sanitized and redacted by the Scan engine on the way in.
    """
    if scan is None:
        # Only reachable in the sliver between the lock being taken and the ``running`` row
        # being committed. The web client accepts a 409 with no Scan in it.
        return http_error(409, "A Scan is already running.")
    return HTTPException(status_code=409, detail=_scan_out(session, scan).model_dump(mode="json"))


async def _wait_for_scan_row(task: asyncio.Task) -> int | None:
    """Give the freshly spawned Scan the event-loop turn it needs to open (and commit) its
    ``job_scans`` row, then report its id.

    This is what lets ``POST /scans`` answer 202 with the Scan itself instead of an empty
    acknowledgement the UI would have to chase. FastAPI's ``BackgroundTasks`` cannot do it --
    those run AFTER the response is composed, so the response could never name the Scan they
    create.
    """
    for _ in range(_SCAN_START_TURNS):
        if scan_service.default_runner.current_scan_id is not None or task.done():
            break
        await asyncio.sleep(0)
    return scan_service.default_runner.current_scan_id


async def _run_immediate_scan(engine: Engine) -> None:
    """The background Scan itself. Exceptions are logged here rather than escaping into a task
    nobody awaits -- the Scan engine has already closed its own row by then (its ``except``
    block), so the failure is visible in ``GET /scans/latest`` as a finished Scan, and the
    request that started it has long been answered."""
    try:
        await scan_service.run_scan(engine, build_registry(), "immediate")
    except scan_service.ScanAlreadyRunning:
        logger.info("immediate Scan skipped: a Scan is already running")
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("immediate Scan failed")


@router.post("/scans", response_model=ScanOut, status_code=202)
async def start_scan(session: Session = Depends(get_session)) -> ScanOut:
    """Immediate Scan (CONTEXT.md: Scan). 202 with the ``running`` Scan; 409 with the current
    one when a Scan already holds the single-flight lock.

    202, not 201: the response describes work that has STARTED, not a finished resource -- the
    boards have not been called yet, and the UI's next move is to poll ``/scans/current``.

    The lock check and the spawn are not a race: there is no ``await`` between them, so nothing
    else on this single event loop can take the lock in the gap. The scheduler still can, in
    the turn that follows -- and that is why ``_run_immediate_scan`` tolerates
    ``ScanAlreadyRunning``.
    """
    if scan_service.default_runner.is_running:
        raise _already_running(session, jobs_repo.get_running_scan(session))
    if jobs_repo.get_search_profile(session) is None:
        # Not a 404 and not an empty Scan: with no Search Profile there is nothing to search
        # for, and running seven boards on defaults the user never chose would be reaching the
        # network on their behalf (the same reason a GET does not persist those defaults).
        raise http_error(
            422, "Save a Search Profile before scanning: there is nothing to search for yet."
        )

    task = asyncio.create_task(_run_immediate_scan(session.get_bind()), name="job-immediate-scan")
    _scan_tasks.add(task)
    task.add_done_callback(_scan_tasks.discard)

    scan_id = await _wait_for_scan_row(task)
    if scan_id is None:
        # The Scan finished (or failed) before this coroutine was resumed -- reachable when no
        # board is enabled, since nothing in that Scan ever suspends.
        latest = jobs_repo.get_latest_scan(session)
        if latest is None:
            raise http_error(500, "The Scan could not be started.")
        return _scan_out(session, latest)
    scan = jobs_repo.get_scan(session, scan_id)
    if scan is None:  # pragma: no cover - phase 1 committed the row before setting the id
        raise http_error(500, "The Scan could not be started.")
    return _scan_out(session, scan)


@router.get(
    "/scans/current",
    response_model=ScanOut,
    responses={204: {"description": "No Scan is running"}},
)
async def get_current_scan(session: Session = Depends(get_session)):
    """The Scan holding the single-flight lock, or **204** when none is running.

    204 rather than ``200 null``: "nothing is running" is the normal state, not a resource with
    a null value, and it is what this endpoint answers most of the time -- the UI polls it only
    while a Scan runs. ``boards`` fills in as each board answers, which is what makes polling
    worth doing.
    """
    scan = jobs_repo.get_running_scan(session)
    if scan is None:
        return Response(status_code=204)
    return _scan_out(session, scan)


@router.get(
    "/scans/latest",
    response_model=ScanOut,
    responses={204: {"description": "Never scanned"}},
)
async def get_latest_scan(session: Session = Depends(get_session)):
    """The most recently started Scan, running or done -- the source of the Board Status flags
    and of ``nextScanAt``. **204** before the first Scan ever ran (a fresh install), for the
    same reason as ``/scans/current``."""
    scan = jobs_repo.get_latest_scan(session)
    if scan is None:
        return Response(status_code=204)
    return _scan_out(session, scan)


# --- Job Listings ------------------------------------------------------------------------------


@router.get("/listings", response_model=JobListingListOut)
async def list_listings(
    status: ListingStatus | None = Query(default=None),
    board: BoardId | None = Query(default=None),
    max_band: MaxApplicantBand | None = Query(default=None),
    include_dismissed: bool = Query(default=False),
    session: Session = Depends(get_session),
) -> JobListingListOut:
    """The ranked list of the LAST Scan (CONTEXT.md: Job Listing -- the list IS the last Scan).

    Query parameters are snake_case while the bodies are camelCase, as the frozen contract
    specifies. They are typed with the contract's own ``Literal``s, so an unknown board or a
    band nobody can pick is a 422 from Pydantic rather than a confidently empty list.

    Order is not negotiable and not a parameter: Visibility Score descending, id ascending.
    Every filter rule lives in ``services/jobs/listing_query.py``.
    """
    filters = listing_query.ListingFilters(
        status=status, board=board, max_band=max_band, include_dismissed=include_dismissed
    )
    return JobListingListOut(listings=listing_query.list_listings(session, filters))


@router.get("/listings/{listing_id}", response_model=JobListingOut)
async def get_listing(listing_id: int, session: Session = Depends(get_session)) -> JobListingOut:
    """One listing with its description and every Listing Source -- and the act of opening it
    is what marks it ``seen`` (CONTEXT.md: Listing Status). Only ``new`` advances; ``applied``
    and ``dismissed`` are the user's verdicts and reading the posting again does not undo them.

    404 for an id the last Scan does not have, which includes every id from a PREVIOUS Scan:
    listings are ephemeral, and answering with a different job would be worse than answering
    with nothing.
    """
    out = listing_query.open_listing(session, listing_id)
    if out is None:
        raise http_error(404, f"Job Listing {listing_id} not found")
    session.commit()
    return out


@router.patch("/listings/{listing_id}/status", response_model=JobListingOut)
async def patch_listing_status(
    listing_id: int, body: ListingStatusUpdateIn, session: Session = Depends(get_session)
) -> JobListingOut:
    """Set the user's verdict on a listing: ``seen`` / ``applied`` / ``dismissed``. ``new`` is
    not settable (the contract's ``Literal`` makes it a 422): a Scan writes it, and undoing a
    dismiss is ``seen``, not amnesia.

    Returns the updated listing rather than 204 so a card can re-render from the response
    alone. The status is stored by identity in the Listing Memory, so it outlives this listing
    row and a dismissed job stays hidden when a later Scan finds it again.
    """
    out = listing_query.set_listing_status(session, listing_id, body.status)
    if out is None:
        raise http_error(404, f"Job Listing {listing_id} not found")
    session.commit()
    return out


# --- One-click Resume / Abrir no chat (ticket 10) ------------------------------------------


@router.post(
    "/listings/{listing_id}/one-click-resume",
    response_class=Response,
    responses={
        200: {"content": {"application/pdf": {}}, "description": "The tailored resume"},
        409: {"description": "This listing is already generating"},
        422: {"description": "The posting is too short to tailor a resume to"},
        502: {"description": "The AI provider failed"},
    },
)
async def one_click_resume(
    listing_id: int,
    regenerate: bool = Query(
        default=False,
        description="1 spends a new LLM call even when the Listing Memory already holds one.",
    ),
    session: Session = Depends(get_session),
) -> Response:
    """The One-click Resume (CONTEXT.md), as a PDF attachment.

    Every status here is a different instruction to the user, which is why they are not one
    generic 500: **422** ``description_too_short`` is a fact about the posting that will not
    change on a retry (the web turns it into its own copy and never prints this code);
    **409** and **502** carry sentences written to be read, so the web shows them verbatim;
    **404** is an id the last Scan no longer has -- listings are ephemeral.

    A **200 costs nothing on the second click**: the Listing Memory already points at the
    generated ``resume_versions`` row, so it is re-rendered rather than regenerated. That is
    the whole reason ``regenerate`` is an explicit parameter and not a cache-busting guess.
    """
    try:
        pdf = await one_click_service.one_click_resume(
            session, listing_id, regenerate=regenerate
        )
    except one_click_service.ListingNotFound as e:
        raise http_error(404, str(e)) from e
    except one_click_service.DescriptionTooShort as e:
        raise http_error(422, str(e)) from e
    except one_click_service.OneClickAlreadyRunning as e:
        raise http_error(409, str(e)) from e
    except one_click_service.OneClickGenerationFailed as e:
        logger.exception("one-click resume failed for listing %s", listing_id)
        raise http_error(502, str(e)) from e
    except one_click_service.PdfRenderFailed as e:
        logger.exception("one-click PDF render failed for listing %s", listing_id)
        raise http_error(500, str(e)) from e
    except FileNotFoundError as e:
        raise http_error(404, str(e)) from e
    except ProfileValidationError as e:
        raise http_error(400, str(e)) from e

    return Response(
        content=pdf.content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{pdf.filename}"'},
    )


@router.post("/listings/{listing_id}/open-in-chat", response_model=OpenInChatOut)
async def open_listing_in_chat(
    listing_id: int, session: Session = Depends(get_session)
) -> OpenInChatOut:
    """Open a Job Listing as an ordinary chat session and return its id -- nothing else.

    No LLM call and no turn is run here (the Job Monitor adds NO new path through the chat):
    the session is created with the posting as its ``job_description`` and as its first ``user``
    message, and the frontend then selects it and streams a turn exactly as if the posting had
    been pasted -- Analysis, Pending Proposal, human approval.
    """
    try:
        chat_session = one_click_service.open_in_chat(session, listing_id)
    except one_click_service.ListingNotFound as e:
        raise http_error(404, str(e)) from e
    session.commit()
    return OpenInChatOut(sessionId=int(chat_session.id or 0))
