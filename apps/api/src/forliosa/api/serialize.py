"""Decimal -> JSON number conversion with the contract's rounding rules."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal


def _q(value: Decimal | float | int | None, places: int) -> float | None:
    if value is None:
        return None
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    q = d.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    f = float(q)
    return 0.0 if f == 0 else f


def money(value: Decimal | float | int | None) -> float | None:
    """Amounts: 2 decimals."""
    return _q(value, 2)


def price(value: Decimal | float | int | None) -> float | None:
    """Prices: up to 4 decimals."""
    return _q(value, 4)


def ratio(value: Decimal | float | int | None) -> float | None:
    """Ratios as fractions (0.0124 = 1.24%), 6 decimals."""
    return _q(value, 6)


def qty(value: Decimal | float | int | None) -> float | int | None:
    """Share quantities: integers stay integers."""
    if value is None:
        return None
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    if d == d.to_integral_value():
        return int(d)
    return float(d.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP))


def safe_div(a: Decimal, b: Decimal) -> Decimal | None:
    return a / b if b else None
