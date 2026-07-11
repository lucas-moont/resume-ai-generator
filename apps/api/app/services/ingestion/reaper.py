"""Source Document reaper (ticket 04, debt c): reconciles the two crash-window orphan shapes an
interrupted upload can leave behind (CONTEXT.md: Source Document lifecycle
stored -> extracted -> proposed -> applied | rejected | failed).

Crash windows:
  1. A file lands on disk (``storage.store_upload``) but the process dies before the DB insert
     that follows it ever commits -- an unreferenced file under ``uploads/`` with no
     ``source_documents`` row pointing at its path.
  2. A row is inserted at ``status='stored'`` or promoted to ``'extracted'`` but the process
     dies before the NEXT transition (extraction, or the merge proposal) ever commits -- a row
     stuck in a transient status forever, since nothing else ever revisits it once the request
     that would have advanced it is gone.

Neither shape is a live "in progress" request -- both only exist because the request that
created them never finished. ``reconcile()`` treats any transient row OLDER than an injectable
``stale_after`` threshold as abandoned: it becomes ``'failed'`` with a recorded, honest reason.
The SAME staleness discipline applies to the orphaned-file sweep (an unreferenced file newer
than the threshold could still be mid-upload -- the file is written by ``store_upload`` slightly
before the DB insert that references it commits, in the SAME request) so a concurrent call to
``reconcile()`` (not just the startup one) never races an in-flight upload.

Called once at FastAPI startup (``app.main``'s lifespan) and importable standalone for a manual
reconcile or a future scheduled job -- ``reconcile(engine, ...)`` is the single public seam
either caller goes through. ``now``/``stale_after``/``uploads_dir`` are all injectable
(pre-agreed test seam, ticket 04) so tests never depend on the real clock, a real elapsed hour,
or the real ``data/uploads`` directory.

Timestamps: ``SourceDocument.created_at`` round-trips through SQLite as a naive ``datetime``
(no tzinfo) -- see ``app.db.tables``'s ``_utcnow()``, which writes UTC but SQLite has no native
timezone-aware storage. ``now`` here is therefore also naive UTC by convention (never
timezone-aware) so the two compare directly; ``datetime.now(timezone.utc).replace(tzinfo=None)``
is what production passes implicitly via the default.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from app import config as config_module
from app.db.tables import SourceDocument

logger = logging.getLogger(__name__)

# CONTEXT.md: Source Document lifecycle -- these two are the only non-terminal statuses; every
# other status ('proposed', 'applied', 'rejected', 'failed') is already settled and must never
# be touched by the reaper, regardless of age.
_TRANSIENT_STATUSES = ("stored", "extracted")

DEFAULT_STALE_AFTER = timedelta(hours=1)


def _naive_utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _epoch_utc(dt: datetime) -> float:
    """``datetime.timestamp()`` on a NAIVE datetime assumes it is in the system's LOCAL
    timezone, not UTC -- a footgun here since ``now``/``created_at`` are naive-but-UTC by this
    module's convention (see module docstring) while file mtimes (``Path.stat().st_mtime``) are
    real UTC epoch seconds. Explicitly attaching ``timezone.utc`` before converting is what
    makes the two comparable regardless of the host machine's local timezone."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _reap_stale_transient_rows(session: Session, *, now: datetime, stale_after: timedelta) -> int:
    cutoff = now - stale_after
    rows = session.exec(
        select(SourceDocument).where(SourceDocument.status.in_(_TRANSIENT_STATUSES))
    ).all()
    reaped = 0
    for row in rows:
        if row.created_at > cutoff:
            continue
        reason = (
            f"Reaped: stuck in '{row.status}' since {row.created_at.isoformat()} "
            "(the process likely crashed mid-upload)"
        )
        row.status = "failed"
        row.error = reason
        session.add(row)
        reaped += 1
        logger.warning("reaper: source_document %s -> failed (%s)", row.id, reason)
    if reaped:
        session.flush()
    return reaped


def _sweep_orphaned_upload_files(
    session: Session, *, uploads_dir: Path, now: datetime, stale_after: timedelta
) -> int:
    if not uploads_dir.exists():
        return 0
    cutoff_ts = _epoch_utc(now - stale_after)
    referenced_names = {
        Path(path).name for path in session.exec(select(SourceDocument.stored_path)).all()
    }
    swept = 0
    for entry in uploads_dir.iterdir():
        if not entry.is_file() or entry.name in referenced_names:
            continue
        if entry.stat().st_mtime > cutoff_ts:
            continue  # too recent -- could still be mid-upload, not yet committed to the DB
        entry.unlink()
        swept += 1
        logger.warning("reaper: removed orphaned upload file %s", entry)
    return swept


def reconcile(
    engine: Engine,
    *,
    now: datetime | None = None,
    stale_after: timedelta = DEFAULT_STALE_AFTER,
    uploads_dir: Path | None = None,
) -> dict:
    """Runs both reconciliation passes against ``engine``: stale transient rows become
    ``'failed'`` first (committed), then orphaned files are swept from ``uploads_dir``
    (``app.config.resolve_uploads_dir()`` by default, read the same way ``storage.py`` does).
    Returns ``{"reapedRows": int, "sweptFiles": int}``, mainly for logging/tests -- neither
    caller (startup, or a manual invocation) needs to branch on it."""
    resolved_now = now if now is not None else _naive_utc_now()
    resolved_uploads_dir = (
        uploads_dir if uploads_dir is not None else config_module.resolve_uploads_dir()
    )
    with Session(engine) as session:
        reaped = _reap_stale_transient_rows(session, now=resolved_now, stale_after=stale_after)
        session.commit()
        swept = _sweep_orphaned_upload_files(
            session, uploads_dir=resolved_uploads_dir, now=resolved_now, stale_after=stale_after
        )
    return {"reapedRows": reaped, "sweptFiles": swept}
