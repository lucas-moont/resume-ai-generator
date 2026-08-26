"""Ad-hoc migrations (no Alembic -- see app/db/tables.py's module docstring), run in order by
app.db.engine.init_db() on every boot.

``MIGRATIONS`` is the ordered, append-only list: adding a schema change for an existing on-disk
DB means adding a new entry at the end, never editing an existing one's behavior once it has
shipped (a DB that already went through it must see it as a no-op on the next boot). Each entry
must be idempotent -- ``run_migrations`` runs the whole list unconditionally, whether the DB is
brand new (nothing to do) or mid-upgrade (exactly one thing to do), and logs each migration by
name so a slow or failing boot is diagnosable.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable

from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


def _drop_legacy_resume_versions_template_id_column(engine: Engine) -> None:
    """v1 DBs on disk may still carry ``resume_versions.template_id``, which the model no
    longer defines as of v2 ticket 01 (see docs/v2-living-profile.md's "Dívida herdada").
    ``create_all()`` only creates tables that don't exist yet, so a pre-existing v1 file keeps
    the dead column until this runs. SQLite gained ``ALTER TABLE ... DROP COLUMN`` in 3.35.0
    (2021); an older SQLite build just keeps the column -- harmless, since nothing reads or
    writes it anymore.
    """
    if engine.dialect.name != "sqlite" or sqlite3.sqlite_version_info < (3, 35, 0):
        return
    with engine.connect() as conn:
        columns = conn.execute(text("PRAGMA table_info(resume_versions)")).fetchall()
        if not columns or not any(row[1] == "template_id" for row in columns):
            return
        conn.execute(text("ALTER TABLE resume_versions DROP COLUMN template_id"))
        conn.commit()


def _add_missing_source_documents_diff_summary_column(engine: Engine) -> None:
    """A `source_documents` table created by a v2-ticket-03-era boot (before ticket 04 added
    `diff_summary`) is missing the column outright. Unlike the DROP COLUMN migration above,
    `ALTER TABLE ... ADD COLUMN` is supported by every SQLite version, so no version gate is
    needed here.
    """
    if engine.dialect.name != "sqlite":
        return
    with engine.connect() as conn:
        columns = conn.execute(text("PRAGMA table_info(source_documents)")).fetchall()
        if not columns or any(row[1] == "diff_summary" for row in columns):
            return
        conn.execute(text("ALTER TABLE source_documents ADD COLUMN diff_summary TEXT"))
        conn.commit()


def _add_missing_chat_sessions_kind_column(engine: Engine) -> None:
    """v5 ticket b1 adds ``chat_sessions.kind`` (`'resume' | 'profile_analysis'`). A pre-v5
    on-disk DB has the table but not the column; ``create_all()`` never ALTERs an existing
    table, so add it here. ``ALTER TABLE ... ADD COLUMN ... DEFAULT 'resume'`` is supported by
    every SQLite version and backfills existing rows to 'resume' (exactly the retrocompatible
    default -- every pre-v5 session is a resume chat). Idempotent: skips when the column exists.
    """
    if engine.dialect.name != "sqlite":
        return
    with engine.connect() as conn:
        columns = conn.execute(text("PRAGMA table_info(chat_sessions)")).fetchall()
        if not columns or any(row[1] == "kind" for row in columns):
            return
        conn.execute(text("ALTER TABLE chat_sessions ADD COLUMN kind TEXT NOT NULL DEFAULT 'resume'"))
        conn.commit()


def _note_improvement_proposals_table_added(engine: Engine) -> None:
    """v4 ticket B1 adds the brand-new `improvement_proposals` table straight to
    app/db/tables.py. Unlike the two migrations above (which ALTER an existing table),
    a wholly new table needs no ALTER-style work here: `SQLModel.metadata.create_all()`
    (app/db/engine.py's `init_db`, which always runs before `run_migrations`) creates any
    table missing from the engine's tables -- a real, pre-v4 on-disk DB goes through the exact
    same `CREATE TABLE IF NOT EXISTS` path a brand-new DB does. By the time this entry runs,
    the table already exists either way. Kept as a documented no-op so MIGRATIONS' ordered
    history stays complete and a future reader scanning this list sees v4's schema change
    accounted for, rather than wondering whether it was missed.
    """
    return


def _note_job_monitor_tables_added(engine: Engine) -> None:
    """v7 ticket 02 adds five brand-new tables (`search_profile`, `job_scans`, `job_listings`,
    `listing_sources`, `listing_memory`) straight to app/db/tables.py. Same situation as
    `_note_improvement_proposals_table_added` above and the same non-work: `create_all()`
    (app/db/engine.py's `init_db`, which always runs before `run_migrations`) creates every
    table missing from the engine, so a real pre-v7 `data/app.db` takes the exact same
    `CREATE TABLE IF NOT EXISTS` path a brand-new file does -- there is nothing to ALTER and
    nothing to backfill, because all five tables start empty on every machine (the Search
    Profile is created by the user's first save, and `job_listings` is rewritten by the first
    Scan). Kept as a documented no-op so this ordered history stays complete: a future reader
    scanning the list sees v7's schema change accounted for rather than missed. The first entry
    with real work here will be the one that RETIRES a Job Board id from
    `search_profile.boards` -- see the note on `BoardId` in app/domain/schemas.py.
    """
    return


def _rebuild_job_monitor_ephemeral_tables_without_rowid_reuse(engine: Engine) -> None:
    """``job_listings`` and ``listing_sources`` must be created WITH ``AUTOINCREMENT`` (v7
    ticket 02: they are emptied by every Scan, and SQLite otherwise recycles the rowid of a
    deleted row, so a listing id the UI captured seconds ago silently resolves to a DIFFERENT
    job -- see the comment on ``JobListing.__table_args__``).

    ``create_all()`` is ``CREATE TABLE IF NOT EXISTS``: a DB whose file already carries these
    two tables from an earlier boot -- exactly what happens to a developer machine whose API
    was running while v7 landed -- keeps the version without the marker forever. So: when the
    stored DDL lacks ``AUTOINCREMENT``, drop both tables and let the current definition create
    them again.

    Dropping data is safe here, and ONLY here, because these two tables are ephemeral by
    definition (CONTEXT.md: Job Listing) -- the list IS the last Scan, and the next Scan
    rewrites them wholesale. Everything that must survive a Scan lives in ``listing_memory``,
    which this migration does not touch. Idempotent: once recreated, the DDL carries the marker
    and this is a no-op on every later boot.
    """
    if engine.dialect.name != "sqlite":
        return
    from app.db.tables import JobListing, ListingSource  # local: avoid an import cycle at boot

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT name, sql FROM sqlite_master WHERE type='table' "
                "AND name IN ('job_listings', 'listing_sources')"
            )
        ).fetchall()
        stale = [name for name, sql in rows if "AUTOINCREMENT" not in (sql or "")]
        if not stale:
            return
        # Child first: listing_sources has a FK to job_listings.
        conn.execute(text("DROP TABLE IF EXISTS listing_sources"))
        conn.execute(text("DROP TABLE IF EXISTS job_listings"))
        conn.commit()
    logger.info("db migration: recreating %s with AUTOINCREMENT", ", ".join(sorted(stale)))
    JobListing.metadata.create_all(
        engine, tables=[JobListing.__table__, ListingSource.__table__]
    )


def _relax_improvement_proposals_session_id_to_nullable(engine: Engine) -> None:
    """v7 ticket 10 makes ``improvement_proposals.session_id`` nullable: a One-click Resume's
    Improvement Proposal belongs to a Job Listing, not to a conversation (CONTEXT.md: One-click
    Resume). Every DB created before this carries the column as ``NOT NULL``, and ``create_all``
    is ``CREATE TABLE IF NOT EXISTS`` -- it never widens an existing column.

    SQLite has no ``ALTER COLUMN``, so this is the standard table rebuild: rename the old table
    aside, let the CURRENT definition create the new one, copy every row across by name, drop
    the old one. Unlike
    ``_rebuild_job_monitor_ephemeral_tables_without_rowid_reuse``, NOTHING is discarded here --
    ``improvement_proposals`` is durable (every approved plan behind an existing resume lives in
    it), so the copy is the whole point and the row count is asserted before the old table goes.

    The copy runs with ``PRAGMA foreign_keys=OFF``, as SQLite's own documented table-rebuild
    procedure prescribes: ``app/db/engine.py`` turns enforcement ON for every connection, and a
    row whose ``chat_sessions`` parent has already gone missing would otherwise make the copy
    (and therefore the boot) fail over pre-existing data this migration did not create and is
    not here to fix.

    Idempotent: once the column is nullable, ``PRAGMA table_info`` says so and this returns
    immediately.
    """
    if engine.dialect.name != "sqlite":
        return
    from app.db.tables import ImprovementProposal  # local: avoid an import cycle at boot

    with engine.connect() as conn:
        columns = conn.execute(text("PRAGMA table_info(improvement_proposals)")).fetchall()
        # row = (cid, name, type, notnull, dflt_value, pk)
        needs_rebuild = any(row[1] == "session_id" and row[3] == 1 for row in columns)
        if not columns or not needs_rebuild:
            return
        column_list = ", ".join(row[1] for row in columns)
        before = conn.execute(text("SELECT COUNT(*) FROM improvement_proposals")).scalar_one()
        conn.execute(
            text("ALTER TABLE improvement_proposals RENAME TO _improvement_proposals_pre_v7")
        )
        conn.commit()

    logger.info("db migration: rebuilding improvement_proposals with a nullable session_id")
    ImprovementProposal.metadata.create_all(engine, tables=[ImprovementProposal.__table__])

    # The DBAPI connection directly, not a SQLAlchemy Connection: ``PRAGMA foreign_keys`` is a
    # no-op inside a transaction, and a SQLAlchemy Connection has already begun one by the time
    # the first statement runs.
    raw = engine.raw_connection()
    try:
        cursor = raw.cursor()
        cursor.execute("PRAGMA foreign_keys=OFF")
        try:
            cursor.execute(
                f"INSERT INTO improvement_proposals ({column_list}) "
                f"SELECT {column_list} FROM _improvement_proposals_pre_v7"
            )
            cursor.execute("SELECT COUNT(*) FROM improvement_proposals")
            after = cursor.fetchone()[0]
            if after != before:  # pragma: no cover - a copy that loses rows is never committed
                raw.rollback()
                raise RuntimeError(
                    f"improvement_proposals rebuild copied {after} of {before} rows; aborting"
                )
            cursor.execute("DROP TABLE _improvement_proposals_pre_v7")
            raw.commit()
        finally:
            # Back on before this connection returns to the pool -- every later user of it
            # expects the enforcement engine.py's connect hook set up.
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    finally:
        raw.close()


# Ordered, append-only -- see module docstring.
MIGRATIONS: list[Callable[[Engine], None]] = [
    _drop_legacy_resume_versions_template_id_column,
    _add_missing_source_documents_diff_summary_column,
    _note_improvement_proposals_table_added,
    _add_missing_chat_sessions_kind_column,
    _note_job_monitor_tables_added,
    _rebuild_job_monitor_ephemeral_tables_without_rowid_reuse,
    _relax_improvement_proposals_session_id_to_nullable,
]


def run_migrations(engine: Engine) -> None:
    """The single entry point app.db.engine.init_db() calls: runs every entry in ``MIGRATIONS``,
    in order, against ``engine``. Safe to call on every boot -- each migration is idempotent."""
    for migration in MIGRATIONS:
        logger.info("db migration: running %s", migration.__name__)
        migration(engine)
