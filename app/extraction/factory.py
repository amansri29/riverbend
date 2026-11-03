from __future__ import annotations

from app.config import Settings
from app.extraction.azure import AzureOpenAIProvider
from app.extraction.fake import FakeProvider
from app.extraction.provider import LLMProvider


def build_provider(s: Settings) -> LLMProvider:
    if s.llm_provider == "azure":
        missing = [
            n for n, v in [
                ("AZURE_OPENAI_ENDPOINT", s.azure_openai_endpoint),
                ("AZURE_OPENAI_API_KEY", s.azure_openai_api_key),
                ("AZURE_OPENAI_DEPLOYMENT", s.azure_openai_deployment),
            ] if not v
        ]
        if missing:
            raise RuntimeError(f"LLM_PROVIDER=azure but missing {', '.join(missing)}")
        return AzureOpenAIProvider(
            endpoint=s.azure_openai_endpoint,
            api_key=s.azure_openai_api_key.get_secret_value(),
            deployment=s.azure_openai_deployment,
            api_version=s.azure_openai_api_version,
            record_dir=s.llm_record_dir or None,
        )
    return FakeProvider(record_dir=s.llm_record_dir or None, fault=s.llm_fault)
