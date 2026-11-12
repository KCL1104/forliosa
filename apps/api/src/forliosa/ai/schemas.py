"""Request / response models of the AI endpoints."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from forliosa.api.schemas import TradePreview, Why


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PageIn(_Strict):
    route: str = Field(default="/", max_length=200, description="前端路由，例如 `/`、`/stock/2330.TW`、`/groups`")
    symbol: str | None = Field(default=None, max_length=20)


class ChatIn(_Strict):
    thread_id: str | None = Field(default=None, max_length=40)
    message: str = Field(min_length=1, max_length=4000)
    page: PageIn = Field(default_factory=PageIn)
    privacy: bool = False


class Citation(BaseModel):
    url: str | None
    title: str | None
    cited_text: str = ""


class ThreadSummary(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str
    message_count: int
    preview: str


class ThreadPage(BaseModel):
    items: list[ThreadSummary]
    next_cursor: str | None


class DraftInstrumentOut(BaseModel):
    symbol: str
    code: str
    name: str
    market: str
    currency: str


class DraftAccount(BaseModel):
    id: str
    name: str


class DraftCard(BaseModel):
    id: str
    status: Literal["pending", "signed", "discarded"]
    input: dict[str, Any]
    instrument: DraftInstrumentOut | None
    preview: TradePreview
    notes: list[str]
    account: DraftAccount | None
    transaction_id: str | None
    created_at: str


class ToolStep(BaseModel):
    name: str
    label: str


class ChatError(BaseModel):
    code: str
    message: str


class ThreadMessage(BaseModel):
    id: str
    turn_id: str
    role: Literal["user", "ai"]
    text: str
    citations: list[Citation] = []
    drafts: list[DraftCard] = []
    tools: list[ToolStep] = []
    error: ChatError | None = None
    at: str


class ThreadDetail(BaseModel):
    id: str
    title: str
    model: str
    created_at: str
    updated_at: str
    messages: list[ThreadMessage]


class DraftPatch(_Strict):
    status: Literal["pending", "signed", "discarded"]
    transaction_id: str | None = Field(default=None, max_length=40)


class SuggestedQuestion(BaseModel):
    kind: str
    text: str
    lines: list[str]
    symbol: str | None = None


class SuggestedAction(BaseModel):
    kind: Literal["draft_transaction", "watchlist_add", "review_drafts"]
    label: str
    prompt: str | None = None
    symbol: str | None = None
    count: int | None = None


class Suggestions(BaseModel):
    route: Literal["ledger", "stock", "groups", "history", "other"]
    symbol: str | None
    questions: list[SuggestedQuestion]
    actions: list[SuggestedAction]


class Usage(BaseModel):
    date: str
    month: str
    messages_today: int
    daily_message_limit: int | None
    messages_remaining: int | None
    tokens_month: int
    monthly_token_budget: int | None
    tokens_remaining: int | None
    cost_usd_month: float
    model: str
    available: bool


class AIWhy(Why):
    """``Why`` plus the optional AI sentence: ``headline`` is the AI sentence when ``ai`` is true (the rule text
    stays in ``rule_headline``); ``citations`` must be shown with it."""

    ai: bool = False
    citations: list[Citation] = Field(default_factory=list)
    rule_headline: str | None = None
