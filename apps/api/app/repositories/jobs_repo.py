"""Repository for the Job Monitor's five tables (v7 ticket 02): `search_profile`, `job_scans`,
`job_listings`, `listing_sources`, `listing_memory`.

Same convention as every other repository here: **callers own the transaction** (commit /
rollback). These functions only `add`/`delete`/`flush`, so several calls on one Session compose
into ONE transaction -- which is not a stylistic detail for this module but the mechanism the
Scan's atomicity rests on. `replace_listings` deletes the previous Scan's listings and writes
the new ones through the same Session, so a failure anywhere between them (or in the memory
updates that follow) rolls the whole thing back and the user keeps the PREVIOUS list, rather
than being left with an empty Job Monitor. Nothing here commits.

Two shapes of state live side by side, and the split is the point (CONTEXT.md: Job Listing vs
Listing Memory):

  * `job_listings` + `listing_sources` are EPHEMERAL -- the list IS the last Scan. They are
    truncated and rewritten wholesale by `replace_listings`; a listing id means nothing once
    the next Scan finishes.
  * `listing_memory` is DURABLE, keyed by `identity_key`, and only ever upserted. It is what
    makes a dismissed job stay dismissed and a Fit Score get paid for once.

The JSON columns (the Search Profile's lists, a Scan's board statuses) are plain TEXT, encoded
and decoded here rather than by the caller -- the same rule app/db/tables.py's module docstring
states for every other JSON column in this schema.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from datetime import datetime

from sqlalchemy import delete
from sqlmodel import Session, select

from app.db.tables import (
    SEARCH_PROFILE_ID,
    JobListing,
    JobScan,
    ListingMemory,
    ListingSource,
    SearchProfile,
    _utcnow,
)


class _Keep:
    """Sentinel for "leave this column exactly as it is", distinct from ``None``, which CLEARS
    it. Both are real instructions for `upsert_memory`: a Scan that only reattaches a memory
    touches neither the Fit nor the One-click Resume, while a Repost whose description changed
    must actively clear the stale `fit_score`/`fit_description_hash` so the listing re-enters
    the LLM scoring stage instead of carrying a number computed for different text."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return "<keep>"


KEEP = _Keep()


def _dumps(values: Iterable[str]) -> str:
    return json.dumps(list(values))


def _loads_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    decoded = json.loads(raw)
    return list(decoded) if isinstance(decoded, list) else []


# --- Search Profile --------------------------------------------------------------------------


def get_search_profile(session: Session) -> SearchProfile | None:
    """The single Search Profile row, or ``None`` when the user has never saved one.

    ``None`` is a meaningful state, not an error: the suggestion endpoint builds a Search
    Profile from the Profile WITHOUT persisting it (that is what ``SearchProfileOut.updatedAt
    is None`` says on the wire), and a scheduled Scan with no row here has nothing to search
    for and does not run.
    """
    return session.get(SearchProfile, SEARCH_PROFILE_ID)


def put_search_profile(
    session: Session,
    *,
    roles: Sequence[str],
    locations: Sequence[str],
    remote: str,
    languages: Sequence[str],
    boards: Sequence[str],
    max_applicant_band: str | None,
    interval_hours: int | None,
) -> SearchProfile:
    """Creates or replaces the Search Profile -- a PUT, never a PATCH: every field is written
    from the arguments, so an omitted list is an EMPTY list, not "unchanged". That mirrors the
    contract (`SearchProfileIn` sends the whole form) and keeps "the user deselected every
    board" expressible; a partial update would silently turn it into "kept the old boards".

    The row always has id ``SEARCH_PROFILE_ID``: get-or-create on that one key is what enforces
    the singleton (see `SearchProfile`'s docstring), and it is why saving twice updates rather
    than accumulating profiles.
    """
    row = session.get(SearchProfile, SEARCH_PROFILE_ID)
    if row is None:
        row = SearchProfile(id=SEARCH_PROFILE_ID)
    row.roles = _dumps(roles)
    row.locations = _dumps(locations)
    row.remote = remote
    row.languages = _dumps(languages)
    row.boards = _dumps(boards)
    row.max_applicant_band = max_applicant_band
    row.interval_hours = interval_hours
    row.updated_at = _utcnow()
    session.add(row)
    session.flush()
    session.refresh(row)
    return row


