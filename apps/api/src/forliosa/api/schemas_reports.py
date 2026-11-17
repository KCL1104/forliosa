"""Response and request models of the market reports (contract §12, §14). Field names match ``apps/web`` types."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from forliosa.api.schemas import StrictModel

Kind = Literal["premarket", "close", "weekly"]


class _Out(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Sentence(_Out):
    """The admin view (``/admin/market-reports/{id}/variants/{label}``) adds ``refs`` (the data pack's ids); a member
    never gets them."""

    text: str
    cites: list[int] = Field(default_factory=list, description="註腳號碼")


class Paragraph(_Out):
    sentences: list[Sentence]


class NumberItem(_Out):
    key: str
    label: str
    value: str
    change: str | None = None
    tone: Literal["rise", "fall", "flat"] | None = None
    date_label: str = ""
    estimate: bool = False
    note: str | None = None


class Item(_Out):
    title: str
    meta: str | None = None
    paragraphs: list[Paragraph]


class Cell(_Out):
    text: str
    tone: Literal["rise", "fall"] | None = None
    sub: str | None = None


class TableColumn(_Out):
    key: str
    label: str
    align: Literal["left", "right"]
    num: bool


class TableRow(_Out):
    cells: dict[str, Cell]
    href: str | None = None


class TableSpec(_Out):
    id: str
    title: str
    rule: str | None = None
    columns: list[TableColumn]
    rows: list[TableRow]
    fold_after: int | None = None
    empty_text: str | None = None
    note: str | None = None
    source_labels: list[str] = Field(default_factory=list)


class TextBlock(_Out):
    type: Literal["text"]
    paragraphs: list[Paragraph]


class ItemsBlock(_Out):
    type: Literal["items"]
    items: list[Item]


class ChartBlock(_Out):
    type: Literal["chart"]
    chart: dict[str, Any] = Field(description="AiChart（line／columns／bars 或對話用的五種）")
    caption: Paragraph | None = None
    chart_of_day: bool = False


class TableBlock(_Out):
    type: Literal["table"]
    table: TableSpec


class NoteBlock(_Out):
    type: Literal["note"]
    text: str


Block = Annotated[TextBlock | ItemsBlock | ChartBlock | TableBlock | NoteBlock, Field(discriminator="type")]


class Section(_Out):
    key: str
    title: str
    origin: Literal["data", "ai"]
    origin_label: str
    collapsed_mobile: bool = False
    blocks: list[Block]


class Footnote(_Out):
    n: int
    kind: Literal["data", "web", "calendar", "filing", "research"]
    label: str
    outlet: str | None = None
    url: str | None = None
    date_label: str | None = None


class WebSource(_Out):
    n: int
    outlet: str
    title: str
    url: str
    published_label: str = ""


class Disagreement(_Out):
    text: str


class Sources(_Out):
    data: list[str] = Field(default_factory=list)
    web: list[WebSource] = Field(default_factory=list)
    disagreements: list[Disagreement] = Field(default_factory=list)
    manual: list[str] = Field(default_factory=list)


class CalRow(_Out):
    time_label: str | None = None
    title: str
    kind: str
    kind_label: str
    sectors: list[str] = Field(default_factory=list)
    symbol: str | None = None
    href: str | None = None
    url: str | None = None
    source_label: str = ""


class CalFold(_Out):
    label: str
    count: int
    rows: list[CalRow]


class CalGroup(_Out):
    date: str
    date_label: str
    rows: list[CalRow]
    folded: list[CalFold] = Field(default_factory=list)


class CalendarBlock(_Out):
    title: str
    groups: list[CalGroup]
    empty_text: str | None = None
    source_labels: list[str] = Field(default_factory=list)


class Period(_Out):
    start: str
    end: str


class Correction(_Out):
    at: str
    note: str


class MarketReport(_Out):
    id: str
    kind: Kind
    kind_label: str
    edition_date: str
    edition_label: str
    period: Period
    next_period: Period | None = None
    version: int
    edition: Literal["data", "ai", "tables", "correction"]
    has_ai: bool
    published_at: str
    first_published_at: str
    as_of: str
    as_of_label: str
    disclaimer_line: str
    title: str
    title_origin: Literal["ai", "rules"]
    highlights: list[Paragraph]
    highlights_origin: Literal["ai", "rules"]
    numbers: list[NumberItem]
    sections: list[Section]
    calendar: CalendarBlock | None = None
    footnotes: list[Footnote]
    sources: Sources
    disclaimer_full: str
    model_line: str | None = None
    corrections: list[Correction] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    status_line: str | None = None
    is_demo: bool = False


class ReportSummary(_Out):
    id: str
    kind: Kind
    kind_label: str
    edition_date: str
    edition_label: str
    title: str
    has_ai: bool
    published_at: str
    corrected: bool


class ReportsStatus(_Out):
    available: bool
    mode: Literal["trial", "public", "paused"] | None = None
    unread: bool
    latest: list[ReportSummary]


class ReportsPage(_Out):
    items: list[ReportSummary]
    next_cursor: str | None = None


# -- admin -------------------------------------------------------------------------------------------------------
Model = Literal["claude-opus-5-5", "claude-sonnet-5-5"]
Effort = Literal["low", "medium", "high", "xhigh"]


class WriterIn(StrictModel):
    model: Model
    effort: Effort


class WritersIn(StrictModel):
    premarket: WriterIn | None = None
    close: WriterIn | None = None
    weekly: WriterIn | None = None


class ReportsConfigIn(StrictModel):
    mode: Literal["trial", "public", "paused"] | None = None
    writers: WritersIn | None = None


class VoteIn(StrictModel):
    preferred: Literal["A", "B", "C"]
    note: str = Field(default="", max_length=500)


class RevealIn(StrictModel):
    force: bool = False


class CorrectionIn(StrictModel):
    note: str = Field(min_length=1, max_length=200)
    drop_sections: list[str] = Field(default_factory=list, max_length=20)


class RebuildIn(StrictModel):
    kind: Kind
    edition_date: date


class NyseIn(StrictModel):
    name: str = Field(min_length=1, max_length=80)
    kind: Literal["closed", "early_close"]
    close_time_et: str | None = Field(default=None, max_length=5)
    source_url: str = Field(min_length=1, max_length=300)
    verified: bool = False


class MacroIn(StrictModel):
    event_date: date
    local_time: str | None = Field(default=None, max_length=5)
    tz: str = Field(min_length=1, max_length=32)
    country: str = Field(min_length=2, max_length=2)
    title: str = Field(min_length=1, max_length=120)
    agency: str = Field(min_length=1, max_length=80)
    official_url: str = Field(min_length=1, max_length=300)
    sectors: list[str] = Field(default_factory=list, max_length=10)
    note: str = Field(default="", max_length=200)


class EarningsIn(StrictModel):
    symbol: str = Field(min_length=1, max_length=20)
    company: str = Field(min_length=1, max_length=100)
    report_date: date
    timing: Literal["bmo", "amc", "during", "unknown"]
    time_et: str | None = Field(default=None, max_length=5)
    official_url: str | None = Field(default=None, max_length=300)
    sectors: list[str] = Field(default_factory=list, max_length=10)
    note: str = Field(default="", max_length=200)
