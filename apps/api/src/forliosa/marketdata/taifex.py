"""Parsers for the TAIFEX OpenAPI (``https://openapi.taifex.com.tw/v1``; spec ``https://openapi.taifex.com.tw/swagger.json``).

Every field name below was read from live responses on 2026-11-12 (trimmed copies are the fixtures in
``tests/archive/fixtures/taifex_*``) and checked against the swagger. Parsers are pure: rows in, dicts out.

Parsing traps (docs/research/open-data-inventory.md §12.3, plus what the live run found):

* **JSON or CSV.** Data endpoints answer ``application/octet-stream`` behind Cloudflare, and the cache serves
  whichever variant it stored first, whatever ``Accept`` says: on 2026-11-12 ``DailyForeignExchangeRates``
  came back as CSV (``content-disposition: …csv``, UTF-8 BOM, headers = the swagger descriptions with
  「／」 written as 「_」, e.g. ``美元_新台幣(匯率)``) while the other endpoints were JSON.
  :func:`decode_rows` accepts both and every parser looks a field up by its JSON key *or* its Chinese header.
* Numbers are strings; missing values are ``"NULL"``, ``"-"`` or ``""`` (:func:`num`). Percentages come as
  ``"1.90%"`` and as ``"107.08"`` (key ``PutCallVolumeRatio%``): both become fractions.
* Dates are Gregorian ``YYYYMMDD`` (TWSE / TPEx use ROC years); ``parse_tw_date`` handles both.
* ``ContractMonth(Week)``: ``202611`` (monthly), ``202611W2`` / ``202611F2`` (weekly, Wednesday / Friday),
  ``202611/202612`` (calendar spread: prices are spread differentials, settlement and OI ``-``).
* ``TradingSession`` 一般 / 盤後. The 盤後 row dated D is the night session from 15:00 on the previous trading
  day to 05:00 on D (TAIFEX books it to the next trading day). Its change is measured from the previous
  trading day's settlement — the same base as D's regular session (TX 2026-11-11: settlement 11-10 = 42,646;
  盤後 42,522 −124; 一般 44,091 +1,445). 盤後 rows have ``SettlementPrice`` ``"NULL"`` and ``OpenInterest`` ``"-"``.
* Large traders' ``SettlementMonth`` sentinels: ``999912`` = all months combined (TXO 999912 call OI 88,811 =
  ``PutCallRatio.CallOI``), ``666666`` = weekly contracts combined. ``TypeOfTraders`` 0 = all large traders,
  1 = of which specific legal entities (特定法人; its numbers are never above type 0's).
* 三大法人 tables name contracts in Chinese (臺股期貨, 臺指選擇權) while the market reports use codes (TX, TXO):
  :data:`CONTRACT_NAMES` plus the names seen in the large-trader and margin datasets build ``taifex_contract_map``.
* Units: 三大法人總表 values are in **million** NT$, every other 三大法人 table in **thousand** NT$; parsers
  return thousands everywhere.
* ``FinalSettlementPrice`` was stale on 2026-11-12: its newest settlement day was 2025-12-05.
"""

from __future__ import annotations

import csv
import io
import json
import re
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any

from forliosa.marketdata.base import ProviderUnavailable, parse_decimal, parse_tw_date

TAIFEX_OPENAPI = "https://openapi.taifex.com.tw/v1"
SOURCE = "taifex-openapi"

ALL_MONTHS = "999912"  # large traders: all contract months combined
WEEKLY_MONTHS = "666666"  # large traders: weekly contracts combined
INDEX_OPTIONS = frozenset({"TXO", "TEO", "TFO"})  # archived in full; other options: two nearest expiries
SESSIONS = {"一般": "regular", "盤後": "after_hours"}
INVESTORS = {"自營商": "dealers", "投信": "trust", "外資及陸資": "foreign"}

