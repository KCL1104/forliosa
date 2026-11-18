"""Built-in instruments (Taiwan ETFs, demo US tickers, offline fallback stocks) and demo parameters.

Anchor prices are only used by the demo provider when no real latest close is available
(offline/tests; US tickers are always synthetic). Taiwan anchors are the real closes observed on
2026-11-10/11 (TWSE OpenAPI STOCK_DAY_ALL, MIS) so offline demo charts end at plausible levels.
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
    # The market page's US row (forliosa.us_prices.MARKET_ETFS): typed as ETFs here (SEC's ticker list calls every
    # listing a stock), named as the funds they are
    _us("SPY", "SPDR S&P 500 ETF Trust", "etf", "ETF", ("標普500", "S&P 500")),
    _us("DIA", "SPDR Dow Jones Industrial Average ETF Trust", "etf", "ETF", ("道瓊", "Dow Jones")),
    _us("ONEQ", "Fidelity Nasdaq Composite Index ETF", "etf", "ETF", ("那斯達克綜合", "Nasdaq Composite")),
    # 市場報告 (2026-11-17; forliosa.us_prices.REPORT_US_SYMBOLS): the semiconductor ETF, typed as the ETF it is (SEC's
    # ticker list calls every listing a stock). TSMC's ADR (TSM) is fetched too but not listed here: SEC's ticker list
    # already has it, and a built-in row would rank it above 台積電 for 「TS」 or put it into 「台積」 searches; the
    # reports label it 台積電 ADR themselves.
    _us("SMH", "VanEck Semiconductor ETF", "etf", "ETF", ("VanEck Semiconductor",)),
]
US_ETF_CODES = frozenset(i.code for i in US_TICKERS if i.type == "etf")

# Offline fallback when shioaji-data is unreachable (tests, CI): a few large caps.
FALLBACK_TW_STOCKS: list[InstrumentInfo] = [
    _tw("2330", "台積電", "TWSE", "stock", "半導體業", ("TSMC",)),
    _tw("2317", "鴻海", "TWSE", "stock", "其他電子業", ("Foxconn",)),
    _tw("2454", "聯發科", "TWSE", "stock", "半導體業", ("MediaTek",)),
    _tw("2303", "聯電", "TWSE", "stock", "半導體業", ("UMC",)),
    _tw("2308", "台達電", "TWSE", "stock", "電子零組件業", ("Delta",)),
    _tw("2382", "廣達", "TWSE", "stock", "電腦及週邊設備業", ("Quanta",)),
    _tw("2412", "中華電", "TWSE", "stock", "通信網路業", ("Chunghwa Telecom",)),
    _tw("2881", "富邦金", "TWSE", "stock", "金融保險業", ()),
    _tw("2882", "國泰金", "TWSE", "stock", "金融保險業", ()),
    _tw("3711", "日月光投控", "TWSE", "stock", "半導體業", ("ASE",)),
    _tw("6488", "環球晶", "TPEX", "stock", "半導體業", ("GlobalWafers",)),
]

ETF_CODES = frozenset(i.code for i in TW_ETFS)

# Real corporate actions the ledger/benchmark must know about (reference data, not demo).
# symbol -> ((first trading day at the new price, new shares per old share), ...): a split's ratio is > 1, a reverse
# split's is 1/n (D(1) / 7: 7 old units become 1). The day is the first one *at the new price* (the day trading
# resumed), never the first halt day that data vendors date it by. Each entry was checked against at least two
# independent public sources (product owner 2026-11-18; working notes in CONTRACT_NOTES.md, 2026-11-18 已知分割).
# Capital reductions (減資) are listed by their share ratio, so every consumer applies them like a split; the cash
# returned per old share is in KNOWN_REDUCTIONS below — see services.reference_close for why a reference close is
# multiplied back only where the stored Yahoo rows really fold the ratio in.
KNOWN_SPLITS: dict[str, tuple[tuple[date, D], ...]] = {
    # -- ETFs --------------------------------------------------------------------------------------------------------
    # 00632R 元大台灣50反1: reverse 7 -> 1 (0.14285714); halted 2024-12-04..12-10, resumed 2024-12-11 (ref 22.96).
    # https://money.udn.com/money/story/5618/8416984 https://udn.com/news/story/123006/8400559
    # https://ec.ltn.com.tw/article/breakingnews/4882439 https://www.ctee.com.tw/news/20241107700261-439901
    # https://news.cnyes.com/news/id/5796991 https://www.pinview.com.tw/News/34604.html
    # https://stockevents.app/en/stock/00632R.TW
    "00632R.TW": ((date(2024, 12, 11), D(1) / 7),),
    # 00676R 富邦臺灣加權反1: reverse 6 -> 1 (0.16666667); halted 2025-02-12..02-18, resumed 2025-02-19 (2.04 -> 12.23).
    # https://www.cna.com.tw/news/afe/202412260204.aspx https://udn.com/news/story/123006/8556552
    # https://www.ftvnews.com.tw/news/detail/2024C26W0433 https://stockevents.app/en/stock/00676R.TW
    "00676R.TW": ((date(2025, 2, 19), D(1) / 6),),
    # 00663L 國泰臺灣加權正2: 1 -> 7; last trade 2025-06-03 (170.15), resumed 2025-06-11 (ref 24.3).
    # https://money.udn.com/money/story/5618/8800927 https://news.cnyes.com/news/id/5998105
    # https://www.ctee.com.tw/news/20250617700229-430403 https://wantrich.chinatimes.com/news/20250528900388-420101
    # https://news.cnyes.com/news/id/5946710
    "00663L.TW": ((date(2025, 6, 11), D(7)),),
    # 0050 元大台灣50: 1 -> 4; last trade 2025-06-10 (188.65), halted 06-11..06-17, resumed 2025-06-18 (ref 47.16).
    # https://technews.tw/?p=1396416 https://finance.technews.tw/2025/06/17/net-value-reference-price/
    # https://www.bnext.com.tw/article/82332/0050-etf-split https://news.tvbs.com.tw/money/2784131
    # https://focustaiwan.tw/business/202506180028 https://wantrich.chinatimes.com/news/20250619900355-420101
    # https://www.ctee.com.tw/news/20250424701166-430403
    "0050.TW": ((date(2025, 6, 18), D(4)),),
    # 00673R 期元大S&P原油反1: reverse 4 -> 1 (0.25); last trade 2025-10-14 (7.02), resumed 2025-10-22 (ref 28.08).
    # https://money.udn.com/money/story/5607/9010950 https://money.udn.com/money/story/5618/9085040
    # https://www.ctee.com.tw/news/20250917700521-430201 https://wantrich.chinatimes.com/news/20251022900430-420401
    # https://tw.stock.yahoo.com/news/00673r-00706l%E9%80%B2%E8%A1%8C%E5%8F%8D%E5%88%86%E5%89%B2-10-14%E6%9C%80%E5%BE%8C%E4%BA%A4%E6%98%93-10-070653429.html
    # https://www.yuantafunds.com/active/ETF00706L/assets/pdf/%E3%80%90%E5%95%8F%E7%AD%94%E9%9B%86%E3%80%9100673R%E3%80%8100706L%E5%8F%8D%E5%88%86%E5%89%B2.pdf
    "00673R.TW": ((date(2025, 10, 22), D(1) / 4),),
    # 00706L 期元大S&P日圓正2: reverse 4 -> 1 (0.25); last trade 2025-10-14 (5.54), resumed 2025-10-22 (ref 22.16).
    # https://money.udn.com/money/story/5618/9085040 https://money.udn.com/money/amp/story/5607/9010950
    # https://wantrich.chinatimes.com/news/20251022900430-420401 https://www.peoplenews.tw/?p=28075
    "00706L.TW": ((date(2025, 10, 22), D(1) / 4),),
    # 0052 富邦科技: 1 -> 7; last trade 2025-11-18 (245.3), halted 11-19..11-25, resumed 2025-11-26 (ref 35.04).
    # https://money.udn.com/money/amp/story/5607/9060299 https://finance.ettoday.net/news/3073341
    # https://finance.ettoday.net/news/3069412 https://newtalk.tw/news/view/2025-11-25/1006440
    # https://uanalyze.com.tw/articles/1679940008 https://news.cnyes.com/news/id/6237784
    # https://wantrich.chinatimes.com/news/20250808900566-420101
    "0052.TW": ((date(2025, 11, 26), D(7)),),
    # 00715L 期街口布蘭特正2: reverse 2 -> 1 (0.5); last trade 2025-12-02, halted 12-03..12-09, relisted 2025-12-10.
    # https://wantrich.chinatimes.com/news/20251106900731-420101 https://news.cnyes.com/news/id/6129589
    # https://tw.stock.yahoo.com/news/00715l-12-2%E5%8F%8D%E5%88%86%E5%89%B2%E5%89%8D%E6%9C%80%E5%BE%8C%E4%BA%A4%E6%98%93-201000964.html
    # https://udn.com/news/story/123006/8969932
    "00715L.TW": ((date(2025, 12, 10), D(1) / 2),),
    # 00631L 元大台灣50正2: 1 -> 22; last trade 2026-03-24 (443.15), halted 03-25..03-30, resumed 2026-03-31 (ref 20.14,
    # opened 19.67). Added in the second round (2026-11-18).
    # https://wantrich.chinatimes.com/news/20260302900246-420101 https://www.ctee.com.tw/news/20260302700571-430201
    # https://money.udn.com/money/story/5618/9296771 https://money.udn.com/money/story/5618/9297513
    # https://news.cnyes.com/news/id/6395543 https://news.cnyes.com/news/id/6326361
    # https://finance.ettoday.net/news/3141229 https://news.tvbs.com.tw/money/3165850
    # https://udn.com/news/story/7239/9413624
    # https://www.businesstoday.com.tw/article/category/183013/post/202603240010/
    "00631L.TW": ((date(2026, 3, 31), D(22)),),
    # 00674R 期元大S&P黃金反1: reverse 5 -> 1 (0.2); halted 2026-04-15..04-21, new units from 2026-04-22. Added in the
    # second round (2026-11-18; one earlier article expected 4 -> 1, every notice after the application says 5).
    # https://money.udn.com/money/story/5612/9389606 https://money.udn.com/money/story/5618/9388451
    # https://www.ctee.com.tw/news/20260319700653-430201 https://www.ctee.com.tw/news/20260318701829-430403
    # https://news.cnyes.com/news/id/6389405 https://uanalyze.com.tw/articles/4173649238
    # https://wantrich.chinatimes.com/news/20260318900811-420101
    "00674R.TW": ((date(2026, 4, 22), D(1) / 5),),
    # 00685L 群益臺灣加權正2: 1 -> 24; last trade 2026-06-30 (306), halted 07-01..07-06, resumed 2026-07-07 (ref 12.75).
    # https://www.businesstoday.com.tw/article/category/183013/post/202606300006/
    # https://wantrich.chinatimes.com/news/20260701900193-420401 https://finance.ettoday.net/news/3196520
    # https://www.storm.mg/article/11147479 https://money.udn.com/money/story/5607/9593785
    "00685L.TW": ((date(2026, 7, 7), D(24)),),
    # 00662 富邦NASDAQ: 1 -> 5; last trade 2026-11-10, halted 11-11..11-16, resumed 2026-11-17 (ref 23.56). Checked in
    # two official open datasets: TWSE STOCK_DAY_ALL (open data, data.gov.tw 11549) has no 00662 row on 2026-11-16 and
    # closes it at 23.10 (change -0.46) on 2026-11-17; SITCA's NAV file moves to the new units on 2026-11-11
    # (116.77 -> 23.89 while Nasdaq-100 peers rose 2.2–2.3 %).
    # https://www.twse.com.tw/exchangeReport/STOCK_DAY_ALL?response=open_data
    # https://www.sitca.org.tw/MemberK0000/F/03/nav.csv
    "00662.TW": ((date(2026, 11, 17), D(5)),),
    # -- stocks: par value changes (面額變更) --------------------------------------------------------------------------
    # A lower par value exchanges each old share for (old par / new par) new shares, paid-in capital and cash unchanged:
    # a split to every consumer. All added in the second round (2026-11-18).
    # 6531 愛普: par NT$10 -> 5, 1 -> 2; last trade 2021-10-06, halted 10-07..10-15, new shares from 2021-10-18 (before
    # the backfill's five years: kept for the demo prices and the record).
    # https://www.apmemory.com/tw/news/變更面額?cate=all https://wantrich.chinatimes.com/news/20211008900319-420101
    # https://www.moneydj.com/kmdj/news/newsviewer.aspx?a=936c0111-5bf1-43e9-9048-6894d7669350
    # https://www.moneydj.com/kmdj/news/newsviewer.aspx?a=23a903ba-839e-4e12-a60f-a4dd9cffb24e
    # https://money.udn.com/money/story/5607/5752601 https://news.cnyes.com/news/id/4736202
    "6531.TW": ((date(2021, 10, 18), D(2)),),
    # 6415 矽力*-KY: par NT$10 -> 2.5, 1 -> 4; last trade 2022-07-05 (2485), halted 07-06..07-12, new shares from
    # 2022-07-13 (ref about 621; 95,022,705 -> 380,090,820 shares).
    # https://www.cna.com.tw/news/afe/202207130029.aspx https://www.cna.com.tw/news/afe/202207060182.aspx
    # https://news.cnyes.com/news/id/4898421
    # https://www.moneydj.com/kmdj/news/newsviewer.aspx?a=0d67b282-4b47-4408-b11f-29484c96d8d3
    # https://www.ctee.com.tw/news/20220705700483-430298 https://www.ctee.com.tw/news/20220713700369-430298
    # https://wantrich.chinatimes.com/news/20220713900382-420101 https://money.udn.com/money/story/5607/6437180
    "6415.TW": ((date(2022, 7, 13), D(4)),),
    # 6613 朋億*: par NT$10 -> 5, 1 -> 2; last trade 2022-08-17 (169), new shares from 2022-08-29 (ref half of 169).
    # The TPEx table was seen in a search result only, never fetched (data policy).
    # https://ec.ltn.com.tw/article/breakingnews/4037275
    # https://www.tpex.org.tw/zh-tw/mainboard/listed/flexible-face-value.html
    # https://wantrich.chinatimes.com/news/20230222900116-420101
    # https://ww2.money-link.com.tw/TWStock/StockBasic.aspx?SymId=6613
    "6613.TWO": ((date(2022, 8, 29), D(2)),),
    # 5536 聖暉*: par NT$10 -> 5, 1 -> 2; last trade 2022-09-06, halted 09-07..09-16, new shares from 2022-09-19.
    # https://www.ctee.com.tw/news/20220822700816-430298
    # https://www.moneydj.com/kmdj/news/newsviewer.aspx?a=1db50b6f-df26-4977-a9c5-63e8a6fd0b22
    # https://www.moneydj.com/KMDJ/news/newsviewer.aspx?a=def8dc02-9c98-424a-84b2-77b6ead7383d
    # https://news.cnyes.com/news/id/4951592 https://wantrich.chinatimes.com/news/20220805900891-420101
    "5536.TWO": ((date(2022, 9, 19), D(2)),),
    # 8932 智通*: par NT$10 -> 5, 1 -> 2; last trade 2024-08-28, halted 08-29..09-06, new shares from 2024-09-09. (A
    # second change, NT$5 -> 2.5 with new shares from 2026-03-09, was reported too and is not checked yet: not listed.)
    # https://news.cnyes.com/news/id/5698148 https://www.ctee.com.tw/news/20240815701483-430201
    # https://tw.stock.yahoo.com/news/%E8%82%A1%E7%A5%A8%E9%9D%A2%E9%A1%8D%E8%AE%8A%E6%9B%B4-%E7%B6%A0%E7%95%8C%E7%A7%91%E6%8A%8010%E5%85%83%E8%AE%8A1%E5%85%83-%E6%99%BA%E9%80%9A10%E5%85%83%E8%AE%8A5%E5%85%83-%E6%96%B0%E8%82%A19-9%E6%AB%83%E6%AA%AF%E8%B2%B7%E8%B3%A3-003732857.html
    # https://winvest.tw/News/Detail/31652
    # https://www.moneydj.com/kmdj/news/newsviewer.aspx?a=cd0946b2-477d-49c3-813d-3f461fa70c70
    "8932.TWO": ((date(2024, 9, 9), D(2)),),
    # 5314 世紀: par NT$10 -> 0.5, 1 -> 20; new shares from 2025-03-31 (ref 69.5, or 72.5 = a 3/19 close of 1,450 / 20:
    # the sources differ, the ratio and the day do not).
    # https://www.ctee.com.tw/news/20250403700201-430201 https://www.cmoney.tw/notes/note-detail.aspx?nid=930489
    # https://tw.stock.yahoo.com/news/%E5%8F%B0%E5%8C%97%E8%82%A1%E5%B8%82-%E4%B8%96%E7%B4%80%E5%88%A9%E5%A4%9A%E8%B5%B0%E7%96%B2-%E6%8B%96%E7%B4%AF%E4%B8%8A%E6%9B%9C%E9%9B%86%E5%9C%98%E8%82%A1-034511572.html
    # https://finance.ettoday.net/news/2911933
    "5314.TWO": ((date(2025, 3, 31), D(20)),),
    # 4763 材料*-KY: par NT$10 -> 1, 1 -> 10; last trade 2025-06-18, halted 06-19..06-27, new shares from 2025-06-30.
    # https://news.cnyes.com/news/id/6012466
    # https://www.moneydj.com/kmdj/news/newsviewer.aspx?a=1ed3b1d1-7ee5-4a73-ac94-f761efc788a9
    # https://wantrich.chinatimes.com/news/20250604900372-420101
    # https://tw.stock.yahoo.com/news/%E6%9D%90%E6%96%99-ky%E7%B8%AE%E6%B8%9B%E8%82%A1%E7%A5%A8%E9%9D%A2%E9%A1%8D%E7%88%B21%E5%85%83%E7%8D%B2%E4%BA%A4%E6%98%93%E6%89%80%E6%A0%B8%E5%87%86-%E6%8F%9B%E8%82%A1%E5%BE%8C%E6%96%B0%E8%82%A16-30%E4%B8%8A%E5%B8%82-122459687.html
    # https://www.moneydj.com/kmdj/news/newsviewer.aspx?a=4e4e7d16-80bd-4ef5-a521-35c76320ea2b
    # https://www.ctee.com.tw/news/20250522701109-430201 https://www.ptt.cc/bbs/Stock/M.1748960680.A.A08.html
    "4763.TW": ((date(2025, 6, 30), D(10)),),
    # 2327 國巨: par NT$10 -> 2.5, 1 -> 4; last trade 2025-08-13, halted 08-14..08-22, new shares from 2025-08-25 (ref
    # 136.5 = 546 / 4).
    # https://fnc.ebc.net.tw/fncnews/stock/194757 https://news.cnyes.com/news/id/6124639
    # https://udn.com/news/story/7253/8904616 https://udn.com/news/story/7253/8962234
    # https://wantrich.chinatimes.com/news/20250825900233-420101
    # https://tw.stock.yahoo.com/news/%E5%9C%8B%E5%B7%A8%E8%82%A1%E7%A5%A8%E9%9D%A2%E9%A1%8D-%E6%8B%86%E5%9B%9B-8-13%E7%82%BA%E8%88%8A%E8%82%A1%E6%9C%80%E5%BE%8C%E4%BA%A4%E6%98%93%E6%97%A5-8-233627913.html
    # https://www.sinotrade.com.tw/richclub/hotstock/%E5%9C%8B%E5%B7%A8-2327-%E8%82%A1%E7%A5%A8%E5%88%86%E5%89%B2%E4%B8%80%E6%8B%86%E5%9B%9B-%E7%9B%B8%E9%97%9C%E6%97%A5%E7%A8%8B-%E5%BE%8C%E7%BA%8C%E5%8F%AF%E8%83%BD%E5%BD%B1%E9%9F%BF%E4%B8%80%E6%96%87%E6%8E%8C%E6%8F%A1-%E8%82%A1%E5%B8%82%E8%A9%B1%E9%A1%8C-689ab5417c32b44d13cd847b
    "2327.TW": ((date(2025, 8, 25), D(4)),),
    # 8937 合騏: par NT$10 -> 2.5, 1 -> 4; last trade 2026-03-31, halted 04-01..04-10, new shares from 2026-04-13.
    # https://money.udn.com/money/story/5607/9393220 https://udn.com/news/story/7254/9393220
    # https://www.moneydj.com/kmdj/news/newsviewer.aspx?a=701385e3-d1df-43e7-b800-527a0dd87983
    # https://tw.stock.yahoo.com/news/%E5%90%88%E9%A8%8F-%E5%9B%A0%E8%82%A1%E7%A5%A8%E9%9D%A2%E9%A1%8D%E8%AE%8A%E6%9B%B4%E6%8F%9B%E7%99%BC%E4%B9%8B%E6%99%AE%E9%80%9A%E8%82%A14-13%E8%B5%B7%E6%81%A2%E5%BE%A9%E5%9C%A8%E8%AD%89%E5%88%B8%E5%95%86%E7%87%9F%E6%A5%AD%E8%99%95%E6%89%80%E8%B2%B7%E8%B3%A3-003000205.html
    # https://tw.stock.yahoo.com/news/%E5%90%88%E9%A8%8F-%E5%85%AC%E5%91%8A%E6%9C%AC%E5%85%AC%E5%8F%B8%E8%82%A1%E7%A5%A8%E9%9D%A2%E9%A1%8D%E7%94%B1-%E6%96%B0%E5%8F%B0%E5%B9%A310%E5%85%83-%E8%AE%8A%E6%9B%B4%E7%82%BA-%E6%96%B0%E5%8F%B0%E5%B9%A32-230300853.html
    # https://news.cnyes.com/news/id/6335428
    "8937.TWO": ((date(2026, 4, 13), D(4)),),
    # 3086 華義*: par NT$10 -> 1, 1 -> 10; last trade 2026-04-08, halted 04-09..04-17, new shares from 2026-04-20.
    # https://wantrich.chinatimes.com/news/20260317900500-420101
    # https://wantrich.chinatimes.com/news/20260313900443-420101
    # https://www.moneydj.com/kmdj/news/newsviewer.aspx?a=e1cccd39-47a0-4432-9836-1c69e8100ab7
    # https://www.moneydj.com/kmdj/news/newsviewer.aspx?a=bdf6b760-c4fd-4a85-a711-cfda8af0be56
    # https://news.cnyes.com/news/id/6423032 https://news.cnyes.com/news/id/6405854
    # https://tw.stock.yahoo.com/news/%E8%8F%AF%E7%BE%A9%E5%9B%A0%E8%82%A1%E7%A5%A8%E9%9D%A2%E9%A1%8D%E8%AE%8A%E6%9B%B4%E6%8F%9B%E7%99%BC%E4%B9%8B%E6%96%B0%E8%82%A14-20%E8%B5%B7%E9%96%8B%E5%A7%8B%E4%B8%8A%E6%AB%83%E8%B2%B7%E8%B3%A3-001600565.html
    # https://wealth.firstbank.com.tw/investment-tips/trend-insight/news/news-detail?id=%7BA0B05F7C-0B00-4EF8-A218-1358C8DEA2E5%7D
    "3086.TWO": ((date(2026, 4, 20), D(10)),),
    # 5904 寶雅*: par NT$10 -> 1, 1 -> 10; last trade 2026-07-29, halted 07-30..08-07, new shares from 2026-08-10 (ref
    # 72, opened limit-up at 79.2).
    # https://udn.com/news/story/7252/9681387 https://www.ctee.com.tw/news/20260703700108-439901
    # https://money.udn.com/money/story/11074/9655165 https://udn.com/news/story/7254/9595581
    # https://wantrich.chinatimes.com/news/20260702900004-420101
    # https://www.sinotrade.com.tw/richclub/hotstock/-6a7956ce40c87c0b5724cd00
    # https://money.udn.com/money/story/11074/9596272
    "5904.TWO": ((date(2026, 8, 10), D(10)),),
    # 4747 強生*: par NT$10 -> 5, 1 -> 2; last trade 2026-08-19, halted 08-20..08-28, new shares from 2026-08-31.
    # https://www.ctee.com.tw/news/20260804700607-430201 https://www.setn.com/news/1883764
    # https://www.moneydj.com/kmdj/news/newsviewer.aspx?a=527ddbda-0985-4164-9690-cbbbcdcde56a
    # https://tw.stock.yahoo.com/news/%E5%BC%B7%E7%94%9F-%E5%9B%A0%E8%82%A1%E7%A5%A8%E9%9D%A2%E9%A1%8D%E8%AE%8A%E6%9B%B4%E6%8F%9B%E7%99%BC%E4%B9%8B%E6%96%B0%E8%82%A18-31%E8%B5%B7%E6%81%A2%E5%BE%A9%E4%B8%8A%E6%AB%83%E8%B2%B7%E8%B3%A3-003400109.html
    # https://www.ctee.com.tw/news/20260723701400-430504
    # https://www.moneydj.com/kmdj/news/newsviewer.aspx?a=36cd2907-84a3-4e9b-a5b8-6e460d2727ef
    "4747.TWO": ((date(2026, 8, 31), D(2)),),
    # 6949 (創新板, TWSE): par NT$10 -> 0.5, 1 -> 20; last trade 2026-08-26 (1,490), halted 08-27..09-04, new shares
    # from 2026-09-07 (ref 74.5; 65,580,050 -> 1,311,601,000 shares).
    # https://www.ctee.com.tw/news/20260829700441-430504 https://www.ctee.com.tw/news/20260826700260-430201
    # https://udn.com/news/story/7252/9714653 https://udn.com/news/story/7252/9738591
    # https://money.udn.com/money/story/5710/9714669 https://finance.ettoday.net/news/3232771
    # https://fubon-ebrokerdj.fbs.com.tw//z/zc/zcv/zcvz/zcvz_7CCA2F84-159E-478D-9897-B97CE3E0BCC7.djhtm
    "6949.TW": ((date(2026, 9, 7), D(20)),),
    # -- stocks: capital reductions ----------------------------------------------------------------------------------
    # 2363 矽統: 35 % cash reduction, 650 new per 1,000 old, NT$3.5 back per old share; old shares last 2024-07-18,
    # new shares from 2024-07-29.
    # https://news.cnyes.com/news/id/5628900 https://www.ctee.com.tw/news/20240729700806-430201
    # https://www.moneyweekly.com.tw/_Article?AID=149131 https://news.cnyes.com/news/id/5624523
    # https://www.cna.com.tw/news/afe/202402260209.aspx
    "2363.TW": ((date(2024, 7, 29), D("0.65")),),
    # 2371 大同: 5 % cash reduction, 950 new per 1,000 old, NT$0.5 back per old share; old shares last 2025-06-11,
    # new shares from 2025-06-23.
    # https://www.moneydj.com/kmdj/news/newsviewer.aspx?a=cebf459b-961a-46d4-bac8-da42cfb712d6
    # https://www.ctee.com.tw/news/20250527701947-430503 https://news.cnyes.com/news/id/5981723
    # https://finance.technews.tw/2025/01/21/datong-plans-to-reduce-its-capital-by-5-in-cash/
    # https://www.moneyweekly.com.tw/ArticleData/Info/Article/184561/
    "2371.TW": ((date(2025, 6, 23), D("0.95")),),
    # 2323 中環: 10 % cash reduction, 900 new per 1,000 old, NT$1 back per old share; old shares last 2026-09-30,
    # new shares from 2026-10-12. (Not its 2022 reduction: NT$0.6 back, new shares 2022-10-24.)
    # https://ww2.money-link.com.tw/realtimenews/NewsContent.aspx?SN=2408366002
    # https://www.moneydj.com/kmdj/news/newsviewer.aspx?a=37c7e98d-e2e2-48fa-8165-e6171d6d1630
    # https://tw.stock.yahoo.com/news/%E4%B8%AD%E7%92%B0-%E5%85%AC%E5%8F%B8%E8%88%8A%E8%82%A1%E6%9C%80%E5%BE%8C%E4%BA%A4%E6%98%93%E6%97%A59-30-%E7%8F%BE%E9%87%91%E6%B8%9B%E8%B3%87%E6%8F%9B%E7%99%BC%E6%96%B0%E8%82%A110-12%E8%B5%B7%E4%B8%8A%E5%B8%82%E8%B2%B7%E8%B3%A3-011700706.html
    # https://finance.biggo.com.tw/news/twse_major_2323_1150813_182231 https://www.peoplenews.tw/?p=20938
    "2323.TW": ((date(2026, 10, 12), D("0.9")),),
    # 9945 潤泰新: 10 % cash reduction, 900 new per 1,000 old, NT$1 back per old share; old shares last 2023-09-13,
    # new shares from 2023-09-25.
    # https://news.cnyes.com/news/id/5308334 https://news.cnyes.com/news/id/5312613
    # https://www.moneydj.com/kmdj/news/newsviewer.aspx?a=d7fde9df-4771-433f-bd37-ad9d9e7efc4c
    # https://www.moneydj.com/kmdj/news/newsviewer.aspx?a=1a45fad6-ef0c-4333-af70-e9c787e9ea44
    # https://www.ctee.com.tw/news/20230925701776-430606 https://www.ctee.com.tw/news/20230315700436-430298
    "9945.TW": ((date(2023, 9, 25), D("0.9")),),
    # 4174 浩鼎: 50 % reduction to offset losses (no cash), 500 new per 1,000 old; old shares last 2026-01-26, new
    # shares from 2026-02-03 (the first schedule, new shares 2026-01-26, was withdrawn).
    # https://news.cnyes.com/news/id/6327094
    # https://tw.stock.yahoo.com/news/%E6%B5%A9%E9%BC%8E-%E5%85%AC%E5%8F%B8%E8%88%8A%E8%82%A1%E6%9C%80%E5%BE%8C%E4%BA%A4%E6%98%93%E6%97%A5%E8%AA%BF%E6%95%B4%E7%82%BA115-1-26-%E6%B8%9B%E8%B3%87%E6%8F%9B%E7%99%BC%E6%96%B0%E8%82%A1%E8%AA%BF%E6%95%B4%E7%82%BA115-074600263.html
    # https://m.esunsec.com.tw/news/instant-detail.aspx?id=%7BAFC5C2EA-36A7-4B71-9601-34C59EF8A20F%7D
    # https://tw.stock.yahoo.com/quote/4174.TWO/calendar https://udn.com/news/story/7254/8976720
    # https://news.cnyes.com/news/id/6135764 https://wantrich.chinatimes.com/news/20251124900511-420101
    # https://www.moneydj.com/kmdj/news/newsviewer.aspx?a=ea09d29b-17ff-4ac5-a869-8fa22bc8ef9a
    "4174.TWO": ((date(2026, 2, 3), D("0.5")),),
    # Second round (2026-11-18):
    # 2603 長榮: 60 % cash reduction, 400 new per 1,000 old, NT$6 back per old share; old shares last 2022-09-06
    # (80.8), halted 09-07..09-16, new shares from 2022-09-19 (ref 187 = (80.8 − 6) / 0.4).
    # https://www.cna.com.tw/news/afe/202209190033.aspx https://udn.com/news/story/7252/6622487
    # https://udn.com/news/story/7252/6593296
    # https://finance.technews.tw/2022/08/23/evergreen-marine-60-capital-reduction-in-cash/
    # https://ctee.com.tw/news/stocks/702884.html https://news.cnyes.com/news/id/4957443
    # https://news.cnyes.com/news/id/4954183
    "2603.TW": ((date(2022, 9, 19), D("0.4")),),
    # 2409 友達: 20 % cash reduction, 800 new per 1,000 old, NT$2 back per old share; old shares last 2022-09-28,
    # halted 09-29..10-07, new shares from 2022-10-11 (closed 16.45, +0.60); the NT$1 cash dividend is separate.
    # https://news.cnyes.com/news/id/4932539 https://anuenews.cnyes.com/news/id/4975501
    # https://ctee.com.tw/news/stocks/717176.html https://www.cmoney.tw/notes/note-detail.aspx?nid=499660
    # https://wantrich.chinatimes.com/news/20221006900403-420101 https://www.gvm.com.tw/article/94249
    "2409.TW": ((date(2022, 10, 11), D("0.8")),),
    # 3481 群創: 9.5 % cash reduction, 905 new per 1,000 old, NT$0.95 back per old share; old shares last 2022-09-28
    # (10.45), halted 09-29..10-07, new shares from 2022-10-11 (ref 10.50, closed 11.45). Not its other reductions
    # (NT$1.2 back with new shares from 2024-08-26; one with NT$0.5 back in 2023): not checked yet, not listed.
    # https://ec.ltn.com.tw/article/breakingnews/4082094 https://www.ctee.com.tw/news/20221011701022-439901
    # https://www.ctee.com.tw/news/20221012700291-430203 https://money.udn.com/money/story/122229/6672823
    # https://ec.ltn.com.tw/article/breakingnews/4072411 https://news.cnyes.com/news/id/4939797
    # https://www.bnext.com.tw/article/69122/innlox-capital-reduction-may11
    "3481.TW": ((date(2022, 10, 11), D("0.905")),),
}

# The capital reductions among KNOWN_SPLITS: (symbol, first day at the new price) -> cash returned per old share
# (0 for a reduction to offset losses). The new shares' reference price is (last close − cash) / ratio, not
# last close / ratio: near par the two barely differ, so a check of whether Yahoo scaled its rows by the ratio has to
# know the cash (services.reference_close._folded_in), and a chart says 「減資」, not 「股票分割」 (2026-11-18 review).
KNOWN_REDUCTIONS: dict[tuple[str, date], D] = {
    ("2363.TW", date(2024, 7, 29)): D("3.5"),
    ("2371.TW", date(2025, 6, 23)): D("0.5"),
    ("2323.TW", date(2026, 10, 12)): D(1),
    ("9945.TW", date(2023, 9, 25)): D(1),
    ("4174.TWO", date(2026, 2, 3)): D(0),
    ("2603.TW", date(2022, 9, 19)): D(6),
    ("2409.TW", date(2022, 10, 11)): D(2),
    ("3481.TW", date(2022, 10, 11)): D("0.95"),
}

_Q = (3, 6, 9, 12)

DEMO_SPECS: dict[str, DemoSpec] = {
    # Taiwan stocks (anchors are overridden by the real latest close when available)
    "2330.TW": DemoSpec(D("2395"),
                        waypoints=(
                            ("2018-01-02", "230"), ("2020-03-19", "250"), ("2021-01-21", "670"),
                            ("2022-10-25", "370"), ("2024-07-11", "1080"), ("2025-04-09", "780"),
                            ("2025-06-02", "950"), ("2025-11-03", "1500"), ("2026-09-01", "2440"),
                        ),
                        drift=0.40, vol=0.30, div_months=_Q, div_day=17, div_yield=0.0028,
                        base_volume=30_000_000, target_per=24, target_pbr=6.5, eps_growth=0.30),
    "2317.TW": DemoSpec(D("242"),
                        waypoints=(
                            ("2018-01-02", "90"), ("2020-03-19", "70"), ("2024-07-10", "230"),
                            ("2025-04-09", "130"), ("2025-11-03", "220"),
                        ),
                        drift=0.15, vol=0.32, div_months=(7,), div_day=24, div_yield=0.028,
                        base_volume=60_000_000, target_per=16, target_pbr=1.9),
    "2454.TW": DemoSpec(D("3990"),
                        waypoints=(
                            ("2018-01-02", "300"), ("2020-03-19", "300"), ("2021-12-01", "1100"),
                            ("2022-10-25", "520"), ("2024-07-11", "1400"), ("2025-04-09", "1200"),
                            ("2025-11-03", "1700"),
                        ),
                        drift=0.35, vol=0.38, div_months=(1, 7), div_day=9, div_yield=0.022,
                        base_volume=5_000_000, target_per=26, target_pbr=7.0, eps_growth=0.20),
    "6488.TWO": DemoSpec(D("635"),
                        waypoints=(
                            ("2018-01-02", "330"), ("2021-01-20", "900"), ("2022-10-25", "380"),
                            ("2024-01-15", "600"), ("2025-04-09", "280"), ("2025-11-03", "420"),
                        ),
                        drift=0.0, vol=0.40, div_months=(6,), div_day=23, div_yield=0.018,
                         stock_dividends={2025: D("0.5")}, base_volume=2_000_000, target_per=22, target_pbr=2.4),
    "2303.TW": DemoSpec(D("51.6"), drift=0.02, vol=0.28, div_months=(7,), div_day=10, div_yield=0.055),
    "2308.TW": DemoSpec(D("1295"), drift=0.30, vol=0.32, div_months=(7,), div_day=1, div_yield=0.012),
    "2382.TW": DemoSpec(D("298"), drift=0.20, vol=0.35, div_months=(7,), div_day=10, div_yield=0.035,
                        base_volume=15_000_000, target_per=17, target_pbr=4.0),
    "2412.TW": DemoSpec(D("132.5"), drift=0.03, vol=0.10, div_months=(7,), div_day=17, div_yield=0.037),
    "2881.TW": DemoSpec(D("92.3"), drift=0.08, vol=0.22, div_months=(7,), div_day=3, div_yield=0.045),
    "2882.TW": DemoSpec(D("71.8"), drift=0.08, vol=0.22, div_months=(7,), div_day=8, div_yield=0.04),
    "3711.TW": DemoSpec(D("245"), drift=0.15, vol=0.30, div_months=(7,), div_day=4, div_yield=0.03),
    # Taiwan ETFs (no real price source in this environment)
    "0050.TW": DemoSpec(D("99.70"),
                        waypoints=(
                            ("2018-01-02", "82"), ("2020-03-19", "70"), ("2021-12-01", "145"),
                            ("2022-10-25", "100"), ("2024-07-11", "200"), ("2025-04-09", "150"),
                            ("2025-06-17", "190"),
                        ),
                        drift=0.25, vol=0.20, div_months=(1, 7), div_day=22, div_yield=0.012,
                        splits=((date(2025, 6, 18), D(4)),),
                        base_volume=25_000_000),
    "006208.TW": DemoSpec(D("228.90"),
                        waypoints=(
                            ("2018-01-02", "50"), ("2024-07-11", "115"), ("2025-04-09", "86"),
                        ),
                        drift=0.25, vol=0.20, div_months=(7, 11), div_day=18, div_yield=0.015,
                          base_volume=4_000_000),
    "0056.TW": DemoSpec(D("52.30"),
                        waypoints=(
                            ("2018-01-02", "25"), ("2024-06-17", "39"), ("2025-04-09", "31"),
                        ),
                        drift=0.05, vol=0.14, div_months=(1, 4, 7, 10), div_day=21, div_yield=0.02,
                        base_volume=20_000_000),
    "00878.TW": DemoSpec(D("32.95"),
                        waypoints=(
                            ("2020-07-20", "15"), ("2024-07-11", "23.5"), ("2025-04-09", "19"),
                        ),
                        drift=0.05, vol=0.13, div_months=(2, 5, 8, 11), div_day=18,
                         div_yield=0.017, base_volume=40_000_000),
    "00919.TW": DemoSpec(D("30.90"),
                        waypoints=(
                            ("2023-01-03", "20"), ("2024-07-11", "26"), ("2025-04-09", "20"),
                        ),
                        drift=0.05, vol=0.15, div_months=_Q, div_day=16, div_yield=0.026,
                         base_volume=30_000_000),
    "00929.TW": DemoSpec(D("25.34"),
                        waypoints=(
                            ("2023-06-09", "15"), ("2024-07-11", "20"), ("2025-04-09", "16"),
                        ),
                        drift=0.08, vol=0.17, div_months=tuple(range(1, 13)), div_day=17,
                         div_yield=0.006, base_volume=25_000_000),
    "00713.TW": DemoSpec(D("62.30"),
                        waypoints=(
                            ("2018-01-02", "30"), ("2024-07-11", "56"), ("2025-04-09", "48"),
                        ),
                        drift=0.04, vol=0.12, div_months=_Q, div_day=18, div_yield=0.02,
                         base_volume=3_000_000),
    # US (fully synthetic)
    "AAPL": DemoSpec(D("285.40"),
                        waypoints=(
                            ("2018-01-02", "43"), ("2020-03-23", "61"), ("2022-01-03", "180"),
                            ("2023-01-05", "125"), ("2024-12-26", "255"), ("2025-04-08", "172"),
                        ),
                        drift=0.12, vol=0.27, div_months=(2, 5, 8, 11), div_day=10,
                     div_yield=0.0011, base_volume=50_000_000, pay_lag_days=4, target_per=32, target_pbr=45),
    "NVDA": DemoSpec(D("198.60"),
                        waypoints=(
                            ("2018-01-02", "5"), ("2022-10-13", "11"), ("2023-12-01", "47"),
                            ("2024-06-18", "135"), ("2025-04-04", "94"),
                        ),
                        drift=0.35, vol=0.50, div_months=_Q, div_day=5, div_yield=0.0002,
                     base_volume=200_000_000, pay_lag_days=21, target_per=45, target_pbr=40, eps_growth=0.5),
    "VOO": DemoSpec(D("642.10"),
                        waypoints=(
                            ("2018-01-02", "250"), ("2020-03-23", "200"), ("2022-01-03", "440"),
                            ("2022-10-12", "330"), ("2024-12-06", "555"), ("2025-04-08", "450"),
                        ),
                        drift=0.12, vol=0.17, div_months=_Q, div_day=24, div_yield=0.0032,
                    base_volume=5_000_000, pay_lag_days=4),
    "QQQ": DemoSpec(D("668.30"),
                        waypoints=(
                            ("2018-01-02", "155"), ("2020-03-16", "170"), ("2021-12-27", "400"),
                            ("2022-12-28", "260"), ("2024-12-16", "535"), ("2025-04-08", "420"),
                        ),
                        drift=0.15, vol=0.22, div_months=_Q, div_day=22, div_yield=0.0014,
                    base_volume=40_000_000, pay_lag_days=7),
}


def default_spec(symbol: str, anchor: D, seed: int) -> DemoSpec:
    """Parameters for any other Taiwan stock: mildly varied by a stable per-symbol seed. A known split (KNOWN_SPLITS)
    drops the synthetic prices on its day like the real ones (and 0050's own spec), so a demo price and the split a
    benchmark or chart applies on that day agree (a ×7 benchmark jump otherwise, 2026-11-18)."""
    return DemoSpec(
        anchor=anchor,
        splits=KNOWN_SPLITS.get(symbol, ()),
        drift=0.02 + (seed % 9) / 100,
        vol=0.25 + (seed % 15) / 100,
        div_months=(7,) if seed % 3 else (8,),
        div_day=5 + seed % 20,
        div_yield=0.015 + (seed % 30) / 1000,
        base_volume=1_000_000 + (seed % 50) * 100_000,
        target_per=12 + seed % 14,
        target_pbr=1.2 + (seed % 20) / 10,
    )
