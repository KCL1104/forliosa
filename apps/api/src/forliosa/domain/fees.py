"""Taiwan (and US) brokerage fees, securities transaction tax and NHI supplementary premium.

All money is ``Decimal``. Taiwan amounts are truncated to whole NT$ where the market does so
(brokerage commission, securities transaction tax); the NHI supplementary premium is rounded
half-up to whole NT$ (the NHI rule computes the premium "to the dollar, rounding below").

User-facing rule strings are Traditional Chinese because ``/transactions/preview`` returns them
verbatim to the UI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

ZERO = Decimal(0)
ONE = Decimal(1)

COMMISSION_RATE = Decimal("0.001425")  # 0.1425%
DEFAULT_MIN_FEE = Decimal(20)
BOARD_LOT = 1000  # 1 張 = 1,000 股

STOCK_TAX_RATE = Decimal("0.003")  # 0.3%
ETF_TAX_RATE = Decimal("0.001")  # 0.1%
DAY_TRADE_TAX_RATE = Decimal("0.0015")  # 0.15% (當沖減半)
DAY_TRADE_SUNSET = date(2027, 12, 31)  # last day the halved day-trade rate applies
BOND_ETF_TAX_EXEMPT_UNTIL = date(2026, 12, 31)  # 債券 ETF 停徵證交稅（code ends with "B"）

NHI_RATE = Decimal("0.0211")  # 二代健保補充保費 2.11%
NHI_THRESHOLD = Decimal(20000)  # single payment >= NT$20,000
NHI_CAP = Decimal(10_000_000)  # per-payment ceiling of the premium base

US_DIVIDEND_WITHHOLDING = Decimal("0.30")  # US withholding on dividends paid to Taiwan residents

TW_MARKETS = frozenset({"TWSE", "TPEX"})


def truncate(value: Decimal, places: int = 0) -> Decimal:
    """Truncate toward zero to ``places`` decimals (Taiwan brokers drop fractions of a dollar)."""
    q = Decimal(1).scaleb(-places)
    return value.quantize(q, rounding=ROUND_DOWN)


def round_half_up(value: Decimal, places: int = 0) -> Decimal:
    q = Decimal(1).scaleb(-places)
    return value.quantize(q, rounding=ROUND_HALF_UP)


def fmt_pct(rate: Decimal) -> str:
    """0.001425 -> '0.1425%'; 0.003 -> '0.3%'."""
    s = format((rate * 100).normalize(), "f")
    return f"{s}%"


def fmt_discount(discount: Decimal) -> str:
    """0.28 -> '2.8 折'; 0.6 -> '6 折'; 1 -> '無折扣'."""
    if discount >= ONE:
        return "無折扣"
    s = format((discount * 10).normalize(), "f")
    return f"{s} 折"


def fmt_money(value: Decimal, currency: str = "TWD") -> str:
    prefix = "NT$" if currency == "TWD" else "US$"
    v = value.normalize()
    s = f"{v:,f}" if v == v.to_integral_value() else f"{value:,.2f}"
    return f"{prefix}{s}"


def is_etf(code: str, instrument_type: str | None = None) -> bool:
    """ETF if the instrument master says so; otherwise the Taiwan heuristic "code starts with 00"."""
    if instrument_type is not None:
        return instrument_type == "etf"
    return code.startswith("00")


def is_bond_etf(code: str) -> bool:
    """Taiwan bond ETFs carry a trailing "B" (00679B, 00687B …)."""
    return code.startswith("00") and code.upper().endswith("B")


@dataclass(frozen=True)
class FeeSchedule:
    """A broker account's commission settings."""

    fee_rate: Decimal = COMMISSION_RATE
    fee_discount: Decimal = ONE
    min_fee: Decimal = DEFAULT_MIN_FEE
    min_fee_odd_lot: Decimal | None = None  # None = same as ``min_fee``


@dataclass(frozen=True)
class InstrumentRef:
    """The minimum an instrument needs for fee/tax rules."""

    code: str
    market: str  # "TWSE" | "TPEX" | "US"
    type: str | None = None  # "stock" | "etf" | None (unknown -> heuristic)

    @property
    def is_tw(self) -> bool:
        return self.market in TW_MARKETS