# Chinese product names used by 三大法人 / 大額交易人 / 保證金 -> contract codes of the market reports. Aggregates
# (股票期貨, ETF期貨 …) have no single code. Codes checked against the 2026-11-12 DailyMarketReportFut contract
# list and OpenInterestOfLargeTradersFutures (Contract, ContractName) pairs; the large-trader names differ
# slightly (櫃買期貨 vs 櫃買指數期貨, 臺股期貨(TX+MTX/4)), so both spellings are listed.
CONTRACT_NAMES: dict[str, tuple[str | None, str]] = {
    "臺股期貨": ("TX", "futures"), "臺股期貨(TX+MTX/4)": ("TX", "futures"), "小型臺指期貨": ("MTX", "futures"),
    "小型臺指": ("MTX", "futures"), "微型臺指期貨": ("TMF", "futures"), "電子期貨": ("TE", "futures"),
    "小型電子期貨": ("ZEF", "futures"), "金融期貨": ("TF", "futures"), "小型金融期貨": ("ZFF", "futures"),
    "非金電期貨": ("XIF", "futures"), "櫃買指數期貨": ("GTF", "futures"), "櫃買期貨": ("GTF", "futures"),
    "富櫃200期貨": ("G2F", "futures"), "臺灣永續期貨": ("E4F", "futures"), "臺灣生技期貨": ("BTF", "futures"),
    "半導體30期貨": ("SOF", "futures"), "航運期貨": ("SHF", "futures"), "東證期貨": ("TJF", "futures"),
    "臺灣中型100期貨": ("M1F", "futures"), "美國道瓊期貨": ("UDF", "futures"), "美國標普500期貨": ("SPF", "futures"),
    "美國那斯達克100期貨": ("UNF", "futures"), "美國費城半導體期貨": ("SXF", "futures"),
    "英國富時100期貨": ("F1F", "futures"), "股票期貨": (None, "futures"), "ETF期貨": (None, "futures"),
    "臺指選擇權": ("TXO", "options"), "電子選擇權": ("TEO", "options"), "金融選擇權": ("TFO", "options"),
    "股票選擇權": (None, "options"), "ETF選擇權": (None, "options"),
}

# DailyForeignExchangeRates columns (JSON key, CSV header) -> our pair code (base + quote, ISO; NTD = TWD).
FX_PAIRS = {
    "USD/NTD": "USDTWD", "RMB/NTD": "CNYTWD", "EUR/USD": "EURUSD", "USD/JPY": "USDJPY", "GBP/USD": "GBPUSD",
    "AUD/USD": "AUDUSD", "USD/HKD": "USDHKD", "USD/RMB": "USDCNY", "USD/ZAR": "USDZAR", "NZD/USD": "NZDUSD",
}
FX_HEADERS = {
    "USD/NTD": "美元／新台幣(匯率)", "RMB/NTD": "人民幣／新台幣(匯率)", "EUR/USD": "歐元／美元(匯率)",
    "USD/JPY": "美元／日幣(匯率)", "GBP/USD": "英鎊／美元(匯率)", "AUD/USD": "澳幣／美元(匯率)",
    "USD/HKD": "美元／港幣(匯率)", "USD/RMB": "美元／人民幣(匯率)", "USD/ZAR": "美元／南非幣(匯率)",
    "NZD/USD": "紐幣／美元(匯率)",
}

_MISSING = {"", "-", "--", "---", "NULL", "N/A", "NA", "NONE"}


# -- decoding ---------------------------------------------------------------------------------------------
def decode_rows(raw: bytes) -> list[dict[str, Any]]:
    """A TAIFEX response body (JSON array, or CSV with a header row) -> list of dicts."""
    text = raw.decode("utf-8-sig", errors="replace").strip()
    if not text:
        return []
    if text[0] in "[{":
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise ProviderUnavailable("期交所回傳的 JSON 無法解析") from exc
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list):
            raise ProviderUnavailable("期交所回傳格式不符")
        return [r for r in data if isinstance(r, dict)]
    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    if not header or len(header) < 2:
        raise ProviderUnavailable("期交所回傳的不是 JSON 也不是 CSV")
    header = [h.strip() for h in header]
    return [dict(zip(header, (c.strip() for c in row), strict=False)) for row in reader if any(c.strip() for c in row)]


def _norm(key: Any) -> str:
    return re.sub(r"[\s／/_＿]", "", str(key)).replace("（", "(").replace("）", ")")


class _Row:
    """Field lookup by JSON key or Chinese CSV header (normalized: spaces, ／ / _ removed)."""

    __slots__ = ("d",)

    def __init__(self, raw: dict[str, Any]):
        self.d = {_norm(k): v for k, v in raw.items()}

    def get(self, *names: str) -> Any:
        for n in names:
            v = self.d.get(_norm(n))
            if v is not None:
                return v
        return None

    def text(self, *names: str) -> str:
        return str(self.get(*names) or "").strip()


