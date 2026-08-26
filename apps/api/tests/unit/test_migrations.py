"""Unit tests for app/db/migrations.py (ticket 04, debt b): the dedicated migrations module
extracted from app/db/engine.py's init_db(). Behavior (drop/add column) is already
characterized end-to-end by tests/integration/test_schema_migrations.py via init_db() -- these
tests instead pin the module's own contract: an ordered, logged list that ``run_migrations``
walks in full every time.
"""

from __future__ import annotations

import logging

from sqlmodel.pool import StaticPool

from app.db import migrations as migrations_module
from app.db.engine import create_db_engine


def test_migrations_list_is_ordered_drop_then_add() -> None:
    names = [m.__name__ for m in migrations_module.MIGRATIONS]
    assert names == [
        "_drop_legacy_resume_versions_template_id_column",
        "_add_missing_source_documents_diff_summary_column",
        "_note_improvement_proposals_table_added",
        "_add_missing_chat_sessions_kind_column",
        "_note_job_monitor_tables_added",
        "_rebuild_job_monitor_ephemeral_tables_without_rowid_reuse",
        "_relax_improvement_proposals_session_id_to_nullable",
    ]


def test_run_migrations_logs_each_migration_by_name(caplog) -> None:
    engine = create_db_engine("sqlite://", poolclass=StaticPool)

    with caplog.at_level(logging.INFO, logger=migrations_module.__name__):
        migrations_module.run_migrations(engine)

    for name in (m.__name__ for m in migrations_module.MIGRATIONS):
        assert any(name in record.message for record in caplog.records)


def test_run_migrations_runs_every_entry_even_on_a_fresh_engine(monkeypatch) -> None:
    """A fresh (already-current) DB has nothing to migrate, but every entry must still run
    (each is responsible for its own idempotent no-op) -- run_migrations itself does not skip
    entries based on any notion of "already applied"."""
    engine = create_db_engine("sqlite://", poolclass=StaticPool)
    called: list[str] = []
    fake_migrations = [
        lambda eng: called.append("first"),
        lambda eng: called.append("second"),
    ]
    monkeypatch.setattr(migrations_module, "MIGRATIONS", fake_migrations)

    migrations_module.run_migrations(engine)

    assert called == ["first", "second"]
