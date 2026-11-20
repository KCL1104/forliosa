"""匯入庫存 v1 (``POST /imports/positions``, ``POST /imports/positions/commit``; 產品負責人 2026-11-17, the four
decisions as recommended): read a broker app's holdings (庫存) screens or pasted text, check every row, store nothing;
then write one buy per position as one batch that can be undone like a statement import.

Reading: the statement import's pipeline (``services.imports.read_with_retry``): the same model and retry model, the
same daily limit (``IMPORT_DAILY_LIMIT``, statements and holdings together), the month's budget and ``ai_usage`` rows
under ``feature="import"`` (counts and cost only). Nothing of the upload is kept or logged: not the images, the text,
the rows. Each row (``flags[].code``; ``include`` is the default tick in the review table):

* reading: ``unreadable`` (no code or name, no shares, no cost — or a printed field the model could not read),
  ``unit_fixed`` (a Taiwan stock's 張/股 taken the other way round, because only that unit fits the printed total
  cost or market value: ticked, pointed out),
  ``unknown_symbol`` / ``ambiguous_symbol``, ``fractional_tw_qty``, ``not_whole_lots`` (printed in 張 and not a whole
  number of them: odd lots inside, or a misreading), ``cost_mismatch`` (shares × average cost against the printed
  total cost; also 張/股 mix-ups), ``value_mismatch`` (shares × price against the printed market value; a US
  stock's value printed in NT$ is not compared).
* currency: ``currency_mismatch`` (a US stock's cost printed in NT$, a Taiwan stock's in US$), ``currency_guess`` (a
  US stock with no currency shown: taken as US$).
* kind: ``margin`` (融資: imported as an ordinary holding, tagged), ``short_sale`` (融券: never imported).
* the books: ``in_ledger`` (the account already holds the stock: not ticked; ``in_ledger`` says how many shares at
  what average; 以券商為準 replaces its records), ``in_other_account`` (another account holds it too),
  ``same_symbol_twice`` (two rows of one stock left after identical rows from overlapping screenshots were merged).

Price: the broker's average cost when printed, else total cost ÷ shares (``price_basis``). The batch writes one buy per
row at that price with fee 0 (broker averages usually include the fees), so the ledger's average equals the broker's.

Writing (:func:`commit`): one buy per row on the chosen date (default today, Taipei; per-row override), every row or
none (``services.transactions.check_batch`` / ``write_batch``, ``source="import"``, one ``import_batch_id``). A row of a
stock the account already holds is refused (``in_ledger``) unless its ``replace`` is set (以券商為準): then every
record of that stock in that account is deleted (``services.transactions.delete_records``) in the same
transaction as the batch is written. 定期定額, other stocks, accounts and users are not touched. Undoing the batch
(``DELETE /transactions/batches/{id}``) deletes the buys it wrote; the records a replace deleted do not come back.
"""

from __future__ import annotations

import logging
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from forliosa.ai import importer, positions
from forliosa.ai.importer import ChunkResult, Page
from forliosa.ai.keypool import KeyPool
from forliosa.api import serialize as ser
from forliosa.config import Settings
from forliosa.domain.ledger import replay
from forliosa.marketdata.base import InstrumentInfo
from forliosa.marketdata.service import MarketData
from forliosa.models import BrokerAccount, User
from forliosa.services import auto_dividends, buy_date, sharing
from forliosa.services import imports as stm
from forliosa.services import transactions as txn_svc
from forliosa.services.imports import ReadMessages, dec
from forliosa.services.ledger_io import LedgerInput, load_ledger_input
from forliosa.timeutil import today_taipei

log = logging.getLogger(__name__)

ACCESS_MESSAGE = "這個帳號還不能匯入庫存。"
MESSAGES = ReadMessages("今天已經匯入 {limit} 次，明天再匯入。",
                        "一次太多檔，讀不完。分成幾次匯入。",
                        "讀不出來。換一張清楚的截圖，或改貼文字再試。")
# Not ticked by default (the rest are only pointed out); any ``error`` flag also unticks the row.
EXCLUDED = frozenset({"unknown_symbol", "ambiguous_symbol", "unreadable", "fractional_tw_qty", "currency_mismatch",
                      "short_sale", "in_ledger"})
