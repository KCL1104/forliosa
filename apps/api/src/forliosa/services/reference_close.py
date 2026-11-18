"""Reference closes for days our own archive does not have, from the history backfill (Yahoo Finance).

產品負責人 2026-11-17（選 A）: a friend bought stocks long ago, but the official archive begins 2026-11-12, so the buy
form's 「那天收盤」 hint and the statement import's price check only knew the last few days. The history backfill's
rows (``yahoo-history``, PRICE_HISTORY_SOURCE=yahoo) may now ALSO be read as a *reference* close in exactly two places:

* ``services.instruments.close_on`` (``GET /instruments/{symbol}/close``): ``reference: true`` with a note that the
  close is not official; still one tap to fill, and the user edits it;
* ``services.imports._price_check``: the ``price_far_from_close`` flag says it compared with a reference close.

Never anything that values a ledger or is stored as an official close (market value, P&L, performance, dividends,
recurring drafts, group rankings): those keep to ``source_clause(..., backfill=False)``. The official archive always
wins when it has the day. Switched off or dropped (``history_backfill drop``), there is nothing to read and both
places behave as before.

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

from datetime import date
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from forliosa.datapolicy import HISTORY_SOURCE, history_backfill_enabled, source_clause
from forliosa.marketdata.catalog import KNOWN_REDUCTIONS
from forliosa.marketdata.service import MarketData
from forliosa.models import PriceDaily

# Shown next to a reference close (the stock chart says the same of these days: 「…來自 Yahoo Finance，不是官方資料」)
REFERENCE_NOTE = "來自 Yahoo Finance，不是官方資料"


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
    cash = KNOWN_REDUCTIONS.get((symbol, when), Decimal(0))
    traded = (PriceDaily.close > 0, or_(PriceDaily.volume.is_(None), PriceDaily.volume != 0))
    before = db.scalar(select(PriceDaily.close).where(
        PriceDaily.symbol == symbol, PriceDaily.source == HISTORY_SOURCE, PriceDaily.date < when, *traded)
        .order_by(PriceDaily.date.desc()).limit(1))
    after = db.scalar(select(PriceDaily.close).where(
        PriceDaily.symbol == symbol, PriceDaily.date >= when, *traded,
        or_(PriceDaily.source == HISTORY_SOURCE, source_clause(PriceDaily.source, md.policy)))
        .order_by(PriceDaily.date).limit(1))
    if not before or not after:
        return True
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
