"""Application settings (environment variables)."""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

API_ROOT = Path(__file__).resolve().parents[2]  # apps/api
DEFAULT_SESSION_SECRET = "dev-insecure-session-secret-change-me"
# The private SearXNG (deploy/searxng): the Railway service named ``searxng`` / the local compose service.
SEARXNG_URL_RAILWAY = "http://searxng.railway.internal:8080"
SEARXNG_URL_LOCAL = "http://localhost:8080"
DEFAULT_SEARXNG_ENGINES = ("bing news", "duckduckgo news", "brave.news")


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

    # -- login (M5): Discord OAuth -------------------------------------------------------------------
    # All three must be set for "Sign in with Discord" (GET /auth/providers → discord: true). The client secret is a
    # SecretStr: never shown in reprs or settings dumps, never logged. DISCORD_REDIRECT_URI is the callback on the API
    # host (…/api/v1/auth/discord/callback) exactly as registered in the Discord Developer Portal.
    discord_client_id: str | None = None
    discord_client_secret: SecretStr | None = None
    discord_redirect_uri: str | None = None
    # -- login: Google OAuth (OpenID Connect) ---------------------------------------------------------
    # All three must be set for "Sign in with Google" (GET /auth/providers → google: true). GOOGLE_REDIRECT_URI is the
    # callback on the API host (…/api/v1/auth/google/callback) exactly as registered in Google Cloud Console; https in
    # production. A half-set or non-https configuration does not stop the API (Google is optional): the provider
    # stays off and a warning is logged at startup.
    google_client_id: str | None = None
    google_client_secret: SecretStr | None = None
    google_redirect_uri: str | None = None
    # The frontend's origin (https://app.example.com): OAuth redirects back to it and invite links point at it.
    # Required in prod, where it must be one of CORS_ORIGINS and https.
    frontend_url: str | None = None
    # -- group channels (M5): Telegram bot for group push; without a token telegram_available is false --------
    telegram_bot_token: SecretStr | None = None
    telegram_bot_username: str | None = None

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
    # this to true (see docs/outreach/taifex-licence-inquiry.md and datapolicy.dataset_served). It no longer affects
    # USD/TWD: valuation uses the central bank's 銀行間新臺幣對美元收盤匯率 (OGDL) in every mode.
    taifex_conditional_confirmed: bool = False
    shioaji_data_base_url: str = "https://raw.githubusercontent.com/Sinotrade/shioaji-data/main"
    # SEC EDGAR (US fundamentals and filings). SEC requires a declared User-Agent with a contact e-mail:
    # "Forliosa/1.0 <SEC_CONTACT_EMAIL>". The address is read from the environment only (SecretStr: never shown
    # in reprs or settings dumps, never logged); without it SEC is disabled and US financials / filings return an
    # empty state with a note. Cached rows older than SEC_STALE_HOURS are refreshed on demand (short timeout).
    sec_contact_email: SecretStr | None = None
    sec_enabled: bool = True
    sec_stale_hours: float = 24.0
    sec_on_demand_timeout_seconds: float = 6.0
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
    ai_model_digest: str | None = None  # group weekly digests (M5)
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
    # Group weekly digests (M5): the worker asks for a group-level summary every Saturday 20:00 (Taipei) through the
    # Message Batches API; off = digests keep their facts and are marked failed without a model call.
    ai_digest_enabled: bool = True
    # Off-topic requests (coding, homework, role-play …) with no finance word are declined without a model call.
    ai_scope_precheck: bool = True
    # Threads, messages and drafts are deleted this many days after their last activity (0 = keep forever).
    ai_retention_days: int = 30
    # Who may read GET /ai/admin/keys outside FORLIOSA_ENV=dev/test (comma-separated emails).
    ai_admin_emails: Annotated[list[str], NoDecode] = Field(default_factory=list)
    ai_model_news: str | None = None

    # -- discussions: site admins (ADMIN_EMAILS, comma-separated emails, case-insensitive) ------------------------
    # They moderate *public* discussion content through /admin/discussions/* (reports, hide / unhide, public posting
    # suspensions); everyone else gets 404 there. They never see group content. Empty = no site admin.
    admin_emails: Annotated[list[str], NoDecode] = Field(default_factory=list)
    # The current version of the terms of service and privacy policy (e.g. "2026-11-13"; docs/legal). Recorded on
    # each account at sign-up; when it changes, GET /me shows a different ``terms_version_current`` and the app asks
    # the user to acknowledge it (POST /me/terms-accept). Unset: versions are not tracked.
    terms_version: str | None = None
    # Shown with that request: the day the current version takes effect (YYYY-MM-DD; the terms promise 14 days'
    # notice) and one sentence saying what changed. Both optional; ignored while TERMS_VERSION is unset.
    terms_effective_date: date | None = None
    terms_summary: str | None = None

    # -- News (個股頁「新聞報導」, forliosa.news): metadata only — headline, outlet, time, link ------------------
    # The worker refreshes the tracked symbols (held, watched, or viewed in the last NEWS_VIEW_DAYS days) every
    # NEWS_REFRESH_MINUTES with GDELT DOC 2.0 (free, commercial use allowed with a citation to gdeltproject.org).
    news_enabled: bool = True
    news_refresh_minutes: int = Field(default=45, ge=15)
    news_retention_days: int = Field(default=30, ge=1)
    news_view_days: int = Field(default=3, ge=1)
    news_max_symbols_per_run: int = Field(default=150, ge=1)
    news_gdelt_enabled: bool = True
    news_gdelt_interval_seconds: float = Field(default=6.0, ge=5.0)  # GDELT: one request every 5 s per IP
    # AI web search fills gaps: only for a symbol whose free sources gave fewer than NEWS_AI_MIN_ITEMS headlines in
    # the last 7 days, at most once per NEWS_AI_INTERVAL_HOURS per symbol, paid by the system (feature "news" in
    # ai_usage) and stopped for the rest of the (UTC) month once NEWS_AI_BUDGET_USD is spent.
    news_ai_enabled: bool = True
    news_ai_budget_usd: float = Field(default=30.0, ge=0)
    news_ai_min_items: int = Field(default=3, ge=1)
    news_ai_interval_hours: float = Field(default=24.0, ge=1)
    # SearXNG (self-hosted metasearch, JSON API, deploy/searxng): ON by default (product owner 2026-11-12, third
    # round), reachable only over private networking. Without NEWS_SEARXNG_URL the URL follows FORLIOSA_ENV: prod ->
    # the Railway service ``searxng`` (http://searxng.railway.internal:8080), dev / test -> the local compose service
    # (http://localhost:8080). NEWS_SEARXNG_ENABLED=false or an empty NEWS_SEARXNG_URL turns it off; an unreachable
    # instance only pauses the source (forliosa.news.searxng). Querying upstream search engines automatically breaks
    # their terms; the operator (product owner) carries that risk (docs/research/news-and-external-sources.md §10).
    news_searxng_enabled: bool = True
    news_searxng_url: str | None = None
    # The news engines deploy/searxng/settings.yml enables (kept in step by a test); used to leave out a paused engine.
    news_searxng_engines: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: list(DEFAULT_SEARXNG_ENGINES))
    news_searxng_interval_seconds: float = Field(default=10.0, ge=10.0)  # one query at a time, ≥ 10 s apart
    news_searxng_cache_minutes: float = Field(default=60.0, ge=30.0)  # per symbol: not asked again sooner
    news_searxng_skip_gdelt_items: int = Field(default=8, ge=1)  # GDELT has this many from the last 24 h: skip
    news_searxng_backoff_minutes: float = Field(default=120.0, ge=10.0)  # an engine that refused us (CAPTCHA, 429)
    news_searxng_timeout_seconds: float = Field(default=20.0, ge=5.0, le=60.0)
    # Yahoo股市 per-stock RSS: its terms allow personal, non-commercial use only — used only under
    # DATA_POLICY=personal (this switch can turn it off there too).
    news_yahoo_rss: bool = True
    # Takedown blocklist by domain (a domain blocks its subdomains), on top of the news_blocked_domains table
    # that ``python -m forliosa.news block <domain>`` maintains.
    news_blocked_domains: Annotated[list[str], NoDecode] = Field(default_factory=list)

    # -- 「關於」 description (decision 7): a zh.wikipedia excerpt (CC BY-SA 4.0) or, without an article, an AI-written
    # 2–3 sentence description from official facts (feature "company", system-paid, at most COMPANY_AI_PER_RUN per
    # run). The worker refreshes tracked / recently viewed symbols: Wikipedia monthly, AI only when the facts change.
    company_descriptions_enabled: bool = True
    company_ai_enabled: bool = True
    company_ai_per_run: int = Field(default=10, ge=0)
    company_max_symbols_per_run: int = Field(default=15, ge=1)
    company_wiki_refresh_days: int = Field(default=30, ge=7)
    ai_model_company: str | None = None
    # Optional contact appended to the Wikimedia User-Agent ("Forliosa/1.0 (<contact>)"), per Wikimedia's
    # User-Agent policy. Its own variable: SEC_CONTACT_EMAIL is only ever sent to SEC.
    wikimedia_contact: str | None = None

    @field_validator("news_blocked_domains", mode="before")
    @classmethod
    def _split_news_domains(cls, v: object) -> object:
        if isinstance(v, str):
            return [s.strip().lower().removeprefix("www.") for s in v.split(",") if s.strip()]
        return v

    @field_validator("news_searxng_url", mode="before")
    @classmethod
    def _blank_searxng(cls, v: object) -> object:
        """Unset (None) -> the default for FORLIOSA_ENV (:attr:`searxng_url`); an empty value -> "" (off)."""
        if isinstance(v, str):
            return v.strip().rstrip("/")
        return v

    @field_validator("news_searxng_engines", mode="before")
    @classmethod
    def _split_searxng_engines(cls, v: object) -> object:
        if isinstance(v, str):
            return [" ".join(s.split()).lower() for s in v.split(",") if s.strip()]
        return v

    @field_validator("ai_web_search_allowed_domains", "ai_web_fetch_allowed_domains", "ai_admin_emails",
                     "admin_emails", mode="before")
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

    @field_validator("discord_client_id", "discord_redirect_uri", "google_client_id", "google_redirect_uri",
                     "frontend_url", "telegram_bot_username", "terms_version", "terms_effective_date",
                     "terms_summary", mode="before")
    @classmethod
    def _blank_is_none(cls, v: object) -> object:
        """An empty variable means "not set"; a trailing ``/`` on the frontend URL is dropped (it is an origin)."""
        if isinstance(v, str):
            v = v.strip()
            return v or None
        return v

    @field_validator("frontend_url")
    @classmethod
    def _frontend_origin(cls, v: str | None) -> str | None:
        return v.rstrip("/") if v else v

    @field_validator("discord_client_secret", "google_client_secret", "telegram_bot_token", mode="before")
    @classmethod
    def _blank_secret(cls, v: object) -> object:
        return None if isinstance(v, str) and not v.strip() else v

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
    def discord_enabled(self) -> bool:
        return bool(self.discord_client_id and self.discord_client_secret
                    and self.discord_client_secret.get_secret_value() and self.discord_redirect_uri)

    @property
    def discord_partially_configured(self) -> bool:
        parts = (self.discord_client_id, self.discord_client_secret, self.discord_redirect_uri)
        return any(parts) and not self.discord_enabled

    @property
    def google_enabled(self) -> bool:
        ok = bool(self.google_client_id and self.google_client_secret
                  and self.google_client_secret.get_secret_value() and self.google_redirect_uri)
        # Production: the callback must be https (Google refuses anything else for a public client anyway).
        return ok and (self.forliosa_env != "prod" or (self.google_redirect_uri or "").startswith("https://"))

    @property
    def google_misconfigured(self) -> bool:
        """Some GOOGLE_* variables are set but the provider is off (one missing, or a non-https callback in prod)."""
        parts = (self.google_client_id, self.google_client_secret, self.google_redirect_uri)
        return any(parts) and not self.google_enabled

    @property
    def frontend_base(self) -> str:
        """Where the browser is sent after login and what invite links point at (dev: the first CORS origin)."""
        if self.frontend_url:
            return self.frontend_url
        return self.cors_origins[0] if self.cors_origins else "http://localhost:5173"

    @property
    def telegram_available(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_bot_token.get_secret_value()
                    and self.telegram_bot_username)

    @property
    def searxng_url(self) -> str | None:
        """The private SearXNG the news worker asks, or ``None`` when it is off (NEWS_SEARXNG_ENABLED=false or an
        empty NEWS_SEARXNG_URL). Unset: the Railway service under ``prod``, the local compose service otherwise."""
        if not self.news_searxng_enabled:
            return None
        if self.news_searxng_url is None:
            return SEARXNG_URL_RAILWAY if self.forliosa_env == "prod" else SEARXNG_URL_LOCAL
        return self.news_searxng_url or None

    @property
    def jitter_enabled(self) -> bool:
        return self.demo_jitter if self.demo_jitter is not None else self.forliosa_env == "dev"


@lru_cache
def get_settings() -> Settings:
    return Settings()
