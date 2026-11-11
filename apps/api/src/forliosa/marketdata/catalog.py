"""Built-in instruments (Taiwan ETFs, demo US tickers, offline fallback stocks) and demo parameters.

Anchor prices are only used by the demo provider when no real latest close is available
(ETFs are not in shioaji-data's ``market/daily.json``; US tickers are fully synthetic).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal as D

from forliosa.marketdata.base import InstrumentInfo


@dataclass(frozen=True)
class DemoSpec:
    anchor: D  # fallback latest close
    drift: float = 0.06  # annualized
    vol: float = 0.28  # annualized
    div_months: tuple[int, ...] = (7,)
    div_day: int = 15
    div_yield: float = 0.025  # per distribution, fraction of the previous close
    stock_dividends: dict[int, D] = field(default_factory=dict)  # year -> NT$ per share (配股元)
    splits: tuple[tuple[date, D], ...] = ()
    base_volume: int = 3_000_000
    pay_lag_days: int = 25
    target_per: float = 18.0
    target_pbr: float = 2.2
    eps_growth: float = 0.08
    # Approximate unadjusted price levels the synthetic path is bent through (log-linear bridge),
    # so demo charts look plausible. Not real data.
    waypoints: tuple[tuple[str, str], ...] = ()


def _tw(code: str, name: str, market: str, type_: str, industry: str, aliases: tuple[str, ...] = ()) -> InstrumentInfo:
    suffix = ".TWO" if market == "TPEX" else ".TW"
    return InstrumentInfo(f"{code}{suffix}", code, name, market, type_, "TWD", industry, aliases=aliases,
                          source="built-in")


def _us(code: str, name: str, type_: str, industry: str, aliases: tuple[str, ...]) -> InstrumentInfo:
    return InstrumentInfo(code, code, name, "US", type_, "USD", industry, aliases=aliases, source="built-in")


TW_ETFS: list[InstrumentInfo] = [
    _tw("0050", "元大台灣50", "TWSE", "etf", "ETF", ("台灣50",)),
    _tw("0056", "元大高股息", "TWSE", "etf", "ETF", ("高股息",)),
    _tw("00878", "國泰永續高股息", "TWSE", "etf", "ETF", ("國泰高股息",)),
    _tw("006208", "富邦台50", "TWSE", "etf", "ETF", ("富邦台灣50",)),
    _tw("00919", "群益台灣精選高息", "TWSE", "etf", "ETF", ("群益精選高息",)),
    _tw("00929", "復華台灣科技優息", "TWSE", "etf", "ETF", ("科技優息",)),
    _tw("00713", "元大台灣高息低波", "TWSE", "etf", "ETF", ("高息低波",)),
]

US_TICKERS: list[InstrumentInfo] = [
    _us("AAPL", "Apple", "stock", "科技硬體", ("蘋果", "Apple Inc.")),
    _us("NVDA", "NVIDIA", "stock", "半導體", ("輝達", "NVIDIA Corporation")),
    _us("VOO", "Vanguard S&P 500 ETF", "etf", "ETF", ("標普500", "S&P 500")),
    _us("QQQ", "Invesco QQQ Trust", "etf", "ETF", ("那斯達克100", "Nasdaq 100")),
]

# Offline fallback when shioaji-data is unreachable (tests, CI): a few large caps.
FALLBACK_TW_STOCKS: list[InstrumentInfo] = [
    _tw("2330", "台積電", "TWSE", "stock", "半導體業", ("TSMC",)),
    _tw("2317", "鴻海", "TWSE", "stock", "其他電子業", ("Foxconn",)),
    _tw("2454", "聯發科", "TWSE", "stock", "半導體業", ("MediaTek",)),
    _tw("2303", "聯電", "TWSE", "stock", "半導體業", ("UMC",)),
    _tw("2308", "台達電", "TWSE", "stock", "電子零組件業", ("Delta",)),
    _tw("2412", "中華電", "TWSE", "stock", "通信網路業", ("Chunghwa Telecom",)),
    _tw("2881", "富邦金", "TWSE", "stock", "金融保險業", ()),
    _tw("2882", "國泰金", "TWSE", "stock", "金融保險業", ()),
    _tw("3711", "日月光投控", "TWSE", "stock", "半導體業", ("ASE",)),
    _tw("6488", "環球晶", "TPEX", "stock", "半導體業", ("GlobalWafers",)),
]

ETF_CODES = frozenset(i.code for i in TW_ETFS)

_Q = (3, 6, 9, 12)

DEMO_SPECS: dict[str, DemoSpec] = {
    # Taiwan stocks (anchors are overridden by the real latest close when available)
    "2330.TW": DemoSpec(D("2395"),
                        waypoints=(("2018-01-02", "230"), ("2020-03-19", "250"), ("2021-01-21", "670"), ("2022-10-25", "370"), ("2024-07-11", "1080"), ("2025-04-09", "780"), ("2025-06-02", "950"), ("2025-11-03", "1500"), ("2026-09-01", "2440"),), drift=0.40, vol=0.30, div_months=_Q, div_day=17, div_yield=0.0028,
                        base_volume=30_000_000, target_per=24, target_pbr=6.5, eps_growth=0.30),
    "2317.TW": DemoSpec(D("242"),
                        waypoints=(("2018-01-02", "90"), ("2020-03-19", "70"), ("2024-07-10", "230"), ("2025-04-09", "130"), ("2025-11-03", "220"),), drift=0.15, vol=0.32, div_months=(7,), div_day=24, div_yield=0.028,
                        base_volume=60_000_000, target_per=16, target_pbr=1.9),
    "2454.TW": DemoSpec(D("3990"),
                        waypoints=(("2018-01-02", "300"), ("2020-03-19", "300"), ("2021-12-01", "1100"), ("2022-10-25", "520"), ("2024-07-11", "1400"), ("2025-04-09", "1200"), ("2025-11-03", "1700"),), drift=0.35, vol=0.38, div_months=(1, 7), div_day=9, div_yield=0.022,
                        base_volume=5_000_000, target_per=26, target_pbr=7.0, eps_growth=0.20),
    "6488.TWO": DemoSpec(D("635"),
                        waypoints=(("2018-01-02", "330"), ("2021-01-20", "900"), ("2022-10-25", "380"), ("2024-01-15", "600"), ("2025-04-09", "280"), ("2025-11-03", "420"),), drift=0.0, vol=0.40, div_months=(6,), div_day=23, div_yield=0.018,
                         stock_dividends={2025: D("0.5")}, base_volume=2_000_000, target_per=22, target_pbr=2.4),
    "2303.TW": DemoSpec(D("51.6"), drift=0.02, vol=0.28, div_months=(7,), div_day=10, div_yield=0.055),
    "2308.TW": DemoSpec(D("1385"), drift=0.30, vol=0.32, div_months=(7,), div_day=1, div_yield=0.012),
    "2412.TW": DemoSpec(D("132.5"), drift=0.03, vol=0.10, div_months=(7,), div_day=17, div_yield=0.037),
    "2881.TW": DemoSpec(D("92.3"), drift=0.08, vol=0.22, div_months=(7,), div_day=3, div_yield=0.045),
    "2882.TW": DemoSpec(D("71.8"), drift=0.08, vol=0.22, div_months=(7,), div_day=8, div_yield=0.04),
    "3711.TW": DemoSpec(D("245"), drift=0.15, vol=0.30, div_months=(7,), div_day=4, div_yield=0.03),
    # Taiwan ETFs (no real price source in this environment)
    "0050.TW": DemoSpec(D("88.65"),
                        waypoints=(("2018-01-02", "82"), ("2020-03-19", "70"), ("2021-12-01", "145"), ("2022-10-25", "100"), ("2024-07-11", "200"), ("2025-04-09", "150"), ("2025-06-17", "190"), ("2025-11-03", "62"),), drift=0.25, vol=0.20, div_months=(1, 7), div_day=22, div_yield=0.012,
                        splits=((date(2025, 6, 18), D(4)),), base_volume=25_000_000),
    "006208.TW": DemoSpec(D("204.5"),
                        waypoints=(("2018-01-02", "50"), ("2024-07-11", "115"), ("2025-04-09", "86"), ("2025-11-03", "140"),), drift=0.25, vol=0.20, div_months=(7, 11), div_day=18, div_yield=0.015,
                          base_volume=4_000_000),
    "0056.TW": DemoSpec(D("39.5"),
                        waypoints=(("2018-01-02", "25"), ("2024-06-17", "39"), ("2025-04-09", "31"),), drift=0.05, vol=0.14, div_months=(1, 4, 7, 10), div_day=21, div_yield=0.02,
                        base_volume=20_000_000),
    "00878.TW": DemoSpec(D("22.85"),
                        waypoints=(("2020-07-20", "15"), ("2024-07-11", "23.5"), ("2025-04-09", "19"),), drift=0.05, vol=0.13, div_months=(2, 5, 8, 11), div_day=18,
                         div_yield=0.017, base_volume=40_000_000),
    "00919.TW": DemoSpec(D("23.6"),
                        waypoints=(("2023-01-03", "20"), ("2024-07-11", "26"), ("2025-04-09", "20"),), drift=0.05, vol=0.15, div_months=_Q, div_day=16, div_yield=0.026,
                         base_volume=30_000_000),
    "00929.TW": DemoSpec(D("19.9"),
                        waypoints=(("2023-06-09", "15"), ("2024-07-11", "20"), ("2025-04-09", "16"),), drift=0.08, vol=0.17, div_months=tuple(range(1, 13)), div_day=17,
                         div_yield=0.006, base_volume=25_000_000),
    "00713.TW": DemoSpec(D("53.2"),
                        waypoints=(("2018-01-02", "30"), ("2024-07-11", "56"), ("2025-04-09", "48"),), drift=0.04, vol=0.12, div_months=_Q, div_day=18, div_yield=0.02,
                         base_volume=3_000_000),
    # US (fully synthetic)
    "AAPL": DemoSpec(D("285.40"),
                        waypoints=(("2018-01-02", "43"), ("2020-03-23", "61"), ("2022-01-03", "180"), ("2023-01-05", "125"), ("2024-12-26", "255"), ("2025-04-08", "172"),), drift=0.12, vol=0.27, div_months=(2, 5, 8, 11), div_day=10,
                     div_yield=0.0011, base_volume=50_000_000, pay_lag_days=4, target_per=32, target_pbr=45),
    "NVDA": DemoSpec(D("198.60"),
                        waypoints=(("2018-01-02", "5"), ("2022-10-13", "11"), ("2023-12-01", "47"), ("2024-06-18", "135"), ("2025-04-04", "94"),), drift=0.35, vol=0.50, div_months=_Q, div_day=5, div_yield=0.0002,
                     base_volume=200_000_000, pay_lag_days=21, target_per=45, target_pbr=40, eps_growth=0.5),
    "VOO": DemoSpec(D("642.10"),
                        waypoints=(("2018-01-02", "250"), ("2020-03-23", "200"), ("2022-01-03", "440"), ("2022-10-12", "330"), ("2024-12-06", "555"), ("2025-04-08", "450"),), drift=0.12, vol=0.17, div_months=_Q, div_day=24, div_yield=0.0032,
                    base_volume=5_000_000, pay_lag_days=4),
    "QQQ": DemoSpec(D("668.30"),
                        waypoints=(("2018-01-02", "155"), ("2020-03-16", "170"), ("2021-12-27", "400"), ("2022-12-28", "260"), ("2024-12-16", "535"), ("2025-04-08", "420"),), drift=0.15, vol=0.22, div_months=_Q, div_day=22, div_yield=0.0014,
                    base_volume=40_000_000, pay_lag_days=7),
}


def default_spec(symbol: str, anchor: D, seed: int) -> DemoSpec:
    """Parameters for any other Taiwan stock: mildly varied by a stable per-symbol seed."""
    return DemoSpec(
        anchor=anchor,
        drift=0.02 + (seed % 9) / 100,
        vol=0.25 + (seed % 15) / 100,
        div_months=(7,) if seed % 3 else (8,),
        div_day=5 + seed % 20,
        div_yield=0.015 + (seed % 30) / 1000,
        base_volume=1_000_000 + (seed % 50) * 100_000,
        target_per=12 + seed % 14,
        target_pbr=1.2 + (seed % 20) / 10,
    )
