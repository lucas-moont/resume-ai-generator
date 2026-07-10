"""FastAPI app factory -- extracted from the former monolithic main.py (B4).

Business logic lives in app/services/*; HTTP wiring lives in app/routers/*. This module only
builds and configures the app.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db.engine import create_db_engine, init_db
from app.db.seed import seed_profile_from_disk_if_empty
from app.routers import catalog, export, generate, health, profile, refine


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine = create_db_engine()
    init_db(engine)
    seed_profile_from_disk_if_empty(engine)
    app.state.db_engine = engine
    yield


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
    app.include_router(generate.router)
    app.include_router(refine.router)
    app.include_router(export.router)
    return app


app = create_app()
