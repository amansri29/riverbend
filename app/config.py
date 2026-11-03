"""Configuration. Everything comes from the environment (or an uncommitted .env file).

Secrets are never read from files in the repo; see .env.example for the full list.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    database_url: str = "postgresql://riverbend_app:riverbend_app@localhost:5432/riverbend"
    migration_database_url: str = "postgresql://postgres:postgres@localhost:5432/riverbend"
    app_db_password: str = "riverbend_app"

    # LLM provider
    llm_provider: Literal["azure", "fake"] = "fake"
    azure_openai_endpoint: str | None = None
    azure_openai_api_key: SecretStr | None = None
    azure_openai_deployment: str | None = None
    azure_openai_api_version: str = "2024-10-21"
    llm_price_input_usd_per_1m: float = 2.50
    llm_price_output_usd_per_1m: float = 10.00
    llm_timeout_seconds: float = 20.0
    llm_max_output_tokens: int = 1200
    llm_fault: Literal["", "down", "slow", "garbage"] = ""
    llm_record_dir: str = "samples/recorded"

    # Queue
    dispatcher: Literal["pubsub", "inline"] = "pubsub"
    pubsub_project: str = "riverbend-local"
    pubsub_emulator_host: str | None = None
    pubsub_topic: str = "work-order-jobs"
    pubsub_subscription: str = "work-order-jobs-push"
    pubsub_dlq_topic: str = "work-order-jobs-dlq"
    pubsub_dlq_subscription: str = "work-order-jobs-dlq-push"
    pubsub_push_endpoint: str = "http://worker:8081/pubsub/push"
    pubsub_dlq_push_endpoint: str = "http://worker:8081/pubsub/dlq"

    # Policy
    default_monthly_cap_usd: float = 25.0
    followup_expiry_days: int = 7
    breaker_failure_threshold: int = 3
    breaker_open_seconds: int = 60
    outbox_republish_after_seconds: int = 30
    resume_defer_seconds: int = 5
    max_resume_deferrals: int = 12
    sweep_interval_seconds: int = 15  # 0 disables the in-process loop (Cloud Scheduler calls /sweep instead)

    # Misc
    catalog_path: str = "catalog/catalog.json"
    dev_api_keys: bool = True  # seed deterministic dev keys (dev-key-<shop_id>)

    @property
    def llm_price_input_micros_per_token(self) -> float:
        return self.llm_price_input_usd_per_1m  # USD/1M tokens == micro-USD per token

    @property
    def llm_price_output_micros_per_token(self) -> float:
        return self.llm_price_output_usd_per_1m


@lru_cache
def get_settings() -> Settings:
    return Settings()
