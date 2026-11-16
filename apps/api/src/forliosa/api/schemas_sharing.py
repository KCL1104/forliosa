"""Request/response models of M5 (docs/api-contract.md 「分享（M5）」).

Projection responses (``SharedPortfolio``, ``FeedItem``) are served with ``response_model_exclude_unset``: a block or
field whose share toggle is off is **absent** from the JSON, not ``null``.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator

from forliosa.api.schemas import StrictModel
from forliosa.textsafe import has_control


def _trimmed(v: str, lo: int, hi: int, what: str) -> str:
    v = v.strip()
    if not lo <= len(v) <= hi:
        raise ValueError(f"{what}需為 {lo}–{hi} 字")
    return v


def _name(v: str, lo: int, hi: int, what: str) -> str:
    """A name other people see (and that goes into pushed messages): one visible line (``textsafe.has_control``)."""
    v = _trimmed(v, lo, hi, what)
    if has_control(v):
        raise ValueError(f"{what}不能有換行或控制字元")
    return v


class UserRef(BaseModel):
    user_id: str
    display_name: str
    avatar_url: str | None = None


# -- delegations --------------------------------------------------------------------------------------------
class AccountRef(BaseModel):
    id: str
    name: str


class DelegationOut(BaseModel):
    id: str
    owner: UserRef
    viewer: UserRef
    scope: Literal["all", "accounts"]
    accounts: list[AccountRef]
    created_at: str


class Delegations(BaseModel):
    granted: list[DelegationOut]
    received: list[DelegationOut]


class DelegationCandidate(UserRef):
    delegation_id: str | None = None


class DelegationIn(StrictModel):
    viewer_user_id: str = Field(min_length=1, max_length=32)
    scope: Literal["all", "accounts"]
    account_ids: list[str] = Field(default_factory=list, max_length=100)


class DelegationPatch(StrictModel):
    scope: Literal["all", "accounts"]
    account_ids: list[str] = Field(default_factory=list, max_length=100)


# -- groups -------------------------------------------------------------------------------------------------
class ShareSettings(StrictModel):
    """Every toggle is required: the member confirms each one (default proposal: only ``returns`` on)."""

    returns: bool
    holdings: bool
    amounts: bool
    trades: bool
    trade_prices: bool
    push: bool


class GroupIn(StrictModel):
    name: str

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        return _name(v, 1, 40, "群組名稱")


class GroupPatch(StrictModel):
    name: str | None = None
    ranking_enabled: bool | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, v: str | None) -> str | None:
        return None if v is None else _name(v, 1, 40, "群組名稱")


class TransferIn(StrictModel):
    user_id: str = Field(min_length=1, max_length=32)


class RoleIn(StrictModel):
    role: Literal["admin", "member"]


class GroupMemberOut(UserRef):
    role: Literal["owner", "admin", "member"]
    joined_at: str
    is_me: bool


class PushTarget(BaseModel):
    kind: Literal["discord", "telegram"]
    label: str


class GroupPlanOut(BaseModel):
    """群組加值包 (``services.group_plans``): every member sees it."""

    tier: Literal["free", "boosted"]
    until: str | None = Field(default=None, description="加值的最後一天（YYYY-MM-DD，台北）；null＝免費")
    member_cap: int = Field(description="最多幾位成員（免費 15、加值 50；之前建立的群組維持 50）；滿了就不能再加入")
    grandfathered: bool = Field(description="加值包推出前建立的群組：不論方案都維持 50 位")
    daily_report: bool = Field(description="有群組 AI 日報（加值中）")


class GroupOut(BaseModel):
    id: str
    name: str
    my_role: Literal["owner", "admin", "member"]
    ranking_enabled: bool
    created_at: str
    members: list[GroupMemberOut]
    my_share: ShareSettings
    push_targets: list[PushTarget]
    plan: GroupPlanOut


class GroupSummary(BaseModel):
    id: str
    name: str
    my_role: Literal["owner", "admin", "member"]
    member_count: int
    ranking_enabled: bool
    latest_activity_at: str | None = None
    latest_digest_at: str | None = None
    latest_daily_at: str | None = Field(default=None, description="最新一份群組 AI 日報寫好的時間")
    plan: GroupPlanOut


class PlanAttachIn(StrictModel):
    """The owner puts one of their own boosts (``GET /me/group-passes``) on this group."""

    pass_id: str = Field(min_length=1, max_length=32)


class MyPassGroup(BaseModel):
    id: str
    name: str
    my_role: Literal["owner", "admin", "member"]


class MyGroupPass(BaseModel):
    """A boost this account was granted (as the payer)."""

    id: str
    until: str | None = Field(description="最後一天（YYYY-MM-DD，台北）")
    active: bool
    attached: bool = Field(description="已經用在某個群組")
    group: MyPassGroup | None = Field(description="用在哪個群組（只有我還是成員時才有）")


class InviteIn(StrictModel):
    expires: Literal["24h", "7d"] = "7d"
    multi_use: bool = False


class InviteOut(BaseModel):
    id: str
    url: str | None = Field(default=None, description="只有建立時回傳")
    expires_at: str
    multi_use: bool
    uses: int
    created_at: str


class InvitePreview(BaseModel):
    group_name: str
    inviter_display_name: str | None = None
    status: Literal["valid", "member"]
    # only with status "member" (signed in and already a member); absent otherwise
    group_id: str | None = None


class AcceptIn(StrictModel):
    share: ShareSettings


# -- projections ----------------------------------------------------------------------------------------------
class SharedHolding(BaseModel):
    symbol: str
    name: str
    weight: float


class SharedReturns(BaseModel):
    day: float | None = None
    month: float | None = None
    year: float | None = None
    total: float | None = None


class SharedAmounts(BaseModel):
    market_value: float | None = None
    day_change: float | None = None
    total_pnl: float | None = None


class SharedPortfolio(UserRef):
    """Only the blocks the member shares in this group are present (absent keys, never null)."""

    returns: SharedReturns | None = None
    holdings: list[SharedHolding] | None = None
    amounts: SharedAmounts | None = None
    is_demo: bool | None = None


class ReactionCount(BaseModel):
    emoji: str
    count: int
    mine: bool


class LeaderboardEntry(UserRef):
    return_pct: float | None = None
    total_return_pct: float | None = None
    rank: int | None = None
    is_me: bool
    # only on my own row: the period returns leave out my holdings without a close (US stocks under commercial)
    excludes_unpriced: bool = False


class BenchmarkReturn(BaseModel):
    symbol: str
    name: str
    return_pct: float | None = None


class Leaderboard(BaseModel):
    period: Literal["day", "month", "year"]
    date: date
    start_date: date
    as_of: str
    ranked: bool
    entries: list[LeaderboardEntry]
    benchmarks: list[BenchmarkReturn]
    notes: list[str]
    sources: list[str]
    is_demo: bool
    # the day's thread ``leaderboard:<date>`` (the same for every period), like FeedItem / Digest
    comment_count: int
    reactions: list[ReactionCount]


class MemberHoldings(UserRef):
    holdings: list[SharedHolding]


class CommonHolding(BaseModel):
    symbol: str
    name: str
    holder_count: int


class IndustryOverlap(BaseModel):
    industry: str
    holder_count: int


class GroupHoldings(BaseModel):
    members: list[MemberHoldings]
    common: list[CommonHolding]
    industries: list[IndustryOverlap]
    is_demo: bool


class FeedItem(UserRef):
    """``trade``: one member's buys (or sells) of one symbol on one day; ``price`` / ``currency`` only with the
    member's ``trade_prices``. ``member_joined``: only identity and ``created_at``."""

    id: str
    type: Literal["trade", "member_joined"]
    side: Literal["buy", "sell"] | None = None
    symbol: str | None = None
    name: str | None = None
    trade_date: date | None = None
    count: int | None = None
    price: float | None = None
    currency: str | None = None
    created_at: str
    comment_count: int | None = None
    reactions: list[ReactionCount] | None = None


