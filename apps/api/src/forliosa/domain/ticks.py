"""Taiwan tick sizes (升降單位) and daily price limits (漲跌停).

TWSE / TPEx tick table (stocks, TDRs): < 10 → 0.01; 10–50 → 0.05; 50–100 → 0.1; 100–500 → 0.5;
500–1000 → 1; ≥ 1000 → 5. ETFs, ETNs and beneficiary certificates: < 50 → 0.01; ≥ 50 → 0.05.

Daily limit: ±10 % of the reference price (開盤競價基準). The limit-up price is rounded *down* and the
limit-down price *up* to the tick of the price band the limit falls in, so the limits never exceed
10 %. Checked against TWSE ``TWT84U`` (2026-11-12): 2330 ref 2395 → 2630 / 2160; 0050 ref 103.20 →
113.50 / 92.90; 2382 ref 298 → 327.5 / 268.5; 2881 ref 159.5 → 175 / 144; 00878 ref 33.50 → 36.85 /
30.15; and TPEx 6488 ref 635 → 698 / 572 (``tpex_mainboard_daily_close_quotes`` NextLimitUp/Down).

The ex-rights / ex-dividend reference price is (previous close − cash dividend) ÷ (1 + stock dividend
shares per share), rounded half-up to the tick. Official values (TWT84U, TPEx NextReferencePrice) win
whenever the archive has them; this formula is the fallback.
"""

from __future__ import annotations

from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal

LIMIT_PCT = Decimal("0.10")

_STOCK_BANDS = (
    (Decimal(10), Decimal("0.01")),
    (Decimal(50), Decimal("0.05")),
    (Decimal(100), Decimal("0.1")),
    (Decimal(500), Decimal("0.5")),
    (Decimal(1000), Decimal(1)),
)
_STOCK_TOP = Decimal(5)
_FUND_BANDS = ((Decimal(50), Decimal("0.01")),)
_FUND_TOP = Decimal("0.05")


def is_fund_code(code: str) -> bool:
    """ETFs / ETNs / beneficiary certificates: codes starting with "00" (0050, 00878, 00400A, 020000 …)."""
    return code.startswith("00") or code.startswith("02")


def tick_size(price: Decimal, is_fund: bool = False) -> Decimal:
    bands, top = (_FUND_BANDS, _FUND_TOP) if is_fund else (_STOCK_BANDS, _STOCK_TOP)
    for upper, tick in bands:
        if price < upper:
            return tick
    return top


def round_to_tick(value: Decimal, is_fund: bool = False, rounding: str = ROUND_HALF_UP) -> Decimal:
    tick = tick_size(value, is_fund)
    return (value / tick).quantize(Decimal(1), rounding=rounding) * tick


def price_limits(reference: Decimal, is_fund: bool = False, pct: Decimal = LIMIT_PCT) -> tuple[Decimal, Decimal]:
    """(limit_up, limit_down) for a reference price."""
    up = reference * (1 + pct)
    down = reference * (1 - pct)
    return (round_to_tick(up, is_fund, ROUND_FLOOR).normalize(),
            round_to_tick(down, is_fund, ROUND_CEILING).normalize())


def ex_rights_reference(prev_close: Decimal, cash: Decimal = Decimal(0), stock_per_share: Decimal = Decimal(0),
                        is_fund: bool = False) -> Decimal:
    """除權息參考價 = (昨收 − 現金股利) ÷ (1 + 無償配股率), rounded half-up to the tick."""
    raw = (prev_close - cash) / (1 + stock_per_share)
    return round_to_tick(raw, is_fund, ROUND_HALF_UP).normalize()