# -- value helpers ----------------------------------------------------------------------------------------
def num(value: Any) -> Decimal | None:
    """``"44091"`` -> Decimal; ``"NULL"`` / ``"-"`` / ``""`` -> None (percent signs dropped)."""
    if value is None:
        return None
    s = str(value).strip()
    if s.upper() in _MISSING:
        return None
    return parse_decimal(s.replace("%", ""))


def integer(value: Any) -> int | None:
    d = num(value)
    return int(d) if d is not None else None


def pct(value: Any) -> Decimal | None:
    """``"1.90%"`` and ``"107.08"`` (already a percentage) -> fraction."""
    d = num(value)
    return d / 100 if d is not None else None


def call_put(value: Any) -> str:
    s = str(value or "").strip().upper()
    if s in ("買權", "CALL", "C"):
        return "C"
    if s in ("賣權", "PUT", "P"):
        return "P"
    return ""


def is_monthly(contract_month: str) -> bool:
    """``202611`` (a standard monthly contract); weeklies (``W``/``F``) and spreads (``/``) are not."""
    return bool(re.fullmatch(r"\d{6}", contract_month or ""))


def month_sort_key(contract_month: str) -> tuple[str, str]:
    m = re.match(r"(\d{6})(.*)", contract_month or "")
    return (m.group(1), m.group(2)) if m else (contract_month or "", "")