# Reading problems worth a second reading with the retry model.
RETRY_CODES = frozenset({"unreadable", "cost_mismatch", "value_mismatch", "fractional_tw_qty"})
DIVIDEND_TYPES = frozenset({"cash_dividend", "stock_dividend"})
LOT = Decimal(1000)
COST_TOLERANCE = Decimal("0.005")  # fees in or out of the printed total, averages rounded to 2 decimals
VALUE_TOLERANCE = Decimal("0.01")  # the price and the value may be a tick apart
# A 複委託 screen often prints a US stock's price in US$ and only a NT$ 參考市值: a value this many times shares ×
# price is that NT$ value, not a misreading (no value_mismatch, so no second reading either).
TWD_PER_USD = (Decimal(20), Decimal(50))
PRICE_PLACES = Decimal("0.00000001")  # total ÷ shares, as the database keeps a price (NUMERIC(24, 8))
FIELD_LABELS = {"symbol_code": "代號", "name": "名稱", "kind": "種類", "quantity": "股數", "quantity_unit": "單位",
                "avg_cost": "均價", "total_cost": "總成本", "market_price": "現價", "market_value": "市值",
                "currency": "幣別", "cost": "成本"}  # cost: neither 均價 nor 總成本
NOTICE = {"trade_records": "這是交易明細，不是庫存。請改用「匯入對帳單」。",
          "other": "這裡面沒有看到庫存。",
          "holdings": "畫面上沒有讀到持股。"}

_flag = stm._flag
_num = stm._num


def require_access(user: User, settings: Settings) -> None:
    stm.require_access(user, settings, ACCESS_MESSAGE)


# -- the books: what each account holds now ----------------------------------------------------------------------
@dataclass(frozen=True)
class Held:
    quantity: Decimal
    avg_cost: Decimal  # trade currency, buy fees included (the ledger's average)
    currency: str
    records: int  # the stock's records in the account: what 以券商為準 deletes
    dividends: int = 0  # of which dividends (cash or stock, automatic ones too): income a replace takes away
    sells: int = 0  # of which sells: realized gains a replace takes away

    def out(self) -> dict[str, Any]:
        return {"quantity": ser.qty(self.quantity), "avg_cost": ser.price(self.avg_cost), "currency": self.currency,
                "records": self.records, "dividends": self.dividends, "sells": self.sells}


def holdings(db: Session, user: User, inp: LedgerInput | None = None) -> dict[tuple[str, str], Held]:
    """(account id, symbol) → what the account holds now, for every stock with shares left (``inp``: the user's
    ledger when the caller has loaded it already)."""
    inp = inp or load_ledger_input(db, user)
    ledger = replay(inp.ledger_txns(), inp.method).ledger
    records = Counter((t.account_id, t.symbol) for t in inp.transactions if t.symbol)
    dividends = Counter((t.account_id, t.symbol) for t in inp.transactions if t.symbol and t.type in DIVIDEND_TYPES)
    sells = Counter((t.account_id, t.symbol) for t in inp.transactions if t.symbol and t.type == "sell")
    return {key: Held(p.quantity, p.avg_cost, p.currency, records[key], dividends[key], sells[key])
            for key, p in ledger.positions.items() if p.quantity > 0}


def _avg_text(d: Decimal) -> str:
    return _num(d.quantize(Decimal("0.01") if d >= 10 else Decimal("0.0001")))


# -- one row ---------------------------------------------------------------------------------------------------------
@dataclass
class _Ctx:
    md: MarketData
    account: BrokerAccount
    held: dict[tuple[str, str], Held]
    account_names: dict[str, str]


