"""SQLite engine construction -- WAL journal mode + foreign_keys=ON on every connection
(B5). No Alembic: see app/db/tables.py's module docstring.

WAL mode is a no-op on ``:memory:``/``sqlite://`` databases (SQLite does not support WAL for
in-memory DBs and silently keeps its own in-memory journal mode) -- safe to set
unconditionally, so tests and production share the exact same connection setup code path.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from app import config as config_module
from app.db.migrations import run_migrations


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


def init_db(engine: Engine) -> None:
    SQLModel.metadata.create_all(engine)
    run_migrations(engine)


def new_session(engine: Engine) -> Session:
    """The session factory: one ``Session`` per call, bound to ``engine``. A thin factory
    rather than a context manager itself, so it composes with FastAPI's ``Depends()``
    generator pattern (see app/routers/deps.get_session, its only caller) without engine.py
    needing to know anything about requests."""
    return Session(engine)
