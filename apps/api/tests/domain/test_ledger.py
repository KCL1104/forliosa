"""Hand-calculated ledger replay checks: cost methods, corporate actions, day trades, snapshots."""

from datetime import date
from decimal import Decimal as D

import pytest

from forliosa.domain.ledger import (
    CostMethod,
    LedgerError,
    LedgerTxn,
    OpeningPosition,
    TxnType,
    replay,
)

ACC = "acc_1"
_seq = iter(range(10_000))


def tx(type_, d, symbol="2330.TW", qty=0, price=0, amount=0, fee=0, tax=0, nhi=0, day_trade=False,
       currency="TWD", fx=1):
    n = next(_seq)
    return LedgerTxn(
        id=f"txn_{n}", account_id=ACC, symbol=symbol, type=TxnType(type_), trade_date=d,
        quantity=D(str(qty)), price=D(str(price)), amount=D(str(amount)), fee=D(str(fee)), tax=D(str(tax)),
        health_insurance=D(str(nhi)), currency=currency, is_day_trade=day_trade, fx_rate=D(str(fx)), seq=n,
    )


def two_buys_one_sell():
    return [
        tx("buy", date(2025, 1, 2), qty=1000, price=100, fee=40),  # cost 100,040
        tx("buy", date(2025, 2, 3), qty=1000, price=120, fee=48),  # cost 120,048
        # proceeds = 130,000 - 52 - 390 = 129,558
        tx("sell", date(2025, 3, 3), qty=1000, price=130, fee=52, tax=390),
    ]


def test_average_cost_realized_pnl():
    led = replay(two_buys_one_sell(), CostMethod.AVERAGE).ledger
    # avg = (100,040 + 120,048) / 2,000 = 110.044 ; cost of 1,000 sold = 110,044
    # realized = 129,558 - 110,044 = 19,514
    assert led.realized[0].pnl == D(19514)
    pos = led.positions[(ACC, "2330.TW")]
    assert pos.quantity == 1000 and pos.cost == D(110044) and pos.avg_cost == D("110.044")


def test_fifo_realized_pnl():
    led = replay(two_buys_one_sell(), CostMethod.FIFO).ledger
    # FIFO sells the first lot (cost 100,040): realized = 129,558 - 100,040 = 29,518
    assert led.realized[0].pnl == D(29518)
    pos = led.positions[(ACC, "2330.TW")]
    assert pos.quantity == 1000 and pos.cost == D(120048)


def test_fifo_partial_lots_and_odd_lots():
    txns = [
        tx("buy", date(2025, 1, 2), qty=35, price=1000, fee=1),  # 35,001 -> 1,000.0285714/share
        tx("buy", date(2025, 1, 3), qty=65, price=1100, fee=20),  # 71,520 -> 1,100.3076923/share
        # sell 50: FIFO takes 35 from lot1 (35,001) + 15 from lot2 (71,520 × 15/65 = 16,504.615...)
        tx("sell", date(2025, 1, 6), qty=50, price=1200, fee=17, tax=180),
    ]
    led = replay(txns, CostMethod.FIFO).ledger
    cost = D(35001) + D(71520) * 15 / 65
    proceeds = D(60000) - 17 - 180  # 59,803
    assert led.realized[0].pnl == proceeds - cost
    assert led.positions[(ACC, "2330.TW")].quantity == 50


def test_cash_dividend_net_of_nhi():
    txns = [
        tx("buy", date(2025, 1, 2), qty=5000, price=200, fee=399),
        # 5,000 × 5.0 = 25,000 ; NHI 2.11% = 527.5 -> 528 ; net 24,472
        tx("cash_dividend", date(2025, 7, 10), qty=5000, price=5, amount=25000, nhi=528),
    ]
    led = replay(txns).ledger
    assert led.income[0].net == D(24472)
    # Dividends never touch the cost basis
    assert led.positions[(ACC, "2330.TW")].cost == D(1000399)


def test_stock_dividend_adds_shares_cost_unchanged():
    txns = [
        tx("buy", date(2025, 1, 2), symbol="6488.TWO", qty=1000, price=50, fee=20),  # cost 50,020
        # 配股 1.5 元: 1,000 × 1.5 / 10 = 150 shares
        tx("stock_dividend", date(2025, 8, 1), symbol="6488.TWO", price="1.5"),
    ]
    led = replay(txns).ledger
    pos = led.positions[(ACC, "6488.TWO")]
    assert pos.quantity == 1150
    assert pos.cost == D(50020)
    # avg 50,020 / 1,150 = 43.4956...
    assert pos.avg_cost == D(50020) / D(1150)
    assert led.effective[txns[1].id].quantity == 150


def test_stock_dividend_fraction_paid_as_cash():
    txns = [
        tx("buy", date(2025, 1, 2), symbol="6488.TWO", qty=1234, price=50, fee=20),
        # 1,234 × 0.5 / 10 = 61.7 -> 61 shares + NT$7 cash in lieu (0.7 share × par 10)
        tx("stock_dividend", date(2025, 8, 1), symbol="6488.TWO", price="0.5"),
    ]
    led = replay(txns, CostMethod.FIFO).ledger
    assert led.positions[(ACC, "6488.TWO")].quantity == 1295
    assert led.income[0].net == D(7)


def test_split_scales_quantity_keeps_cost():
    txns = [
        tx("buy", date(2025, 3, 3), symbol="0050.TW", qty=1000, price="190", fee="200"),  # 190,200
        # 0050 1-to-4 split (2025-06-18): 1,000 -> 4,000 shares; avg 190.2 -> 47.55
        tx("split", date(2025, 6, 18), symbol="0050.TW", qty=4),
    ]
    for method in CostMethod:
        pos = replay(txns, method).ledger.positions[(ACC, "0050.TW")]
        assert pos.quantity == 4000
        assert pos.cost == D(190200)
        assert pos.avg_cost == D("47.55")