@dataclass
class _Pos:
    raw: dict[str, Any]
    info: InstrumentInfo | None
    name: str
    kind: str
    currency: str
    quantity: Decimal | None
    price: Decimal | None
    basis: str | None  # average_cost | total_cost
    total_cost: Decimal | None
    chunk: int
    flags: list[dict[str, str]] = field(default_factory=list)
    in_ledger: Held | None = None
    # 資產組成原型: the estimated buy date (``None``: no crossing, see the ``no_crossing`` flag); only rows that were
    # estimated have it (``estimated``), the others leave ``estimated_date`` out of the response
    estimated: bool = False
    estimated_date: date | None = None

    def add(self, flag: dict[str, str] | None) -> None:
        if flag is not None and all(f["code"] != flag["code"] for f in self.flags):
            self.flags.append(flag)

    @property
    def include(self) -> bool:
        return not any(f["code"] in EXCLUDED or f["severity"] == "error" for f in self.flags)

    @property
    def same_key(self) -> tuple[Any, ...] | None:
        """Identical rows (overlapping screenshots) share this key; None when there is nothing to compare."""
        if self.quantity is None or self.price is None:
            return None
        who = self.info.symbol if self.info is not None else stm._key(self.raw["symbol_code"] + self.raw["name"])
        return who, self.kind, self.quantity, self.price


def _tolerance(qty: Decimal, printed: Decimal, tw: bool, relative: Decimal) -> Decimal:
    return max(Decimal(1) if tw else Decimal("0.02"), printed * relative, qty * Decimal("0.005"))


def _near(qty: Decimal, unit: Decimal, printed: Decimal, tw: bool, relative: Decimal) -> bool:
    return abs(qty * unit - printed) <= _tolerance(qty, printed, tw, relative)


Pair = tuple[Decimal, Decimal, Decimal]  # a per-share amount, the printed total it makes, the relative tolerance


def _printed_pairs(avg: Decimal | None, total: Decimal | None, market_price: Decimal | None,
                   market_value: Decimal | None) -> list[Pair]:
    """average × shares = total cost and price × shares = market value, where both sides are printed."""
    return [(u, t, rel) for u, t, rel in ((avg, total, COST_TOLERANCE), (market_price, market_value, VALUE_TOLERANCE))
            if u and t]


def _fits(qty: Decimal, pairs: Sequence[Pair]) -> bool:
    """Taiwan shares ``qty`` agree with every printed pair (and there is one)."""
    return bool(pairs) and all(_near(qty, u, t, True, rel) for u, t, rel in pairs)


def _unit_by_arithmetic(lots: bool, raw_qty: Decimal, pairs: Sequence[Pair]) -> bool | None:
    """A Taiwan stock's 張 or 股 as the printed amounts say: the other unit when the number as read fits none of the
    printed pairs and the other unit fits all of them (the model took a 庫存股數 column for 張: live check
    2026-11-17). None: the reading stands."""
    as_read, other = (raw_qty * LOT, raw_qty) if lots else (raw_qty, raw_qty * LOT)
    if any(_near(as_read, u, t, True, rel) for u, t, rel in pairs):
        return None
    return (not lots) if _fits(other, pairs) else None


def _check_product(row: _Pos, code: str, what: str, qty: Decimal, unit: Decimal, printed: Decimal,
                   raw_qty: Decimal | None, lots: bool, tw: bool, relative: Decimal) -> None:
    """shares × ``unit`` against a printed total (``what``: 均價和總成本, 現價和市值), with a 張/股 hint."""
    tol = _tolerance(qty, printed, tw, relative)
    gross = qty * unit
    if abs(gross - printed) <= tol:
        return
    message = f"股數 × {what}差 {_num(abs(gross - printed).quantize(Decimal('0.01')))}"
    if tw and not lots and abs(gross * LOT - printed) <= tol:
        message += "，股數可能是張數（1 張＝1,000 股）"
    elif tw and lots and raw_qty is not None and abs(raw_qty * unit - printed) <= tol:
        message += "，數量可能是股數，不是張數"
    row.add(_flag(code, message + "。"))


def _value_in_twd(info: InstrumentInfo, gross: Decimal, printed: Decimal) -> bool:
    """A US stock's market value printed in NT$ against its price in US$ (``TWD_PER_USD``)."""
    return info.currency == "USD" and gross > 0 and TWD_PER_USD[0] <= printed / gross <= TWD_PER_USD[1]


