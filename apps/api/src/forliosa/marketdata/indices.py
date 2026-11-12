"""Benchmark indices: not tradable instruments (no quote, not in the instrument master, not searchable).

The symbols start with ``^`` (the usual convention for indices) so they can never collide with a
Taiwan code (``2330``), a Taiwan symbol (``2330.TW``) or a US ticker (``AAPL``).

* ``^TAIEXTR`` — 臺灣證券交易所「發行量加權股價報酬指數」(TAIEX Total Return Index): the TAIEX
  with cash dividends reinvested, so it is directly comparable with a portfolio's time-weighted
  return (which counts dividends). Daily closes come from our archive of the official open data: TWSE
  OpenAPI ``exchangeReport/MI_INDEX`` (every index, the latest day) and ``indicesReport/MFI94U`` (the
  current month, used to backfill on the first run) — table ``index_daily``, name ``archive_name``. Under a
  personal opt-in FinMind ``TaiwanStockTotalReturnIndex`` (data_id ``TAIEX``) fills older days.
* ``^TPEXTR`` — 證券櫃檯買賣中心「櫃買報酬指數」(TPEx Total Return Index), for portfolios of OTC stocks:
  TPEx OpenAPI ``tpex_reward_index`` (current month, archived daily); FinMind data_id ``TPEx``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BenchmarkIndex:
    symbol: str
    name: str
    data_id: str  # FinMind TaiwanStockTotalReturnIndex data_id
    archive_name: str  # index_daily.name (the index name the exchange publishes)
    source_key: str  # datapolicy dataset key for attribution


INDICES: dict[str, BenchmarkIndex] = {
    "^TAIEXTR": BenchmarkIndex("^TAIEXTR", "發行量加權股價報酬指數", "TAIEX", "發行量加權股價報酬指數",
                               "twse-openapi/index"),
    "^TPEXTR": BenchmarkIndex("^TPEXTR", "櫃買報酬指數", "TPEx", "櫃買報酬指數", "tpex-openapi/total_return"),
}


def resolve_index(text: str) -> str | None:
    """'^taiextr' / 'TAIEXTR' -> '^TAIEXTR'; anything else -> None."""
    s = text.strip().upper()
    if not s.startswith("^"):
        s = "^" + s
    return s if s in INDICES else None


def is_index(symbol: str) -> bool:
    return symbol in INDICES


def index_by_data_id(data_id: str) -> BenchmarkIndex | None:
    return next((i for i in INDICES.values() if i.data_id == data_id), None)
