"""Migration test for the Job Monitor's schema (v7 ticket 02).

Companion to tests/unit/test_jobs_repo.py, kept separate because what it exercises is not the
repository but ``app/db/migrations.py`` against a REAL file-backed SQLite DB that already
carries an older version of these tables -- the one case ``create_all()`` (``CREATE TABLE IF
NOT EXISTS``) cannot fix by itself, and the reason this repo has ad-hoc migrations at all.

Named ``test_jobs_repo_migrations`` rather than added to tests/integration/test_schema_
migrations.py so it does not collide with the other v7 tickets working in the same tree.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from app.db.engine import create_db_engine, init_db

# The DDL a boot of this repo produced BEFORE ``sqlite_autoincrement`` was set on these two
# tables -- i.e. exactly what a developer machine whose API was running mid-v7 has on disk.
# Trimmed to the columns the migration cares about: it keys off the DDL text, not the shape.
_STALE_DDL = (
    """
    CREATE TABLE job_scans (
        id INTEGER NOT NULL PRIMARY KEY,
        started_at DATETIME NOT NULL,
        finished_at DATETIME,
        trigger VARCHAR NOT NULL,
        status VARCHAR NOT NULL,
        board_statuses VARCHAR NOT NULL,
        listings_found INTEGER NOT NULL,
        listings_scored INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE job_listings (
        id INTEGER NOT NULL PRIMARY KEY,
        scan_id INTEGER NOT NULL,
        identity_key VARCHAR NOT NULL,
        title VARCHAR NOT NULL,
        company VARCHAR NOT NULL,
        location VARCHAR,
        is_remote BOOLEAN NOT NULL,
        description VARCHAR NOT NULL,
        description_word_count INTEGER NOT NULL,
        date_posted DATETIME,
        is_repost BOOLEAN NOT NULL,
        applicant_band VARCHAR NOT NULL,
        fit_score INTEGER NOT NULL,
        fit_estimated BOOLEAN NOT NULL,
        visibility_score FLOAT NOT NULL,
        locale VARCHAR NOT NULL,
        FOREIGN KEY(scan_id) REFERENCES job_scans (id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE listing_sources (
        id INTEGER NOT NULL PRIMARY KEY,
        listing_id INTEGER NOT NULL,
        board VARCHAR NOT NULL,
        url VARCHAR NOT NULL,
        date_posted DATETIME,
        applicant_band VARCHAR NOT NULL,
        FOREIGN KEY(listing_id) REFERENCES job_listings (id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE listing_memory (
        id INTEGER NOT NULL PRIMARY KEY,
        identity_key VARCHAR NOT NULL UNIQUE,
        status VARCHAR NOT NULL,
        fit_score INTEGER,
        fit_description_hash VARCHAR,
        resume_version_id INTEGER,
        first_seen_at DATETIME NOT NULL,
        last_seen_at DATETIME NOT NULL,
        status_changed_at DATETIME NOT NULL
    )
    """,
)


def _stale_db(tmp_path: Path) -> Path:
    path = tmp_path / "app.db"
    conn = sqlite3.connect(path)
    for ddl in _STALE_DDL:
        conn.execute(ddl)
    conn.execute(
        "INSERT INTO listing_memory (identity_key, status, first_seen_at, last_seen_at, "
        "status_changed_at) VALUES ('acme|backend engineer', 'dismissed', "
        "'2026-08-01 10:00:00', '2026-08-01 10:00:00', '2026-08-01 10:00:00')"
    )
    conn.commit()
    conn.close()
    return path


def _ddl(path: Path, table: str) -> str:
    conn = sqlite3.connect(path)
    try:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
    finally:
        conn.close()
    return row[0] if row else ""


def test_a_db_carrying_the_pre_autoincrement_tables_is_rebuilt(tmp_path: Path) -> None:
    path = _stale_db(tmp_path)
    assert "AUTOINCREMENT" not in _ddl(path, "job_listings")

    init_db(create_db_engine(f"sqlite:///{path}"))

    assert "AUTOINCREMENT" in _ddl(path, "job_listings")
    assert "AUTOINCREMENT" in _ddl(path, "listing_sources")


def test_the_rebuild_does_not_touch_the_listing_memory(tmp_path: Path) -> None:
    """Only the two EPHEMERAL tables are dropped. The Listing Memory is the Monitor's durable
    state -- a dismissed job must still be dismissed after the upgrade."""
    path = _stale_db(tmp_path)

    init_db(create_db_engine(f"sqlite:///{path}"))

    conn = sqlite3.connect(path)
    try:
        rows = conn.execute("SELECT identity_key, status FROM listing_memory").fetchall()
    finally:
        conn.close()
    assert rows == [("acme|backend engineer", "dismissed")]


def test_the_rebuild_is_a_no_op_on_the_second_boot(tmp_path: Path) -> None:
    path = _stale_db(tmp_path)
    init_db(create_db_engine(f"sqlite:///{path}"))
    first = _ddl(path, "job_listings")

    init_db(create_db_engine(f"sqlite:///{path}"))

    assert _ddl(path, "job_listings") == first


def test_a_brand_new_db_gets_the_tables_straight_from_create_all(tmp_path: Path) -> None:
    path = tmp_path / "fresh.db"

    init_db(create_db_engine(f"sqlite:///{path}"))

    assert "AUTOINCREMENT" in _ddl(path, "job_listings")
    assert _ddl(path, "search_profile") != ""
