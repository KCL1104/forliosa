"""Seed a demo user with two accounts, ~2 years of realistic transactions and a 定期定額 plan.

Usage: ``uv run python -m forliosa.seed`` (runs ``alembic upgrade head`` first; re-running replaces
the demo user's data). Every transaction goes through the same service as ``POST /transactions`` — so
fees, taxes and the NHI premium are auto-calculated by the production rules and the ledger is validated.

Trade prices: under ``DATA_POLICY=personal`` each price is the close the market-data facade returns for
that day (real where available). Under ``commercial`` (the default) there is no commercially usable price
history before our archive starts, so the demo user's trades — fictional user input, not market data —
are priced from a private synthetic path that ends at the real latest close. The API itself never serves
demo market data under ``commercial``; it makes no FinMind / MIS / Yahoo call either way.
"""

from __future__ import annotations

import argparse
import logging
import math
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from forliosa.config import API_ROOT
from forliosa.db import session_factory
from forliosa.ids import new_id
from forliosa.marketdata.base import Candle, market_of_symbol
from forliosa.marketdata.demo import DemoProvider
from forliosa.marketdata.service import MarketData, get_market_data
from forliosa.models import BrokerAccount, RecurringPlan, User, WatchlistItem
from forliosa.services import transactions as txn_svc
from forliosa.services.ledger_io import DEFAULT_PREFERENCES, load_ledger_input, shares_held
from forliosa.timeutil import today_taipei

log = logging.getLogger("forliosa.seed")

DEMO_EMAIL = "demo@forliosa.local"
DEMO_WATCHLIST = ("2382.TW", "2308.TW", "2881.TW")  # 廣達、台達電、富邦金
DEMO_NAME = "示範使用者"
# Candidates for a real 配股 (stock dividend) event in the last two years (financials often pay one).
STOCK_DIVIDEND_CANDIDATES = ("2884.TW", "5880.TW", "2892.TW", "2801.TW", "2887.TW", "2890.TW")


def run_migrations() -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(Path(API_ROOT) / "alembic.ini"))
    command.upgrade(cfg, "head")


@dataclass
class PriceBook:
    md: MarketData
    start: date
    end: date

    def __post_init__(self):
        self._candles: dict[str, list[Candle]] = {}
        self.demo_symbols: set[str] = set()

    def candles(self, symbol: str) -> list[Candle]:
        if symbol not in self._candles:
            h = self.md.history(symbol, self.start, self.end)
            if h.is_demo:
                self.demo_symbols.add(symbol)
            self._candles[symbol] = h.candles
        return self._candles[symbol]

    def on_or_after(self, symbol: str, d: date) -> Candle:
        for c in self.candles(symbol):
            if c.t >= d:
                return c
        return self.candles(symbol)[-1]


def trade_price_source(md: MarketData) -> MarketData:
    """Where the seed reads its (fictional) trade prices and dividends from; see the module docstring."""
    if md.demo_data_allowed:
        return md
    return MarketData([DemoProvider(anchor_fn=md._real_anchor)], policy="personal")


class Seeder:
    def __init__(self, db: Session, md: MarketData, today: date, prices: MarketData | None = None):
        self.db, self.md, self.today = db, md, today
        self.pmd = prices or trade_price_source(md)
        self.prices = PriceBook(self.pmd, today - timedelta(days=760), today)
        self.count = 0
        self.first_buy: dict[str, date] = {}

    def add(self, user: User, **body) -> None:
        body.setdefault("note", "")
        txn_svc.create(self.db, user, body, self.md)
        self.count += 1

    def trade(self, user: User, acc: BrokerAccount, side: str, symbol: str, days_ago: int, qty: int,
              note: str = "", day_trade: bool = False, use_open: bool = False) -> Candle:
        c = self.prices.on_or_after(symbol, self.today - timedelta(days=days_ago))
        price = c.o if use_open else c.c
        self.add(user, account_id=acc.id, symbol=symbol, type=side, trade_date=c.t, quantity=Decimal(qty),
                 price=price, is_day_trade=day_trade, note=note)
        if side == "buy":
            self.first_buy[symbol] = min(self.first_buy.get(symbol, c.t), c.t)
        return c

    def held(self, user: User, acc: BrokerAccount, symbol: str, before: date) -> Decimal:
        inp = load_ledger_input(self.db, user, accounts=[acc])
        return shares_held(inp, acc.id, symbol, before)

    def dividends(self, user: User, acc: BrokerAccount, symbol: str, since: date, until: date | None = None,
                  cash: bool = True, stock: bool = True) -> None:
        """Record every dividend of ``symbol`` with an ex-date in (since, until] on its ex-date."""
        ans = self.pmd.dividends(symbol)
        last_day = self.prices.candles(symbol)[-1].t if self.prices.candles(symbol) else self.today
        for ev in sorted(ans.value, key=lambda e: e.ex_dividend_date or date.min):
            ex = ev.ex_dividend_date
            if ex is None or not (since < ex <= min(until or last_day, last_day)):
                continue
            if self.held(user, acc, symbol, ex) <= 0:
                continue
            if stock and ev.stock_dividend > 0:
                self.add(user, account_id=acc.id, symbol=symbol, type="stock_dividend", trade_date=ex,
                         price=ev.stock_dividend, note=f"配股 {ev.period}")
            if cash and ev.cash_dividend > 0:
                self.add(user, account_id=acc.id, symbol=symbol, type="cash_dividend", trade_date=ex,
                         price=ev.cash_dividend, note=f"現金股利 {ev.period}（以除息日入帳）")

    def splits(self, user: User, acc: BrokerAccount, symbol: str, since: date) -> None:
        for e in self.md.corporate_events(symbol):
            if e.kind == "split" and since < e.date <= self.today:
                self.add(user, account_id=acc.id, symbol=symbol, type="split", trade_date=e.date, quantity=e.ratio,
                         note=f"分割：1 股換 {e.ratio} 股")


