"""Worker process: Pub/Sub push target. Also serves the dead-letter push and the sweep hook."""

from __future__ import annotations

import asyncio
import base64
import logging
from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import FastAPI, Request, Response

from app import logging as applog
from app.catalog import load_catalog
from app.config import Settings, get_settings
from app.db import Database
from app.dispatch import Dispatcher, JobEnvelope, PubSubDispatcher
from app.extraction.provider import LLMProvider
from app.worker.pipeline import JobResult, Pipeline, build_pipeline
from app.worker.sweeper import sweep_once

log = logging.getLogger("worker")


def create_worker_app(settings: Settings | None = None, *, db: Database | None = None,
                      provider: LLMProvider | None = None, dispatcher: Dispatcher | None = None) -> FastAPI:
    settings = settings or get_settings()
    applog.configure()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        app.state.db = db or Database(settings.database_url)
        if db is None:
            await app.state.db.open()
        catalog = load_catalog(settings.catalog_path)
        app.state.pipeline = build_pipeline(settings, app.state.db, catalog, provider=provider)
        app.state.dispatcher = dispatcher or PubSubDispatcher(settings.pubsub_project, settings.pubsub_topic)
        loop_task = None
        if settings.sweep_interval_seconds > 0:
            loop_task = asyncio.create_task(_sweep_loop(app))
        try:
            yield
        finally:
            if loop_task:
                loop_task.cancel()
            if db is None:
                await app.state.db.close()

    app = FastAPI(title="Riverbend worker", version="0.1.0", lifespan=lifespan)

    @app.get("/healthz")
    async def healthz() -> dict:
        async with app.state.db.tx() as conn:
            await conn.execute("SELECT 1")
        return {"ok": True}

    @app.post("/pubsub/push")
    async def push(request: Request) -> Response:
        env = await _envelope(request)
        pipeline: Pipeline = app.state.pipeline
        result = await pipeline.run_job(UUID(env.job_id))
        # 2xx acks. 5xx makes Pub/Sub redeliver with the subscription's backoff policy.
        if result is JobResult.RETRY:
            return Response(status_code=503)
        return Response(status_code=204)

    @app.post("/pubsub/dlq")
    async def dlq(request: Request) -> Response:
        env = await _envelope(request)
        await app.state.pipeline.dead_letter(UUID(env.job_id))
        return Response(status_code=204)

    @app.post("/sweep")
    async def sweep() -> dict:
        return await sweep_once(app.state.db, app.state.dispatcher, app.state.settings)

    return app


async def _envelope(request: Request) -> JobEnvelope:
    body = await request.json()
    data = body["message"]["data"]
    return JobEnvelope.from_bytes(base64.b64decode(data))


async def _sweep_loop(app: FastAPI) -> None:
    while True:
        try:
            await sweep_once(app.state.db, app.state.dispatcher, app.state.settings)
        except Exception:  # noqa: BLE001
            log.exception("sweep failed")
        await asyncio.sleep(app.state.settings.sweep_interval_seconds)


app = create_worker_app()
