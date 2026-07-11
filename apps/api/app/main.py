"""FastAPI app factory -- extracted from the former monolithic main.py (B4).

Business logic lives in app/services/*; HTTP wiring lives in app/routers/*. This module only
builds and configures the app.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import config as config_module
from app.db.engine import create_db_engine, init_db
from app.db.seed import seed_profile_from_disk_if_empty
from app.routers import catalog, chat, documents, export, generate, github, health, profile, refine, settings
from app.services.ingestion.reaper import reconcile


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine = create_db_engine()
    init_db(engine)
    seed_profile_from_disk_if_empty(engine)
    app.state.db_engine = engine
    # v3 ticket 01 fix round: without this, config.get_runtime_config() would lazily build a
    # SECOND engine+pool on the same on-disk DATABASE_URL the first time a settings read
    # happens -- wasteful, and the lazy path's double-checked locking is only a fallback for
    # non-FastAPI callers (scripts, tests without this fixture), not the production path.
    config_module.set_settings_engine(engine)
    # Ticket 04, debt c: reconciles any Source Document rows/files an interrupted upload left
    # behind from a PREVIOUS run before this boot ever serves a request -- see
    # services/ingestion/reaper.py's module docstring for the two crash-window shapes.
    reconcile(engine)
    yield
    config_module.set_settings_engine(None)


def create_app() -> FastAPI:
    app = FastAPI(title="Resume Agent API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(catalog.router)
    app.include_router(profile.router)
    app.include_router(documents.router)
    app.include_router(github.router)
    app.include_router(generate.router)
    app.include_router(refine.router)
    app.include_router(export.router)
    app.include_router(chat.router)
    app.include_router(settings.router)
    return app


app = create_app()
