"""Ad-hoc schema migrations run at boot by app.db.engine.init_db() (no Alembic -- see
app/db/tables.py's module docstring). v2 ticket 01 drops ``resume_versions.template_id``:
v1 DBs on disk may still carry the column (dead weight since the model no longer defines it --
see docs/v2-living-profile.md's "Dívida herdada"). These tests simulate a legacy v1 SQLite
file (created with the OLD schema, template_id included) and confirm init_db() drops the
column in place without touching existing rows.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlmodel import Session

from app.db.engine import create_db_engine, init_db
from app.repositories import proposal_repo


def _create_legacy_v1_resume_versions_table(engine) -> None:
    """Raw SQL matching the pre-v2 schema (SQLModel.metadata.create_all only creates tables
    that don't exist yet, so a hand-rolled legacy table is the only way to exercise the
    DROP COLUMN migration path against a table the current model no longer describes)."""
    with engine.connect() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE resume_versions (
                    id INTEGER PRIMARY KEY,
                    session_id INTEGER,
                    parent_version_id INTEGER,
                    profile_version_id INTEGER,
                    data TEXT NOT NULL,
                    template_id TEXT DEFAULT 'modern',
                    model_used TEXT,
                    provider_used TEXT,
                    created_at TIMESTAMP
                )
                """
            )
        )
        conn.execute(
            text(
                "INSERT INTO resume_versions (id, data, template_id, created_at) "
                "VALUES (1, :data, 'classic', '2026-01-01T00:00:00')"
            ),
            {"data": '{"fullName": "Legacy Person"}'},
        )
        conn.commit()


def _table_columns(engine, table_name: str) -> list[str]:
    with engine.connect() as conn:
        rows = conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
    return [row[1] for row in rows]


def test_init_db_drops_template_id_from_a_legacy_v1_resume_versions_table(tmp_path):
    engine = create_db_engine(f"sqlite:///{(tmp_path / 'legacy.db').as_posix()}")
    _create_legacy_v1_resume_versions_table(engine)
    assert "template_id" in _table_columns(engine, "resume_versions")

    init_db(engine)

    assert "template_id" not in _table_columns(engine, "resume_versions")
    # Existing rows survive the migration untouched.
    with Session(engine) as session:
        row = session.exec(text("SELECT id, data FROM resume_versions WHERE id = 1")).first()
        assert row is not None
        assert row[1] == '{"fullName": "Legacy Person"}'


def test_init_db_is_a_no_op_when_the_column_is_already_gone(tmp_path):
    """A fresh v2 DB (or a legacy DB that already went through the migration once) must not
    error on a second boot -- init_db() runs on every lifespan startup."""
    engine = create_db_engine(f"sqlite:///{(tmp_path / 'fresh.db').as_posix()}")

    init_db(engine)
    init_db(engine)  # second boot, simulating a server restart

    assert "template_id" not in _table_columns(engine, "resume_versions")


def _create_legacy_v2_ticket03_source_documents_table(engine) -> None:
    """Raw SQL matching the ticket-03-era schema (before ticket 04 added `diff_summary`) --
    same rationale as the legacy resume_versions table above: create_all() only creates tables
    that don't exist yet, so a hand-rolled legacy table is the only way to exercise the ADD
    COLUMN migration path."""
    with engine.connect() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE source_documents (
                    id INTEGER PRIMARY KEY,
                    filename TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    sha256 TEXT NOT NULL UNIQUE,
                    size_bytes INTEGER NOT NULL,
                    stored_path TEXT NOT NULL,
                    extracted_json TEXT,
                    proposed_patch TEXT,
                    status TEXT NOT NULL DEFAULT 'stored',
                    error TEXT,
                    created_at TIMESTAMP
                )
                """
            )
        )
        conn.execute(
            text(
                "INSERT INTO source_documents (id, filename, media_type, sha256, size_bytes, "
                "stored_path, status, created_at) VALUES "
                "(1, 'a.json', 'json', :sha, 1, 'p', 'extracted', '2026-01-01T00:00:00')"
            ),
            {"sha": "a" * 64},
        )
        conn.commit()


def test_init_db_adds_diff_summary_to_a_legacy_ticket03_source_documents_table(tmp_path):
    engine = create_db_engine(f"sqlite:///{(tmp_path / 'legacy_v2.db').as_posix()}")
    _create_legacy_v2_ticket03_source_documents_table(engine)
    assert "diff_summary" not in _table_columns(engine, "source_documents")

    init_db(engine)

    assert "diff_summary" in _table_columns(engine, "source_documents")
    with Session(engine) as session:
        row = session.exec(text("SELECT id, filename FROM source_documents WHERE id = 1")).first()
        assert row is not None
        assert row[1] == "a.json"


def test_init_db_diff_summary_migration_is_a_no_op_on_a_fresh_db(tmp_path):
    engine = create_db_engine(f"sqlite:///{(tmp_path / 'fresh_v2.db').as_posix()}")

    init_db(engine)
    init_db(engine)  # second boot must not error

    assert "diff_summary" in _table_columns(engine, "source_documents")


def _create_legacy_pre_v5_chat_sessions_table(engine) -> None:
    """Raw SQL matching the pre-v5 chat_sessions schema (before ticket b1 added ``kind``) --
    same rationale as the legacy tables above: create_all() only creates tables that don't
    exist yet, so a hand-rolled legacy table is the only way to exercise the ADD COLUMN path."""
    with engine.connect() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE chat_sessions (
                    id INTEGER PRIMARY KEY,
                    title TEXT,
                    job_description TEXT,
                    locale TEXT,
                    active_resume_version_id INTEGER,
                    created_at TIMESTAMP,
                    updated_at TIMESTAMP
                )
                """
            )
        )
        conn.execute(
            text(
                "INSERT INTO chat_sessions (id, title, created_at, updated_at) "
                "VALUES (1, 'Legacy chat', '2026-01-01T00:00:00', '2026-01-01T00:00:00')"
            )
        )
        conn.commit()


