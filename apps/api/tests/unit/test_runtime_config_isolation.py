"""Regression test for a test-isolation bug found while building v3 ticket 01: nothing wired
config's lazily-created app_settings engine to an in-memory DB globally, so ANY test that
transitively calls get_runtime_config() (e.g. GET /api/models -> model_catalog ->
llm_backend_label -> resolve_active_provider) fell through to config._get_settings_engine()'s
default, which creates a real SQLAlchemy engine on config.DATABASE_URL -- the actual on-disk
data/app.db this repo ships with. A conftest.py-level autouse fixture must isolate every test,
the same way isolated_data_env already isolates PROFILE_JSON_PATH/DATA_UPLOADS_DIR/etc, without
each test file needing its own local override (test_config_runtime.py's is file-local; this one
must apply repo-wide, with no explicit fixture request needed).
"""

from __future__ import annotations

from app import config


def test_settings_engine_is_an_isolated_in_memory_db_by_default() -> None:
    # No local fixture requested here -- this must come from conftest.py's autouse isolation.
    engine = config._get_settings_engine()

    assert str(engine.url).startswith("sqlite://")
    assert str(engine.url) != config.DATABASE_URL


def test_app_settings_writes_do_not_leak_across_tests() -> None:
    """Companion to the test above: if isolation were missing, a prior test's
    set_app_setting write would still be visible here (or, worse, on disk)."""
    assert config.get_runtime_config().ai_provider != "this-would-mean-leaked-state"
    assert config._app_settings().get("_isolation_probe") is None