class FeedPage(BaseModel):
    items: list[FeedItem]
    next_cursor: str | None = None


TARGET_PATTERN = r"^(trade|digest|leaderboard):[A-Za-z0-9_\-]{1,58}$"
Target = Annotated[str, Field(min_length=3, max_length=64, pattern=TARGET_PATTERN)]
EmojiLiteral = Literal["👍", "🎉", "🔥", "😮", "😢", "👀"]


class CommentIn(StrictModel):
    target: Target
    body: str

    @field_validator("body")
    @classmethod
    def _body(cls, v: str) -> str:
        return _trimmed(v, 1, 500, "留言")


class CommentOut(BaseModel):
    id: str
    target: str
    user_id: str | None = None
    display_name: str
    avatar_url: str | None = None
    body: str
    created_at: str
    can_delete: bool


class CommentPage(BaseModel):
    items: list[CommentOut]
    next_cursor: str | None = None


class ReactionIn(StrictModel):
    target: Target
    emoji: EmojiLiteral


class Reactions(BaseModel):
    target: str
    reactions: list[ReactionCount]


class Providers(BaseModel):
    discord: bool
    dev_login: bool


# -- weekly AI digest ----------------------------------------------------------------------------------------------
class DigestReturn(BaseModel):
    user_id: str
    display_name: str
    week_return_pct: float | None = None


