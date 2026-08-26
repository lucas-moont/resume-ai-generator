"""Reading the Job Monitor's list: Job Listings joined with their Listing Memory (v7 ticket 09).

The two halves of a listing live in two tables on purpose (CONTEXT.md: Job Listing vs Listing
Memory) -- the ephemeral row the last Scan wrote, and the durable memory keyed by identity --
and ``JobListingOut`` is the two of them together. Composing them is deliberately NOT in
``jobs_repo`` (ticket 02, decision 9: filtering by status/board/band would explode into a
combinatorial set of keyword arguments there), and deliberately not in the router either: every
rule below is a product rule that deserves a test without an HTTP client in it.

The rules, once:

* **Order is not a parameter.** Visibility Score descending, id ascending, always -- the ONE
  order this product has. It comes from ``jobs_repo.list_listings`` and is never re-sorted here.
* **``dismissed`` is hidden unless asked for.** That is what dismissing a job means. A Scan
  already leaves a dismissed listing out of ``job_listings`` entirely; the ones this filter
  catches are those dismissed AFTER the Scan that found them.
* **``?status=`` narrows within what is visible.** ``?status=dismissed`` alone therefore returns
  nothing, and needs ``?include_dismissed=1`` to return anything -- the same composition the web
  client's own mock encodes, and the honest reading of two independent filters.
* **``unknown`` never fails a band cap** (CONTEXT.md: Applicant Band). The rule is
  ``scan_service.passes_band_cap``, imported rather than restated: the Scan applies the Search
  Profile's cap when it writes, this applies the request's, and two copies of one rule would
  eventually disagree.
* **``description`` travels only in the detail.** Fifty full postings is a payload nobody reads;
  ``descriptionWordCount`` is always there so a card can pre-disable One-click without it.

Writes (marking ``seen``, setting a status) go through ``jobs_repo``; the ROUTER commits, as
everywhere else in this codebase.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlmodel import Session

from app.db.tables import JobListing, ListingMemory, ListingSource
from app.domain.recency import as_utc
from app.domain.schemas import JobListingOut, ListingSourceOut
from app.repositories import jobs_repo
from app.services.jobs.scan_service import passes_band_cap

# What a listing's status is when nothing remembers it. A Scan writes a memory for every job it
# finds, so this is the fallback for a listing whose memory was wiped, not the normal path.
DEFAULT_STATUS = "new"


@dataclass(frozen=True)
class ListingFilters:
    """The query string of ``GET /api/jobs/listings``, parsed. Every field optional, every
    default the widest one -- an unfiltered call returns the whole ranked list minus what the
    user dismissed."""

    status: str | None = None
    board: str | None = None
    max_band: str | None = None
    include_dismissed: bool = False


def status_of(memory: ListingMemory | None) -> str:
    return memory.status if memory is not None else DEFAULT_STATUS


def has_one_click_resume(memory: ListingMemory | None) -> bool:
    """Whether the Listing Memory already holds a One-click Resume for this identity -- what
    turns the detail view's button into "Baixar PDF" / "Regerar" instead of spending an LLM
    call again."""
    return memory is not None and memory.resume_version_id is not None


def to_listing_out(
    listing: JobListing,
    sources: list[ListingSource],
    memory: ListingMemory | None,
    *,
    include_description: bool,
) -> JobListingOut:
    """One listing on the wire. ``include_description`` is the list/detail difference and the
    only one: everything else, ``descriptionWordCount`` included, is identical in both."""
    return JobListingOut(
        id=int(listing.id or 0),
        title=listing.title,
        company=listing.company,
        location=listing.location,
        isRemote=listing.is_remote,
        description=listing.description if include_description else None,
        descriptionWordCount=listing.description_word_count,
        datePosted=as_utc(listing.date_posted),
        isRepost=listing.is_repost,
        applicantBand=listing.applicant_band,  # type: ignore[arg-type]
        fitScore=listing.fit_score,
        fitEstimated=listing.fit_estimated,
        visibilityScore=listing.visibility_score,
        locale=listing.locale,
        status=status_of(memory),  # type: ignore[arg-type]
        hasOneClickResume=has_one_click_resume(memory),
        sources=[_source_out(s) for s in sources],
    )


def _source_out(source: ListingSource) -> ListingSourceOut:
    return ListingSourceOut(
        board=source.board,  # type: ignore[arg-type]
        url=source.url,
        datePosted=as_utc(source.date_posted),
        applicantBand=source.applicant_band,  # type: ignore[arg-type]
    )


def matches(
    listing: JobListing, sources: list[ListingSource], memory: ListingMemory | None, filters: ListingFilters
) -> bool:
    """Whether one listing survives the request's filters (see the module docstring for why
    each rule reads the way it does). Pure -- no session, no I/O -- so the filter matrix is
    testable as a table."""
    status = status_of(memory)
    if status == "dismissed" and not filters.include_dismissed:
        return False
    if filters.status is not None and status != filters.status:
        return False
    if filters.board is not None and not any(s.board == filters.board for s in sources):
        return False
    if not passes_band_cap(listing.applicant_band, filters.max_band):
        return False
    return True


def list_listings(
    session: Session, filters: ListingFilters | None = None
) -> list[JobListingOut]:
    """The ranked list of the last Scan, filtered. Three queries regardless of how many
    listings there are: the rows, all their sources, all their memories."""
    filters = filters or ListingFilters()
    rows = jobs_repo.list_listings(session)
    if not rows:
        return []
    sources_by_listing = jobs_repo.get_sources_by_listing(session, [int(r.id or 0) for r in rows])
    memories = jobs_repo.get_memories(session, [r.identity_key for r in rows])

    out: list[JobListingOut] = []
    for row in rows:
        sources = sources_by_listing.get(int(row.id or 0), [])
        memory = memories.get(row.identity_key)
        if not matches(row, sources, memory, filters):
            continue
        out.append(to_listing_out(row, sources, memory, include_description=False))
    return out


def get_listing(session: Session, listing_id: int) -> JobListingOut | None:
    """One listing WITH its description and every source, or ``None`` when the last Scan has
    no such id (which includes an id from a PREVIOUS Scan -- see ``JobListing``'s docstring on
    why those resolve to nothing rather than to a different job)."""
    row = jobs_repo.get_listing(session, listing_id)
    if row is None:
        return None
    memory = jobs_repo.get_memory(session, row.identity_key)
    sources = jobs_repo.get_listing_sources(session, int(row.id or 0))
    return to_listing_out(row, sources, memory, include_description=True)


def open_listing(session: Session, listing_id: int) -> JobListingOut | None:
    """The detail view's read: ``get_listing`` plus the side effect that OPENING a listing is
    what marks it ``seen`` (CONTEXT.md: Listing Status ``new -> seen``).

    Only ``new`` is advanced. ``applied`` and ``dismissed`` are the user's own verdicts and
    reading the posting again does not undo either; ``seen`` is already there. The caller
    commits.
    """
    row = jobs_repo.get_listing(session, listing_id)
    if row is None:
        return None
    memory = jobs_repo.get_memory(session, row.identity_key)
    if status_of(memory) == DEFAULT_STATUS:
        memory = _set_status(session, row.identity_key, "seen", memory)
    sources = jobs_repo.get_listing_sources(session, int(row.id or 0))
    return to_listing_out(row, sources, memory, include_description=True)


def set_listing_status(
    session: Session, listing_id: int, status: str
) -> JobListingOut | None:
    """``PATCH /listings/{id}/status``. Returns the listing as it now IS -- the card re-renders
    from the response alone -- or ``None`` when the id is not in the last Scan. The caller
    commits.

    Addressed by listing id but stored by identity: the status outlives this listing row, so
    dismissing a job today still hides it when a Scan finds it again next week.
    """
    row = jobs_repo.get_listing(session, listing_id)
    if row is None:
        return None
    memory = _set_status(
        session, row.identity_key, status, jobs_repo.get_memory(session, row.identity_key)
    )
    sources = jobs_repo.get_listing_sources(session, int(row.id or 0))
    return to_listing_out(row, sources, memory, include_description=True)


def remember_one_click_resume(
    session: Session,
    identity_key: str,
    *,
    resume_version_id: int,
    memory: ListingMemory | None,
) -> ListingMemory:
    """Point a Job Listing's memory at the One-click Resume just generated for it (v7 ticket
    10) -- what makes ``hasOneClickResume`` true and the SECOND click free.

    Goes through ``_write_memory`` for the same reason ``_set_status`` does: a click is not a
    sighting. The caller commits.
    """
    return _write_memory(
        session, identity_key, memory=memory, resume_version_id=resume_version_id
    )


def _set_status(
    session: Session, identity_key: str, status: str, memory: ListingMemory | None
) -> ListingMemory:
    """Write a status the USER chose, without pretending the Monitor just saw the job."""
    return _write_memory(session, identity_key, memory=memory, status=status)


def _write_memory(
    session: Session,
    identity_key: str,
    *,
    memory: ListingMemory | None,
    status: str | None = None,
    resume_version_id: int | None = None,
) -> ListingMemory:
    """Write to the Listing Memory on the USER's account, without pretending the Monitor just
    saw the job.

    ``upsert_memory`` bumps ``last_seen_at`` on every call, which is right for the Scan (its
    only other caller) and wrong here: ``last_seen_at`` is the baseline Repost detection
    compares a posting's date against (``scan_service.is_repost``), so letting a click move it
    forward would make a job reposted between the Scan and the click read as not-a-Repost on
    the next Scan. So the previous value is put back afterwards -- deliberately NOT by passing
    ``seen_at``, which would drag ``status_changed_at`` back with it and misdate the very thing
    a status write exists to record. Same shape as the Scan engine overriding ``finished_at``
    right after ``finish_scan``.

    One function rather than one per column (status in ticket 09, the One-click Resume in
    ticket 10) because the rule being protected is the same rule, and two copies of it would
    eventually disagree about which timestamps a click may move.

    ``None`` means "leave this column alone" for BOTH columns here -- not ``upsert_memory``'s
    three-way KEEP/None/value, whose "clear it" arm exists for the Scan (a Repost must clear a
    stale Fit) and has no meaning on a click: nothing the user does from the UI un-generates a
    resume or un-sets a status.
    """
    previous_seen: datetime | None = memory.last_seen_at if memory is not None else None
    row = jobs_repo.upsert_memory(
        session,
        identity_key,
        status=status,
        resume_version_id=jobs_repo.KEEP if resume_version_id is None else resume_version_id,
    )
    if previous_seen is not None:
        row.last_seen_at = previous_seen
        session.add(row)
        session.flush()
    return row