def get_roles(row: SearchProfile) -> list[str]:
    """Decodes ``roles``. Four one-line accessors (rather than one dict) so a caller reading the
    Search Profile gets a typed ``list[str]`` per field and a typo is an AttributeError here,
    not a silently empty query sent to seven job boards."""
    return _loads_list(row.roles)


def get_locations(row: SearchProfile) -> list[str]:
    return _loads_list(row.locations)


def get_languages(row: SearchProfile) -> list[str]:
    return _loads_list(row.languages)


def get_boards(row: SearchProfile) -> list[str]:
    """The board ids switched ON. ``str``, not ``BoardId``: a row written before a board was
    retired can still name it, and the Scan engine skips an id with no registered provider --
    validating that Literal is the router's job, on the way in."""
    return _loads_list(row.boards)


# --- Scans -----------------------------------------------------------------------------------


def start_scan(session: Session, *, trigger: str) -> JobScan:
    """Opens a ``running`` Scan row. Deliberately does NOT check for another running Scan:
    single-flight is an in-process ``asyncio`` lock in the Scan service (spec Backend-3), and
    duplicating the rule here as a DB read would be a second, weaker answer -- one that races
    exactly where the lock does not. Callers acquire the lock, then call this."""
    row = JobScan(trigger=trigger, status="running")
    session.add(row)
    session.flush()
    session.refresh(row)
    return row


def get_running_scan(session: Session) -> JobScan | None:
    """The Scan currently holding the single-flight state, if any -- what ``GET /scans/current``
    polls and what the 409 body carries. Most recent first, so a crashed process that left a
    stale ``running`` row behind cannot hide a genuinely current Scan."""
    return session.exec(
        select(JobScan).where(JobScan.status == "running").order_by(JobScan.started_at.desc())
    ).first()


def get_latest_scan(session: Session) -> JobScan | None:
    """The most recently STARTED Scan, running or done (``GET /scans/latest``). Ordered by
    ``started_at`` and then by id: two Scans can share a timestamp on a coarse clock, and the
    id is the only strictly increasing tiebreaker."""
    return session.exec(
        select(JobScan).order_by(JobScan.started_at.desc(), JobScan.id.desc())
    ).first()


def get_scan(session: Session, scan_id: int) -> JobScan | None:
    """One Scan by id. Added in ticket 07: the engine opens a SECOND Session to write the
    results (the first one only opened the ``running`` row and committed it, so the UI can poll
    it while the boards are being called), and it needs the same row back in that Session to
    close it."""
    return session.exec(select(JobScan).where(JobScan.id == scan_id)).first()


def list_recent_scans(session: Session, *, limit: int = 100) -> list[JobScan]:
    """The most recently started Scans, newest first (ticket 07).

    Reads history so the engine can answer "when did this board last actually answer us?" --
    the fact that decides ``skipped``. That answer is DERIVED from ``board_statuses`` rather
    than kept in a column of its own: a per-board "last contacted" table would be a second
    source of truth for something the Scan history already records exactly, and one that could
    drift from it after a crash between the two writes.

    ``limit`` bounds the walk: only the newest scan in which a given board reported ``ok``
    matters, so the loop stops at the first hit per board and the cap only guards against
    reading years of history on a board that has never answered.
    """
    return list(
        session.exec(
            select(JobScan).order_by(JobScan.started_at.desc(), JobScan.id.desc()).limit(limit)
        ).all()
    )


