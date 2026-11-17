"""匯入對帳單 v1 (``POST /imports/statement``; 產品負責人 2026-11-16): read a statement, check every row, store nothing.

Flow: the model transcribes the pages (``ai.importer``); each row becomes a candidate transaction (``TransactionIn``
without ``source``) with flags from the server's own checks; the user corrects the rows in the review table and the
batch is written by ``POST /transactions/batch`` (``services.transactions.create_batch``). Nothing of the upload is
kept: not the pages, the text layer or the rows — only ``ai_usage`` rows (counts and cost, ``feature="import"``).

Checks (``flags[].code``; ``include`` is the default tick in the review table):

* reading: ``unreadable`` (a field the model could not read, or a buy/sell without date, shares or price),
  ``unknown_symbol`` / ``ambiguous_symbol`` (name or code → instrument, a code whose name does not match),
  ``currency_mismatch`` (a US stock priced in NT$, or a US fee above US$50 and 1%: NT$ on a 複委託 statement),
  ``fractional_tw_qty``; ``day_trade`` (listed, not ticked),
  ``margin`` (imported as an ordinary trade and tagged); dividends (``dividend_auto``: Taiwan dividends are booked
  automatically) and short sales (``short_sale``) are never imported.
* arithmetic (Taiwan): ``amount_mismatch`` (shares × price against the printed 價金; also 張/股 mix-ups),
  ``fee_out_of_range`` (above 0.1425% of 價金 or the NT$20 minimum), ``tax_out_of_range`` (a sell's tax not 0.3%,
  0.15% for a day trade, 0.1% or 0 for an ETF), ``side_inconsistent`` (a buy with tax, or the sign of 應收付 against the
  side).
* dates and price: ``not_trading_day``, ``outside_period``; ``price_far_from_close`` against our own archived
  official close (``prices_daily`` under the data policy): Taiwan ±10.5% of the previous close (the daily limit is
  10%), US ±20% of that day's close. A trade from before the archive began is compared with the history backfill's
  close as a reference (product owner 2026-11-17, ``services.reference_close``), and the message says so
  (「那天參考收盤 1,030（非官方資料），這裡是 103。」); the archive wins whenever it has a close in the lookback. A
  known split between the previous day and the trade puts the previous close on the trade day's basis first.
* the books, for the rows ticked by default (``services.transactions.check_batch``): ``oversell``,
  ``ledger_inconsistent``, ``duplicate``, ``possible_duplicate``.
* the whole statement: ``totals_check`` (the rows added up against the statement's own 合計 row) and
  ``embedded_instructions`` (text in the file that tried to instruct the model: quoted, not followed).

When reading checks fail on some pages, the totals do not match, something was unreadable or the model refused, those
pages are read once more with ``AI_MODEL_IMPORT_RETRY`` (not in 省錢模式), and the better reading is kept.
"""

from __future__ import annotations

import logging
import re
import time
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_FLOOR, Decimal, InvalidOperation
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from forliosa import plans
from forliosa.ai import importer, store
from forliosa.ai.importer import ChunkResult, Extraction, Page
from forliosa.ai.keypool import KeyPool, get_key_pool
from forliosa.ai.pricing import CallUsage
from forliosa.api import serialize as ser
from forliosa.api.errors import ApiError, not_found
from forliosa.config import Settings
from forliosa.datapolicy import source_clause
from forliosa.ids import new_id
from forliosa.market_calendar import load_official_calendar
from forliosa.marketdata.base import InstrumentInfo
from forliosa.marketdata.service import MarketData
from forliosa.models import AiUsage, BrokerAccount, PriceDaily, User
from forliosa.services import transactions as txn_svc
from forliosa.services.reference_close import reference_closes, split_factor
from forliosa.timeutil import is_tw_trading_day, today_taipei

log = logging.getLogger(__name__)

FEATURE = "import"
# Not ticked by default (the rest are only pointed out); any ``error`` flag also unticks the row.
EXCLUDED = frozenset({"unknown_symbol", "ambiguous_symbol", "oversell", "duplicate", "possible_duplicate",
                      "dividend_auto", "short_sale", "day_trade", "currency_mismatch", "fractional_tw_qty",
                      "unreadable", "ledger_inconsistent"})
# Reading problems worth a second reading with the retry model (not the books', not an unknown instrument).
RETRY_CODES = frozenset({"unreadable", "amount_mismatch", "fee_out_of_range", "tax_out_of_range", "side_inconsistent",
                         "not_trading_day", "outside_period", "price_far_from_close", "fractional_tw_qty"})
