"""Market-data provider protocol and the value types providers return.

Every method may return ``None`` meaning "this provider cannot answer"; the
:class:`~forliosa.marketdata.service.MarketData` facade then asks the next provider.
Providers raise :class:`ProviderUnavailable` on network/format problems; the facade
temporarily skips a provider that keeps failing.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable


class ProviderUnavailable(RuntimeError):
    """Upstream unreachable, blocked, rate limited or returned an unexpected shape."""


def market_of_symbol(symbol: str) -> str:
    if symbol.endswith(".TWO"):
        return "TPEX"
    if symbol.endswith(".TW"):
        return "TWSE"
    return "US"


def code_of_symbol(symbol: str) -> str:
    return symbol.split(".", 1)[0]


def tw_symbol(code: str, market: str) -> str:
    return f"{code}.TWO" if market.upper() in ("TPEX", "OTC") else f"{code}.TW"


@dataclass(frozen=True)
class InstrumentInfo:
    symbol: str
    code: str
    name: str
    market: str  # "TWSE" | "TPEX" | "US"
    type: str  # "stock" | "etf"
    currency: str  # "TWD" | "USD"
    industry: str | None = None
    summary: str | None = None
    chain_stage: str | None = None
    aliases: tuple[str, ...] = ()
    source: str = ""


@dataclass(frozen=True)
class InstrumentProfile:
    symbol: str
    summary: str | None = None
    chain_stage: str | None = None
    themes: tuple[str, ...] = ()
    shares_outstanding: int | None = None
    market_cap: Decimal | None = None
    data_sources: tuple[str, ...] = ()
    is_demo: bool = False


@dataclass
class QuoteData:
    symbol: str
    price: Decimal | None = None
    prev_close: Decimal | None = None
    open: Decimal | None = None
    high: Decimal | None = None
    low: Decimal | None = None
    volume: int | None = None  # shares
    as_of: datetime | None = None
    trade_date: date | None = None
    is_realtime: bool = False
    is_demo: bool = False
    source: str = ""

    _MERGEABLE = ("price", "prev_close", "open", "high", "low", "volume", "as_of", "trade_date")

    def missing(self) -> list[str]:
        return [f for f in self._MERGEABLE if getattr(self, f) is None]

    def merged_with(self, other: QuoteData) -> QuoteData:
        """Fill this quote's missing fields from ``other`` (a lower-priority provider)."""
        if other.trade_date and self.trade_date and other.trade_date != self.trade_date:
            # Do not mix days: only fill prev_close from a provider that agrees on the day.
            fillable = ()
        else:
            fillable = tuple(self.missing())
        updates = {f: getattr(other, f) for f in fillable if getattr(other, f) is not None}
        if not updates:
            return self
        sources = [s for s in (self.source, other.source) if s]
        return replace(
            self, **updates, is_demo=self.is_demo or other.is_demo, source="+".join(dict.fromkeys(sources))
        )


@dataclass(frozen=True)
class Candle:
    t: date
    o: Decimal
    h: Decimal
    l: Decimal  # noqa: E741 - contract field name
    c: Decimal
    v: int


@dataclass(frozen=True)
class DividendEvent:
    symbol: str
    year: int
    period: str
    cash_dividend: Decimal  # per share
    stock_dividend: Decimal  # NT$ per share (配股元)
    ex_dividend_date: date | None
    payment_date: date | None
    is_demo: bool = False


@dataclass(frozen=True)
class CorporateEvent:
    symbol: str
    date: date
    kind: str  # "split" | "capital_reduction"
    ratio: Decimal  # split: new shares per old; capital_reduction: shares removed per share


@dataclass(frozen=True)
class RevenueRow:
    period: str  # "2026-10"
    revenue: int  # thousand TWD
    yoy_pct: Decimal | None  # fraction
    mom_pct: Decimal | None
    ytd: int | None
    ytd_yoy_pct: Decimal | None


@dataclass(frozen=True)
class QuarterFundamentals:
    period: str  # "2026Q2"
    eps: Decimal | None  # quarterly basic EPS
    bvps: Decimal | None  # book value per share at quarter end