def finish_scan(
    session: Session,
    row: JobScan,
    *,
    board_statuses: dict[str, dict],
    listings_found: int,
    listings_scored: int,
) -> JobScan:
    """Closes a Scan: ``done``, ``finished_at``, the per-board report and the two counters.

    ``done`` regardless of how the boards fared -- there is no ``failed`` status, because a Scan
    where every board blocked still produced the fact that they blocked (CONTEXT.md: Scan is
    partial, never failed). Idempotent enough to be safe in a ``finally``: calling it on an
    already-closed row just rewrites the same fields.
    """
    row.status = "done"
    row.finished_at = _utcnow()
    row.board_statuses = json.dumps(board_statuses)
    row.listings_found = listings_found
    row.listings_scored = listings_scored
    session.add(row)
    session.flush()
    session.refresh(row)
    return row


def get_board_statuses(row: JobScan) -> dict[str, dict]:
    """Decodes ``board_statuses`` -- ``{board_id: {"status": ..., "message": ..., "count": ...}}``.
    The router turns this map into the wire's ordered ``BoardStatusOut[]``."""
    if not row.board_statuses:
        return {}
    decoded = json.loads(row.board_statuses)
    return decoded if isinstance(decoded, dict) else {}


# --- Job Listings (ephemeral) -----------------------------------------------------------------


def replace_listings(
    session: Session,
    *,
    scan_id: int,
    listings: Sequence[tuple[JobListing, Sequence[ListingSource]]],
) -> list[JobListing]:
    """Truncate-and-write: drops EVERY previous listing and source, then writes this Scan's,
    all through the caller's single transaction (see the module docstring). The old list
    survives untouched if anything downstream raises before the commit.

    Takes ``(listing, sources)`` pairs of unsaved rows rather than a parallel set of DTOs: the
    table is already the definition of a listing's shape, and duplicating its sixteen columns
    into a write-model here would just be a second place to forget one. This function owns two
    things the caller must not set -- ``scan_id`` and each source's ``listing_id`` -- so the
    linkage cannot be built wrong.

    Sources are deleted FIRST and explicitly, even though the FK carries ON DELETE CASCADE: the
    cascade is the database's safety net, while the explicit delete is what keeps SQLAlchemy's
    identity map from holding a source whose listing this Session just removed.
    """
    session.exec(delete(ListingSource))
    session.exec(delete(JobListing))

    for listing, _sources in listings:
        listing.id = None
        listing.scan_id = scan_id
        session.add(listing)
    session.flush()  # assigns listing ids -- required before the sources can point at them

    for listing, sources in listings:
        for source in sources:
            source.id = None
            source.listing_id = listing.id
            session.add(source)
    session.flush()

    return [listing for listing, _ in listings]


def list_listings(session: Session) -> list[JobListing]:
    """Every listing of the latest Scan, ordered by ``visibility_score`` descending -- the ONE
    order this product has (CONTEXT.md: Visibility Score is the ranking key), with the id as a
    stable tiebreaker so two equally-scored listings do not swap places between requests.

    No status/board/band filters here: they need the Listing Memory joined in and the Search
    Profile's cap read, which is the router's composition to make (ticket 09), not a
    combinatorial explosion of keyword arguments in the repository.
    """
    return list(
        session.exec(
            select(JobListing).order_by(JobListing.visibility_score.desc(), JobListing.id)
        ).all()
    )


def get_listing(session: Session, listing_id: int) -> JobListing | None:
    """One listing by id, via a plain SELECT (not ``Session.get``) for the same reason
    `proposal_repo.get` does: the row may have been deleted out from under an
    already-identity-mapped instance -- here by the Scan that finished mid-request -- and
    ``Session.get`` would raise ``ObjectDeletedError`` where ``None`` is the honest answer for
    an id that the latest Scan no longer has."""
    return session.exec(select(JobListing).where(JobListing.id == listing_id)).first()