def _currency(row: _Pos, info: InstrumentInfo, printed: str) -> None:
    if info.currency == "USD":
        if printed in ("TWD", "other"):
            row.add(_flag("currency_mismatch", "美股的成本寫的是新台幣，要改成美元的成本。" if printed == "TWD"
                          else "這一列的成本不是美元。", "error"))
        elif printed == "not_shown":
            row.add(_flag("currency_guess", "畫面上沒寫幣別，當成美元。"))
    elif printed in ("USD", "other"):
        row.add(_flag("currency_mismatch", "台股的成本寫的是美元。" if printed == "USD"
                      else "這一列的成本不是新台幣。", "error"))


def _books(ctx: _Ctx, row: _Pos, info: InstrumentInfo) -> None:
    held = ctx.held.get((ctx.account.id, info.symbol))
    if held is not None:
        row.in_ledger = held
        same = (row.quantity == held.quantity and row.price is not None
                and abs(held.avg_cost - row.price) <= max(Decimal("0.01"), row.price * Decimal("0.0005")))
        row.add(_flag("in_ledger", "帳本裡已經有，股數和均價都一樣。" if same else
                      f"帳本裡已經有 {_num(held.quantity)} 股，均價 {_avg_text(held.avg_cost)}。"))
    others = [(a, h) for (a, s), h in ctx.held.items() if s == info.symbol and a != ctx.account.id]
    if len(others) == 1:
        a, h = others[0]
        row.add(_flag("in_other_account", f"「{ctx.account_names.get(a, '')}」帳戶也有 {_num(h.quantity)} 股。"))
    elif others:
        row.add(_flag("in_other_account", f"另外 {len(others)} 個帳戶也有這一檔。"))


def build_row(ctx: _Ctx, x: dict[str, Any], chunk: int) -> _Pos:
    """One transcribed row → shares, price and the reading, currency and books flags."""
    kind = x.get("kind") if x.get("kind") in positions.KINDS else "other"
    printed = x.get("currency") if x.get("currency") in positions.CURRENCIES else "not_shown"
    raw = {f: importer.scrub(importer.clip(x.get(f), 120)) for f in positions.ROW_FIELDS}
    raw["page"] = x.get("page")
    raw["raw_line"] = importer.scrub(importer.clip(x.get("raw_line"), 500))
    raw_qty, avg, total = (abs(v) if v is not None else None for v in (dec(x.get(f)) for f in
                                                                         ("quantity", "avg_cost", "total_cost")))
    market_price, market_value = (abs(v) if v is not None else None for v in (dec(x.get(f)) for f in
                                                                               ("market_price", "market_value")))
    info, symbol_flag = stm.resolve_symbol(ctx.md, x.get("symbol_code") or "", x.get("name") or "",
                                           "USD" if printed == "USD" else "", "畫面")
    tw = info.currency == "TWD" if info is not None else printed != "USD"
    lots = x.get("quantity_unit") == "lots" and tw
    pairs = _printed_pairs(avg, total, market_price, market_value) if tw and info is not None and raw_qty else []
    unit_fixed = _unit_by_arithmetic(lots, raw_qty, pairs) if pairs and raw_qty else None
    if unit_fixed is not None:
        lots = unit_fixed
    qty = raw_qty * LOT if lots and raw_qty is not None else raw_qty
    qty = qty or None  # 0 shares: nothing to import
    price, basis = None, None
    if avg:
        price, basis = avg, "average_cost"
    elif total and qty:
        price, basis = (total / qty).quantize(PRICE_PLACES), "total_cost"
    currency = info.currency if info is not None else (printed if printed in ("TWD", "USD") else
                                                       ctx.account.currency)
    name = info.name if info is not None else raw["name"] or raw["symbol_code"]
    row = _Pos(raw, info, name, kind, currency, qty, price, basis, total or None, chunk)
    if kind == "short":
        row.add(_flag("short_sale", "融券的庫存不匯入。"))
        return row
    if kind == "margin":
        row.add(_flag("margin", "融資的庫存，當成一般持股匯入。"))
    missing = [f for f, v in (("quantity", qty), ("cost", price)) if not v]
    if not (raw["symbol_code"] or raw["name"]):
        missing.insert(0, "name")
    # a field left blank (or currency not_shown) was not printed: its unclear mark adds nothing (``missing`` covers a
    # needed one); nor does an unclear 張/股 that the printed amounts settle (the model marked an absent 均價 and 幣別
    # and the unit on a 總成本-only screen as unclear: live check 2026-11-17)
    settled = {"quantity_unit"} if qty and _fits(qty, pairs) else set()
    unclear = [f for f in x.get("unclear") or [] if f in FIELD_LABELS and f not in settled
               and str(x.get(f) or "").strip() not in ("", "not_shown")]
    fields = list(dict.fromkeys([*missing, *unclear]))
    if fields:
        row.add(_flag("unreadable", f"這一列的{'、'.join(FIELD_LABELS[f] for f in fields)}沒讀清楚。", "error"))
    if raw["symbol_code"] or raw["name"]:
        row.add(symbol_flag)
    if info is None:
        return row
    _currency(row, info, printed)
    if unit_fixed is not None:
        row.add(_flag("unit_fixed", "照畫面上的金額算，數量是張數（1 張＝1,000 股），已經換成股數。" if unit_fixed
                      else "照畫面上的金額算，數量是股數，不是張數。"))
    if tw and qty is not None and qty != qty.to_integral_value():
        row.add(_flag("fractional_tw_qty", "台股的股數要是整數。", "error"))
    elif lots and raw_qty is not None and raw_qty != raw_qty.to_integral_value():
        row.add(_flag("not_whole_lots", f"畫面上是 {_num(raw_qty)} 張，算成 {_num(qty or 0)} 股；不是整張，確認一下。"))
    if qty and avg and total:
        _check_product(row, "cost_mismatch", "均價和總成本", qty, avg, total, raw_qty, lots, tw, COST_TOLERANCE)
    if qty and market_price and market_value and not _value_in_twd(info, qty * market_price, market_value):
        _check_product(row, "value_mismatch", "現價和市值", qty, market_price, market_value, raw_qty, lots, tw,
                       VALUE_TOLERANCE)
    _books(ctx, row, info)
    return row


