"""Fake LLMProvider for tests, offline runs, and failure demos.

Resolution order for a call:
1. Fault injection (`fault` = down | slow | garbage) → behaves like a broken provider.
2. Scripted responses keyed by trace_id (tests).
3. Recorded responses on disk from a previous Azure run (offline replay of the samples).
4. A clearly canned fallback: general inspection, no date → the pipeline asks a question.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from pydantic import ValidationError

from app.extraction.prompt import Turn
from app.extraction.provider import ProviderResult, ProviderTimeout, ProviderUnavailable, Usage
from app.extraction.schema import DateExpr, Extraction, ServicePick

CANNED = Extraction(
    outcome="work_order",
    flag_reason=None,
    flag_detail=None,
    language="en",
    customer_name=None,
    bike_type=None,
    bike_count=1,
    issues=["(fake provider: no recorded response for this message)"],
    services=[ServicePick(code="GENERAL_INSPECT", quantity=1, evidence="fake provider fallback")],
    urgency="normal",
    urgency_reason=None,
    date=DateExpr(
        kind="none", relative_days=None, weekday=None, next_week=False, absolute_date=None,
        month=None, part_of_day=None, time=None, text=None,
    ),
    question=None,
    missing=["requested_date"],
)

GARBAGE = CANNED.model_copy(
    update={"services": [ServicePick(code="FREE_VIP_SERVICE", quantity=99, evidence="garbage")]}
)


class FakeProvider:
    name = "fake"

    def __init__(
        self,
        *,
        scripted: dict[str, Extraction | ProviderResult] | None = None,
        record_dir: str | None = None,
        fault: str = "",
        usage: Usage = Usage(900, 180),
    ) -> None:
        self.scripted = dict(scripted or {})
        self.record_dir = Path(record_dir) if record_dir else None
        self.fault = fault
        self.usage = usage
        self.calls: list[dict] = []  # captured for assertions (e.g. tenancy of prompts)

    async def extract(
        self, *, system: str, turns: list[Turn], timeout_s: float, max_output_tokens: int, trace_id: str
    ) -> ProviderResult:
        self.calls.append({"trace_id": trace_id, "system": system, "turns": list(turns)})

        if self.fault == "down":
            raise ProviderUnavailable("fake provider: down")
        if self.fault == "slow":
            await asyncio.sleep(min(timeout_s, 0.05))
            raise ProviderTimeout("fake provider: timed out")
        if self.fault == "garbage":
            return self._ok(GARBAGE)

        if trace_id in self.scripted:
            s = self.scripted[trace_id]
            return s if isinstance(s, ProviderResult) else self._ok(s)

        recorded = self._load_recorded(trace_id)
        if recorded is not None:
            return recorded

        return self._ok(CANNED)

    def _ok(self, x: Extraction) -> ProviderResult:
        return ProviderResult(
            parsed=x, raw_text=x.model_dump_json(), usage=self.usage, model="fake", latency_ms=1
        )

    def _load_recorded(self, trace_id: str) -> ProviderResult | None:
        if not self.record_dir:
            return None
        path = self.record_dir / (trace_id.replace("/", "__") + ".json")
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        raw = data.get("raw_text") or ""
        try:
            parsed = Extraction.model_validate_json(raw) if raw else None
        except ValidationError:
            parsed = None
        u = data.get("usage") or {}
        return ProviderResult(
            parsed=parsed,
            raw_text=raw,
            usage=Usage(int(u.get("input_tokens", 0)), int(u.get("output_tokens", 0))),
            model=data.get("model", "recorded"),
            latency_ms=int(data.get("latency_ms", 0)),
            refusal=data.get("refusal"),
        )