def test_capital_reduction_returns_cash_and_lowers_cost():
    txns = [
        tx("buy", date(2025, 1, 2), symbol="1101.TW", qty=2000, price=50),  # cost 100,000
        # 現金減資 30%: every share loses 0.3 share; NT$3 back per old share
        # shares 2,000 × 0.7 = 1,400 ; cash 2,000 × 3 = 6,000 ; cost 100,000 - 6,000 = 94,000
        tx("capital_reduction", date(2025, 9, 1), symbol="1101.TW", qty="0.3", price=3),
    ]
    res = replay(txns)
    pos = res.ledger.positions[(ACC, "1101.TW")]
    assert pos.quantity == 1400
    assert pos.cost == D(94000)
    assert res.flows_by_date[date(2025, 9, 1)].outflow == D(6000)
    assert res.ledger.realized == []


def test_capital_reduction_floor_and_loss_offset():
    txns = [
        tx("buy", date(2025, 1, 2), symbol="1101.TW", qty=1234, price=10),  # cost 12,340
        # 彌補虧損減資 (no cash back) 40%: 1,234 × 0.6 = 740.4 -> 740 shares, cost unchanged
        tx("capital_reduction", date(2025, 9, 1), symbol="1101.TW", qty="0.4"),
    ]
    pos = replay(txns, CostMethod.FIFO).ledger.positions[(ACC, "1101.TW")]
    assert pos.quantity == 740 and pos.cost == D(12340)


def test_day_trade_does_not_disturb_inventory_average():
    txns = [
        tx("buy", date(2025, 1, 2), symbol="2317.TW", qty=1000, price=100),  # inventory avg 100
        tx("buy", date(2025, 1, 6), symbol="2317.TW", qty=1000, price=110, fee=43, day_trade=True),
        # day-trade sell matched to the day-trade buy: (112,000 - 44 - 168) - 110,043 = 1,745
        tx("sell", date(2025, 1, 6), symbol="2317.TW", qty=1000, price=112, fee=44, tax=168, day_trade=True),
    ]
    for method in CostMethod:
        led = replay(txns, method).ledger
        assert led.realized[0].pnl == D(1745)
        pos = led.positions[(ACC, "2317.TW")]
        assert pos.quantity == 1000 and pos.avg_cost == D(100)


def test_holdings_snapshot_is_opening_position():
    opening = OpeningPosition(ACC, "2330.TW", date(2026, 1, 5), D(1500), D("612.5"))
    txns = [tx("sell", date(2026, 3, 2), qty=500, price=1000, fee=142, tax=1500)]
    led = replay(txns, openings=[opening]).ledger
    # cost of 500 = 612.5 × 500 = 306,250 ; proceeds 500,000 - 142 - 1,500 = 498,358 ; pnl 192,108
    assert led.realized[0].pnl == D(192108)
    assert led.positions[(ACC, "2330.TW")].quantity == 1000


def test_strict_mode_rejects_overselling():
    txns = [tx("buy", date(2025, 1, 2), qty=100, price=10), tx("sell", date(2025, 1, 3), qty=200, price=10)]
    with pytest.raises(LedgerError):
        replay(txns, strict=True)
    led = replay(txns).ledger
    assert led.warnings and led.positions[(ACC, "2330.TW")].quantity == 0


def test_dividend_on_ex_date_belongs_to_previous_holders():
    # A buy on the ex-date is processed after the dividend/stock-dividend of that date.
    txns = [
        tx("buy", date(2025, 1, 2), symbol="6488.TWO", qty=1000, price=50),
        tx("buy", date(2025, 8, 1), symbol="6488.TWO", qty=1000, price=48),
        tx("stock_dividend", date(2025, 8, 1), symbol="6488.TWO", price="1"),  # 1,000 × 1/10 = 100
    ]
    led = replay(txns).ledger
    assert led.positions[(ACC, "6488.TWO")].quantity == 2100


def test_usd_position_tracks_twd_cost_at_trade_fx():
    txns = [
        tx("buy", date(2025, 1, 2), symbol="AAPL", qty=10, price=200, fee=0, currency="USD", fx="32.5"),
        tx("buy", date(2025, 2, 3), symbol="AAPL", qty=10, price=220, fee=0, currency="USD", fx="33"),
        # avg USD 210 ; TWD cost = 65,000 + 72,600 = 137,600 -> 6,880 per share
        tx("sell", date(2025, 3, 3), symbol="AAPL", qty=10, price=230, currency="USD", fx="32"),
    ]
    led = replay(txns).ledger
    r = led.realized[0]
    assert r.pnl == D(200)  # 2,300 - 2,100 USD
    # TWD: 2,300 × 32 = 73,600 - 68,800 = 4,800 (includes the FX effect)
    assert r.pnl_twd == D(4800)


def test_cash_balance_tracking():
    txns = [
        tx("deposit", date(2025, 1, 2), symbol=None, amount=500000),
        tx("buy", date(2025, 1, 3), qty=1000, price=100, fee=40),
        tx("interest", date(2025, 6, 21), symbol=None, amount=12),
        tx("withdrawal", date(2025, 7, 1), symbol=None, amount=100000),
    ]
    led = replay(txns).ledger
    # 500,000 - 100,040 + 12 - 100,000 = 299,972
    assert led.cash[(ACC, "TWD")] == D(299972)


def test_non_strict_oversell_with_nothing_held_books_no_gain():
    led = replay([tx("sell", date(2025, 1, 3), qty=100, price=10)]).ledger
    assert led.realized[0].pnl == 0 and led.warnings
