"""The provider boundary (ADR-5). Everything the rest of the service knows about an LLM is
in this file: one call, a typed result, normalised usage, and two error classes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.extraction.prompt import Turn
from app.extraction.schema import Extraction


class ProviderError(Exception):
    """The provider could not serve the call. `retryable` drives the retry/breaker policy."""

    retryable = True


class ProviderTimeout(ProviderError):
    retryable = True


class ProviderUnavailable(ProviderError):
    retryable = True


class ProviderRejected(ProviderError):
    """4xx that will not succeed on retry (bad schema, content filter, auth)."""

    retryable = False


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class ProviderResult:
    parsed: Extraction | None  # None when the output did not conform to the schema
    raw_text: str
    usage: Usage
    model: str
    latency_ms: int
    refusal: str | None = None


class LLMProvider(Protocol):
    name: str

    async def extract(
        self,
        *,
        system: str,
        turns: list[Turn],
        timeout_s: float,
        max_output_tokens: int,
        trace_id: str,
    ) -> ProviderResult: ...


def to_messages(system: str, turns: list[Turn]) -> list[dict[str, str]]:
    return [{"role": "system", "content": system}] + [{"role": t.role, "content": t.content} for t in turns]
