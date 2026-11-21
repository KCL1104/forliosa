"""Reference closes for days our own archive does not have, from the history backfill (Yahoo Finance).

產品負責人 2026-11-17（選 A）: a friend bought stocks long ago, but the official archive begins 2026-11-12, so the buy
form's 「那天收盤」 hint and the statement import's price check only knew the last few days. The history backfill's
rows (``yahoo-history``, PRICE_HISTORY_SOURCE=yahoo) may now ALSO be read as a *reference* close in exactly two places:

* ``services.instruments.close_on`` (``GET /instruments/{symbol}/close``): ``reference: true`` with a note that the
  close is not official; still one tap to fill, and the user edits it;
* ``services.imports._price_check``: the ``price_far_from_close`` flag says it compared with a reference close.

Never anything stored as an official close or that values holdings now (market value, P&L, dividends, recurring
drafts): those keep to ``source_clause(..., backfill=False)``. The official archive always wins when it has the day.
Switched off or dropped (``history_backfill drop``), there is nothing to read and every place behaves as before.

產品負責人 2026-11-18（選 A）: the group board's 本月 and 今年 both read 「11/12 收盤 → 11/17 收盤」 because
nothing valued a ledger before the archive's first day. A third use, :func:`valuation_prices`: performance and
time-weighted returns over time (the ledger's 績效 and the hero trend, benchmarks, group boards, digests and daily
reports) may value the days **before the archive's first day** with these closes as traded — one series per
symbol, the archive's rows when present, otherwise the backfill's; from the archive's first day on, exactly the
official closes as before. Every response that used them says so (:func:`reference_note`, ``reference_until``).
Holdings' current value stays official.

Yahoo's prices are split-adjusted (0050 before its 2025 split reads a quarter of what it traded at), and a reference
for a trade has to be the price as traded. The backfill stored only days before the symbol's first official close and
only when Yahoo agreed with that close, so the splits folded into the stored rows are the ones after the day and no
later than the first official close; those we know of (``MarketData.corporate_events``: the catalogue's known splits,
the archive's US splits) are multiplied back — each only where the stored rows show Yahoo really folded it in
(:func:`_folded_in`: a split Yahoo has not applied yet, or a capital reduction it treats otherwise, leaves the rows as
traded, and multiplying those would be off by the ratio). A split we do not know of cannot be undone — one more reason
it is only a reference the user confirms. The import check compares a Taiwan trade with the previous day's close, so
a split between the two is divided back out (:func:`split_factor`) before comparing.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from forliosa.datapolicy import HISTORY_SOURCE, history_backfill_enabled, source_clause
from forliosa.marketdata.base import Candle, HistoryResult
from forliosa.marketdata.catalog import KNOWN_REDUCTIONS
from forliosa.marketdata.service import MarketData
from forliosa.models import PriceDaily

# Shown next to a reference close (the stock chart says the same of these days: 「…來自 Yahoo Finance，不是官方資料」)
REFERENCE_NOTE = "來自 Yahoo Finance，不是官方資料"
IN_CHUNK = 500  # symbols per ``IN (…)`` list, as the archive's batched reads (``archive_provider.IN_CHUNK``)


def reference_closes(db: Session, md: MarketData, symbol: str, start: date, end: date) -> dict[date, Decimal]:
    """day -> the history backfill's close of ``symbol`` as traded, for ``start``..``end``. Empty when the backfill
    is switched off, dropped or has no row there. Callers read it only for days the official archive lacks."""
    if not history_backfill_enabled():
        return {}
    rows = [(d, Decimal(c)) for d, c in db.execute(select(PriceDaily.date, PriceDaily.close).where(
        PriceDaily.symbol == symbol, PriceDaily.source == HISTORY_SOURCE, PriceDaily.date >= start,
        PriceDaily.date <= end)).all() if c is not None and c > 0]
    if not rows:
        return {}
    first_official = db.scalar(select(func.min(PriceDaily.date)).where(
        PriceDaily.symbol == symbol, source_clause(PriceDaily.source, md.policy)))
    oldest = min(d for d, _ in rows)
    splits = [(when, ratio) for when, ratio in _known_splits(md, symbol)
              if oldest < when and (first_official is None or when <= first_official)
              and _folded_in(db, md, symbol, when, ratio)]
    out: dict[date, Decimal] = {}
    for d, c in rows:
        factor = Decimal(1)
        for when, ratio in splits:
            if d < when:
                factor *= ratio
        out[d] = c * factor
    return out


def split_factor(md: MarketData, symbol: str, after: date, through: date) -> Decimal:
    """The known splits after ``after`` up to and including ``through``, their ratios multiplied: a close as traded
    on ``after`` divided by it is on the basis of the shares as they traded on ``through`` (0050's close of 2025-06-10,
    188, is 47 next to its first day after the 1-to-4 split, 2025-06-18). 1 when there is none."""
    factor = Decimal(1)
    for when, ratio in _known_splits(md, symbol):
        if after < when <= through:
            factor *= ratio
    return factor


def _folded_in(db: Session, md: MarketData, symbol: str, when: date, ratio: Decimal) -> bool:
    """Do the stored backfill rows of ``symbol`` fold in the split of ``when``? Yahoo scales the days before a split by
    its ratio, but a split it has not applied yet when the backfill ran (00662 resumed on 2026-11-17 at a fifth of its
    price) or a capital reduction it does not treat as a split of that ratio (2363 矽統 2024: 650 new shares per
    1,000 and NT$3.5 back) would leave them as traded. The backfill's last *traded* close before the day (a halt's
    rows, volume 0, may sit on either basis: a vendor that dates the split by the halt's first day repeats the old
    price there) and the first traded close from the day on (the backfill's or the archive's; both on the new basis)
    tell. With ``b`` the earlier and ``c`` the cash a reduction returns per old share (``KNOWN_REDUCTIONS``, else 0),
    the new shares start at (P − c) / ratio, so the later close over ``b`` is about 1 − c / (ratio·b) if the rows are
    scaled (P = ratio·b) and (b − c) / (ratio·b) if they are as traded (P = b); whichever the level is nearer to (in
    log terms) decides. A split is 1 against 1/ratio: a ×4 needs a 100 % move overnight to fool it. Without the cash a
    reduction near par (2323 中環 2026 at about NT$10.8, NT$1 back) would look level either way; with it the two
    expectations stay about 1/ratio apart, so a 0.9 is fooled only by a move of some 6 % and is then off by 10 %.
    Nothing to compare: folded in, as Yahoo does."""
    traded = (PriceDaily.close > 0, or_(PriceDaily.volume.is_(None), PriceDaily.volume != 0))
    before = db.scalar(select(PriceDaily.close).where(
        PriceDaily.symbol == symbol, PriceDaily.source == HISTORY_SOURCE, PriceDaily.date < when, *traded)
        .order_by(PriceDaily.date.desc()).limit(1))
    after = db.scalar(select(PriceDaily.close).where(
        PriceDaily.symbol == symbol, PriceDaily.date >= when, *traded,
        or_(PriceDaily.source == HISTORY_SOURCE, source_clause(PriceDaily.source, md.policy)))
        .order_by(PriceDaily.date).limit(1))
    return _fold_decision(symbol, when, ratio, before, after)


def _fold_decision(symbol: str, when: date, ratio: Decimal, before: Any, after: Any) -> bool:
    """:func:`_folded_in`'s answer from the last traded backfill close before the day (``before``) and the first traded
    close from the day on (``after``)."""
    if not before or not after:
        return True
    cash = KNOWN_REDUCTIONS.get((symbol, when), Decimal(0))
    b = Decimal(before)
    scaled = 1 - cash / (ratio * b)
    as_traded = (b - cash) / (ratio * b)
    if scaled <= 0:  # the cash is more than a scaled row's price could pay back: the rows are as traded
        return False
    level = Decimal(after) / b
    return as_traded <= 0 or abs((level / scaled).ln()) <= abs((level / as_traded).ln())


def _known_splits(md: MarketData, symbol: str) -> list[tuple[date, Decimal]]:
    """(first day at the new price, ratio) of each split we know of (``MarketData.corporate_events``)."""
    return [(e.date, e.ratio) for e in md.corporate_events(symbol) if e.kind == "split" and e.ratio and e.ratio > 0]


# -- valuing a ledger over time before the archive (產品負責人 2026-11-18) -------------------------------------------
def reference_note(until: date) -> str:
    """The one line a page computed with reference closes shows (the ledger's 績效, group boards, digests): the last
    day valued with them, inclusive, like the charts' 「… 以前的日線來自 Yahoo Finance」."""
    return f"{until.strftime('%Y/%m/%d')} 以前用 Yahoo 參考價計算，不是官方資料"


PRICE_ONLY_TAIL = "以前只算價格，不含股利"


def price_only_note(name: str, until: date) -> str:
    """A stock benchmark (0050) valued with reference closes: before the archive we have no ex-dividend dates (the
    archive keeps only the notices from its first day on, and the backfill stores closes only), so those days are a
    price return, not the total return the benchmark is otherwise (2026-11-18 review). Said next to the comparison
    rather than guessed; the AI card then leaves out 「基準含股利」."""
    return f"{name}在 {until.strftime('%Y/%m/%d')} {PRICE_ONLY_TAIL}"


@dataclass
class ValuationPrices:
    """Daily closes for valuing a ledger over time: the histories as read (``official``: the archive's rows, exactly as
    before), and for symbols the archive did not cover yet, the history backfill's closes as traded (``reference``)
    for the days before ``cutoff[symbol]`` — the archive's first day (or the symbol's first close, if earlier). A day
    is priced from one of the two, never both; from the cutoff on only the official closes count, so nothing after the
    archive began changes."""

    official: dict[str, HistoryResult]
    reference: dict[str, list[Candle]] = field(default_factory=dict)
    cutoff: dict[str, date] = field(default_factory=dict)

    def is_reference(self, symbol: str, day: date) -> bool:
        cut = self.cutoff.get(symbol)
        return cut is not None and day < cut

    def days(self, symbols: Iterable[str], lo: date, hi: date) -> set[date]:
        """The days in ``lo``..``hi`` that have a reference close of one of ``symbols``."""
        return {c.t for s in symbols for c in self.reference.get(s, ()) if lo <= c.t <= hi}

    def filled(self, axis: list[date], symbol: str, candles: list[Candle]) -> dict[date, Decimal]:
        """``symbol``'s close on each day of ``axis`` (the last close on or before it): from ``candles`` (the official
        series, as before) and, on days before the cutoff, from the reference closes."""
        out = forward_filled(axis, {c.t: c.c for c in candles})
        ref = self.reference.get(symbol)
        if not ref:
            return out
        cut = self.cutoff[symbol]
        early = forward_filled([d for d in axis if d < cut], {c.t: c.c for c in ref})
        return {d: early[d] if d in early else out[d] for d in axis if d in early or d in out}

    def covers(self, symbols: Iterable[str]) -> bool:
        """Every one of ``symbols`` was read here (a board's members share one read: ``sharing.Projector.prime``)."""
        return all(s in self.official for s in symbols)


def forward_filled(axis: list[date], closes: dict[date, Decimal]) -> dict[date, Decimal]:
    """day of ``axis`` -> the last close on or before it (days before the first close are left out)."""
    out: dict[date, Decimal] = {}
    known = sorted(closes)
    j = 0
    last: Decimal | None = None
    for d in axis:
        while j < len(known) and known[j] <= d:
            last = closes[known[j]]
            j += 1
        if last is not None:
            out[d] = last
    return out


def valuation_prices(db: Session, md: MarketData, histories: dict[str, HistoryResult], start: date,
                     need_from: date) -> ValuationPrices:
    """The histories (read from ``start``) and, where they begin after ``need_from`` because the archive began
    later, the history backfill's closes as traded for the days before the archive's first day.

    Nothing is read — the answer is ``histories`` alone — when the backfill is switched off or dropped, or the period
    from ``need_from`` is within the archive. Otherwise one query per :data:`IN_CHUNK` symbols reads the backfill's rows
    of every symbol that needs them (the speed work's rule: no query per holding). Known splits and capital reductions
    are multiplied back where the rows fold them in (:func:`_folded_in`, checked on the rows already read; the database
    is asked only when they cannot tell), as for the buy form's reference close."""
    out = ValuationPrices(histories)
    if not history_backfill_enabled():
        return out
    since = md.archive_since()
    if since is None or need_from >= since:
        return out
    wanted: dict[str, date] = {}
    for s, h in histories.items():
        first = h.candles[0].t if h.candles else None
        if h.is_demo or (first is not None and first <= need_from):
            continue  # demo data (personal mode), or the series already covers the period
        # up to the symbol's own first official close: TPEx's archive began a day after TWSE's (11/13 vs 11/12), and
        # cutting every symbol at the archive's first day left 11/12 unpriced for OTC stocks — performance then
        # started after that gap and dropped the whole history before it (2026-11-21)
        wanted[s] = first if first is not None else since
    if not wanted:
        return out
    rows: dict[str, list[Any]] = {s: [] for s in wanted}
    syms = sorted(wanted)
    for i in range(0, len(syms), IN_CHUNK):
        stmt = (select(PriceDaily.symbol, PriceDaily.date, PriceDaily.open, PriceDaily.high, PriceDaily.low,
                       PriceDaily.close, PriceDaily.volume)
                .where(PriceDaily.source == HISTORY_SOURCE, PriceDaily.symbol.in_(syms[i:i + IN_CHUNK]),
                       PriceDaily.date >= start)
                .order_by(PriceDaily.symbol, PriceDaily.date))
        for r in db.execute(stmt):
            rows[r.symbol].append(r)
    have = [s for s in syms if any(r.date < wanted[s] and r.close and r.close > 0 for r in rows[s])]
    if not have:
        return out
    events = md.corporate_events_many(have)
    for s in have:
        splits = [(e.date, e.ratio) for e in events.get(s, []) if e.kind == "split" and e.ratio and e.ratio > 0]
        candles = _as_traded(db, md, s, rows[s], histories[s].candles, wanted[s], splits)
        if candles:
            out.reference[s] = candles
            out.cutoff[s] = wanted[s]
    return out


def _as_traded(db: Session, md: MarketData, symbol: str, rows: list[Any], official: list[Candle], cutoff: date,
               splits: list[tuple[date, Decimal]]) -> list[Candle]:
    """The backfill's rows before ``cutoff`` as candles at the prices as traded: :func:`reference_closes`' factors.
    ``rows``: every backfill row of ``symbol`` from the start read (all of them before its first official close);
    ``official``: its official candles from the same start."""
    usable = [r for r in rows if r.close is not None and r.close > 0]
    priced = [r for r in usable if r.date < cutoff]
    if not priced:
        return []
    first_official = official[0].t if official else None
    oldest = priced[0].date
    active = [(when, ratio) for when, ratio in splits
              if oldest < when and (first_official is None or when <= first_official)
              and _folded_in_rows(db, md, symbol, when, ratio, usable, official)]
    out = []
    for r in priced:
        factor = Decimal(1)
        for when, ratio in active:
            if r.date < when:
                factor *= ratio
        c = Decimal(r.close) * factor
        out.append(Candle(r.date, Decimal(r.open) * factor if r.open else c, Decimal(r.high) * factor if r.high else c,
                          Decimal(r.low) * factor if r.low else c, c, r.volume or 0))
    return out


def _folded_in_rows(db: Session, md: MarketData, symbol: str, when: date, ratio: Decimal, rows: list[Any],
                    official: list[Candle]) -> bool:
    """:func:`_folded_in` from rows already read: the last traded backfill close before ``when`` and the first traded
    close from ``when`` on (the backfill's rows come before every official close). When the rows read cannot tell —
    nothing traded before the day since the start, or the first official close has no volume (a halt, or not
    recorded) — the database is asked, as :func:`_folded_in` does."""
    traded = [r for r in rows if r.volume is None or r.volume != 0]
    before = next((r.close for r in reversed(traded) if r.date < when), None)
    after = next((r.close for r in traded if r.date >= when), None)
    if after is None:
        first = next((c for c in official if c.t >= when and c.c > 0), None)
        if first is not None and first.v:
            after = first.c
        else:
            return _folded_in(db, md, symbol, when, ratio)
    if before is None:
        return _folded_in(db, md, symbol, when, ratio)
    return _fold_decision(symbol, when, ratio, before, after)