class DigestBenchmark(BaseModel):
    symbol: str
    name: str
    week_return_pct: float | None = None


class DigestFacts(BaseModel):
    """Filtered on every read by the current memberships and share settings."""

    returns: list[DigestReturn]
    benchmarks: list[DigestBenchmark]
    common_holdings: list[CommonHolding]
    industries: list[IndustryOverlap]
    trades_count: int


class Digest(BaseModel):
    id: str
    status: Literal["pending", "ready", "failed"]
    week_start: date
    week_end: date
    created_at: str
    summary: str
    facts: DigestFacts
    notes: list[str]
    disclaimer: str
    sources: list[str]
    is_demo: bool
    comment_count: int
    reactions: list[ReactionCount]


class DigestPage(BaseModel):
    items: list[Digest]
    next_cursor: str | None = None


# -- 群組 AI 日報 (boosted groups) ------------------------------------------------------------------------------------
class DailyReturn(BaseModel):
    user_id: str
    display_name: str
    day_return_pct: float | None = None


class DailyBenchmark(BaseModel):
    symbol: str
    name: str
    day_return_pct: float | None = None


class DailyCommonHolding(BaseModel):
    symbol: str
    name: str
    holder_count: int
    day_change_pct: float | None = Field(default=None, description="這檔股票這天的漲跌（台股；美股為 null）")


class DailyTrade(BaseModel):
    """The day's trades without names: side and stock, merged."""

    side: Literal["buy", "sell"]
    symbol: str
    name: str
    count: int


class DailyWhy(BaseModel):
    """A common holding that moved the most: link to its 「為什麼漲跌」 on the stock page (/stock/{symbol})."""

    symbol: str
    name: str
    day_change_pct: float | None = None


class DailyFacts(BaseModel):
    """Filtered on every read by the current memberships and share settings."""

    returns: list[DailyReturn]
    benchmarks: list[DailyBenchmark]
    common_holdings: list[DailyCommonHolding]
    trades: list[DailyTrade]
    trades_count: int
    why: list[DailyWhy]


class DailyReport(BaseModel):
    id: str
    status: Literal["pending", "ready", "failed"] = Field(
        description="pending：AI 摘要還在寫；ready：寫好了（summary 可能是空的，notes 會說為什麼）；failed：只有數字")
    trading_day: date
    created_at: str
    finished_at: str | None = None
    summary: str
    facts: DailyFacts
    notes: list[str]
    market_summary: bool = Field(description="市場頁有這天的 AI 收盤重點（連到 /market）")
    disclaimer: str
    sources: list[str]
    is_demo: bool


class DailyReportPage(BaseModel):
    items: list[DailyReport]
    next_cursor: str | None = None


# -- push channels ------------------------------------------------------------------------------------------------
class DiscordIn(StrictModel):
    """The webhook URL is checked strictly and tested before it is saved; it is never echoed back."""

    webhook_url: str = Field(min_length=1, max_length=300)
    notify_trades: bool = True
    notify_digest: bool = True
    notify_daily: bool | None = Field(default=None, description="群組 AI 日報；省略＝不變（新的頻道是關的）")


class ChannelPatch(StrictModel):
    notify_trades: bool | None = None
    notify_digest: bool | None = None
    notify_daily: bool | None = None


class DiscordChannel(BaseModel):
    configured: bool
    status: Literal["active", "disabled"] | None = None
    disabled_reason: str | None = None
    webhook_hint: str | None = Field(default=None, description="只有擁有者看得到（…/最後 4 碼）")
    notify_trades: bool
    notify_digest: bool
    notify_daily: bool = Field(description="群組 AI 日報（加值的群組；預設關）")


class TelegramChannel(BaseModel):
    configured: bool
    status: Literal["active", "disabled"] | None = None
    disabled_reason: str | None = None
    chat_title: str | None = None
    notify_trades: bool
    notify_digest: bool
    notify_daily: bool = Field(description="群組 AI 日報（加值的群組；預設關）")


class Channels(BaseModel):
    discord: DiscordChannel
    telegram: TelegramChannel
    telegram_available: bool


class TelegramLink(BaseModel):
    code: str
    bot_username: str
    expires_at: str
