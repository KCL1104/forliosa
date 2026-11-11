"""Benchmark indices: not tradable instruments (no quote, not in the instrument master, not searchable).

The symbols start with ``^`` (the usual convention for indices) so they can never collide with a
Taiwan code (``2330``), a Taiwan symbol (``2330.TW``) or a US ticker (``AAPL``).

* ``^TAIEXTR`` — 臺灣證券交易所「發行量加權股價報酬指數」(TAIEX Total Return Index): the TAIEX
  with cash dividends reinvested, so it is directly comparable with a portfolio's time-weighted
  return (which counts dividends). Daily levels come from FinMind ``TaiwanStockTotalReturnIndex``
  (data_id ``TAIEX``); the index is published by TWSE after the close.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BenchmarkIndex:
    symbol: str
    name: str
    data_id: str  # FinMind TaiwanStockTotalReturnIndex data_id


INDICES: dict[str, BenchmarkIndex] = {
    "^TAIEXTR": BenchmarkIndex("^TAIEXTR", "發行量加權股價報酬指數", "TAIEX"),
}


def resolve_index(text: str) -> str | None:
    """'^taiextr' / 'TAIEXTR' -> '^TAIEXTR'; anything else -> None."""
    s = text.strip().upper()
    if not s.startswith("^"):
        s = "^" + s
    return s if s in INDICES else None


def is_index(symbol: str) -> bool:
    return symbol in INDICES