def get_sources_by_listing(
    session: Session, listing_ids: Sequence[int]
) -> dict[int, list[ListingSource]]:
    """Every listing's sources in ONE query, keyed by ``listing_id`` (ticket 09).

    The list endpoint needs the sources of all fifty listings at once -- the cards render a
    chip per board and the ``?board=`` filter asks which boards a listing was found on -- and
    calling ``get_listing_sources`` per row would be fifty queries for one page. Same ordering
    as the single-listing reader (by id, i.e. the order the Scan wrote them, i.e. the order the
    boards answered in); a listing with no sources is simply absent from the map.
    """
    if not listing_ids:
        return {}
    rows = session.exec(
        select(ListingSource)
        .where(ListingSource.listing_id.in_(list(listing_ids)))
        .order_by(ListingSource.id)
    ).all()
    grouped: dict[int, list[ListingSource]] = {}
    for row in rows:
        grouped.setdefault(row.listing_id, []).append(row)
    return grouped


def get_listing_sources(session: Session, listing_id: int) -> list[ListingSource]:
    """Every board this listing was found on (CONTEXT.md: a Job Listing always keeps every
    source link), ordered by id -- i.e. the order the Scan wrote them, which is the order the
    boards answered in."""
    return list(
        session.exec(
            select(ListingSource)
            .where(ListingSource.listing_id == listing_id)
            .order_by(ListingSource.id)
        ).all()
    )


# --- Listing Memory (durable) -------------------------------------------------------------


def get_memory(session: Session, identity_key: str) -> ListingMemory | None:
    return session.exec(
        select(ListingMemory).where(ListingMemory.identity_key == identity_key)
    ).first()


def get_memories(session: Session, identity_keys: Sequence[str]) -> dict[str, ListingMemory]:
    """Bulk lookup keyed by ``identity_key`` -- how a Scan reattaches memories to the listings
    it just found, in one query instead of one per listing. Keys with no memory are simply
    absent from the result (a job seen for the first time)."""
    if not identity_keys:
        return {}
    rows = session.exec(
        select(ListingMemory).where(ListingMemory.identity_key.in_(list(identity_keys)))
    ).all()
    return {row.identity_key: row for row in rows}


def upsert_memory(
    session: Session,
    identity_key: str,
    *,
    status: str | None = None,
    fit_score: int | None | _Keep = KEEP,
    fit_description_hash: str | None | _Keep = KEEP,
    resume_version_id: int | None | _Keep = KEEP,
    seen_at: datetime | None = None,
) -> ListingMemory:
    """The ONE write path into the Listing Memory: creates the row for an identity seen for the
    first time, updates it otherwise. Idempotent by ``identity_key`` -- calling it twice for the
    same job produces one row, and ``first_seen_at`` keeps the FIRST time, which is the only
    field a repeat call can never change.

    Every optional column distinguishes three intents: omit it to leave it alone (``KEEP``),
    pass ``None`` to clear it, pass a value to set it. ``status`` is the exception -- it is NOT
    NULL, so ``None`` there can only mean "leave alone", and ``status_changed_at`` moves only
    when the status actually differs. A Scan reattaching a memory therefore bumps
    ``last_seen_at`` and nothing else, which is what keeps "dismissed six months ago" readable
    as exactly that.

    ``seen_at`` overrides the clock for the timestamps -- for the Scan, which writes one
    consistent instant across every memory it touches, and for tests.

    No locking or ON CONFLICT: the app is single-user and local, and at most one Scan runs at a
    time, so the read-then-write window here has no second writer to race with. The unique index
    on ``identity_key`` is the backstop that turns a future violation of that assumption into an
    IntegrityError rather than a duplicated memory.
    """
    now = seen_at or _utcnow()
    row = get_memory(session, identity_key)
    if row is None:
        row = ListingMemory(
            identity_key=identity_key,
            status=status or "new",
            first_seen_at=now,
            last_seen_at=now,
            status_changed_at=now,
        )
    else:
        row.last_seen_at = now
        if status is not None and status != row.status:
            row.status = status
            row.status_changed_at = now

    if not isinstance(fit_score, _Keep):
        row.fit_score = fit_score
    if not isinstance(fit_description_hash, _Keep):
        row.fit_description_hash = fit_description_hash
    if not isinstance(resume_version_id, _Keep):
        row.resume_version_id = resume_version_id

    session.add(row)
    session.flush()
    session.refresh(row)
    return row