def find_stock_dividend(md: MarketData, today: date) -> tuple[str, date, Decimal] | None:
    for sym in STOCK_DIVIDEND_CANDIDATES:
        if md.instrument(sym) is None:
            continue
        ans = md.dividends(sym)
        if ans.is_demo:
            continue
        for ev in sorted(ans.value, key=lambda e: e.ex_dividend_date or date.min, reverse=True):
            ex = ev.ex_dividend_date
            if ev.stock_dividend > 0 and ex and today - timedelta(days=660) < ex < today - timedelta(days=20):
                return sym, ex, ev.stock_dividend
    return None


def seed(db: Session, md: MarketData, today: date | None = None) -> dict:
    today = today or today_taipei()
    existing = db.scalar(select(User).where(User.email == DEMO_EMAIL))
    if existing is not None:
        db.delete(existing)
        db.commit()
    user = User(id=new_id("usr"), email=DEMO_EMAIL, display_name=DEMO_NAME, preferences=dict(DEFAULT_PREFERENCES))
    tw = BrokerAccount(id=new_id("acc"), user_id=user.id, name="永豐－一般", broker="永豐金證券", currency="TWD",
                       fee_rate=Decimal("0.001425"), fee_discount=Decimal("0.28"), min_fee=Decimal(20),
                       min_fee_odd_lot=Decimal(1), tracking_mode="transactions")
    us = BrokerAccount(id=new_id("acc"), user_id=user.id, name="國泰－複委託", broker="國泰證券", currency="USD",
                       fee_rate=Decimal("0.001"), fee_discount=Decimal(1), min_fee=Decimal(0),
                       min_fee_odd_lot=Decimal(0), tracking_mode="transactions")
    db.add(user)
    db.flush()  # no ORM relationship from User, so insert it before the accounts explicitly
    db.add_all([tw, us])
    db.commit()

    s = Seeder(db, md, today)
    start = today - timedelta(days=730)

    # -- Taiwan account ------------------------------------------------------------------------
    s.add(user, account_id=tw.id, type="deposit", trade_date=start, amount=Decimal(3_000_000), note="入金")
    s.trade(user, tw, "buy", "2330.TW", 700, 1000)
    s.trade(user, tw, "buy", "0050.TW", 690, 2000)
    s.trade(user, tw, "buy", "00878.TW", 680, 10000)
    # 2317: size the position so that its next annual cash dividend is ≥ NT$20,000 (NHI premium applies)
    hh_buy = s.prices.on_or_after("2317.TW", today - timedelta(days=650)).t
    future = [e for e in s.pmd.dividends("2317.TW").value
              if e.ex_dividend_date and e.ex_dividend_date > hh_buy and e.cash_dividend > 0]
    dps = min(future, key=lambda e: e.ex_dividend_date).cash_dividend if future else Decimal(5)
    hh_qty = max(5000, math.ceil(Decimal(21000) / dps / 1000) * 1000)
    s.trade(user, tw, "buy", "2317.TW", 650, hh_qty, note="鴻海（股利 ≥ 2 萬會扣二代健保）")
    s.trade(user, tw, "buy", "2454.TW", 600, 50, note="零股")
    s.trade(user, tw, "buy", "6488.TWO", 550, 1000)
    s.trade(user, tw, "buy", "2330.TW", 500, 35, note="零股")
    s.trade(user, tw, "buy", "2454.TW", 400, 30, note="零股")
    s.trade(user, tw, "sell", "00878.TW", 300, 4000, note="ETF 證交稅 0.1%")
    s.trade(user, tw, "buy", "2317.TW", 250, 1000, note="當沖買進", day_trade=True, use_open=True)
    s.trade(user, tw, "sell", "2317.TW", 250, 1000, note="當沖賣出（證交稅減半）", day_trade=True)
    s.trade(user, tw, "sell", "2330.TW", 120, 200)
    s.trade(user, tw, "buy", "0050.TW", 90, 150, note="零股定期定額")
    s.add(user, account_id=tw.id, type="withdrawal", trade_date=today - timedelta(days=60), amount=Decimal(200_000),
          note="出金")
    s.add(user, account_id=tw.id, type="interest", trade_date=today - timedelta(days=45), amount=Decimal(12),
          note="交割戶利息")

    stock_div = find_stock_dividend(md, today)
    if stock_div is not None:
        sym, ex, _ = stock_div
        s.trade(user, tw, "buy", sym, (today - ex).days + 45, 10000, note="為了示範配股")
        s.dividends(user, tw, sym, since=ex - timedelta(days=1), until=ex)
    else:
        log.warning("沒有找到真實的配股事件（FinMind 可能暫時無法使用），略過配股示範")

    for sym in ("2330.TW", "0050.TW", "00878.TW", "2317.TW", "2454.TW", "6488.TWO"):
        s.splits(user, tw, sym, s.first_buy[sym])
        s.dividends(user, tw, sym, since=s.first_buy[sym])

    # -- US account (複委託) -----------------------------------------------------------------------
    s.add(user, account_id=us.id, type="deposit", trade_date=start, amount=Decimal(25_000), currency="USD",
          note="入金（美元）")
    s.trade(user, us, "buy", "AAPL", 650, 15)
    s.trade(user, us, "buy", "NVDA", 600, 30)
    s.trade(user, us, "buy", "VOO", 500, 10)
    s.trade(user, us, "buy", "AAPL", 200, 5)
    s.trade(user, us, "sell", "NVDA", 100, 10)
    for sym in ("AAPL", "VOO"):
        s.dividends(user, us, sym, since=today - timedelta(days=365))

    # -- 定期定額: 0050, NT$5,000 on the 6th and the 19th ------------------------------------------------
    db.add(RecurringPlan(id=new_id("rcp"), user_id=user.id, account_id=tw.id, symbol="0050.TW", amount=Decimal(5000),
                         days_of_month=[6, 19], start_date=today - timedelta(days=120), end_date=None, active=True,
                         note="示範：每月 6 日、19 日扣款"))

    # -- watchlist ---------------------------------------------------------------------------------
    for sym in DEMO_WATCHLIST:
        resolved = md.resolve(sym)
        if resolved:
            db.add(WatchlistItem(id=new_id("wl"), user_id=user.id, symbol=resolved))
    db.commit()

    real = sorted({sym for sym in s.prices._candles if sym not in s.prices.demo_symbols})
    return {
        "user_id": user.id,
        "accounts": {"tw": tw.id, "us": us.id},
        "transactions": s.count,
        "real_price_symbols": real,
        "demo_price_symbols": sorted(s.prices.demo_symbols),
        "stock_dividend": stock_div[0] if stock_div else None,
        "policy": md.policy,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="建立示範使用者與兩年的交易紀錄")
    parser.add_argument("--no-migrate", action="store_true", help="不要先執行 alembic upgrade head")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if not args.no_migrate:
        run_migrations()
    md = get_market_data()
    with session_factory()() as db:
        result = seed(db, md)
    print(f"示範資料建立完成：{result['transactions']} 筆交易")
    print(f"  使用者：{DEMO_EMAIL}（{result['user_id']}）；定期定額：0050 每月 6、19 日 NT$5,000")
    if result["policy"] == "commercial":
        print("  DATA_POLICY=commercial：交易價格是虛構的示範帳本輸入；行情只用官方開放資料與自建存檔，")
        print("  存檔不足處顯示「資料累積中」（先執行 python -m forliosa.archive run 存一次官方資料）")
        return
    print(f"  真實價格：{', '.join(result['real_price_symbols']) or '無'}")
    print(f"  示範價格：{', '.join(result['demo_price_symbols']) or '無'}")
    if result["stock_dividend"]:
        print(f"  配股示範：{result['stock_dividend']}")
    us_only = [sym for sym in result["demo_price_symbols"] if market_of_symbol(sym) != "US"]
    if us_only:
        print("  注意：部分台股使用示範價格（真實資料源暫時無法取得），稍後可重新執行 seed。")


if __name__ == "__main__":
    main()
