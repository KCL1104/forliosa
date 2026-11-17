"""Request/response models of the site admins' back office (docs/api-contract.md 「管理後台」).

The response models list every field explicitly: no email, user id or key material can reach a response by being
added to a service dict later (unknown keys are dropped by the response model). The one exception is the members list
(``AdminMember``): an admin grants membership by email, so it shows the members' emails.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from forliosa.api.schemas import StrictModel
from forliosa.plans import NOTE_MAX
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


class AdminUsPrices(BaseModel):
    """US closes from Databento (``forliosa.us_prices``): progress of the backfill and the newest session stored."""

    enabled: bool = Field(description="US_PRICE_SOURCE=databento（金鑰只放在 worker 上，抓資料的是 worker）")
    rows: int = Field(description="已存的美股日線筆數")
    pending: int = Field(description="還沒回補的代號數")
    first_day: str = Field(description="資料最早從哪一天（EQUS.SUMMARY：2024-07-01）")
    stored_through: str | None = Field(description="已存的最新美股交易日（紐約日期）")
    symbols: dict[str, int] = Field(description="各狀態的代號數：done、untracked（沒人追蹤、停更）、not_found、error")


NewsSourceState = Literal["ok", "paused", "off"]


class AdminNewsSource(BaseModel):
    """One news source: on or off, paused after a refusal (until when, why), when it last answered, what it added."""

    key: str = Field(description="gdelt | searxng | ai_search | yahoo_rss | langsearch")
    name: str
    state: NewsSourceState = Field(description="ok：照常問；paused：暫停中（paused_until 或預算）；off：沒有開")
    paused_until: str | None = Field(description="暫停到什麼時候（+08:00）；不是暫停或沒有期限時是 null")
    reason: Literal["rate_limited", "blocked", "unreachable", "budget"] | None = Field(
        description="暫停的原因：限流（429）、拒絕（封鎖、每個引擎都暫停）、連不上、本月 AI 預算用完")
    last_success_at: str | None = Field(description="最近一次有回答的時間（+08:00）")
    new_24h: int = Field(description="過去 24 小時存進來的新標題數")


class AdminNewsEngine(BaseModel):
    engine: str = Field(description="SearXNG 的上游引擎，例如 \"bing news\"")
    until: str = Field(description="暫停到什麼時候（+08:00）")


class AdminLangSearch(BaseModel):
    """LangSearch's UTC day (``forliosa.news.langsearch.status``; 2026-11-17): counts only."""

    enabled: bool = Field(description="NEWS_LANGSEARCH_ENABLED")
    configured: bool = Field(description="開著而且有 LANGSEARCH_API_KEY")
    day_utc: str = Field(description="這些數字的 UTC 日期（台北 08:00 換日）")
    requests: int = Field(description="今天送出的請求數")
    request_cap: int = Field(description="今天的請求上限（降級時是前一天被擋前成功次數的 80%）")
    tokens: int = Field(description="今天用掉的 token（input + output）")
    token_cap: int = Field(description="NEWS_LANGSEARCH_MAX_TOKENS_PER_DAY")
    first_fills: int = Field(description="今天第一次查的檔數")
    stopped: Literal["quota", "contract", "blocked"] | None = Field(
        description="今天為什麼停下：quota（額度，429）、contract（回應超過 token 上限）、blocked（401／403／轉址）")
    level: int = Field(
        description="降級：0 正常；1 連 2 天碰到額度（上限 80%、中小型股放慢）；2 只跑大盤和有人持有的大型股")
    paused_until: str | None = Field(description="整個來源暫停到什麼時候（+08:00）")
    warning: Literal["contents_cap_ignored"] | None = Field(
        description="contents_cap_ignored：回應的 token 遠超過上限，字數限制沒有生效，今天停用")
    tiers: dict[str, int] = Field(description="各分級的檔數：large、mid、small、quiet")


class AdminNews(BaseModel):
    enabled: bool = Field(description="NEWS_ENABLED")
    refresh_minutes: int = Field(description="多久整理一次（分鐘）")
    last_run_at: str | None = Field(description="最近一次向任何來源問新聞的時間（+08:00）")
    new_24h: int = Field(description="過去 24 小時存進來的新標題數（全部來源）")
    sources: list[AdminNewsSource]
    paused_engines: list[AdminNewsEngine] = Field(description="暫停中的 SearXNG 上游引擎")
    ai_month_cost_usd: float = Field(description="本月（UTC）新聞 AI 搜尋的估計費用")
    ai_budget_usd: float = Field(description="NEWS_AI_BUDGET_USD")
    langsearch: AdminLangSearch | None = Field(default=None, description="LangSearch 今天（UTC）的用量與狀態")


class AdminOverview(BaseModel):
    users: AdminUsers
    ai: AdminAi
    datasets: list[AdminDataset]
    history_backfill: AdminBackfill
    us_prices: AdminUsPrices | None = None
    news: AdminNews


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


class AdminMember(BaseModel):
    """An account granted membership (``forliosa.plans``); expired ones stay listed so they can be renewed."""

    user_id: str
    email: str
    display_name: str
    until: str | None = Field(description="最後一天（YYYY-MM-DD，台北）；null＝沒有到期日")
    note: str | None = Field(description="站方自己的備註（例如收款紀錄）")
    active: bool = Field(description="今天還是會員")


class MemberGrantIn(StrictModel):
    email: str = Field(min_length=3, max_length=320)
    until: date | None = Field(default=None, description="最後一天（台北）；null＝沒有到期日")
    note: str | None = None

    @field_validator("note")
    @classmethod
    def _note(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        v = v.strip()
        if len(v) > NOTE_MAX:
            raise ValueError(f"備註最多 {NOTE_MAX} 個字")
        if has_control(v):
            raise ValueError("備註不能有控制字元")
        return v


def _admin_note(v: str | None) -> str | None:
    if v is None or not v.strip():
        return None
    v = v.strip()
    if len(v) > NOTE_MAX:
        raise ValueError(f"備註最多 {NOTE_MAX} 個字")
    if has_control(v):
        raise ValueError("備註不能有控制字元")
    return v


class AdminGroupPass(BaseModel):
    """A 群組加值包 granted by hand (``services.group_plans``). Only the payer and the group's id: never the group's
    name, members or content."""

    id: str
    payer_user_id: str | None = Field(description="付款人；帳號刪除後是 null（加值照樣用到到期）")
    email: str | None
    display_name: str | None
    until: str | None = Field(description="最後一天（YYYY-MM-DD，台北）")
    note: str | None = Field(description="站方自己的備註（例如收款紀錄）")
    active: bool = Field(description="今天還在加值")
    group_id: str | None = Field(description="用在哪個群組（編號）；null＝付款人還沒選")
    attached_at: str | None = None
    created_at: str


class GroupPassGrantIn(StrictModel):
    email: str = Field(min_length=3, max_length=320, description="付款人的 email（對方要先登入過一次）")
    until: date = Field(description="最後一天（台北）")
    note: str | None = None
    group_id: str | None = Field(default=None, min_length=1, max_length=32,
                                 description="直接用在這個群組（付款人必須是擁有者）；省略＝由付款人在群組設定選")

    @field_validator("note")
    @classmethod
    def _note(cls, v: str | None) -> str | None:
        return _admin_note(v)


class GroupPassPatch(StrictModel):
    until: date | None = Field(default=None, description="新的最後一天（延長或縮短）")
    note: str | None = None

    @field_validator("note")
    @classmethod
    def _note(cls, v: str | None) -> str | None:
        return _admin_note(v)