@dataclass(frozen=True)
class ValuationInputs:
    symbol: str
    quarters: tuple[QuarterFundamentals, ...]
    is_demo: bool = False
    source: str = ""


@dataclass
class HistoryResult:
    symbol: str
    candles: list[Candle]
    is_demo: bool
    source: str


@runtime_checkable
class MarketDataProvider(Protocol):
    name: str
    is_demo: bool

    def instruments(self) -> list[InstrumentInfo] | None: ...

    def profile(self, symbol: str) -> InstrumentProfile | None: ...

    def quotes(self, symbols: list[str]) -> dict[str, QuoteData] | None: ...

    def history(self, symbol: str, start: date, end: date) -> list[Candle] | None: ...

    def valuation_inputs(self, symbol: str) -> ValuationInputs | None: ...

    def monthly_revenue(self, symbol: str) -> list[RevenueRow] | None: ...

    def dividends(self, symbol: str) -> list[DividendEvent] | None: ...

    def corporate_events(self, symbol: str) -> list[CorporateEvent] | None: ...

    def fx_history(self, pair: str, start: date, end: date) -> dict[date, Decimal] | None: ...


class BaseProvider:
    """Default "cannot answer" implementations; concrete providers override what they support."""

    name = "base"
    is_demo = False

    def instruments(self) -> list[InstrumentInfo] | None:
        return None

    def profile(self, symbol: str) -> InstrumentProfile | None:
        return None

    def quotes(self, symbols: list[str]) -> dict[str, QuoteData] | None:
        return None

    def history(self, symbol: str, start: date, end: date) -> list[Candle] | None:
        return None

    def valuation_inputs(self, symbol: str) -> ValuationInputs | None:
        return None

    def monthly_revenue(self, symbol: str) -> list[RevenueRow] | None:
        return None

    def dividends(self, symbol: str) -> list[DividendEvent] | None:
        return None

    def corporate_events(self, symbol: str) -> list[CorporateEvent] | None:
        return None

    def fx_history(self, pair: str, start: date, end: date) -> dict[date, Decimal] | None:
        return None


def parse_decimal(value: object) -> Decimal | None:
    """Parse upstream numeric strings: thousands separators, "--", "N/A", "-", "" -> None."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float | Decimal):
        return Decimal(str(value))
    s = str(value).strip().replace(",", "").replace(" ", "")
    if s in ("", "-", "--", "---", "----", "N/A", "NA", "null", "除息", "除權", "除權息"):
        return None
    if s.startswith("+"):
        s = s[1:]
    try:
        return Decimal(s)
    except ArithmeticError:
        return None


def parse_int(value: object) -> int | None:
    d = parse_decimal(value)
    return int(d) if d is not None else None


def parse_tw_date(value: object) -> date | None:
    """Accept ROC "1150929", "115/09/29", Gregorian "20260929", "2026-09-29", "2026/09/29"."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    s2 = s.replace("/", "").replace("-", "")
    if not s2.isdigit():
        return None
    try:
        if "/" in s and len(s.split("/")[0]) <= 3:  # ROC with slashes
            y, m, d = (int(p) for p in s.split("/"))
            return date(y + 1911, m, d)
        if len(s2) == 7:  # ROC yyyMMdd
            return date(int(s2[:3]) + 1911, int(s2[3:5]), int(s2[5:7]))
        if len(s2) == 8:
            return date(int(s2[:4]), int(s2[4:6]), int(s2[6:8]))
    except ValueError:
        return None
    return None


__all__ = [
    "BaseProvider",
    "Candle",
    "CorporateEvent",
    "DividendEvent",
    "HistoryResult",
    "InstrumentInfo",
    "InstrumentProfile",
    "MarketDataProvider",
    "ProviderUnavailable",
    "QuarterFundamentals",
    "QuoteData",
    "RevenueRow",
    "ValuationInputs",
    "code_of_symbol",
    "market_of_symbol",
    "parse_decimal",
    "parse_int",
    "parse_tw_date",
    "tw_symbol",
]