@dataclass
class FeeBreakdown:
    gross: Decimal
    fee: Decimal = ZERO
    tax: Decimal = ZERO
    health_insurance: Decimal = ZERO
    net_cash: Decimal = ZERO
    rules: list[str] = field(default_factory=list)


def commission(
    gross: Decimal, quantity: Decimal, schedule: FeeSchedule, instrument: InstrumentRef
) -> tuple[Decimal, list[str]]:
    """Brokerage commission and the rules applied.

    Taiwan: ``floor(gross × fee_rate × discount)``; if that is below the account minimum
    (``min_fee_odd_lot`` for orders under 1,000 shares) the minimum is charged.
    US: ``gross × fee_rate × discount`` rounded half-up to cents, then the minimum (default 0).
    """
    rules: list[str] = []
    if gross <= 0:
        return ZERO, rules
    raw = gross * schedule.fee_rate * schedule.fee_discount
    if instrument.is_tw:
        fee = truncate(raw)
        odd_lot = quantity < BOARD_LOT
        minimum = schedule.min_fee
        if odd_lot and schedule.min_fee_odd_lot is not None:
            minimum = schedule.min_fee_odd_lot
        rules.append(f"手續費 {fmt_pct(schedule.fee_rate)} × {fmt_discount(schedule.fee_discount)}，元以下捨去")
        if fee < minimum:
            fee = minimum
            label = "零股最低手續費" if odd_lot and schedule.min_fee_odd_lot is not None else "最低手續費"
            rules.append(f"低於{label}，以 {fmt_money(minimum)} 計")
        return fee, rules
    # US (複委託)
    if schedule.fee_rate <= 0:
        rules.append("美股手續費：帳戶未設定費率（以 0 計）")
        return max(ZERO, schedule.min_fee), rules
    fee = round_half_up(raw, 2)
    rules.append(f"美股手續費 {fmt_pct(schedule.fee_rate)} × {fmt_discount(schedule.fee_discount)}")
    if fee < schedule.min_fee:
        fee = schedule.min_fee
        rules.append(f"低於最低手續費，以 {fmt_money(schedule.min_fee, 'USD')} 計")
    return fee, rules


def transaction_tax(
    gross: Decimal, instrument: InstrumentRef, trade_date: date, is_day_trade: bool = False
) -> tuple[Decimal, list[str]]:
    """Securities transaction tax on a SELL (buyers pay none), truncated to whole NT$."""
    if not instrument.is_tw:
        return ZERO, ["美股無證交稅"]
    if gross <= 0:
        return ZERO, []
    if is_etf(instrument.code, instrument.type):
        if is_bond_etf(instrument.code) and trade_date <= BOND_ETF_TAX_EXEMPT_UNTIL:
            return ZERO, [f"證交稅：債券 ETF 停徵（至 {BOND_ETF_TAX_EXEMPT_UNTIL.isoformat()}）"]
        rate, rule = ETF_TAX_RATE, f"證交稅：ETF {fmt_pct(ETF_TAX_RATE)}"
        if is_day_trade:
            rule += "（ETF 當沖稅率相同）"
    elif is_day_trade and trade_date <= DAY_TRADE_SUNSET:
        rate = DAY_TRADE_TAX_RATE
        rule = f"證交稅：當沖減半 {fmt_pct(DAY_TRADE_TAX_RATE)}（優惠至 {DAY_TRADE_SUNSET.isoformat()}）"
    elif is_day_trade:
        rate = STOCK_TAX_RATE
        rule = f"證交稅：當沖優惠已於 {DAY_TRADE_SUNSET.isoformat()} 到期，以股票 {fmt_pct(STOCK_TAX_RATE)} 計"
    else:
        rate, rule = STOCK_TAX_RATE, f"證交稅：股票 {fmt_pct(STOCK_TAX_RATE)}"
    return truncate(gross * rate), [rule + "，元以下捨去"]


