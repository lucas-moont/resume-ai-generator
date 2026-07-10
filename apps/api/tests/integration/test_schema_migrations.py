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
