"""Synthetic data for the asset-composition prototype (``docs/proposals/asset-composition.md``): a five-year price
archive and ledgers like the ones an imported holdings screenshot with estimated buy dates produces. No network.

* Prices: a seeded random walk per symbol with open / high / low / close. Days before ``archive_start`` are stored as
  the history backfill (``yahoo-history``), from it on as official closes (``twse-openapi`` / ``tpex-openapi``), as in
  production (the archive began 2026-11-12, the backfill holds five years before it). US symbols get Databento rows
  (``databento-equs``) from 2024-07-01. USD/TWD for every day.
* Ledgers: :func:`five_year_ledger` — 17 Taiwan stocks and 3 US stocks (20 holdings), each bought over the five years
  with later buys, a sell and yearly cash dividends; :func:`imported_today_ledger` — the same 20 holdings all bought
  on one day (what 匯入庫存 wrote before buy dates were estimated: no history).

Used by the opt-in cost benchmark (``tests/test_composition_cost.py``) and the asset-composition tests.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

from sqlalchemy import insert
from sqlalchemy.orm import Session

from forliosa.ids import new_id
from forliosa.models import (
    BrokerAccount,
    DatasetStatus,
    FxRate,
    Group,
    GroupMember,
    GroupShareSetting,
    PriceDaily,
    Transaction,
    User,
)
from forliosa.timeutil import last_tw_trading_day, today_taipei, tw_trading_days

# 17 Taiwan stocks the demo catalogue knows (0050 left out: the benchmark, and a 1-to-4 split in 2025 the synthetic
# ledger would have to book) and 3 US stocks: 20 holdings
TW_HOLDINGS = ["2330.TW", "2317.TW", "2454.TW", "2303.TW", "2308.TW", "2382.TW", "2412.TW", "2881.TW", "2882.TW",
               "3711.TW", "6488.TWO", "0056.TW", "00878.TW", "006208.TW", "00919.TW", "00929.TW", "00713.TW"]
US_HOLDINGS = ["VOO", "AAPL", "NVDA"]
BENCHMARK = "0050.TW"
US_FROM = date(2024, 7, 1)
ARCHIVE_SESSIONS = 6  # official closes for the last few sessions only, as in production (archive began 2026-11-12)


@dataclass
class Archive:
    days: list[date]  # Taiwan trading days, oldest first
    archive_start: date  # first official close
    us_days: list[date]
    bars: dict[str, dict[date, tuple[D, D, D, D]]] = field(default_factory=dict)  # as traded: (o, h, l, c)

    def close(self, symbol: str, d: date) -> D:
        return self.bars[symbol][d][3]


def _walk(symbol: str, days: list[date], seed: int) -> dict[date, tuple[D, D, D, D]]:
    rng = random.Random(f"{symbol}-{seed}")
    px = 20 + rng.random() * 480
    out: dict[date, tuple[D, D, D, D]] = {}
    for d in days:
        o = px * math.exp(rng.gauss(0, 0.006))
        c = px * math.exp(rng.gauss(0.0002, 0.018))
        h = max(o, c) * (1 + rng.random() * 0.012)
        lo = min(o, c) * (1 - rng.random() * 0.012)
        out[d] = tuple(D(str(round(x, 2))) for x in (o, h, lo, c))  # type: ignore[assignment]
        px = c
    return out


def end_day() -> date:
    """The last close in the archive: the trading day before today (Taipei)."""
    return last_tw_trading_day(today_taipei() - timedelta(days=1))


def build_archive(engine, years: int = 5, seed: int = 1, symbols: list[str] | None = None) -> Archive:
    """Store ``years`` of daily bars for the holdings and the benchmark (``symbols``: instead of the default set)."""
    end = end_day()
    days = tw_trading_days(end - timedelta(days=366 * years), end)
    us_days = [d for d in days if d >= US_FROM]  # (US sessions approximated by the Taiwan calendar)
    archive = Archive(days, days[-ARCHIVE_SESSIONS], us_days)
    tw = [s for s in (symbols or [*TW_HOLDINGS, BENCHMARK]) if not s.isalpha()]
    us = [s for s in (symbols or US_HOLDINGS) if s.isalpha()]
    rows: list[dict] = []
    for s in tw:
        archive.bars[s] = _walk(s, days, seed)
        official = "tpex-openapi" if s.endswith(".TWO") else "twse-openapi"
        for d, (o, h, lo, c) in archive.bars[s].items():
            rows.append({"symbol": s, "date": d, "open": o, "high": h, "low": lo, "close": c, "volume": 1_000_000,
                         "source": official if d >= archive.archive_start else "yahoo-history"})
    for s in us:
        archive.bars[s] = _walk(s, us_days, seed)
        for d, (o, h, lo, c) in archive.bars[s].items():
            rows.append({"symbol": s, "date": d, "open": o, "high": h, "low": lo, "close": c, "volume": 5_000_000,
                         "source": "databento-equs"})
    with Session(engine) as db:
        for i in range(0, len(rows), 5000):
            db.execute(insert(PriceDaily), rows[i:i + 5000])
        db.execute(insert(FxRate), [{"pair": "USDTWD", "date": d, "rate": D("30.5") + D(i % 150) / 100,
                                     "source": "cbc-opendata"} for i, d in enumerate(days)])
        now = datetime.now(UTC)
        for key in ("twse-openapi/price", "tpex-openapi/price"):
            db.merge(DatasetStatus(key=key, data_date=end, rows=1, fetched_at=now))
        db.commit()
    return archive


# -- ledgers ---------------------------------------------------------------------------------------------------------
def _txn(user_id: str, account_id: str, symbol: str | None, kind: str, d: date, qty: D, price: D, currency: str,
         seq: int, **extra) -> dict:
    amount = extra.pop("amount", qty * price)
    created = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=seq)
    return {"id": new_id("txn"), "user_id": user_id, "account_id": account_id, "symbol": symbol, "type": kind,
            "trade_date": d, "quantity": qty, "price": price, "amount": amount, "fee": extra.pop("fee", D(0)),
            "tax": extra.pop("tax", D(0)), "health_insurance": D(0), "currency": currency, "is_day_trade": False,
            "note": "", "source": extra.pop("source", "manual"), "created_at": created, "updated_at": created,
            **extra}


def five_year_ledger(archive: Archive, user_id: str, tw_account: str, us_account: str, seed: int) -> list[dict]:
    """17 Taiwan holdings bought in the first year and added to three times, one sell each, a cash dividend every July;
    3 US holdings bought after 2024-07-01 and added to once. Prices are the day's close as traded."""
    rng = random.Random(f"ledger-{seed}")
    out: list[dict] = []
    days = archive.days
    n = len(days)
    seq = 0
    for s in TW_HOLDINGS:
        buys = sorted([rng.randrange(0, 200), *rng.sample(range(220, n - 10), 3)])
        sell = rng.randrange(buys[1] + 1, n - 5)
        events: list[tuple[int, str, D]] = [(i, "buy", D(1000 * rng.randint(1, 5))) for i in buys]
        events.append((sell, "sell", D(1000)))
        for year in range(days[0].year, days[-1].year + 1):
            july = next((i for i, d in enumerate(days) if d >= date(year, 7, 15)), None)
            if july is not None and july > buys[0]:
                events.append((july, "div", D(0)))
        held = D(0)
        for i, kind, qty in sorted(events):
            d = days[i]
            px = archive.close(s, d)
            seq += 1
            if kind == "buy":
                held += qty
                out.append(_txn(user_id, tw_account, s, "buy", d, qty, px, "TWD", seq,
                                fee=(qty * px * D("0.001425")).quantize(D(1))))
            elif kind == "sell" and held >= qty:
                held -= qty
                out.append(_txn(user_id, tw_account, s, "sell", d, qty, px, "TWD", seq,
                                fee=(qty * px * D("0.001425")).quantize(D(1)),
                                tax=(qty * px * D("0.003")).quantize(D(1))))
            elif kind == "div" and held > 0:
                per = (px * D("0.03")).quantize(D("0.01"))
                out.append(_txn(user_id, tw_account, s, "cash_dividend", d, held, per, "TWD", seq,
                                amount=(held * per).quantize(D(1))))
    us_days = [i for i, d in enumerate(days) if d >= US_FROM]
    for s in US_HOLDINGS:
        for i in sorted(rng.sample(us_days[:-10], 2)):
            seq += 1
            out.append(_txn(user_id, us_account, s, "buy", days[i], D(rng.randint(5, 30)), archive.close(s, days[i]),
                            "USD", seq))
    return out


