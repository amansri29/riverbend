"""Delivery of job ids to the worker (ADR-4). The outbox row in Postgres is the truth; the
dispatcher only moves an id. Three implementations:

- PubSubDispatcher: Google Pub/Sub (emulator locally via PUBSUB_EMULATOR_HOST, real on GCP).
- InlineDispatcher: runs the pipeline in-process with a broker-like retry loop. Used when
  DISPATCHER=inline (tests, and a no-emulator dev mode).
- CollectingDispatcher: records publishes for tests that drive the pipeline by hand.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID

log = logging.getLogger("dispatch")


@dataclass(frozen=True)
class JobEnvelope:
    job_id: str
    shop_id: str
    kind: str

    def to_bytes(self) -> bytes:
        return json.dumps({"job_id": self.job_id, "shop_id": self.shop_id, "kind": self.kind}).encode()

    @classmethod
    def from_bytes(cls, data: bytes) -> JobEnvelope:
        d = json.loads(data.decode())
        return cls(job_id=str(d["job_id"]), shop_id=str(d["shop_id"]), kind=str(d["kind"]))


class Dispatcher(Protocol):
    async def publish(self, env: JobEnvelope) -> None: ...


class PubSubDispatcher:
    def __init__(self, project: str, topic: str) -> None:
        from google.cloud import pubsub_v1  # imported lazily so tests never need it

        self._publisher = pubsub_v1.PublisherClient()
        self._topic_path = self._publisher.topic_path(project, topic)

    async def publish(self, env: JobEnvelope) -> None:
        future = self._publisher.publish(self._topic_path, env.to_bytes(), shop_id=env.shop_id, kind=env.kind)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, future.result, 10)


RunJob = Callable[[UUID], Awaitable[str]]  # returns a JobResult name


class InlineDispatcher:
    """Emulates the broker's retry policy in-process: redeliver on RETRY, give up after
    max_attempts (the DLQ handler marks the job failed)."""

    def __init__(self, run_job: RunJob, dead_letter: Callable[[UUID], Awaitable[None]],
                 *, max_attempts: int = 5, backoff_seconds: float = 0.2) -> None:
        self._run_job = run_job
        self._dead_letter = dead_letter
        self._max_attempts = max_attempts
        self._backoff = backoff_seconds
        self.tasks: set[asyncio.Task] = set()

    async def publish(self, env: JobEnvelope) -> None:
        task = asyncio.create_task(self._deliver(env))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def _deliver(self, env: JobEnvelope) -> None:
        job_id = UUID(env.job_id)
        for attempt in range(1, self._max_attempts + 1):
            try:
                result = await self._run_job(job_id)
            except Exception:  # noqa: BLE001 - broker semantics: an exception is a failed delivery
                log.exception("inline delivery crashed", extra={"job_id": env.job_id})
                result = "RETRY"
            if result != "RETRY":
                return
            await asyncio.sleep(self._backoff * (2 ** (attempt - 1)))
        await self._dead_letter(job_id)

    async def drain(self) -> None:
        while self.tasks:
            await asyncio.gather(*list(self.tasks), return_exceptions=True)


@dataclass
class CollectingDispatcher:
    published: list[JobEnvelope] = field(default_factory=list)

    async def publish(self, env: JobEnvelope) -> None:
        self.published.append(env)


class FailingDispatcher:
    """For the outbox test: publishing always fails, so the sweeper must pick the job up."""

    async def publish(self, env: JobEnvelope) -> None:
        raise RuntimeError("broker unreachable")