def test_init_db_adds_kind_to_a_legacy_chat_sessions_table_backfilling_resume(tmp_path):
    engine = create_db_engine(f"sqlite:///{(tmp_path / 'legacy_v4.db').as_posix()}")
    _create_legacy_pre_v5_chat_sessions_table(engine)
    assert "kind" not in _table_columns(engine, "chat_sessions")

    init_db(engine)

    assert "kind" in _table_columns(engine, "chat_sessions")
    # The existing row survives and is backfilled to the retrocompatible default.
    with Session(engine) as session:
        row = session.exec(text("SELECT id, title, kind FROM chat_sessions WHERE id = 1")).first()
        assert row is not None
        assert row[1] == "Legacy chat"
        assert row[2] == "resume"


def test_init_db_kind_migration_is_a_no_op_on_a_fresh_db(tmp_path):
    engine = create_db_engine(f"sqlite:///{(tmp_path / 'fresh_v5.db').as_posix()}")

    init_db(engine)
    init_db(engine)  # second boot must not error

    assert "kind" in _table_columns(engine, "chat_sessions")


def _column_is_not_null(engine, table_name: str, column: str) -> bool:
    with engine.connect() as conn:
        rows = conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
    return any(row[1] == column and row[3] == 1 for row in rows)


def _create_legacy_pre_v7_improvement_proposals_table(engine) -> None:
    """Raw SQL matching the v4 improvement_proposals schema, whose ``session_id`` is NOT NULL.
    v7 ticket 10 makes it nullable (a One-click Resume's proposal belongs to a Job Listing, not
    to a conversation), and SQLite has no ALTER COLUMN -- so the migration rebuilds the table
    and this is the only way to exercise that path."""
    with engine.connect() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE improvement_proposals (
                    id INTEGER PRIMARY KEY,
                    session_id INTEGER NOT NULL,
                    job_description TEXT NOT NULL,
                    items TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    resume_version_id INTEGER,
                    model_used TEXT,
                    created_at TIMESTAMP,
                    updated_at TIMESTAMP
                )
                """
            )
        )
        conn.execute(
            text(
                "INSERT INTO improvement_proposals "
                "(id, session_id, job_description, items, revision, status, created_at, updated_at) "
                "VALUES (7, 3, 'a real posting', '[]', 2, 'approved', "
                "'2026-01-01T00:00:00', '2026-01-02T00:00:00')"
            )
        )
        conn.commit()


def test_init_db_relaxes_improvement_proposals_session_id_without_losing_rows(tmp_path):
    engine = create_db_engine(f"sqlite:///{(tmp_path / 'legacy_v6.db').as_posix()}")
    _create_legacy_pre_v7_improvement_proposals_table(engine)
    assert _column_is_not_null(engine, "improvement_proposals", "session_id")

    init_db(engine)

    assert not _column_is_not_null(engine, "improvement_proposals", "session_id")
    # Nothing is discarded: this table is durable (every approved plan behind an existing
    # resume lives in it), unlike the ephemeral job_listings the other v7 rebuild drops.
    with Session(engine) as session:
        row = session.exec(
            text(
                "SELECT session_id, job_description, revision, status, updated_at "
                "FROM improvement_proposals WHERE id = 7"
            )
        ).first()
        assert row is not None
        assert row[0] == 3
        assert row[1] == "a real posting"
        assert row[2] == 2
        assert row[3] == "approved"
    # The scaffolding table is gone, not left behind for the next boot to trip over.
    with engine.connect() as conn:
        leftovers = conn.execute(
            text("SELECT name FROM sqlite_master WHERE name = '_improvement_proposals_pre_v7'")
        ).fetchall()
    assert leftovers == []


def test_a_sessionless_proposal_can_be_written_after_the_rebuild(tmp_path):
    """The point of the migration: the One-click Resume's proposal has no chat session."""
    engine = create_db_engine(f"sqlite:///{(tmp_path / 'legacy_v6b.db').as_posix()}")
    _create_legacy_pre_v7_improvement_proposals_table(engine)

    init_db(engine)

    with Session(engine) as session:
        row = proposal_repo.create_pending(
            session, session_id=None, job_description="a listing", items=[]
        )
        session.commit()
        assert row.session_id is None
    with Session(engine) as session:
        assert proposal_repo.get(session, row.id).session_id is None


def test_init_db_proposal_rebuild_is_a_no_op_on_a_fresh_db(tmp_path):
    engine = create_db_engine(f"sqlite:///{(tmp_path / 'fresh_v7.db').as_posix()}")

    init_db(engine)
    init_db(engine)  # second boot must not error

    assert not _column_is_not_null(engine, "improvement_proposals", "session_id")
