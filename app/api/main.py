"""API process: accepts messages, serves customer status and the shop's work-order list."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import logging as applog
from app.api.routes import router
from app.catalog import load_catalog
from app.config import Settings, get_settings
from app.db import Database
from app.dispatch import Dispatcher, InlineDispatcher, PubSubDispatcher


def create_app(
    settings: Settings | None = None, *, db: Database | None = None, dispatcher: Dispatcher | None = None
) -> FastAPI:
    """Build the API app; the database and dispatcher are injectable for tests."""
    settings = settings or get_settings()
    applog.configure()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        app.state.catalog = load_catalog(settings.catalog_path)
        app.state.db = db or Database(settings.database_url)
        if db is None:
            await app.state.db.open()
        app.state.dispatcher = dispatcher or _build_dispatcher(settings, app)
        try:
            yield
        finally:
            if db is None:
                await app.state.db.close()

    app = FastAPI(title="Riverbend work orders", version="0.1.0", lifespan=lifespan)
    app.include_router(router)
    return app


def _build_dispatcher(settings: Settings, app: FastAPI) -> Dispatcher:
    if settings.dispatcher == "pubsub":
        return PubSubDispatcher(settings.pubsub_project, settings.pubsub_topic)
    # Inline: the API process also runs the pipeline (no broker, no worker). Dev/test only.
    from app.worker.pipeline import build_pipeline

    pipeline = build_pipeline(settings, app.state.db, app.state.catalog)
    return InlineDispatcher(pipeline.run_job_named, pipeline.dead_letter)


app = create_app()