TW_PRICE_BAND = Decimal("0.105")
US_PRICE_BAND = Decimal("0.20")
FEE_RATE = Decimal("0.001425")
FEE_MIN = Decimal(20)
US_FEE_FLOOR, US_FEE_RATE = Decimal(50), Decimal("0.01")  # a US fee above both is probably NT$ (複委託)
STOCK_TAX, DAY_TRADE_TAX, ETF_TAX = Decimal("0.003"), Decimal("0.0015"), Decimal("0.001")
LOT = Decimal(1000)
CENT = Decimal("0.01")
CLOSE_LOOKBACK_DAYS = 15
MISSED_ROW = 2  # comparing two readings: a row one of them missed
WEEKDAYS = "一二三四五六日"
FIELD_LABELS = {"trade_date": "日期", "symbol_code": "代號", "name": "名稱", "side": "買賣", "kind": "種類",
                "quantity": "股數", "quantity_unit": "單位", "price": "價格", "amount": "價金", "fee": "手續費",
                "tax": "交易稅", "currency": "幣別"}
NOTICE = {"holdings_snapshot": "這是庫存畫面，沒有買進日期，還不能匯入。請改用對帳單或成交明細。",
          "not_a_trade_record": "這個檔案裡沒有買賣紀錄。"}


# -- who may import, and how many today -----------------------------------------------------------------------------
def require_access(user: User, settings: Settings) -> None:
    if not plans.statement_import_open(user, settings):
        raise ApiError(403, "import_not_enabled", "這個帳號還不能匯入對帳單。")


def imports_today(db: Session, user: User) -> int:
    """Statements read today (Taipei): one ``ai_usage.thread_id`` per read, counted when its first call starts."""
    return db.scalar(select(func.count(func.distinct(AiUsage.thread_id))).where(
        AiUsage.user_id == user.id, AiUsage.feature == FEATURE, AiUsage.created_at >= store.day_start())) or 0


def usage_fields(db: Session, user: User, settings: Settings) -> dict[str, Any]:
    """``GET /ai/usage``: ``imports_today`` and ``import_daily_limit`` (None: no limit)."""
    return {"imports_today": imports_today(db, user), "import_daily_limit": settings.import_daily_limit or None}


# -- parsing what the model transcribed -----------------------------------------------------------------------------
def _nfkc(text: Any) -> str:
    return unicodedata.normalize("NFKC", str(text if text is not None else "")).strip()


def dec(text: Any) -> Decimal | None:
    s = re.sub(r"[,\s]", "", _nfkc(text))
    if not s:
        return None
    try:
        d = Decimal(s)
    except InvalidOperation:
        return None
    return d if d.is_finite() else None


_DATE_SPLIT = re.compile(r"[./\-年月]")
EARLIEST_YEAR = 1990  # as the batch write checks it (``bad_date``)


def _plausible(d: date | None, today: date) -> date | None:
    """A date a statement can hold: 1990 up to next year (anything else is a misreading, and would break the price
    lookup's arithmetic near ``date.min``)."""
    return d if d is not None and EARLIEST_YEAR <= d.year <= today.year + 1 else None