# -- the whole reading ---------------------------------------------------------------------------------------------
@dataclass
class _Reading:
    results: list[ChunkResult]
    extraction: positions.Extraction
    rows: list[_Pos]
    merged: int  # identical rows (overlapping screenshots) counted once

    def score(self) -> int:
        """Reading problems (lower is better): rows with a reading flag, unreadable notes."""
        return (sum(1 for r in self.rows if any(f["code"] in RETRY_CODES for f in r.flags))
                + len(self.extraction.unreadable))

    def retry_chunks(self) -> list[int]:
        need = {i for i, r in enumerate(self.results) if not r.ok and r.failure != "bad_request"}
        if self.extraction.document_kind == "holdings":
            need |= {i for i, r in enumerate(self.results) if r.ok and (r.data or {}).get("unreadable")}
            need |= {r.chunk for r in self.rows if any(f["code"] in RETRY_CODES for f in r.flags)}
        return sorted(need)


def merge_rows(rows: list[_Pos]) -> tuple[list[_Pos], int]:
    """Identical rows (same stock, kind, shares and price: overlapping screenshots) counted once; two different rows
    of one stock (整股 and 零股 listed apart, 現股 and 融資) both kept and flagged ``same_symbol_twice``."""
    seen: set[tuple[Any, ...]] = set()
    out: list[_Pos] = []
    merged = 0
    for r in rows:
        k = r.same_key
        if k is not None and k in seen:
            merged += 1
            continue
        if k is not None:
            seen.add(k)
        out.append(r)
    by_symbol: defaultdict[str, list[_Pos]] = defaultdict(list)
    for r in out:
        if r.info is not None:
            by_symbol[r.info.symbol].append(r)
    for same in by_symbol.values():
        if len(same) > 1:
            for r in same:
                r.add(_flag("same_symbol_twice",
                            f"這一檔有 {len(same)} 列，都匯入會加在一起（例如整股和零股分開列）。"))
    return out, merged


def _evaluate(ctx: _Ctx, results: list[ChunkResult]) -> _Reading:
    ext = positions.merge(results)
    page_chunk = {n: i for i, r in enumerate(results) for n in r.pages}
    rows, merged = merge_rows([build_row(ctx, x, page_chunk.get(x["page"], 0)) for x in ext.rows])
    return _Reading(results, ext, rows, merged)


