from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AGENT_",
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )

    database_url: str = Field(default="sqlite:///./data/agent.db")
    log_level: str = Field(default="INFO")

    # LLM provider — auto-detected from whichever key is set if left blank
    llm_provider: str = Field(default="")   # "anthropic" | "gemini"
    llm_model: str = Field(default="")      # uses provider default when blank

    # Provider keys — set exactly one
    anthropic_api_key: str = Field(default="")
    gemini_api_key: str = Field(default="")

    # Per-node model tiers for the CSV Insight Agent graph (spec/agent.md).
    # fast = latency-sensitive nodes (classify/observe/stuck); quality =
    # code-generation and final-answer composition.
    llm_model_fast: str = Field(default="gemini-2.5-flash")
    # NOTE / spec deviation: spec/agent.md specifies a pro-tier "quality"
    # model (e.g. "gemini-3.1-pro"), but every pro-tier model
    # (gemini-3.1-pro, gemini-3.1-pro-preview, gemini-2.5-pro) returns real
    # HTTP 429 RESOURCE_EXHAUSTED with quota limit 0 on this key's current
    # billing plan, as verified directly against the live API. Defaulting to
    # "gemini-2.5-flash" (same as the fast tier) so the app is real and
    # runnable end-to-end with the key present in .env today. The
    # fast/quality tier distinction remains in the code and graph design;
    # this is only a working default, fully overridable via
    # AGENT_LLM_MODEL_QUALITY once the plan is upgraded to grant pro-tier
    # quota.
    llm_model_quality: str = Field(default="gemini-2.5-flash")

    # Dataset upload storage (api-routes slice, spec/api.md `POST /datasets`).
    upload_dir: str = Field(default="./data/uploads")
    max_upload_mb: int = Field(default=100)


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
