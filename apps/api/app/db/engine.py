"""SQLite engine construction -- WAL journal mode + foreign_keys=ON on every connection
(B5). No Alembic: see app/db/tables.py's module docstring.

WAL mode is a no-op on ``:memory:``/``sqlite://`` databases (SQLite does not support WAL for
in-memory DBs and silently keeps its own in-memory journal mode) -- safe to set
unconditionally, so tests and production share the exact same connection setup code path.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from app import config as config_module


def create_db_engine(database_url: str | None = None, *, echo: bool = False, **engine_kwargs: Any) -> Engine:
    """``database_url`` defaults to ``app.config.DATABASE_URL``, read at CALL time (module-
    qualified) rather than baked in as a function-default value -- a plain default parameter
    is bound once when this function is defined, so a test monkeypatching
    ``app.config.DATABASE_URL`` afterward would never take effect for the no-arg call main.py's
    lifespan makes. Pass an explicit URL (e.g. an in-memory ``sqlite://``) to bypass config
    entirely."""
    url = database_url if database_url is not None else config_module.DATABASE_URL
    connect_args = engine_kwargs.pop("connect_args", {"check_same_thread": False})
    engine = create_engine(url, echo=echo, connect_args=connect_args, **engine_kwargs)

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def _drop_legacy_resume_versions_template_id_column(engine: Engine) -> None:
    """Ad-hoc migration (no Alembic -- see app/db/tables.py's docstring): v1 DBs on disk may
    still carry ``resume_versions.template_id``, which the model no longer defines as of v2
    ticket 01 (see docs/v2-living-profile.md's "Dívida herdada"). ``create_all()`` above only
    creates tables that don't exist yet, so a pre-existing v1 file keeps the dead column until
    this runs. SQLite gained ``ALTER TABLE ... DROP COLUMN`` in 3.35.0 (2021); an older SQLite
    build just keeps the column -- harmless, since nothing reads or writes it anymore.
    """
    if engine.dialect.name != "sqlite" or sqlite3.sqlite_version_info < (3, 35, 0):
        return
    with engine.connect() as conn:
        columns = conn.execute(text("PRAGMA table_info(resume_versions)")).fetchall()
        if not columns or not any(row[1] == "template_id" for row in columns):
            return
        conn.execute(text("ALTER TABLE resume_versions DROP COLUMN template_id"))
        conn.commit()


def init_db(engine: Engine) -> None:
    SQLModel.metadata.create_all(engine)
    _drop_legacy_resume_versions_template_id_column(engine)


def new_session(engine: Engine) -> Session:
    """The session factory: one ``Session`` per call, bound to ``engine``. A thin factory
    rather than a context manager itself, so it composes with FastAPI's ``Depends()``
    generator pattern (see app/routers/deps.get_session, its only caller) without engine.py
    needing to know anything about requests."""
    return Session(engine)