def imported_today_ledger(archive: Archive, user_id: str, tw_account: str, us_account: str) -> list[dict]:
    """The same 20 holdings bought on the last close (匯入庫存 before buy dates were estimated: no history)."""
    d = archive.days[-1]
    out = [_txn(user_id, tw_account, s, "buy", d, D(3000), archive.close(s, d), "TWD", i, source="import")
           for i, s in enumerate(TW_HOLDINGS)]
    out += [_txn(user_id, us_account, s, "buy", d, D(10), archive.close(s, d), "USD", 100 + i, source="import")
            for i, s in enumerate(US_HOLDINGS)]
    return out


def add_accounts(db: Session, user_id: str) -> tuple[str, str]:
    tw = BrokerAccount(id=new_id("acc"), user_id=user_id, name="永豐", broker="", currency="TWD",
                       fee_rate=D("0.001425"), fee_discount=D(1), min_fee=D(20), min_fee_odd_lot=D(1))
    us = BrokerAccount(id=new_id("acc"), user_id=user_id, name="複委託", broker="", currency="USD",
                       fee_rate=D(0), fee_discount=D(1), min_fee=D(0), min_fee_odd_lot=D(0))
    db.add_all([tw, us])
    db.flush()
    return tw.id, us.id


def add_user(db: Session, n: int) -> str:
    u = User(id=new_id("usr"), email=f"member{n}@forliosa.local", display_name=f"成員{n}", preferences={})
    db.add(u)
    db.flush()
    return u.id