# -- market reports ---------------------------------------------------------------------------------------
def parse_futures_daily(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """DailyMarketReportFut -> rows of ``taifex_futures_daily`` (all contracts, both sessions, spreads kept)."""
    out = []
    for raw in rows:
        r = _Row(raw)
        d = parse_tw_date(r.get("Date", "日期"))
        contract = r.text("Contract", "契約")
        month = r.text("ContractMonth(Week)", "到期月份(週別)")
        session = SESSIONS.get(r.text("TradingSession", "交易時段"))
        if d is None or not contract or not month or session is None:
            continue
        out.append({
            "trade_date": d, "session": session, "contract": contract, "contract_month": month,
            "open": num(r.get("Open", "開盤價")), "high": num(r.get("High", "最高價")),
            "low": num(r.get("Low", "最低價")),
            "last": num(r.get("Last", "最後成交價")), "change": num(r.get("Change", "漲跌價")),
            "change_pct": pct(r.get("%", "漲跌%")), "volume": integer(r.get("Volume", "合計成交量")),
            "settlement_price": num(r.get("SettlementPrice", "結算價")),
            "open_interest": integer(r.get("OpenInterest", "未沖銷契約數")),
            "best_bid": num(r.get("BestBid", "最後最佳買價")), "best_ask": num(r.get("BestAsk", "最後最佳賣價")),
            "hist_high": num(r.get("HistoricalHigh", "歷史最高價")),
            "hist_low": num(r.get("HistoricalLow", "歷史最低價")),
            "halted": r.text("TradingHalt", "是否因訊息面暫停交易")[:16],
            "spread_volume": integer(r.get("Volume(ExecutionsAmongSpreadOrderAndSingleOrderOnly)",
                                           "價差對單式委託成交量")),
        })
    return out


def parse_options_daily(rows: list[dict[str, Any]], nearest: int = 2) -> list[dict[str, Any]]:
    """DailyMarketReportOpt -> rows of ``taifex_options_daily``.

    TXO / TEO / TFO are kept in full; other contracts (stock and ETF options) only for their ``nearest``
    expiries of the day (about 14,000 rows a day otherwise, 3.5 million a year).
    """
    parsed = []
    months: dict[str, set[str]] = defaultdict(set)
    for raw in rows:
        r = _Row(raw)
        d = parse_tw_date(r.get("Date", "日期"))
        contract = r.text("Contract", "契約")
        month = r.text("ContractMonth(Week)", "到期月份(週別)")
        session = SESSIONS.get(r.text("TradingSession", "交易時段"))
        strike = num(r.get("StrikePrice", "履約價"))
        cp = call_put(r.get("CallPut", "買賣權"))
        if d is None or not contract or not month or session is None or strike is None or not cp:
            continue
        months[contract].add(month)
        parsed.append({
            "trade_date": d, "session": session, "contract": contract, "contract_month": month, "strike": strike,
            "call_put": cp, "open": num(r.get("Open", "開盤價")), "high": num(r.get("High", "最高價")),
            "low": num(r.get("Low", "最低價")), "close": num(r.get("Close", "最後成交價")),
            "volume": integer(r.get("Volume", "成交量")), "settlement_price": num(r.get("SettlementPrice", "結算價")),
            "open_interest": integer(r.get("OpenInterest", "未沖銷契約量")),
            "best_bid": num(r.get("BestBid", "最後最佳買價")), "best_ask": num(r.get("BestAsk", "最後最佳賣價")),
        })
    keep = {c: set(sorted(ms, key=month_sort_key)[:nearest]) for c, ms in months.items()}
    return [p for p in parsed if p["contract"] in INDEX_OPTIONS or p["contract_month"] in keep[p["contract"]]]


# -- 三大法人 ----------------------------------------------------------------------------------------------
_VALUE_FIELDS = (  # our column, JSON key stem, (thousand-NT$ key suffix), Chinese stem
    ("long_vol", "TradingVolume(Long)", "多方交易口數"),
    ("short_vol", "TradingVolume(Short)", "空方交易口數"),
    ("net_vol", "TradingVolume(Net)", "多空交易口數淨額"),
    ("oi_long", "OpenInterest(Long)", "多方未平倉口數"),
    ("oi_short", "OpenInterest(Short)", "空方未平倉口數"),
    ("oi_net", "OpenInterest(Net)", "多空未平倉口數淨額"),
)
_AMOUNT_FIELDS = (  # our column, JSON key stem (… (Thousands) / (Millions)), Chinese stem (…(千元) / (百萬元))
    ("long_value_k", "TradingValue(Long)", "多方交易契約金額"),
    ("short_value_k", "TradingValue(Short)", "空方交易契約金額"),
    ("net_value_k", "TradingValue(Net)", "多空交易契約金額淨額"),
    ("oi_long_value_k", "ContractValueofOpenInterest(Long)", "多方未平倉契約金額"),
    ("oi_short_value_k", "ContractValueofOpenInterest(Short)", "空方未平倉契約金額"),
    ("oi_net_value_k", "ContractValueofOpenInterest(Net)", "多空未平倉契約金額淨額"),
)
# 選擇權買賣權分計 uses 買方／賣方 wording in its Chinese headers.
_CP_ZH = {"多方交易口數": "買方交易口數", "空方交易口數": "賣方交易口數", "多空交易口數淨額": "交易口數買賣淨額",
          "多方未平倉口數": "買方未平倉口數", "空方未平倉口數": "賣方未平倉口數",
          "多空未平倉口數淨額": "未平倉口數買賣淨額",
          "多方交易契約金額": "買方交易契約金額", "空方交易契約金額": "賣方交易契約金額",
          "多空交易契約金額淨額": "交易契約金額買賣淨額", "多方未平倉契約金額": "買方未平倉契約金額",
          "空方未平倉契約金額": "賣方未平倉契約金額", "多空未平倉契約金額淨額": "未平倉契約金額買賣淨額"}


def _values(r: _Row, prefix: str = "", zh_prefix: str = "", millions: bool = False,
            calls_puts: bool = False) -> dict[str, int | None]:
    out: dict[str, int | None] = {}
    for col, key, zh in _VALUE_FIELDS:
        zh = _CP_ZH.get(zh, zh) if calls_puts else zh
        out[col] = integer(r.get(f"{prefix}{key}", f"{zh_prefix}{zh}"))
    unit, zh_unit = ("(Millions)", "(百萬元)") if millions else ("(Thousands)", "(千元)")
    for col, key, zh in _AMOUNT_FIELDS:
        zh = _CP_ZH.get(zh, zh) if calls_puts else zh
        v = num(r.get(f"{prefix}{key}{unit}", f"{prefix}{key.replace('ofOpen', 'OfOpen')}{unit}",
                      f"{zh_prefix}{zh}{zh_unit}"))
        out[col] = int(v * 1000) if v is not None and millions else (int(v) if v is not None else None)
    return out


def _inst_row(d: date, scope: str, name: str, cp: str, investor: str, values: dict[str, int | None]) -> dict:
    code = CONTRACT_NAMES.get(name, (None, ""))[0]
    return {"trade_date": d, "scope": scope, "contract_name": name, "call_put": cp, "investor": investor,
            "contract_code": code, **values}


def parse_institutional_general(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """MarketDataOfMajorInstitutionalTradersGeneralBytheDate (總表; amounts in millions -> thousands)."""
    out = []
    for raw in rows:
        r = _Row(raw)
        d, investor = parse_tw_date(r.get("Date", "日期")), r.text("Item", "身份別")
        if d is None or not investor:
            continue
        out.append(_inst_row(d, "all", "", "", investor, _values(r, millions=True)))
    return out


def parse_institutional_fut_opt(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """…DividedByFuturesAndOptionsBytheDate: one row per investor -> a 期貨 row and a 選擇權 row."""
    out = []
    for raw in rows:
        r = _Row(raw)
        d, investor = parse_tw_date(r.get("Date", "日期")), r.text("Item", "身份別")
        if d is None or not investor:
            continue
        for name, prefix, zh in (("期貨", "Futures", "期貨"), ("選擇權", "Options", "選擇權")):
            out.append(_inst_row(d, "fut_opt", name, "", investor, _values(r, prefix, zh)))
    return out


def parse_institutional_contracts(rows: list[dict[str, Any]], scope: str) -> list[dict[str, Any]]:
    """…DetailsOfFuturesContractsBytheDate (scope ``futures``) / …DetailsOfOptionsContracts… (``options``) /
    …DetailsOfCallsAndPuts… (``calls_puts``; CallPut CALL/PUT)."""
    out = []
    for raw in rows:
        r = _Row(raw)
        d, investor = parse_tw_date(r.get("Date", "日期")), r.text("Item", "身份別")
        name = r.text("ContractCode", "商品名稱")
        cp = call_put(r.get("CallPut", "買賣權別")) if scope == "calls_puts" else ""
        if d is None or not investor or not name or (scope == "calls_puts" and not cp):
            continue
        out.append(_inst_row(d, scope, name, cp, investor, _values(r, calls_puts=scope == "calls_puts")))
    return out


# -- large traders, put/call, FX ----------------------------------------------------------------------------
def parse_large_traders(rows: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    """OpenInterestOfLargeTraders{Futures,Options} (``kind`` futures | options)."""
    out = []
    for raw in rows:
        r = _Row(raw)
        d = parse_tw_date(r.get("Date", "日期"))
        contract = r.text("Contract", "契約")
        month = r.text("SettlementMonth", "到期月份(週別)")
        trader_type = integer(r.get("TypeOfTraders", "交易人類別"))
        cp = call_put(r.get("CallPut", "買賣權")) if kind == "options" else ""
        if d is None or not contract or not month or trader_type is None or (kind == "options" and not cp):
            continue
        out.append({"trade_date": d, "kind": kind, "contract": contract, "call_put": cp, "settlement_month": month,
                    "trader_type": trader_type, "contract_name": r.text("ContractName", "商品名稱(契約名稱)")[:60],
                    "top5_buy": integer(r.get("Top5Buy", "前五大交易人買方數量")),
                    "top5_sell": integer(r.get("Top5Sell", "前五大交易人賣方數量")),
                    "top10_buy": integer(r.get("Top10Buy", "前十大交易人買方數量")),
                    "top10_sell": integer(r.get("Top10Sell", "前十大交易人賣方數量")),
                    "market_oi": integer(r.get("OIOfMarket", "全市場未沖銷部位數"))})
    return out


def parse_put_call_ratio(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """PutCallRatio (about a month of days per response): ratios ``"107.08"`` -> 1.0708."""
    out = []
    for raw in rows:
        r = _Row(raw)
        d = parse_tw_date(r.get("Date", "日期"))
        if d is None:
            continue
        out.append({"trade_date": d, "put_volume": integer(r.get("PutVolume", "賣權成交量")),
                    "call_volume": integer(r.get("CallVolume", "買權成交量")),
                    "volume_ratio": pct(r.get("PutCallVolumeRatio%", "買賣權成交量比率%")),
                    "put_oi": integer(r.get("PutOI", "賣權未平倉量")),
                    "call_oi": integer(r.get("CallOI", "買權未平倉量")),
                    "oi_ratio": pct(r.get("PutCallOIRatio%", "買賣權未平倉量比率%"))})
    return out


def parse_fx(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """DailyForeignExchangeRates (about six weeks per response) -> [{date, pair, rate}] (pair ``USDTWD`` …)."""
    out = []
    for raw in rows:
        r = _Row(raw)
        d = parse_tw_date(r.get("Date", "日期"))
        if d is None:
            continue
        for key, pair in FX_PAIRS.items():
            rate = num(r.get(key, FX_HEADERS[key]))
            if rate is not None and rate > 0:
                out.append({"date": d, "pair": pair, "rate": rate})
    return out


# -- weekly / when-changed --------------------------------------------------------------------------------
def parse_final_settlement(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for raw in rows:
        r = _Row(raw)
        d = parse_tw_date(r.get("TheFinalSettlementDay", "最後結算日"))
        contract, month = r.text("Contract", "商品代號"), r.text("DeliveryMonth", "契約月份")
        if d is None or not contract or not month:
            continue
        out.append({"contract": contract[:24], "delivery_month": month[:12], "settlement_day": d,
                    "contract_name": r.text("ContractName", "商品名稱")[:80],
                    "price": num(r.get("TheFinalSettlementPrice", "最後結算價"))})
    return out


def parse_margins(rows: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    """保證金一覽表 (``kind`` index | stock | etf). Index rows name the product in Chinese (臺股期貨); stock rows
    give rates (``"13.50%"`` -> 0.135), ETF rows amounts."""
    out = []
    for raw in rows:
        r = _Row(raw)
        d = parse_tw_date(r.get("Date", "日期"))
        contract = r.text("Contract", "商品別", "股票期貨英文代碼")
        if d is None or not contract:
            continue
        is_rate = kind == "stock"
        if is_rate:
            values = (pct(r.get("ClearingMarginRate", "結算保證金適用比例")),
                      pct(r.get("MaintenanceMarginRate", "維持保證金適用比例")),
                      pct(r.get("InitialMarginRate", "原始保證金適用比例")))
        else:
            values = (num(r.get("ClearingMargin", "結算保證金")), num(r.get("MaintenanceMargin", "維持保證金")),
                      num(r.get("InitialMargin", "原始保證金")))
        name = r.text("ContractName", "股票期貨中文簡稱") or (contract if kind == "index" else "")
        out.append({"kind": kind, "contract": contract[:60], "date": d, "name": name[:80],
                    "underlying_code": r.text("UnderlyingSecurityCode", "股票期貨標的證券代號")[:12] or None,
                    "group_level": r.text("GroupLevel", "保證金所屬級距")[:16] or None, "is_rate": is_rate,
                    "clearing": values[0], "maintenance": values[1], "initial": values[2]})
    return out


def parse_underlyings(rows: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    """SSFLists / SSOLists (``kind`` SSF | SSO)."""
    out = []
    for raw in rows:
        r = _Row(raw)
        contract = r.text("Contract", "股票期貨商品代碼", "股票期貨商品契約代碼")
        code = r.text("StockCode", "證券代號")
        if not contract or not code:
            continue
        out.append({"kind": kind, "contract": contract[:12], "stock_code": code[:12],
                    "stock_name": r.text("StockName", "標的證券簡稱")[:60],
                    "type": r.text("Type", "標的證券種類")[:40]})
    return out


def contract_map_rows(large_traders: list[dict[str, Any]] = (), margins: list[dict[str, Any]] = ()) -> list[dict]:
    """``taifex_contract_map`` rows: the static names plus (code, name) pairs seen in the data.

    Large-trader rows pair a code with its name (TX ↔ 臺股期貨(TX+MTX/4); stock futures as CD ↔ 台積電期貨,
    without the trailing F of the market report's CDF); stock-futures margin rows pair CDF ↔ 台積電期貨.
    """
    out: dict[str, dict[str, Any]] = {}
    for r in large_traders:
        name = (r.get("contract_name") or "").strip()
        if name and r.get("contract"):
            out[name] = {"name_zh": name[:60], "contract_code": r["contract"], "kind": r["kind"], "source": SOURCE}
    for r in margins:
        if r.get("kind") in ("stock", "etf") and r.get("name") and r.get("contract"):
            out[r["name"]] = {"name_zh": r["name"][:60], "contract_code": r["contract"], "kind": "futures",
                              "source": SOURCE}
    for name, (code, kind) in CONTRACT_NAMES.items():
        out[name] = {"name_zh": name, "contract_code": code, "kind": kind, "source": "static"}
    return list(out.values())


def latest_date(rows: list[dict[str, Any]], *keys: str) -> date | None:
    """Newest date among ``rows``' ``keys`` (for ``dataset_status``)."""
    dates = [r[k] for r in rows for k in keys if isinstance(r.get(k), date)]
    return max(dates) if dates else None
