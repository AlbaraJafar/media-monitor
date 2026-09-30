from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://mm:mm_local_password@localhost:5432/media_monitor"

    # Shared secret for n8n -> API calls. Empty disables auth (local tinkering only).
    api_key: str = ""

    # LLMs. The vendor is picked from the model name ("claude-*" -> Anthropic,
    # anything else -> OpenAI), so a provider switch is a config change and the
    # fallback can sit at a different vendor. Versions are pinned so the eval
    # numbers stay meaningful; re-run `make eval` whenever these change.
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    gemini_api_key: str = ""   # for gemini-* models (OpenAI-compatible endpoint)
    humain_api_key: str = ""   # for humain-* models (HUMAIN Node, approved preview access)
    classify_model: str = "gpt-6-luna"         # cheap tier, high volume, structured output
    classify_reasoning_effort: str | None = None  # e.g. "low"; unset = model default
    brief_model: str = "gpt-6-sol"             # briefing draft + claim verifier
    brief_fallback_model: str = "gpt-5.6-sol"  # previous generation; set a claude-* model for cross-vendor failover
    classify_concurrency: int = 8

    # Alerting
    risk_alert_threshold: float = 0.7
    alert_target_minutes: int = 15

    # Dedup. Tuned on live data (2026-09-29): true same-story pairs scored 0.90-0.98;
    # at 0.88-0.89 distinct stories were merged (e.g. "South Korea hits 15M visitors"
    # into a Saudi tourism-investment story). A false merge hides a story from the
    # briefing; a missed merge only shows it twice — so err high.
    dedup_similarity_threshold: float = 0.90
    dedup_lookback_hours: int = 72

    # Ingestion
    max_items_per_feed: int = 25
    max_article_age_hours: int = 72
    fetch_concurrency: int = 8

    # Briefing
    briefing_timezone: str = "Asia/Riyadh"
    briefing_max_articles: int = 40

    # Embeddings
    embedding_model_name: str = "intfloat/multilingual-e5-large"


settings = Settings()