def read_positions(db: Session, user: User, account_id: str | None, pages: Sequence[Page], md: MarketData,
                   settings: Settings, pool: KeyPool | None = None,
                   cancelled: Callable[[], bool] | None = None) -> dict[str, Any]:
    """Read holdings screenshots (or one page of pasted text) and check every row against ``account_id``'s books
    (default: the user's first account). Errors: ``services.imports.read_with_retry``'s."""
    account = stm._account(db, user, account_id)
    inp = load_ledger_input(db, user)
    ctx = _Ctx(md, account, holdings(db, user, inp), {a.id: a.name for a in inp.accounts})
    run = stm.read_with_retry(db, user, pages, settings, pool, cancelled, spec=positions.SPEC,
                              evaluate=lambda results: _evaluate(ctx, results), id_prefix="pos", messages=MESSAGES)
    estimate_buy_dates(db, md, run.reading.rows)
    out = _response(run.reading, account, run.model, run.retried)
    log.info("positions import %s: %d pages, %d rows, %d merged, %d calls, retried=%s, %.1f s", run.read_id,
             len(pages), len(out["rows"]), run.reading.merged, run.calls, run.retried, time.monotonic() - run.began)
    return out


def estimate_buy_dates(db: Session, md: MarketData, rows: Sequence[_Pos]) -> None:
    """資產組成原型 (``docs/proposals/asset-composition.md``): each row with a stock and a cost, short sales left out,
    gets its estimated buy date — the most recent day, looking back from today (Taipei), the price as traded crossed
    the cost (``services.buy_date``); none: ``estimated_date`` null and a ``no_crossing`` warning (not unticked). Demo
    prices (personal mode) estimate nothing: those rows are as before.
    Every stock's prices are read together, once, after the reading (not for a retry's reading). The estimate
    failing (a database error) does not lose the paid reading: it is logged and every row comes back without
    ``estimated_date`` — as from a server that does not estimate (the review table keeps one date for the batch), never
    as ``no_crossing``."""
    wanted = [(r, r.info, r.price) for r in rows if r.info is not None and r.price is not None
              and not any(f["code"] == "short_sale" for f in r.flags)]
    try:
        found = buy_date.estimate_rows(db, md, [(info.symbol, price, info.currency) for _, info, price in wanted],
                                       today_taipei())
    except Exception:  # the reading is paid for: a failed estimate leaves the rows as an older server sent them
        log.warning("positions import: buy dates not estimated for %d rows", len(wanted), exc_info=True)
        db.rollback()  # (the reading's usage rows are committed already)
        return
    for (r, _, _), e in zip(wanted, found, strict=True):
        if e.skipped:  # demo prices: the row is left as before (no ``estimated_date``)
            continue
        r.estimated, r.estimated_date = True, e.estimated_date
        if e.message is not None:
            r.add(_flag(buy_date.NO_CROSSING, e.message))


def _response(reading: _Reading, account: BrokerAccount, model: str, retried: bool) -> dict[str, Any]:
    ext = reading.extraction
    rows = [{"row_id": f"p{i}", "symbol": r.info.symbol if r.info is not None else None, "name": r.name,
             "currency": r.currency, "quantity": ser.qty(r.quantity), "price": ser.price(r.price),
             "price_basis": r.basis, "total_cost": ser.money(r.total_cost), "raw": r.raw, "flags": r.flags,
             "include": r.include, "in_ledger": r.in_ledger.out() if r.in_ledger is not None else None,
             **({"estimated_date": r.estimated_date} if r.estimated else {})}
            for i, r in enumerate(reading.rows, start=1)]
    return {
        "account_id": account.id,
        "document_kind": ext.document_kind,
        "broker_name": importer.scrub(ext.broker_name),
        "trade_date": today_taipei().isoformat(),
        "rows": rows,
        "merged_duplicates": reading.merged,
        "unreadable": [importer.scrub(u) for u in ext.unreadable],
        "embedded_instructions": [importer.scrub(u) for u in ext.embedded_instructions],
        "model_used": model,
        "retried": retried,
        "notice": NOTICE.get(ext.document_kind) if not rows else None,
    }


