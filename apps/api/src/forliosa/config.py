"""Application settings (environment variables)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from typing_extensions import Annotated

API_ROOT = Path(__file__).resolve().parents[2]  # apps/api


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    forliosa_env: Literal["dev", "prod", "test"] = "dev"
    database_url: str = "sqlite:///./var/forliosa.db"
    redis_url: str | None = None
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )
    session_secret: str = "dev-insecure-session-secret-change-me"
    session_ttl_days: int = 30
    cookie_secure: bool | None = None  # None -> secure in prod
    cookie_domain: str | None = None

    market_data_providers: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["shioaji_data", "demo"]
    )
    shioaji_data_base_url: str = "https://raw.githubusercontent.com/Sinotrade/shioaji-data/main"
    cache_dir: Path = Path("var/cache")
    http_timeout_seconds: float = 20.0
    finmind_token: str | None = None
    stream_interval_seconds: float = 5.0
    demo_jitter: bool | None = None  # None -> on in dev

    @field_validator("cors_origins", "market_data_providers", mode="before")
    @classmethod
    def _split_csv(cls, v: object) -> object:
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
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
