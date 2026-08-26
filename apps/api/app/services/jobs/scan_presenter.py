"""One Scan row as the wire's ``ScanOut`` (v7 ticket 09).

A presenter rather than a few lines inside the router, because THREE endpoints serve the same
shape and one of them is an error body: ``GET /scans/current``, ``GET /scans/latest`` and the
409 that refuses a second Immediate Scan. A Scan rendered three ways is a Scan rendered once.

Two conversions live here, and both are the reason this is not a plain
``ScanOut.model_validate``:

* ``board_statuses`` is a MAP in the database and a LIST on the wire (ticket 01, decision 8).
  The map is how the engine fills it in as each board answers; the list is what gives the
  BoardStatusBar a stable order -- the catalog's order, the same one the Search Profile form
  and the engine's own ``_ordered_statuses`` use.
* ``nextScanAt`` is COMPUTED, never persisted: only the last Scan knows when the next one is
  due, and the interval it is due after lives in the Search Profile, which the scheduler
  re-reads every turn.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import get_args

from app.db.tables import JobScan
from app.domain.recency import as_utc
from app.domain.schemas import BoardStatus, BoardStatusOut, ScanOut
from app.repositories import jobs_repo
from app.services.jobboards.provider_registry import BOARD_SPECS

_KNOWN_STATUSES: frozenset[str] = frozenset(get_args(BoardStatus))


def board_statuses_out(scan: JobScan) -> list[BoardStatusOut]:
    """``job_scans.board_statuses`` as an ordered list, in catalog order.

    A board id the catalog no longer knows is DROPPED rather than served: the column stores
    plain strings so an old Scan survives a board being retired (same reason
    ``search_profile_service._to_out`` filters on the way out), and validating it against
    ``BoardId`` here would turn every read of that Scan's history into a 500.

    A status string outside ``BoardStatus`` is reported as ``error`` with its message intact.
    Nothing this app writes can produce one -- the engine only ever stores the four -- but
    "we cannot read what this board reported" IS an error, and it beats either dropping the
    board (the user is owed a flag for every board that ran) or a 500.
    """
    stored = jobs_repo.get_board_statuses(scan)
    out: list[BoardStatusOut] = []
    for spec in BOARD_SPECS:
        entry = stored.get(spec.id)
        if not isinstance(entry, dict):
            continue
        status = entry.get("status")
        message = entry.get("message")
        count = entry.get("count")
        out.append(
            BoardStatusOut(
                board=spec.id,
                status=status if status in _KNOWN_STATUSES else "error",  # type: ignore[arg-type]
                message=message if isinstance(message, str) else None,
                count=count if isinstance(count, int) and not isinstance(count, bool) else 0,
            )
        )
    return out


def next_scan_at(scan: JobScan, interval_hours: int | None) -> datetime | None:
    """When the scheduler will next wake, or ``None`` when nobody can say.

    ``None`` in three cases, all of them honest rather than defensive:

    * scheduling is off (``interval_hours is None``) -- Immediate Scans still work, but nothing
      is scheduled, so a "próxima varredura" label would be inventing one;
    * this Scan is still running -- the next one is due after THIS one, whose end is unknown;
    * the Scan has no ``finished_at`` (a row left behind by a crashed process).

    Measured from ``finished_at``, as the frozen contract specifies (``ScanOut.nextScanAt``:
    "``finishedAt + interval_hours``"). Worth knowing when reading a label that looks slightly
    late: the scheduler itself measures due-ness from ``started_at`` (ticket 07, decision 10,
    so that an interval survives a restart), so the real wake-up is earlier than this by
    exactly how long the Scan took -- seconds, normally.
    """
    if interval_hours is None or scan.status == "running":
        return None
    finished = as_utc(scan.finished_at)
    if finished is None:
        return None
    return finished + timedelta(hours=interval_hours)


def to_scan_out(scan: JobScan, *, interval_hours: int | None = None) -> ScanOut:
    """The whole Scan as the wire shape. ``interval_hours`` comes from the Search Profile
    (``None`` when it is off or was never saved) and only feeds ``nextScanAt``."""
    return ScanOut(
        id=int(scan.id or 0),
        startedAt=as_utc(scan.started_at) or scan.started_at,
        finishedAt=as_utc(scan.finished_at),
        trigger=scan.trigger,  # type: ignore[arg-type]
        status=scan.status,  # type: ignore[arg-type]
        boards=board_statuses_out(scan),
        listingsFound=scan.listings_found,
        listingsScored=scan.listings_scored,
        nextScanAt=next_scan_at(scan, interval_hours),
    )