# -- writing the batch ---------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class CommitRow:
    """One position to write (``PositionsCommitRowIn``): ``price`` or ``total_cost`` (price = total ÷ shares)."""

    symbol: str
    quantity: Decimal
    price: Decimal | None = None
    total_cost: Decimal | None = None
    trade_date: date | None = None
    currency: str | None = None
    replace: bool = False
    # 資產組成原型: how this row's date came about (the review table says) and the estimate it started from
    date_basis: str | None = None
    estimated_date: date | None = None

    def unit_price(self) -> Decimal | None:
        if self.price is not None:
            return self.price
        if self.total_cost is not None and self.quantity > 0:
            return (self.total_cost / self.quantity).quantize(PRICE_PLACES)
        return None


def date_basis_of(row: CommitRow, trade_date: date, imported_on: date) -> tuple[str, date | None]:
    """資產組成原型: the stored ``(date_basis, estimated_date)`` of a row the review table sent a basis for. The table
    says what it showed; the dates decide: an ``estimated`` row whose date is not its estimate, or an ``import_day`` row
    not on the import day, was changed by the user (``picked``). ``import_day`` keeps no estimate.

    The import day is the day the screenshot was read, the commit's day may be the next one (read at 23:59, signed at
    00:01): an ``import_day`` row dated the calendar day before the commit is still ``import_day`` (the smallest honest
    fix — its date is the read's day, which is what the table showed; ``imported_on`` stays the commit's day). The
    estimate itself was checked by :func:`basis_errors`."""
    est = row.estimated_date
    if row.date_basis == "estimated" and est is not None and trade_date == est:
        return "estimated", est
    if row.date_basis == "import_day" and imported_on - timedelta(days=1) <= trade_date <= imported_on:
        return "import_day", None
    return "picked", est


def basis_errors(row: CommitRow, symbol: str, trade_date: date, imported_on: date,
                 change: buy_date.ShareChange | None) -> list[dict[str, str]]:
    """資產組成原型: why a row the review table sent a basis for cannot be written (row errors; a row without
    ``date_basis`` is as before):

    * ``bad_estimated_date``: its ``estimated_date`` is not a day the estimator could have searched — before five years
      back (a US stock: 2024-07-01; one day of slack for a read before midnight), before the share-count limit, or
      after the import day (today, Taipei);
    * ``before_share_change``: its date is before the share-count limit (``change``: the latest split, capital
      reduction or stock dividend on or before the import day; ``services.buy_date.share_changes``) — the broker's
      shares already include it, and the ledger would book it again."""
    if row.date_basis is None:
        return []
    out: list[dict[str, str]] = []
    est = row.estimated_date
    if est is not None:
        lo = buy_date.search_floor(symbol, imported_on - timedelta(days=1), change)
        if not lo <= est <= imported_on:
            out.append(_flag(buy_date.BAD_ESTIMATED_DATE,
                             f"估計的買入日 {buy_date.ymd_text(est)} 不在估得到的期間（{buy_date.ymd_text(lo)} – "
                             f"{buy_date.ymd_text(imported_on)}）。", "error"))
    if change is not None and trade_date < change.date:
        out.append(_flag(buy_date.BEFORE_SHARE_CHANGE, f"{buy_date.before_change_message(change)}。", "error"))
    return out


