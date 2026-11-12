"""Application settings (environment variables)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

API_ROOT = Path(__file__).resolve().parents[2]  # apps/api
DEFAULT_SESSION_SECRET = "dev-insecure-session-secret-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    forliosa_env: Literal["dev", "prod", "test"] = "dev"
    database_url: str = "sqlite:///./var/forliosa.db"
    redis_url: str | None = None
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )
    session_secret: str = DEFAULT_SESSION_SECRET
    session_ttl_days: int = 30
    cookie_secure: bool | None = None  # None -> secure in prod
    cookie_domain: str | None = None

    # "commercial" (default): only legally commercially usable data — government open data (TWSE/TPEx
    # OpenAPI, TDCC open data, shioaji-data's official files) and our own archive built from them; never
    # demo data. "personal" (explicit opt-in): every configured source may be used (FinMind, MIS and the
    # TWSE website are labelled 「非商用」 in responses) and demo data fills gaps.
    data_policy: Literal["personal", "commercial"] = "commercial"
    # Highest priority first. archive: our own daily archive of official open data (prices_daily …);
    # twse_openapi / tpex_openapi: official latest-day data; shioaji_data: master/profile/revenue/statements;
    # demo: synthetic data (answers only under DATA_POLICY=personal; under commercial it only names
    # instruments). finmind is NOT in the default: it is a non-commercial source that is built only when
    # DATA_POLICY=personal and it is listed here explicitly. The TWSE MIS provider was removed.
    market_data_providers: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["archive", "twse_openapi", "tpex_openapi", "shioaji_data", "demo"]
    )
    # TAIFEX OpenAPI datasets the open-data inventory marks ``conditional`` (no matching data.gov.tw OGDL
    # dataset found: 期貨／選擇權每日交易行情, 每日外幣參考匯率, 選擇權大額交易人 …) are archived but, under
    # DATA_POLICY=commercial, NOT shown to users until the owner has TAIFEX's written confirmation and sets
    # this to true (see docs/outreach/taifex-licence-inquiry.md and datapolicy.dataset_served).
    taifex_conditional_confirmed: bool = False
    shioaji_data_base_url: str = "https://raw.githubusercontent.com/Sinotrade/shioaji-data/main"
    cache_dir: Path = Path("var/cache")
    http_timeout_seconds: float = 20.0
    finmind_token: str | None = None
    stream_interval_seconds: float = 5.0
    demo_jitter: bool | None = None  # None -> on in dev

    # -- AI (M4) ------------------------------------------------------------------------------------
    # API keys are deliberately NOT settings fields (they would show up in Settings dumps): forliosa.ai.keypool
    # reads CLAUDE_API_KEY_<n> (any letter case, e.g. Claude_API_KEY_1; slot n, one workspace per key) and
    # falls back to ANTHROPIC_API_KEY (slot 0), plus the optional per-slot AI_KEY_<n>_MONTHLY_BUDGET_USD.
    ai_model: str = "claude-haiku-5-5"
    ai_model_chat: str | None = None
    ai_model_why: str | None = None
    ai_model_import: str | None = None
    ai_model_report: str | None = None
    ai_model_analyst: str | None = None
    ai_effort_chat: Literal["low", "medium", "high", "xhigh", "max"] = "low"
    ai_effort_why: Literal["low", "medium", "high", "xhigh", "max"] = "low"
    ai_effort_analyst: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    ai_max_tokens_chat: int = 8000
    ai_max_tool_rounds: int = 8
    ai_daily_message_limit: int = 50  # chat messages per user per Taipei day (0 = no limit)
    ai_monthly_token_budget: int = 3_000_000  # billable tokens per user per Taipei month (0 = no limit)
    ai_thread_max_context_tokens: int = 90_000  # keep prompts under the 100K-token price tier
    ai_dev_dummy_key: bool = False  # send a placeholder key; a proxy injects the real one
    ai_key_cooldown_seconds: float = 60.0
    # A thread stays on its key slot while the slot recovers within this many seconds; otherwise it moves to the
    # slot with the most headroom and continues from a plain-text recap.
    ai_key_sticky_wait_seconds: float = 5.0
    ai_request_timeout_seconds: float = 120.0
    ai_web_search: bool = True
    ai_web_search_max_uses: int = 3
    ai_web_search_allowed_domains: Annotated[list[str], NoDecode] = Field(default_factory=list)  # [] = any
    ai_web_fetch: bool = True
    ai_web_fetch_allowed_domains: Annotated[list[str], NoDecode] = Field(default_factory=list)
    ai_web_dynamic_filtering: bool = False
    ai_eager_tool_streaming: bool = False
    ai_why_enabled: bool = True  # cached per symbol per trading day; rule text on any failure
    ai_why_blocking: bool = False  # True: /why waits for the model; False: generate in the background
    # Analyst views (/instruments/{symbol}/analyst-views): third-party ratings found by web search, shared per
    # symbol per trading day; off = POST answers "unavailable" without a model call.
    ai_analyst_enabled: bool = True
    ai_analyst_search_max_uses: int = 3
    # Off-topic requests (coding, homework, role-play …) with no finance word are declined without a model call.
    ai_scope_precheck: bool = True
    # Threads, messages and drafts are deleted this many days after their last activity (0 = keep forever).
    ai_retention_days: int = 30
    # Who may read GET /ai/admin/keys outside FORLIOSA_ENV=dev/test (comma-separated emails).
    ai_admin_emails: Annotated[list[str], NoDecode] = Field(default_factory=list)

    @field_validator("ai_web_search_allowed_domains", "ai_web_fetch_allowed_domains", "ai_admin_emails",
                     mode="before")
    @classmethod
    def _split_ai_domains(cls, v: object) -> object:
        if isinstance(v, str):
            return [s.strip().lower() for s in v.split(",") if s.strip()]
        return v

    @field_validator("data_policy", mode="before")
    @classmethod
    def _lower_policy(cls, v: object) -> object:
        return v.strip().lower() if isinstance(v, str) else v

    @field_validator("cors_origins", "market_data_providers", mode="before")
    @classmethod
    def _split_csv(cls, v: object) -> object:
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        return v

    @field_validator("cors_origins")
    @classmethod
    def _normalize_origins(cls, v: list[str]) -> list[str]:
        """Browsers send ``Origin: https://app.example.com`` (no path, no trailing slash)."""
        return list(dict.fromkeys(o.strip().rstrip("/") for o in v if o.strip()))

    @field_validator("cookie_domain", mode="before")
    @classmethod
    def _blank_cookie_domain(cls, v: object) -> object:
        """``COOKIE_DOMAIN=`` (empty) means a host-only cookie, not ``Domain=``."""
        if isinstance(v, str) and not v.strip():
            return None
        return v.strip() if isinstance(v, str) else v

    @field_validator("database_url")
    @classmethod
    def _psycopg_driver(cls, v: str) -> str:
        """Railway/Heroku style ``postgres://`` / ``postgresql://`` -> SQLAlchemy + psycopg 3."""
        for prefix in ("postgres://", "postgresql://"):
            if v.startswith(prefix):
                return "postgresql+psycopg://" + v[len(prefix):]
        return v

    @property
    def is_dev(self) -> bool:
        return self.forliosa_env in ("dev", "test")

    @property
    def secure_cookies(self) -> bool:
        return self.cookie_secure if self.cookie_secure is not None else self.forliosa_env == "prod"

    @property
    def jitter_enabled(self) -> bool:
        return self.demo_jitter if self.demo_jitter is not None else self.forliosa_env == "dev"


@lru_cache
def get_settings() -> Settings:
    return Settings()
