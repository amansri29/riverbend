"""Azure OpenAI implementation of LLMProvider using structured outputs.

SDK auto-retry is disabled: retry policy belongs to the worker and the queue (ADR-10).
With `record_dir` set, every successful response is written to disk so the fake provider
can replay the exact same run offline.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import openai
from openai import AsyncAzureOpenAI, AsyncOpenAI

from app.extraction.prompt import Turn
from app.extraction.provider import (
    ProviderRejectedError,
    ProviderResult,
    ProviderTimeoutError,
    ProviderUnavailableError,
    Usage,
    to_messages,
)
from app.extraction.schema import Extraction


class AzureOpenAIProvider:
    """LLMProvider backed by Azure OpenAI structured outputs; SDK errors map to the provider error types."""

    name = "azure_openai"

    def __init__(
        self,
        *,
        endpoint: str,
        api_key: str,
        deployment: str,
        api_version: str,
        record_dir: str | None = None,
        reasoning_effort: str = "",
    ) -> None:
        if api_version == "v1":
            # Azure's OpenAI-compatible surface: same endpoints as OpenAI, no api-version query parameter.
            self._client = AsyncOpenAI(base_url=endpoint.rstrip("/") + "/openai/v1/", api_key=api_key, max_retries=0)
        else:
            self._client = AsyncAzureOpenAI(
                azure_endpoint=endpoint, api_key=api_key, api_version=api_version, max_retries=0
            )
        self._deployment = deployment
        self._record_dir = Path(record_dir) if record_dir else None
        self._extra: dict = {"reasoning_effort": reasoning_effort} if reasoning_effort else {}

    async def extract(
        self, *, system: str, turns: list[Turn], timeout_s: float, max_output_tokens: int, trace_id: str
    ) -> ProviderResult:
        started = time.perf_counter()
        try:
            resp = await self._client.chat.completions.parse(
                model=self._deployment,
                messages=to_messages(system, turns),
                response_format=Extraction,
                max_completion_tokens=max_output_tokens,
                timeout=timeout_s,
                **self._extra,
            )
        except openai.APITimeoutError as e:
            raise ProviderTimeoutError(str(e)) from e
        except openai.LengthFinishReasonError:
            # Output truncated: the schema cannot have been completed. Treat as invalid output.
            latency = int((time.perf_counter() - started) * 1000)
            return ProviderResult(None, "", Usage(0, max_output_tokens), self._deployment, latency, "length")
        except openai.ContentFilterFinishReasonError as e:
            raise ProviderRejectedError(f"content filter: {e}") from e
        except openai.RateLimitError as e:
            raise ProviderUnavailableError(f"rate limited: {e}") from e
        except openai.APIStatusError as e:
            if e.status_code >= 500:
                raise ProviderUnavailableError(f"{e.status_code}: {e.message}") from e
            raise ProviderRejectedError(f"{e.status_code}: {e.message}") from e
        except openai.APIConnectionError as e:
            raise ProviderUnavailableError(str(e)) from e

        latency = int((time.perf_counter() - started) * 1000)
        choice = resp.choices[0]
        usage = Usage(
            input_tokens=resp.usage.prompt_tokens if resp.usage else 0,
            output_tokens=resp.usage.completion_tokens if resp.usage else 0,
        )
        result = ProviderResult(
            parsed=choice.message.parsed,
            raw_text=choice.message.content or "",
            usage=usage,
            model=resp.model or self._deployment,
            latency_ms=latency,
            refusal=choice.message.refusal,
        )
        self._record(trace_id, result)
        return result

    def _record(self, trace_id: str, r: ProviderResult) -> None:
        if not self._record_dir:
            return
        self._record_dir.mkdir(parents=True, exist_ok=True)
        path = self._record_dir / (trace_id.replace("/", "__") + ".json")
        path.write_text(
            json.dumps(
                {
                    "raw_text": r.raw_text,
                    "usage": {"input_tokens": r.usage.input_tokens, "output_tokens": r.usage.output_tokens},
                    "model": r.model,
                    "latency_ms": r.latency_ms,
                    "refusal": r.refusal,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
