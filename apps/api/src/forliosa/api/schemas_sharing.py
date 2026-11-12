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


class GroupOut(BaseModel):
    id: str
    name: str
    my_role: Literal["owner", "admin", "member"]
    ranking_enabled: bool
    created_at: str
    members: list[GroupMemberOut]
    my_share: ShareSettings
    push_targets: list[PushTarget]


class GroupSummary(BaseModel):
    id: str
    name: str
    my_role: Literal["owner", "admin", "member"]
    member_count: int
    ranking_enabled: bool
    latest_activity_at: str | None = None
    latest_digest_at: str | None = None


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


class LeaderboardEntry(UserRef):
    return_pct: float | None = None
    total_return_pct: float | None = None
    rank: int | None = None
    is_me: bool


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


class ReactionCount(BaseModel):
    emoji: str
    count: int
    mine: bool


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


# -- push channels ------------------------------------------------------------------------------------------------
class DiscordIn(StrictModel):
    """The webhook URL is checked strictly and tested before it is saved; it is never echoed back."""

    webhook_url: str = Field(min_length=1, max_length=300)
    notify_trades: bool = True
    notify_digest: bool = True


class ChannelPatch(StrictModel):
    notify_trades: bool | None = None
    notify_digest: bool | None = None


class DiscordChannel(BaseModel):
    configured: bool
    status: Literal["active", "disabled"] | None = None
    disabled_reason: str | None = None
    webhook_hint: str | None = Field(default=None, description="只有擁有者看得到（…/最後 4 碼）")
    notify_trades: bool
    notify_digest: bool


class TelegramChannel(BaseModel):
    configured: bool
    status: Literal["active", "disabled"] | None = None
    disabled_reason: str | None = None
    chat_title: str | None = None
    notify_trades: bool
    notify_digest: bool


class Channels(BaseModel):
    discord: DiscordChannel
    telegram: TelegramChannel
    telegram_available: bool


class TelegramLink(BaseModel):
    code: str
    bot_username: str
    expires_at: str
