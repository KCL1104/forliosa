"""Request/response models of the site admins' back office (docs/api-contract.md 「管理後台」).

The response models list every field explicitly: no email, user id or key material can reach a response by being
added to a service dict later (unknown keys are dropped by the response model).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from forliosa.api.schemas import StrictModel
from forliosa.services.admin import REASON_MAX
from forliosa.textsafe import has_control

KeyState = Literal["ok", "cooling", "disabled", "exhausted", "over_budget", "not_configured"]


class AdminUsers(BaseModel):
    total: int
    new_7d: int = Field(description="過去 7 天建立的帳號數")


class AdminKeySlot(BaseModel):
    """One key slot (``CLAUDE_API_KEY_<n>``): status and this UTC month's usage. Never the key."""

    slot: int
    configured: bool
    state: KeyState
    retry_in_seconds: int | None
    workspace_id: str | None
    month_cost_usd: float = Field(description="本月（UTC）估計費用")
    month_calls: int
    monthly_budget_usd: float | None
    threads: int = Field(description="黏在這把金鑰上的對話數")
    last_error: str | None = Field(description="最近一次失敗的狀態碼與錯誤類型（例如 \"429 rate_limit_error\"）")


class AdminAi(BaseModel):
    month: str = Field(description="UTC 月份（金鑰槽的預算以 UTC 月計）")
    slots: list[AdminKeySlot]


class AdminDataset(BaseModel):
    key: str
    name: str
    agency: str | None
    data_date: str | None = Field(description="存檔看到的最新資料日期")
    fetched_at: str | None = Field(description="最近一次存檔的時間（+08:00）")
    days_behind: int | None = Field(description="最新資料離今天幾天（日曆天）")
    stale: bool = Field(description="最新資料落後今天 3 個交易日以上")


class AdminBackfill(BaseModel):
    enabled: bool = Field(description="PRICE_HISTORY_SOURCE=yahoo")
    rows: int = Field(description="已存的回補日線筆數")
    pending: int = Field(description="還沒問過（或要再問一次）的代號數")
    symbols: dict[str, int] = Field(description="各狀態的代號數：done、not_found、mismatch、no_overlap、error")


class AdminOverview(BaseModel):
    users: AdminUsers
    ai: AdminAi
    datasets: list[AdminDataset]
    history_backfill: AdminBackfill


class BlockedDomain(BaseModel):
    domain: str
    reason: str | None
    created_at: str | None = Field(description="加入的時間（+08:00）；設定在環境變數的沒有")
    from_env: bool = Field(description="寫在 NEWS_BLOCKED_DOMAINS：這裡不能解除")


class BlockDomainIn(StrictModel):
    domain: str = Field(min_length=1, max_length=300)
    reason: str | None = None

    @field_validator("reason")
    @classmethod
    def _reason(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        v = v.strip()
        if len(v) > REASON_MAX:
            raise ValueError(f"原因最多 {REASON_MAX} 個字")
        if has_control(v):
            raise ValueError("原因不能有換行或控制字元")
        return v


class BlockDomainOut(BaseModel):
    domain: str = Field(description="正規化之後的網域（小寫、去掉 www.）")
    deleted_headlines: int = Field(description="刪掉幾則已存的標題（含子網域）")
