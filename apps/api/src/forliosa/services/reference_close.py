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
the archive's US splits) are multiplied back. A split we do not know of cannot be undone — one more reason it is only
a reference the user confirms. The import check compares a Taiwan trade with the previous day's close, so a split
between the two is divided back out (:func:`split_factor`) before comparing.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from forliosa.datapolicy import HISTORY_SOURCE, history_backfill_enabled, source_clause
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
    splits = [(when, ratio) for when, ratio in _known_splits(md, symbol)
              if first_official is None or when <= first_official]
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


def _known_splits(md: MarketData, symbol: str) -> list[tuple[date, Decimal]]:
    """(first day at the new price, ratio) of each split we know of (``MarketData.corporate_events``)."""
    return [(e.date, e.ratio) for e in md.corporate_events(symbol) if e.kind == "split" and e.ratio and e.ratio > 0]
