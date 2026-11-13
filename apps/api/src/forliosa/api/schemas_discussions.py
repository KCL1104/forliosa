"""Request/response models of the discussion threads (docs/api-contract.md 「討論串…」).

Responses are served with ``response_model_exclude_unset``: a **public** author is exactly ``{"name", "is_you"}`` —
``user_id`` and ``avatar_url`` are absent (not ``null``); they only exist on group-scope authors.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator

from forliosa.api.schemas import StrictModel
from forliosa.api.schemas_sharing import EmojiLiteral, ReactionCount
from forliosa.textsafe import has_control, name_key, normalize_text, text_has_control, visible

TITLE_MAX = 80
TOPIC_BODY_MAX = 5000
REPLY_BODY_MAX = 2000
NOTE_MAX = 300
MAX_SYMBOLS = 5
PUBLIC_NAME_MIN, PUBLIC_NAME_MAX = 2, 20
PUBLIC_NAME_KEY_MAX = 200
# Not allowed in a public name, in any letter case or width (also as part of a longer name).
RESERVED_NAMES = ("forliosa", "官方", "管理員", "站方", "admin", "system")

TARGET_PATTERN = r"^(topic|reply):[A-Za-z0-9_]{1,40}$"
Target = Annotated[str, Field(min_length=3, max_length=48, pattern=TARGET_PATTERN)]
ScopeLiteral = Literal["public", "group"]
ReasonLiteral = Literal["spam", "solicitation", "abuse", "other"]


def _one_line(v: str, lo: int, hi: int, what: str) -> str:
    """One visible line: ``lo``–``hi`` characters, of which at least ``lo`` show something (``textsafe.visible``)."""
    v = v.strip()
    if not lo <= len(v) <= hi or len(visible(v)) < lo:
        raise ValueError(f"{what}需為 {lo}–{hi} 字")
    if has_control(v):
        raise ValueError(f"{what}不能有換行或控制字元")
    return v


def _text(v: str, hi: int, what: str, lo: int = 1) -> str:
    """Multi-line plain text (``textsafe.normalize_text``); LF is the only control character allowed."""
    v = normalize_text(v)
    if not lo <= len(v) <= hi or len(visible(v)) < lo:
        raise ValueError(f"{what}需為 {lo}–{hi} 字")
    if text_has_control(v):
        raise ValueError(f"{what}不能有 Tab、控制字元或看不見的格式字元")
    return v


# -- public name ----------------------------------------------------------------------------------------------
class PublicNameIn(StrictModel):
    public_name: str = Field(description="2–20 字、一行；不分大小寫與全半形唯一；不能含保留字")

    @field_validator("public_name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = _one_line(v, PUBLIC_NAME_MIN, PUBLIC_NAME_MAX, "公開暱稱")
        key = name_key(v)
        if len(key) > PUBLIC_NAME_KEY_MAX:  # compatibility characters that expand into many (the column is 400)
            raise ValueError("公開暱稱含有不支援的字元")
        squeezed = "".join(key.split())
        if any(name_key(word) in key or name_key(word) in squeezed for word in RESERVED_NAMES):
            raise ValueError("公開暱稱不能包含保留字（forliosa、官方、管理員、站方、admin、system）")
        return v


# -- requests -------------------------------------------------------------------------------------------------
class TopicIn(StrictModel):
    scope: ScopeLiteral
    group_id: str | None = Field(default=None, max_length=32)
    title: str
    body: str
    symbols: list[Annotated[str, Field(min_length=1, max_length=20)]] | None = Field(default=None,
                                                                                    max_length=MAX_SYMBOLS)

    @field_validator("title")
    @classmethod
    def _title(cls, v: str) -> str:
        return _one_line(v, 1, TITLE_MAX, "標題")

    @field_validator("body")
    @classmethod
    def _body(cls, v: str) -> str:
        return _text(v, TOPIC_BODY_MAX, "內文")


class ReplyIn(StrictModel):
    body: str

    @field_validator("body")
    @classmethod
    def _body(cls, v: str) -> str:
        return _text(v, REPLY_BODY_MAX, "回覆")


class ReactionIn(StrictModel):
    target: Target
    emoji: EmojiLiteral


class ReportIn(StrictModel):
    target: Target
    reason: ReasonLiteral
    note: str | None = None

    @field_validator("note")
    @classmethod
    def _note(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        return _text(v.strip(), NOTE_MAX, "補充說明")


class ModerationIn(StrictModel):
    target: Target
    action: Literal["hide", "unhide", "dismiss"]


class SuspensionIn(StrictModel):
    """``days`` is required: ``null`` means permanent (never by omission)."""

    target: Target
    days: Literal[1, 7, 30] | None
    reason: str | None = None

    @field_validator("reason")
    @classmethod
    def _reason(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        return _text(v.strip(), NOTE_MAX, "原因")


# -- responses ------------------------------------------------------------------------------------------------
class Author(BaseModel):
    """Public scope: only ``name`` (the public name) and ``is_you``. Group scope: also ``user_id`` and
    ``avatar_url`` (``name`` is the display name). ``name`` is null once the account is deleted."""

    name: str | None
    is_you: bool
    user_id: str | None = None
    avatar_url: str | None = None


class GroupRef(BaseModel):
    id: str
    name: str


class SymbolRef(BaseModel):
    symbol: str
    code: str
    name: str


class _TopicBase(BaseModel):
    id: str
    scope: ScopeLiteral
    group: GroupRef | None
    title: str
    symbols: list[SymbolRef]
    author: Author
    created_at: str
    last_activity_at: str
    reply_count: int
    status: Literal["visible", "hidden"]
    mine: bool


class TopicSummary(_TopicBase):
    excerpt: str


class Topic(_TopicBase):
    body: str | None
    reactions: list[ReactionCount]
    can_delete: bool
    can_report: bool
    can_reply: bool


class TopicPage(BaseModel):
    items: list[TopicSummary]
    next_cursor: str | None


class Reply(BaseModel):
    id: str
    topic_id: str
    body: str | None
    author: Author
    created_at: str
    status: Literal["visible", "hidden"]
    reactions: list[ReactionCount]
    mine: bool
    can_delete: bool
    can_report: bool


class ReplyPage(BaseModel):
    items: list[Reply]
    next_cursor: str | None


# -- site admin -----------------------------------------------------------------------------------------------
class AdminReportItem(BaseModel):
    """Reports of one piece of public content. Never an email or a user id: the author is named by public name."""

    target: str
    kind: Literal["topic", "reply"]
    excerpt: str
    author_name: str | None
    topic_id: str
    report_count: int
    reasons: dict[str, int]
    notes: list[str]
    first_reported_at: str
    status: Literal["open", "resolved"]
    hidden: bool


class AdminReportPage(BaseModel):
    items: list[AdminReportItem]
    next_cursor: str | None


class SuspensionOut(BaseModel):
    id: str
    public_name: str | None
    until: str
    reason: str | None
    created_at: str
