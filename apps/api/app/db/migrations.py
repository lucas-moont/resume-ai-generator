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


# Ordered, append-only -- see module docstring.
MIGRATIONS: list[Callable[[Engine], None]] = [
    _drop_legacy_resume_versions_template_id_column,
    _add_missing_source_documents_diff_summary_column,
    _note_improvement_proposals_table_added,
]


def run_migrations(engine: Engine) -> None:
    """The single entry point app.db.engine.init_db() calls: runs every entry in ``MIGRATIONS``,
    in order, against ``engine``. Safe to call on every boot -- each migration is idempotent."""
    for migration in MIGRATIONS:
        logger.info("db migration: running %s", migration.__name__)
        migration(engine)