def nhi_premium(amount: Decimal, currency: str = "TWD", capital_surplus: Decimal = ZERO) -> tuple[Decimal, list[str]]:
    """二代健保補充保費 on a single cash-dividend payment.

    2.11% when the single payment is >= NT$20,000 (base capped at NT$10,000,000), rounded half-up
    to whole NT$. Only Taiwan-dollar dividends from Taiwan issuers are subject to it.

    ``capital_surplus`` is the part of the payment distributed from 資本公積: it is generally not dividend
    income, so it is left out of both the NT$20,000 threshold and the premium base.
    """
    if currency != "TWD":
        return ZERO, ["二代健保：海外股利不適用"]
    rules: list[str] = []
    excluded = min(max(capital_surplus, ZERO), amount)
    income = amount - excluded
    if excluded > 0:
        rules.append(f"二代健保：其中資本公積發放 {fmt_money(excluded)} 一般不屬股利所得，不計入")
    if income < NHI_THRESHOLD:
        label = "股利所得" if excluded > 0 else "單筆股利"
        return ZERO, [*rules, f"二代健保：{label}未達 {fmt_money(NHI_THRESHOLD)}，免扣"]
    base = min(income, NHI_CAP)
    label = "股利所得" if excluded > 0 else "單筆股利"
    return round_half_up(base * NHI_RATE), [
        *rules, f"二代健保：{label} ≥ {fmt_money(NHI_THRESHOLD)}，扣 {fmt_pct(NHI_RATE)}（元以下四捨五入）"
    ]


def gross_amount(quantity: Decimal, price: Decimal) -> Decimal:
    """成交價金 = 股數 × 成交價 (kept exact; serialized to 2 decimals)."""
    return quantity * price


def preview_buy(
    quantity: Decimal, price: Decimal, schedule: FeeSchedule, instrument: InstrumentRef,
    trade_date: date,
) -> FeeBreakdown:
    gross = gross_amount(quantity, price)
    fee, rules = commission(gross, quantity, schedule, instrument)
    rules.append("證交稅：買進免稅" if instrument.is_tw else "美股無證交稅")
    return FeeBreakdown(gross=gross, fee=fee, net_cash=-(gross + fee), rules=rules)


def preview_sell(
    quantity: Decimal, price: Decimal, schedule: FeeSchedule, instrument: InstrumentRef,
    trade_date: date, is_day_trade: bool = False,
) -> FeeBreakdown:
    gross = gross_amount(quantity, price)
    fee, rules = commission(gross, quantity, schedule, instrument)
    tax, tax_rules = transaction_tax(gross, instrument, trade_date, is_day_trade)
    rules.extend(tax_rules)
    return FeeBreakdown(gross=gross, fee=fee, tax=tax, net_cash=gross - fee - tax, rules=rules)


def preview_cash_dividend(
    amount: Decimal, currency: str, instrument: InstrumentRef | None, fee: Decimal = ZERO,
    capital_surplus: Decimal = ZERO,
) -> FeeBreakdown:
    """Cash dividend: NHI premium for TWD payments (``capital_surplus`` part excluded), 30% US withholding
    for US issuers."""
    rules: list[str] = []
    tax = ZERO
    nhi = ZERO
    if instrument is not None and instrument.market == "US":
        tax = round_half_up(amount * US_DIVIDEND_WITHHOLDING, 2)
        rules.append(f"美股股利預扣稅 {fmt_pct(US_DIVIDEND_WITHHOLDING)}")
        rules.append("二代健保：海外股利不適用")
    else:
        nhi, nhi_rules = nhi_premium(amount, currency, capital_surplus)
        rules.extend(nhi_rules)
        rules.append("股利所得稅：不計入績效（申報時另行試算）")
    if fee > 0:
        rules.append(f"匯費 {fmt_money(fee, currency)}")
    return FeeBreakdown(
        gross=amount, fee=fee, tax=tax, health_insurance=nhi, net_cash=amount - nhi - tax - fee, rules=rules
    )


def dividend_cash_amount(shares: Decimal, per_share: Decimal, currency: str) -> Decimal:
    """Cash dividend paid on ``shares``: whole NT$ (truncated) in Taiwan, cents for USD."""
    raw = shares * per_share
    return truncate(raw) if currency == "TWD" else truncate(raw, 2)


def stock_dividend_shares(shares: Decimal, stock_dividend_per_share: Decimal) -> tuple[Decimal, Decimal]:
    """配股: each NT$1 of stock dividend = 0.1 share (par NT$10).

    Returns ``(new_whole_shares, cash_in_lieu)``: fractional shares are paid in cash at par
    (NT$10 per share), truncated to whole NT$.
    """
    exact = shares * stock_dividend_per_share / Decimal(10)
    whole = truncate(exact)
    cash = truncate((exact - whole) * Decimal(10))
    return whole, cash