# one read of each stock's ex-dividend notices for the check, the strict replay and the re-sync together, replaced
# stocks included (``auto_dividends.shared_events``, as the statement import's ``create_batch``)
@auto_dividends.shared_events
def commit(db: Session, user: User, account_id: str, rows: Sequence[CommitRow], md: MarketData,
           trade_date: date | None = None, dry_run: bool = False) -> dict[str, Any]:
    """Write ``rows`` into ``account_id`` as one buy each (fee 0) on ``trade_date`` (default today, Taipei; a row's
    own date wins), every row or none, in one transaction with the deletions its replaces ask for.

    Row errors are ``check_batch``'s (``unknown_symbol``, ``bad_date``, ``validation_error`` …) plus ``in_ledger``: the
    account already holds the stock and the row does not replace it (a buy on top would double it). ``dry_run``:
    the same work, rolled back — the flags, and what each replace would delete. Otherwise 422 ``batch_rejected`` on
    any error (nothing written or deleted); 404 when the account is not the user's. ``account_id`` names the account:
    never the default (first) account the reading falls back to, since a replace deletes records there.

    資產組成原型: a row with ``date_basis`` stores it (:func:`date_basis_of`), its ``estimated_date`` and
    ``imported_on`` = today (Taipei); the buy is the same (the broker's cost, fee 0), only its date is estimated. Such a
    row is refused (:func:`basis_errors`) when its estimate is not one the estimator could have found, or its date is
    before the stock's share-count limit. Rows without one are written exactly as before."""
    account = txn_svc._get_account(db, user, account_id)  # named, never the default account: a write may delete
    auto_dividends.lock_accounts(db, [account.id])
    day = trade_date or today_taipei()
    imported_on = today_taipei()
    held = holdings(db, user)
    infos = [md.instrument(r.symbol) for r in rows]
    replacing = sorted({info.symbol for r, info in zip(rows, infos, strict=True) if r.replace and info is not None})
    in_ledger = [held.get((account.id, info.symbol)) if info is not None else None for info in infos]
    limits = buy_date.share_changes(md, [info.symbol for r, info in zip(rows, infos, strict=True)
                                         if info is not None and r.date_basis is not None], imported_on)
    pre: list[list[dict[str, str]]] = [[] for _ in rows]
    for i, (r, info, h) in enumerate(zip(rows, infos, in_ledger, strict=True)):
        if info is not None and h is not None and info.symbol not in replacing:
            pre[i].append(_flag("in_ledger", f"帳本裡已經有 {_num(h.quantity)} 股。勾「以券商為準」才會換掉，"
                                             "不然這一列不要匯入。", "error"))
        if info is not None:
            pre[i] += basis_errors(r, info.symbol, r.trade_date or day, imported_on, limits.get(info.symbol))
    replaced: list[dict[str, Any]] = []
    feed_keys: list[sharing.TradeKey] = []
    for symbol in replacing:
        gone = txn_svc.delete_records(db, user, [account.id], symbol)  # the step 刪除這檔 uses too
        feed_keys += gone.feed_keys
        replaced.append({"symbol": symbol, "deleted": gone.count})
    batch = [{"symbol": info.symbol if info is not None else r.symbol, "type": "buy",
              "trade_date": r.trade_date or day, "quantity": r.quantity, "price": r.unit_price(), "fee": Decimal(0),
              "tax": Decimal(0), "currency": r.currency, "note": ""} for r, info in zip(rows, infos, strict=True)]
    check = txn_svc.check_batch(db, user, account.id, batch, md)
    for flags, extra in zip(check.flags, pre, strict=True):
        flags[:0] = extra
    if dry_run:
        db.rollback()  # the replaces' deletions too: nothing is written
        return {"dry_run": True, "ok": check.ok, "trade_date": day,
                "rows": [{"index": i, "flags": f, "in_ledger": h.out() if h is not None else None}
                         for i, (f, h) in enumerate(zip(check.flags, in_ledger, strict=True))],
                "replaced": replaced,
                "problems": [{"code": p["code"], "message": p["message"]} for p in check.problems]}
    if not check.ok:
        db.rollback()
        raise txn_svc.batch_rejected(check)
    for r, cand in zip(rows, check.candidates, strict=True):
        if cand is not None and r.date_basis is not None:
            cand.date_basis, cand.estimated_date = date_basis_of(r, cand.trade_date, imported_on)
            cand.imported_on = imported_on
    res = txn_svc.write_batch(db, user, check, md, also_sync=[(account.id, s) for s in replacing],
                              purge_feed_keys=feed_keys)
    log.info("positions import batch %s: %d rows, %d stocks replaced", res.batch_id, len(res.created), len(replaced))
    return {"dry_run": False, "batch_id": res.batch_id, "trade_date": day, "created": [t.id for t in res.created],
            "replaced": replaced, "auto_dividends_added": res.auto_dividends_added}