def _try_date(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def parse_date(text: Any, year_hint: int | None, today: date) -> date | None:
    """A date as printed: 2026/10/03, 115/10/03 (民國), 2026-10-03, 20261003, 10/03/2026 or 10/03/26 (US), 26/10/03,
    or 10/03 (the year of the statement's period, else this year — last year when that would be in the future).
    None for what cannot be read, a two-digit year that reads both ways, or a year outside 1990 … next year."""
    s = re.sub(r"\s+", "", _nfkc(text)).removesuffix("日")
    if not s:
        return None
    if re.fullmatch(r"\d{8}", s):
        return _plausible(_try_date(int(s[:4]), int(s[4:6]), int(s[6:])), today)
    parts = [p for p in _DATE_SPLIT.split(s) if p]
    if not parts or not all(p.isdigit() for p in parts):
        return None
    n = [int(p) for p in parts]
    if len(parts) == 3:
        if len(parts[0]) == 4:
            return _plausible(_try_date(n[0], n[1], n[2]), today)
        if len(parts[2]) == 4:
            return _plausible(_try_date(n[2], n[0], n[1]), today)
        if len(parts[0]) == 3 or (len(parts[0]) == 2 and n[0] >= 79):  # 民國 79 = 1990
            return _plausible(_try_date(n[0] + 1911, n[1], n[2]), today)
        if len(parts[0]) <= 2 and len(parts[2]) <= 2:
            # YY/MM/DD or the US MM/DD/YY: the statement's year decides; without one, only a reading that makes sense
            ymd = _plausible(_try_date(2000 + n[0], n[1], n[2]), today)
            mdy = _plausible(_try_date(2000 + n[2], n[0], n[1]), today)
            if year_hint is not None:
                ymd = ymd if ymd and ymd.year == year_hint else None
                mdy = mdy if mdy and mdy.year == year_hint else None
            else:
                ymd = ymd if ymd and ymd <= today else None
                mdy = mdy if mdy and mdy <= today else None
            return (ymd or mdy) if not (ymd and mdy) or ymd == mdy else None
        return None
    if len(parts) == 2:
        d = _try_date(year_hint or today.year, n[0], n[1])
        if d is not None and year_hint is None and d > today:
            d = _try_date(d.year - 1, d.month, d.day)
        return _plausible(d, today)
    return None


def _num(d: Decimal) -> str:
    """1,000 / 0.5 / 1,030.25."""
    return f"{d.normalize():,f}"


def _md(d: date, today: date) -> str:
    return f"{d.month}/{d.day}" if d.year == today.year else f"{d.year}/{d.month}/{d.day}"


def _flag(code: str, message: str, severity: str = "warning") -> dict[str, str]:
    return {"code": code, "message": message, "severity": severity}


def _key(text: str) -> str:
    return re.sub(r"[\s・·.,()（）]", "", _nfkc(text)).upper()


# -- instruments ----------------------------------------------------------------------------------------------------
def _name_matches(md: MarketData, info: InstrumentInfo, name: str) -> bool:
    n = _key(name)
    names = [_key(info.name), *(_key(a) for a in info.aliases)]
    if any(n and x and (n == x or n in x or x in n) for x in names):
        return True
    return any(i.symbol == info.symbol for i in md.search(name, 10))


def resolve_symbol(md: MarketData, code: str, name: str, currency: str
                   ) -> tuple[InstrumentInfo | None, dict[str, str] | None]:
    """The printed code (checked against the printed name for Taiwan stocks), else the name; or a flag."""
    code, name = _nfkc(code), _nfkc(name)
    info = md.instrument(code) if code else None
    if info is not None:
        if name and not name.isascii() and not _name_matches(md, info, name):
            return info, _flag("ambiguous_symbol", f"代號 {code} 是{info.name}，對帳單上寫的是「{name}」。", "error")
        return info, None
    if name:
        found = md.search(name, 8)
        local = [i for i in found if (i.market == "US") == (currency == "USD")]
        found = local or found
        exact = [i for i in found if _key(i.name) == _key(name) or name in i.aliases]
        if len(exact) == 1:
            return exact[0], None
        if len(found) == 1:
            return found[0], None
        if found:
            return None, _flag("ambiguous_symbol", f"「{name}」對得到好幾檔，選一檔。", "error")
    return None, _flag("unknown_symbol", f"找不到「{name or code}」。", "error")


# -- one row ----------------------------------------------------------------------------------------------------------
@dataclass
class _Ctx:
    db: Session
    md: MarketData
    account: BrokerAccount
    today: date
    period: tuple[date | None, date | None]
    closes: dict[tuple[str, date], tuple[Decimal | None, Decimal | None, bool]] = field(default_factory=dict)

    @property
    def year_hint(self) -> int | None:
        d = self.period[1] or self.period[0]
        return d.year if d else None


@dataclass
class _Row:
    raw: dict[str, Any]
    candidate: dict[str, Any]
    flags: list[dict[str, str]]
    chunk: int
    ledger: dict[str, Any] | None = None  # what ``check_batch`` checks (a buy or sell ticked by default)

    def add(self, flag: dict[str, str] | None) -> None:
        if flag is not None and all(f["code"] != flag["code"] for f in self.flags):
            self.flags.append(flag)

    @property
    def include(self) -> bool:
        return not any(f["code"] in EXCLUDED or f["severity"] == "error" for f in self.flags)


def _closes(ctx: _Ctx, symbol: str, d: date) -> tuple[Decimal | None, Decimal | None, bool]:
    """(that day's close, the previous one, whether they are reference closes): the official closes from our own
    archive; when it has neither (a trade from before the archive began), the history backfill's closes as a
    reference (product owner 2026-11-17, ``services.reference_close``)."""
    key = (symbol, d)
    if key not in ctx.closes:
        since = d - timedelta(days=CLOSE_LOOKBACK_DAYS)
        rows = ctx.db.execute(select(PriceDaily.date, PriceDaily.close).where(
            PriceDaily.symbol == symbol, PriceDaily.date <= d, PriceDaily.date >= since,
            source_clause(PriceDaily.source, ctx.md.policy)).order_by(PriceDaily.date.desc()).limit(2)).all()
        day = next((Decimal(c) for t, c in rows if t == d), None)
        prev = next((Decimal(c) for t, c in rows if t < d), None)
        reference = False
        if day is None and prev is None:
            refs = reference_closes(ctx.db, ctx.md, symbol, since, d)  # each day's close as traded
            day = refs.get(d)
            before = max((t for t in refs if t < d), default=None)
            if before is not None:
                # a known split in between (0050 resumed on 2025-06-18 at a quarter of 2025-06-10's 188): the
                # previous close on the trade day's basis to compare with; with no close of the trade day to show,
                # no comparison rather than a message whose two numbers look alike
                k = split_factor(ctx.md, symbol, before, d)
                prev = refs[before] / k if day is not None or k == 1 else None
            reference = day is not None or prev is not None
        ctx.closes[key] = (day, prev, reference)
    return ctx.closes[key]


def _unreadable(x: dict[str, Any], missing: list[str]) -> dict[str, str] | None:
    unclear = [f for f in x.get("unclear") or [] if f in FIELD_LABELS]
    fields = list(dict.fromkeys([*missing, *unclear]))
    if not fields:
        return None
    return _flag("unreadable", f"這一列的{'、'.join(FIELD_LABELS[f] for f in fields)}沒讀清楚。", "error")


def _arithmetic(row: _Row, info: InstrumentInfo, kind_day_trade: bool, t: str, qty: Decimal, price: Decimal,
                amount: Decimal | None, fee: Decimal | None, tax: Decimal | None, net: Decimal | None,
                raw_qty: Decimal | None, lots: bool) -> None:
    tw = info.currency == "TWD"
    gross = qty * price
    tolerance = Decimal(1) if tw else Decimal("0.02")
    if amount is not None and abs(gross - amount) > tolerance:
        message = f"股數 × 價格和成交金額差 {_num(abs(gross - amount).quantize(Decimal('0.01')))}"
        if tw and not lots and abs(gross * LOT - amount) <= tolerance:
            message += "，股數可能是張數（1 張＝1,000 股）"
        elif tw and lots and raw_qty is not None and abs(raw_qty * price - amount) <= tolerance:
            message += "，數量可能是股數，不是張數"
        row.add(_flag("amount_mismatch", message + "。"))
    # 價金 as printed, or shares × price when that is what was misread: one misread figure gives one flag
    bases = {amount, gross} if amount is not None else {gross}
    base = amount if amount is not None else gross
    if tw and fee is not None and fee > max((max(bases) * FEE_RATE).to_integral_value(ROUND_FLOOR), FEE_MIN) + 1:
        row.add(_flag("fee_out_of_range", f"手續費 {_num(fee)} 比一般高很多。"))
    # 複委託 settled in NT$ often prints the fee in NT$ next to US$ prices: booked as US$ it would inflate the cost
    if not tw and fee is not None and fee > max(US_FEE_FLOOR, max(bases) * US_FEE_RATE):
        row.add(_flag("currency_mismatch", f"手續費 {_num(fee)} 以美元來說太高，可能是新台幣。"))
    if t == "buy" and tw and tax is not None and tax > 0:
        row.add(_flag("side_inconsistent", "買進卻有交易稅，買賣可能看反了。"))
    if t == "sell" and tw and tax is not None:
        rates = (ETF_TAX, Decimal(0)) if info.type == "etf" else (STOCK_TAX, DAY_TRADE_TAX)
        if not any(abs(tax - (b * r).to_integral_value(ROUND_FLOOR)) <= max(Decimal(1), b * r * Decimal("0.02"))
                   for r in rates for b in bases):
            usual = ETF_TAX if info.type == "etf" else (DAY_TRADE_TAX if kind_day_trade else STOCK_TAX)
            expected = (base * usual).to_integral_value(ROUND_FLOOR)
            row.add(_flag("tax_out_of_range", f"賣出的交易稅是 {_num(tax)}，一般是成交金額的 "
                                              f"{_num(usual * 100)}%（{_num(expected)}）。"))
    if net is not None and net != 0 and ((t == "buy" and net > 0) or (t == "sell" and net < 0)):
        row.add(_flag("side_inconsistent", "應收付金額的正負和買賣對不上，買賣可能看反了。"))


def _price_check(ctx: _Ctx, row: _Row, info: InstrumentInfo, d: date, price: Decimal) -> None:
    day, prev, reference = _closes(ctx, info.symbol, d)
    tw = info.currency == "TWD"
    ref = (prev or day) if tw else (day or prev)
    if ref is None or ref <= 0:
        return
    if abs(price / ref - 1) > (TW_PRICE_BAND if tw else US_PRICE_BAND):
        # a reference close (the history backfill) says so: 「那天參考收盤 1,030（非官方資料），這裡是 103。」
        what, tail = ("參考收盤", "（非官方資料）") if reference else ("收盤", "")
        num = (lambda x: _num(x.quantize(CENT))) if reference else _num  # a split multiplied back: to the cent
        shown = f"那天{what} {num(day)}" if day is not None else f"前一個交易日{what} {num(prev or ref)}"
        row.add(_flag("price_far_from_close", f"{shown}{tail}，這裡是 {_num(price)}。"))


def build_row(ctx: _Ctx, x: dict[str, Any], chunk: int) -> _Row:
    """One transcribed row → candidate + reading, arithmetic, date and price flags (the books come later)."""
    side = x.get("side") if x.get("side") in importer.SIDES else "other"
    kind = x.get("kind") if x.get("kind") in importer.KINDS else "other"
    printed_currency = x.get("currency") if x.get("currency") in ("TWD", "USD") else ""
    raw = {f: importer.scrub(importer.clip(x.get(f), 120)) for f in importer.ROW_FIELDS}
    raw["page"] = x.get("page")
    raw["raw_line"] = importer.scrub(importer.clip(x.get("raw_line"), 500))
    raw_qty, price, amount = dec(x.get("quantity")), dec(x.get("price")), dec(x.get("amount"))
    fee, tax, net = dec(x.get("fee")), dec(x.get("tax")), dec(x.get("net_amount"))
    raw_qty, price, amount, fee, tax = (abs(v) if v is not None else None for v in (raw_qty, price, amount, fee, tax))
    d = parse_date(x.get("trade_date"), ctx.year_hint, ctx.today)
    info, symbol_flag = resolve_symbol(ctx.md, x.get("symbol_code") or "", x.get("name") or "", printed_currency)
    tw = info is None or info.currency == "TWD"
    lots = x.get("quantity_unit") == "lots" and tw
    qty = raw_qty * LOT if lots and raw_qty is not None else raw_qty
    # a side the model could not read: the sign of 應收付 decides the candidate (and the row is flagged unreadable)
    t = side if side != "other" else ("sell" if net is not None and net > 0 else "buy")
    dividend = side in ("cash_dividend", "stock_dividend") or kind == "dividend"
    candidate = {
        "account_id": ctx.account.id, "symbol": info.symbol if info is not None else None,
        "type": "cash_dividend" if dividend and t not in ("cash_dividend", "stock_dividend") else t,
        "trade_date": d.isoformat() if d else "", "quantity": ser.qty(qty), "price": ser.price(price),
        "amount": ser.money(amount), "fee": ser.money(fee), "tax": ser.money(tax),
        "currency": info.currency if info is not None else (printed_currency or ctx.account.currency),
        "is_day_trade": kind == "daytrade", "note": "",
    }
    row = _Row(raw, candidate, [], chunk)
    if dividend:
        row.add(_flag("dividend_auto", "股利已經自動入帳。" if tw else "股利先不匯入。"))
        return row
    if kind == "short":
        row.add(_flag("short_sale", "融券不匯入。"))
        return row
    if kind == "daytrade":
        row.add(_flag("day_trade", "當沖：同一天買進又賣出，先不匯入。"))
    if kind == "margin":
        what = "買進" if t == "buy" else "賣出"
        row.add(_flag("margin", f"融資{what}，當成一般{what}匯入。"))
    missing = [f for f, v in (("trade_date", d), ("quantity", qty), ("price", price)) if not v]
    if side == "other":
        missing.append("side")
    row.add(_unreadable(x, missing))
    row.add(symbol_flag)
    if info is None:
        return row
    if printed_currency and printed_currency != info.currency:
        message = ("美股的價格寫的是新台幣，可能是複委託換算過的。" if info.currency == "USD"
                   else "台股的價格寫的是美元。")
        row.add(_flag("currency_mismatch", message))
    if info.currency == "TWD" and qty is not None and qty != qty.to_integral_value():
        row.add(_flag("fractional_tw_qty", "台股的股數要是整數。", "error"))
    if qty and price:
        _arithmetic(row, info, kind == "daytrade", t, qty, price, amount, fee, tax, net, raw_qty, lots)
    if d is not None:
        trading = is_tw_trading_day(d) if info.currency == "TWD" else d.weekday() < 5
        if not trading:
            row.add(_flag("not_trading_day", f"{_md(d, ctx.today)}（{WEEKDAYS[d.weekday()]}）不是交易日。"))
        start, end = ctx.period
        if start and end and not (start <= d <= end):
            row.add(_flag("outside_period", f"{_md(d, ctx.today)} 不在對帳單的期間（{_md(start, ctx.today)}–"
                                            f"{_md(end, ctx.today)}）裡。"))
        if price and d <= ctx.today:
            _price_check(ctx, row, info, d, price)
    if row.include and d is not None and qty and price:
        row.ledger = {"symbol": info.symbol, "type": t, "trade_date": d, "quantity": qty, "price": price,
                      "fee": fee, "tax": tax, "currency": info.currency, "is_day_trade": kind == "daytrade",
                      "note": ""}
    return row


# -- the whole statement ----------------------------------------------------------------------------------------------
@dataclass
class _Reading:
    results: list[ChunkResult]
    extraction: Extraction
    rows: list[_Row]
    totals: dict[str, Any] | None

    def score(self) -> int:
        """Reading problems (lower is better): rows with a reading flag, unreadable notes, totals that do not add up."""
        s = sum(1 for r in self.rows if any(f["code"] in RETRY_CODES for f in r.flags))
        s += len(self.extraction.unreadable)
        return s + (3 if self.totals and self.totals["ok"] is False else 0)


def parse_month(text: Any, last: bool) -> date | None:
    """A month as printed (2026/10, 2026 年 10 月, 115/10 民國): its first day, or its last with ``last``."""
    m = re.fullmatch(r"(\d{3,4})[./\-年](\d{1,2})月?", re.sub(r"\s+", "", _nfkc(text)))
    if not m:
        return None
    year, month = int(m.group(1)), int(m.group(2))
    year = year + 1911 if year < 1000 else year
    if not 1 <= month <= 12 or year < EARLIEST_YEAR or year > today_taipei().year + 1:
        return None
    first = date(year, month, 1)
    return (first.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1) if last else first


def _period(ext: Extraction, today: date) -> tuple[date | None, date | None]:
    """The statement's period; a month printed alone (``2026 年 10 月``) is that month."""
    starts = [d for d in (parse_date(s, None, today) or parse_month(s, False) for s in ext.period_from) if d]
    ends = [d for d in (parse_date(s, None, today) or parse_month(s, True) for s in ext.period_to) if d]
    start, end = (min(starts) if starts else None), (max(ends) if ends else None)
    return (start, end) if not (start and end and start > end) else (None, None)


def totals_check(rows: Sequence[dict[str, Any]], printed: dict[str, str]) -> dict[str, Any]:
    """The transcribed rows added up against the statement's own 合計 row: ``diff`` = rows − printed (the first figure
    that differs: 價金, 應收付, 手續費, 交易稅); ``ok`` None when no total is printed."""
    sums = {"amount": Decimal(0), "fee": Decimal(0), "tax": Decimal(0), "net_amount": Decimal(0)}
    for x in rows:
        for k in sums:
            v = dec(x.get(k))
            if v is not None:
                sums[k] += v if k == "net_amount" else abs(v)
    compared, diff = 0, None
    for k in ("amount", "net_amount", "fee", "tax"):
        p = dec(printed.get(k))
        if p is None:
            continue
        compared += 1
        d = sums[k] - (p if k == "net_amount" else abs(p))
        if k == "net_amount" and abs(d) > 1 and abs(sums[k] + p) <= 1:
            d = Decimal(0)  # the total printed without its sign
        if abs(d) > 1 and diff is None:
            diff = d
    if not compared:
        return {"ok": None, "diff": None}
    return {"ok": diff is None, "diff": ser.money(diff or 0)}


def _evaluate(ctx: _Ctx, results: list[ChunkResult]) -> _Reading:
    ext = importer.merge(results)
    ctx.period = _period(ext, ctx.today)
    if ext.document_kind == "holdings_snapshot":
        return _Reading(results, ext, [], None)
    page_chunk = {n: i for i, r in enumerate(results) for n in r.pages}
    rows = [build_row(ctx, x, page_chunk.get(x["page"], 0)) for x in ext.rows]
    return _Reading(results, ext, rows, totals_check(ext.rows, ext.printed_totals))


def _needs_retry(reading: _Reading) -> list[int]:
    if reading.extraction.document_kind == "holdings_snapshot":
        return []
    need = {i for i, r in enumerate(reading.results) if not r.ok and r.failure != "bad_request"}
    need |= {i for i, r in enumerate(reading.results) if r.ok and (r.data or {}).get("unreadable")}
    need |= {r.chunk for r in reading.rows if any(f["code"] in RETRY_CODES for f in r.flags)}
    if reading.totals and reading.totals["ok"] is False:
        need |= {i for i, r in enumerate(reading.results) if r.failure != "bad_request"}
    return sorted(need)


def _account(db: Session, user: User, account_id: str | None) -> BrokerAccount:
    if account_id:
        acc = db.get(BrokerAccount, account_id)
        if acc is None or acc.user_id != user.id:
            raise not_found("找不到這個帳戶")
        return acc
    acc = db.scalar(select(BrokerAccount).where(BrokerAccount.user_id == user.id)
                    .order_by(BrokerAccount.created_at, BrokerAccount.id).limit(1))
    if acc is None:
        raise ApiError(422, "no_account", "請先新增一個券商帳戶。")
    return acc


def _lock_user(db: Session, user: User) -> None:
    """PostgreSQL: lock the user's row until the transaction ends (counting today's reads and recording a new one)."""
    if db.get_bind().dialect.name == "postgresql":
        db.execute(select(User.id).where(User.id == user.id).with_for_update())


def read_statement(db: Session, user: User, account_id: str | None, pages: Sequence[Page], md: MarketData,
                   settings: Settings, pool: KeyPool | None = None,
                   cancelled: Callable[[], bool] | None = None) -> dict[str, Any]:
    """Read ``pages`` and check every row against ``account_id``'s books (default: the user's first account).

    429 ``ai_import_daily_limit`` after ``IMPORT_DAILY_LIMIT`` reads today; 429 ``ai_monthly_budget`` once the month's
    budget and 省錢模式's allowance are spent (in 省錢模式 the pages are read once, with no second reading); 503
    ``ai_unavailable`` without a usable key; 422 ``unreadable_file`` when no page could be read (refused by the API,
    cut off, refused by the model). ``cancelled``: true once the client has gone (no second reading then; the first
    one still counts as one of today's reads, it was billed)."""
    account = _account(db, user, account_id)
    limit = settings.import_daily_limit
    if limit > 0 and imports_today(db, user) >= limit:
        raise ApiError(429, "ai_import_daily_limit", f"今天已經匯入 {limit} 份，明天再匯入。", extra={"limit": limit})
    economy = store.check_month_budget(db, user, settings, economy_ok=True)
    pool = pool or get_key_pool()
    if not pool.available:
        raise ApiError(503, "ai_unavailable", "AI 暫時不能用。")
    costs = store.slot_month_costs(db)
    if not pool.ranked(costs):
        raise ApiError(503, "ai_unavailable", "AI 暫時不能用，晚一點再試。")
    model, retry_model = store.model_for(FEATURE, settings), settings.ai_model_import_retry.strip()
    read_id = new_id("stm")
    user_id = user.id
    # Counts toward today's reads from the start. The count is taken again with the user's row locked until the
    # 'started' row is committed, so two reads sent at once are counted one after the other (PostgreSQL; SQLite, used
    # in development, has no row locks).
    _lock_user(db, user)
    if limit > 0 and imports_today(db, user) >= limit:
        raise ApiError(429, "ai_import_daily_limit", f"今天已經匯入 {limit} 份，明天再匯入。", extra={"limit": limit})
    started = store.record_usage(db, user_id=user_id, thread_id=read_id, feature=FEATURE, model=model, key_slot=None,
                                 usage=CallUsage(), stop_reason="started")  # commits: the lock is released
    began = time.monotonic()
    billed = 0

    def record(results: Sequence[ChunkResult]) -> None:
        nonlocal billed
        for r in results:
            for c in r.calls:
                store.record_usage(db, user_id=user_id, thread_id=read_id, feature=FEATURE, model=c.model,
                                   key_slot=c.slot, usage=c.usage, stop_reason=c.stop_reason)
                billed += 1

    by_number = {p.number: p for p in pages}
    first = importer.read_pages(pool, pages, model, settings.ai_effort_import, settings.ai_import_max_tokens, costs)
    record(first)
    load_official_calendar(db)
    ctx = _Ctx(db, md, account, today_taipei(), (None, None))
    reading = _evaluate(ctx, first)
    retried, used = False, model
    # no second reading in 省錢模式, or once the user has cancelled (closed the request): nobody would see it
    gone = cancelled is not None and cancelled()
    need = [] if economy or not retry_model or gone else _needs_retry(reading)
    if need:
        groups = [[by_number[n] for n in first[i].pages] for i in need]
        second = importer.read_groups(pool, groups, retry_model, importer.RETRY_EFFORT,
                                      settings.ai_import_max_tokens, costs)
        record(second)
        retried = True
        combined: list[ChunkResult] = []
        for i, r in enumerate(first):
            parts = [s for s in second if set(s.pages) <= set(r.pages)]
            # a chunk's second reading replaces its first only when all of it was read (or the first failed too):
            # a part that failed again must not take the rows the first reading had with it
            retry_used = i in need and parts and (all(s.ok for s in parts) or not r.ok)
            combined += parts if retry_used else [r]
        other = _evaluate(ctx, combined)
        n_first, n_other = len(reading.rows), len(other.rows)
        # a row one reading has and the other does not counts against the shorter one (a missed row is worse than a
        # flagged one: nobody sees it); ties go to the retry model
        if other.score() + MISSED_ROW * max(0, n_first - n_other) \
                <= reading.score() + MISSED_ROW * max(0, n_other - n_first) and any(s.ok for s in second):
            reading, used = other, retry_model
    if not any(r.ok for r in reading.results):
        failures = {r.failure for r in reading.results}
        if not billed:
            db.delete(started)  # nothing reached the model: not one of today's reads
            db.commit()
        if failures <= {"unavailable"}:
            raise ApiError(503, "ai_unavailable", "AI 暫時不能用，晚一點再試。")
        # nothing was read (cut off, refused, not the schema's JSON): say so, not "no trades in this file"
        if "max_tokens" in failures:
            raise ApiError(422, "unreadable_file", "明細太多，一次讀不完。分成幾張截圖，或把 PDF 分開再匯入。")
        raise ApiError(422, "unreadable_file", "這個檔案讀不了。換成截圖，或重新匯出 PDF 再試。")
    ctx.period = _period(reading.extraction, ctx.today)
    problems = _check_books(db, user, md, account, reading.rows)
    db.rollback()  # the books check writes nothing; make sure nothing is left pending
    out = _response(reading, ctx, used, retried, problems)
    log.info("statement import %s: %d pages, %d rows, %d calls, retried=%s, %.1f s", read_id, len(pages),
             len(out["rows"]), billed, retried, time.monotonic() - began)
    return out


def _check_books(db: Session, user: User, md: MarketData, account: BrokerAccount, rows: Sequence[_Row]
                 ) -> list[dict[str, str]]:
    """The rows ticked by default, replayed with the account's books (``check_batch``: nothing is written)."""
    eligible = [r for r in rows if r.ledger is not None and r.include]
    if not eligible:
        return []
    check = txn_svc.check_batch(db, user, account.id, [r.ledger for r in eligible], md)
    for r, flags in zip(eligible, check.flags, strict=True):
        for f in flags:
            r.add(_flag(f["code"], f["message"], f["severity"]))
    return [{"code": p["code"], "message": p["message"]} for p in check.problems]


def _response(reading: _Reading, ctx: _Ctx, model: str, retried: bool, problems: list[dict[str, str]]
              ) -> dict[str, Any]:
    ext = reading.extraction
    start, end = ctx.period
    printed = {k: v for k, v in ext.printed_totals.items() if v}
    rows = [{"row_id": f"r{i}", "candidate": r.candidate, "raw": r.raw, "flags": r.flags, "include": r.include}
            for i, r in enumerate(reading.rows, start=1)]
    return {
        "document_kind": ext.document_kind,
        "broker_name": importer.scrub(ext.broker_name),
        "period": {"from": start.isoformat() if start else None, "to": end.isoformat() if end else None}
        if start or end else None,
        "rows": rows,
        "printed_totals": printed or None,
        "totals_check": reading.totals,
        "unreadable": [importer.scrub(u) for u in ext.unreadable],
        "embedded_instructions": [importer.scrub(u) for u in ext.embedded_instructions],
        "model_used": model,
        "retried": retried,
        "notice": NOTICE.get(ext.document_kind) if not rows else None,
        "problems": problems,
    }
