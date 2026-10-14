from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "LeadPilot"
    database_url: str = "sqlite:///./leadpilot.db"

    # Security. Empty API_KEY disables auth (local dev / public demo only).
    api_key: str = ""
    webhook_secret: str = ""

    # LLM. Provider "none" runs the deterministic heuristic agents (no key needed).
    llm_provider: Literal["openai", "anthropic", "none"] = "none"
    llm_model: str = "gpt-4o-mini"
    openai_api_key: str = ""
    anthropic_api_key: str = ""

    # Who you sell to. The qualifier agent scores every lead against this.
    icp_description: str = (
        "B2B companies (5-500 employees) that want AI agents, RAG assistants, "
        "workflow automation or backend/API work, with a real budget and a clear use case."
    )

    # CRM
    crm_provider: Literal["mock", "hubspot", "zoho"] = "mock"
    hubspot_token: str = ""
    zoho_client_id: str = ""
    zoho_client_secret: str = ""
    zoho_refresh_token: str = ""
    zoho_dc: str = "com"  # com, eu, in, com.au, jp, ca

    # Enrichment
    enrich_fetch_website: bool = True
    enrich_timeout_s: float = 6.0

    # Scoring thresholds
    hot_threshold: int = 70
    warm_threshold: int = 45

    # Background jobs
    run_worker: bool = True
    worker_interval_s: float = 3.0
    max_attempts: int = 3
    report_cron_day: str = "mon"
    report_cron_hour: int = 8

    # Notifications
    slack_webhook_url: str = ""

    seed_demo: bool = False

    @property
    def sqlalchemy_url(self) -> str:
        url = self.database_url
        # Render / Heroku / Railway hand out postgres:// URLs.
        if url.startswith("postgres://"):
            url = "postgresql+psycopg://" + url[len("postgres://"):]
        elif url.startswith("postgresql://"):
            url = "postgresql+psycopg://" + url[len("postgresql://"):]
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()