def store_ledger(engine, rows: list[dict]) -> None:
    with Session(engine) as db:
        for i in range(0, len(rows), 2000):
            db.execute(insert(Transaction), rows[i:i + 2000])
        db.commit()


def build_group(engine, archive: Archive, owner_id: str, members: int = 50, five_years: bool = True,
                first_member: int = 1) -> str:
    """A group of ``members`` (the owner included) sharing their returns; every other member has a five-year ledger
    of their own (another seed), or with ``five_years=False`` the 20 holdings bought on the last close."""
    with Session(engine) as db:
        gid = new_id("grp")
        db.add(Group(id=gid, name="五十人", ranking_enabled=True, grandfathered_member_cap=members))
        db.flush()
        db.add(GroupMember(group_id=gid, user_id=owner_id, role="owner"))
        db.flush()
        db.add(GroupShareSetting(group_id=gid, user_id=owner_id, returns=True))
        rows: list[dict] = []
        for n in range(first_member, first_member + members - 1):
            uid = add_user(db, n)
            tw, us = add_accounts(db, uid)
            db.add(GroupMember(group_id=gid, user_id=uid, role="member",
                               joined_at=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=n)))
            db.flush()
            db.add(GroupShareSetting(group_id=gid, user_id=uid, returns=True))
            rows += (five_year_ledger(archive, uid, tw, us, seed=1000 + n) if five_years
                     else imported_today_ledger(archive, uid, tw, us))
        db.commit()
    store_ledger(engine, rows)
    return gid
