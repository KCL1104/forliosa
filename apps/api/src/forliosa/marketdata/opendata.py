"""Parsers for official open-data datasets archived by ``forliosa.archive``.

Every field name below was read from a live response on 2026-11-12 (trimmed copies are the test
fixtures in ``tests/archive/fixtures``) and checked against the swagger files
(``https://openapi.twse.com.tw/v1/swagger.json``, ``https://www.tpex.org.tw/openapi/swagger.json``).
Parsers are pure: rows in, plain dicts out (ready for the archive upserts).

TWSE OpenAPI (``https://openapi.twse.com.tw/v1``; latest day only; dates ROC "1151111")
* ``/exchangeReport/TWT84U`` 上市個股股價升降幅度 — Code, TodayLimitUp, TodayOpeningRefPrice,
  TodayLimitDown, PreviousDayPrice, LastTradingDay. "Today" = the trading day after LastTradingDay.
* ``/exchangeReport/MI_MARGN`` 融資融券餘額 — Chinese keys 股票代號, 融資今日餘額, 融資限額, 融券今日餘額
  (lots). The dataset has no date field: the archive job stamps it with the latest trading date.
* ``/announcement/notice`` 當日注意股票 — Code, Name, TradingInfoForAttention, Date, ClosingPrice; when
  nothing was announced it returns a single placeholder row with empty Code.
* ``/announcement/punish`` 處置股票 — Date, Code, Name, ReasonsOfDisposition, DispositionPeriod
  ("115/11/09～115/11/13"), DispositionMeasures, Detail.
* ``/opendata/t187ap04_L`` 每日重大訊息 — 公司代號, 發言日期, 發言時間, ``"主旨 "`` (note the trailing
  space in the key), 說明, 事實發生日. Keys are stripped before use.
* ``/opendata/t187ap06_L_{ci,basi,bd,fh,ins,mim}`` 綜合損益表 — 年度, 季別, 公司代號, 營業收入, 營業毛利（毛損）,
  營業利益（損失）, 本期淨利（淨損）, 淨利（淨損）歸屬於母公司業主, 基本每股盈餘（元）. **Year-to-date** values in
  thousand NT$ (6488 2026Q3 營業收入 44,069,861 = the sum of its three quarters in shioaji-data).
* ``/opendata/t187ap07_L_*`` 資產負債表 — 資產總計, 負債總計, 權益總計, 每股參考淨值 (balances).
* ``/opendata/t187ap17_L`` 營益分析 — 毛利率(%)(營業毛利)/(營業收入), 營業利益率(%)…, 稅後純益率(%)….
* ``/opendata/t187ap41_L`` 股東會 — 公司代號, 股東常(臨時)會, 開會日期, 開會地點.
* ``/exchangeReport/TWT48U_ALL`` 除權除息預告 — parsed by :func:`forliosa.marketdata.twse.parse_twt48u_all`.
* ``/opendata/t187ap05_L`` 每月營業收入彙總表 — 出表日期, 資料年月 ("11510"), 公司代號, 營業收入-當月營收 (thousand
  NT$), 營業收入-去年同月增減(%), 營業收入-上月比較增減(%). No filing date per company.
* ``/news/newsList`` 證交所新聞 — Title, Url (a www.twse.com.tw content page; linked, never fetched), Date.
* ``/opendata/t187ap47_L`` 基金基本資料彙總表 — 基金代號, 基金簡稱, 基金類型, 標的指數/追蹤指數名稱, 成立日期,
  上市日期 ….
* ``/holidaySchedule/holidaySchedule`` 市場開休市日期 — Name, Date, Weekday, Description; also lists trading-day
  markers (「…開始交易日」「…最後交易日」) and settlement-only days (「市場無交易，僅辦理結算交割作業」 = closed).
* ``/exchangeReport/MI_INDEX`` 每日收盤行情-大盤統計資訊 — 日期, 指數 (267 names incl. 發行量加權股價報酬指數),
  收盤指數, 漲跌 (+/-), 漲跌點數 (unsigned, "1,545.23"), 漲跌百分比 (signed), 特殊處理註記. Latest day only.
* ``/indicesReport/MFI94U`` 發行量加權股價報酬指數 — Date (ROC), TAIEXTotalReturnIndex; the whole current month
  (2026-11-11: 102,340.20, the same as MI_INDEX's 發行量加權股價報酬指數).
* ``/opendata/t187ap45_L`` 上市公司股利分派情形 — 出表日期, 公司代號, 決議（擬議）進度, 股利年度, 股利所屬年(季)度
  (年度／上半年／下半年／第1季…), 股利所屬期間 ("1150701~1150930"), 期別, 董事會（擬議）股利分派日, 股東會日期,
  股東配發-盈餘分配之現金股利(元/股), 股東配發-法定盈餘公積發放之現金(元/股), 股東配發-資本公積發放之現金(元/股),
  股東配發-股東配發之現金(股利)總金額(元), 股東配發-盈餘轉增資配股(元/股), …法定盈餘公積轉增資配股, …資本公積轉增資配股,
  股東配發-股東配股總股數(股). No ex-date (that comes later in TWT48U_ALL).
* ``/opendata/t187ap03_L`` 上市公司基本資料 — 出表日期, 公司代號, 公司名稱, 公司簡稱, 產業別 (code "24"), 成立日期,
  上市日期 (Gregorian "19940905"), 普通股每股面額, 實收資本額, 特別股, 已發行普通股數或TDR原股發行股數, 英文簡稱, 網址,
  住址, 簽證會計師事務所, 股票過戶機構, 董事長, 總經理 … Kept since 2026-11-12 (decision 6): the 縣市 of 住址, the firm
  names, 董事長 and 總經理 as published (overwritten daily, no history). Not read: 發言人, 代理發言人, 簽證會計師 names,
  phones, fax, e-mail, 營利事業統一編號.
* 重大訊息 符合條款 seen live: 第31款 = board approval of a financial report (說明 has 「財務報告或年度自結財務資訊
  報導期間 起訖日期: 115/01/01~115/09/30」), 第12款 = 法人說明會 (事實發生日 = the conference date; 說明 has
  「召開法人說明會之日期：115/11/23」), 第51款／第53款 = monthly revenue announcements and corrections.

TPEx OpenAPI (``https://www.tpex.org.tw/openapi/v1``)
* ``tpex_mainboard_daily_close_quotes`` — also NextReferencePrice, NextLimitUp, NextLimitDown (for the
  trading day after Date).
* ``tpex_mainboard_peratio_analysis`` — Date, SecuritiesCompanyCode, PriceEarningRatio, YieldRatio (%),
  PriceBookRatio.
* ``tpex_mainboard_margin_balance`` — MarginPurchaseBalance, MarginPurchaseQuota, ShortSaleBalance (lots).
* ``tpex_3insti_daily_trading`` — in shares: ``ForeignInvestorsInclude MainlandAreaInvestors-Difference``
  (foreign incl. foreign dealers), ``SecuritiesInvestmentTrustCompanies-Difference``,
  ``Dealers-Difference`` (all dealers), ``TotalDifference`` (6488 2026-11-11: 1,265,318 − 405,182 +
  442,393 = 1,302,529). Key spellings (spaces included) are the upstream ones.
* ``tpex_3insti_qfii`` — PercentageOfSharesOC/FMIHeld ("29.49%"), CurrentlySharesOC/FIHeld.
* ``tpex_exright_prepost`` — ExRrightsExDividendDate, ExRrightsExDividend, StockDividendRatio,
  CashDividend ("尚未公告" when not announced).
* ``tpex_trading_warning_information`` (注意) — Date, SecuritiesCompanyCode, TradingInformation.
* ``tpex_disposal_information`` (處置) — Date, DispositionPeriod ("1151112~1151118"), DispositionReasons,
  DisposalCondition.
* ``mopsfin_t187ap04_O`` 重大訊息 — 發言日期, SecuritiesCompanyCode, 主旨, 符合條款, 事實發生日, 說明.
* ``mopsfin_t187ap05_O`` 每月營業收入彙總表 — the same Chinese keys as ``t187ap05_L``.
* ``mopsfin_t187ap03_O`` 上櫃股票基本資料 — Date, SecuritiesCompanyCode, CompanyName, CompanyAbbreviation,
  SecuritiesIndustryCode, DateOfIncorporation, DateOfListing, Paidin.Capital.NTDollars, IssueShares, Symbol,
  WebAddress …
* ``tpex_exright_daily`` 除權除息計算結果 — Date (= the ex-date), ClosePriceBeforeExRightsDiviend, ExRightsDiviendQuote
  (unrounded), OpeningReferencePrice (the official reference, 3680 2026-11-12: 435.50 -> 425.50), LimitUp, LimitDown,
  CashDivdend (sic), StockDividend (權值), ExRightsDiviend (除權／除息).
* ``tpex_index`` 櫃買指數 (Gregorian Date "20261102", Open, High, Low, Close, Change) and ``tpex_reward_index``
  (ROC Date, TPExIndex, TPExTotalReturnIndex): the current month.
* ``mopsfin_t187ap06_O_*`` (Year, Season, SecuritiesCompanyCode + the same Chinese line items),
  ``mopsfin_t187ap07_O_*`` (公司代號 …), ``mopsfin_187ap17_O`` (Year, 季別, 毛利率, 營業利益率, 稅後純益率),
  ``t187ap41_O`` (公司代號, 開會日期). Industries without TPEx companies (``07_O_ins``, ``07_O_mim`` …) return one
  blank row (empty code and year, 出表日期 1100616): it is skipped and never overwrites archived statements. The
  securities-firm variant (``06_O_bd``) spells some items differently (收益, 營業利益, 淨利（損）歸屬於母公司業主).

TDCC open data ``https://opendata.tdcc.com.tw/getOD.ashx?id=1-5`` (CSV, current week only):
資料日期, 證券代號 (space padded), 持股分級 (1–15, 16 = 差異數調整, 17 = 合計), 人數, 股數, 占集保庫存數比例%.

The TWSE / TPEx **websites** (T86, MI_QFIIS, peQryDate …) are not used: their terms forbid automated
downloads without written consent (docs/research/data-sources-licensing.md).
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from datetime import date
from decimal import Decimal
from typing import Any

from forliosa.marketdata.base import parse_decimal, parse_int, parse_tw_date, tw_symbol

# Stocks (4 digits, incl. KY) and funds/ETFs/ETNs ("00…"); warrants, bonds and TDR warrants are skipped.
_CODE = re.compile(r"^(\d{4}|00\d{2,4}[A-Z]?)$")

TDCC_LEVELS = {
    1: "1–999 股", 2: "1–5 張", 3: "5–10 張", 4: "10–15 張", 5: "15–20 張", 6: "20–30 張", 7: "30–40 張",
    8: "40–50 張", 9: "50–100 張", 10: "100–200 張", 11: "200–400 張", 12: "400–600 張", 13: "600–800 張",
    14: "800–1,000 張", 15: "1,000 張以上",
}


def is_listed_code(code: str) -> bool:
    return bool(_CODE.match(code.strip()))


def _strip_keys(row: dict[str, Any]) -> dict[str, Any]:
    return {str(k).strip(): v for k, v in row.items()}


def _text(value: Any) -> str:
    return str(value or "").replace("\r\n", "\n").strip()


def _positive(value: Any) -> Decimal | None:
    d = parse_decimal(value)
    return d if d is not None and d > 0 else None


def _pct(value: Any) -> Decimal | None:
    d = parse_decimal(str(value or "").replace("%", ""))
    return d / 100 if d is not None else None


def event_key(*parts: Any) -> str:
    raw = "|".join(str(p) for p in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]


def _roc_range(value: Any) -> tuple[date | None, date | None]:
    """'115/11/09～115/11/13' or '1151112~1151118' -> (start, end)."""
    parts = re.split(r"[～~－-]", str(value or "").strip())
    if len(parts) != 2:
        return None, None
    return parse_tw_date(parts[0].strip()), parse_tw_date(parts[1].strip())


# -- TWSE OpenAPI ----------------------------------------------------------------------------------
def parse_twt84u(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """-> [{code, last_trading_day, reference_price, limit_up, limit_down, previous_close}]."""
    out = []
    for r in rows:
        code = _text(r.get("Code"))
        ref = _positive(r.get("TodayOpeningRefPrice"))
        last = parse_tw_date(r.get("LastTradingDay"))
        if not is_listed_code(code) or ref is None or last is None:
            continue
        out.append({"code": code, "last_trading_day": last, "reference_price": ref,
                    "limit_up": _positive(r.get("TodayLimitUp")), "limit_down": _positive(r.get("TodayLimitDown")),
                    "previous_close": _positive(r.get("PreviousDayPrice"))})
    return out


def parse_mi_margn(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        code = _text(r.get("股票代號"))
        if not is_listed_code(code):
            continue
        out.append({"code": code, "margin_balance": parse_int(r.get("融資今日餘額")),
                    "short_balance": parse_int(r.get("融券今日餘額")), "margin_limit": parse_int(r.get("融資限額"))})
    return out


def parse_twse_notice(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """注意股票 -> events (type attention). The 'nothing today' placeholder row is skipped."""
    out = []
    for r in rows:
        code, d = _text(r.get("Code")), parse_tw_date(r.get("Date"))
        if not code or d is None:
            continue
        info = _text(r.get("TradingInfoForAttention"))
        out.append({"code": code, "market": "TWSE", "date": d, "end_date": None, "type": "attention",
                    "title": "列為注意股票", "detail": info, "data": {"count": _text(r.get("NumberOfAnnouncement"))},
                    "key": event_key("twse-attention", code, d)})
    return out


def parse_twse_punish(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        code, d = _text(r.get("Code")), parse_tw_date(r.get("Date"))
        if not code or d is None:
            continue
        start, end = _roc_range(r.get("DispositionPeriod"))
        measures = _text(r.get("DispositionMeasures"))
        out.append({"code": code, "market": "TWSE", "date": start or d, "end_date": end, "type": "disposition",
                    "title": f"處置股票（{measures or '處置'}）", "detail": _text(r.get("Detail")),
                    "data": {"reason": _text(r.get("ReasonsOfDisposition")), "announced": d.isoformat()},
                    "key": event_key("twse-disposition", code, d, start)})
    return out


def parse_material_info(rows: list[dict[str, Any]], market: str) -> list[dict[str, Any]]:
    """t187ap04_L / mopsfin_t187ap04_O 重大訊息."""
    out = []
    for raw in rows:
        r = _strip_keys(raw)
        code = _text(r.get("公司代號") or r.get("SecuritiesCompanyCode"))
        d = parse_tw_date(r.get("發言日期"))
        title = _text(r.get("主旨")).replace("\n", "")
        if not code or d is None or not title:
            continue
        fact = parse_tw_date(r.get("事實發生日"))
        out.append({"code": code, "market": market, "date": d, "end_date": None, "type": "material_info",
                    "title": title, "detail": _text(r.get("說明"))[:2000],
                    "data": {"time": _text(r.get("發言時間")), "clause": _text(r.get("符合條款")),
                             "fact_date": fact.isoformat() if fact else None},
                    "key": event_key("material", market, code, d, _text(r.get("發言時間")), title)})
    return out


def parse_monthly_revenue(rows: list[dict[str, Any]], market: str) -> list[dict[str, Any]]:
    """t187ap05_L / mopsfin_t187ap05_O 每月營業收入彙總表 -> [{code, market, period, published, revenue, …}].

    Keys (live 2026-11-12): 出表日期 ("1151111"), 資料年月 ("11510" = 2026-10), 公司代號, 營業收入-當月營收
    (thousand NT$), 營業收入-上月比較增減(%), 營業收入-去年同月增減(%). There is no per-company filing date:
    the archive records the day a (company, month) row first appears (see ``Archiver._revenue``).
    """
    out = []
    for raw in rows:
        r = _strip_keys(raw)
        code = _text(r.get("公司代號") or r.get("SecuritiesCompanyCode"))
        m = re.fullmatch(r"(\d{2,3})(\d{2})", _text(r.get("資料年月")))
        if not is_listed_code(code) or not m or not 1 <= int(m.group(2)) <= 12:
            continue
        out.append({"code": code, "market": market, "period": f"{int(m.group(1)) + 1911}-{int(m.group(2)):02d}",
                    "published": parse_tw_date(r.get("出表日期")),
                    "revenue": parse_int(r.get("營業收入-當月營收")),
                    "yoy_pct": _pct(r.get("營業收入-去年同月增減(%)")),
                    "mom_pct": _pct(r.get("營業收入-上月比較增減(%)"))})
    return out


def parse_shareholder_meetings(rows: list[dict[str, Any]], market: str) -> list[dict[str, Any]]:
    """t187ap41_L / t187ap41_O 股東常（臨時）會."""
    out = []
    for raw in rows:
        r = _strip_keys(raw)
        code = _text(r.get("公司代號"))
        d = parse_tw_date(r.get("開會日期"))
        if not code or d is None:
            continue
        kind = _text(r.get("股東常(臨時)會")) or "股東會"
        title = "股東臨時會" if "臨時" in kind else "股東常會"
        out.append({"code": code, "market": market, "date": d, "end_date": None, "type": "shareholder_meeting",
                    "title": title, "detail": _text(r.get("開會地點")), "data": {},
                    "key": event_key("meeting", market, code, d, kind)})
    return out


def parse_twt48u_events(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """TWT48U_ALL 除權除息預告 -> ex_dividend events (cash per share, stock shares per share)."""
    out = []
    for r in rows:
        code, d = _text(r.get("Code")), parse_tw_date(r.get("Date"))
        if not code or d is None:
            continue
        cash = parse_decimal(r.get("CashDividend"))
        ratio = parse_decimal(r.get("StockDividendRatio"))
        kind = _text(r.get("Exdividend"))  # 息 / 權 / 權息
        out.append(_ex_event(code, "TWSE", d, kind, cash, ratio))
    return out


def parse_tpex_exright_events(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        code, d = _text(r.get("SecuritiesCompanyCode")), parse_tw_date(r.get("ExRrightsExDividendDate"))
        if not code or d is None:
            continue
        cash = parse_decimal(r.get("CashDividend"))  # None when "尚未公告"
        ratio = parse_decimal(r.get("StockDividendRatio"))
        out.append(_ex_event(code, "TPEX", d, _text(r.get("ExRrightsExDividend")), cash, ratio))
    return out


def _ex_event(code: str, market: str, d: date, kind: str, cash: Decimal | None, ratio: Decimal | None) -> dict:
    parts = []
    if cash:
        parts.append(f"現金股利 {cash.normalize():f} 元")
    if ratio:
        parts.append(f"配股率 {ratio.normalize():f}")
    detail = "、".join(parts) or "金額尚未公告"
    label = "除權息" if "權" in kind and "息" in kind else ("除權" if "權" in kind else "除息")
    return {"code": code, "market": market, "date": d, "end_date": None, "type": "ex_dividend",
            "title": label, "detail": detail,
            "data": {"cash": str(cash) if cash is not None else None,
                     "stock_ratio": str(ratio) if ratio is not None else None},
            "key": event_key("ex", market, code, d)}


_INCOME_FIELDS = {
    "revenue": ("營業收入", "淨收益", "收益合計", "收入", "收益"),
    "gross_profit": ("營業毛利（毛損）淨額", "營業毛利（毛損）"),
    "operating_income": ("營業利益（損失）", "營業利益"),
    "pretax_income": ("稅前淨利（淨損）", "繼續營業單位稅前損益", "繼續營業單位稅前淨利（淨損）"),
    "net_income": ("本期淨利（淨損）", "本期稅後淨利（淨損）"),
    "net_income_parent": ("淨利（淨損）歸屬於母公司業主", "淨利（損）歸屬於母公司業主"),
    "eps": ("基本每股盈餘（元）",),
}
_BALANCE_FIELDS = {
    "total_assets": ("資產總計", "資產總額"),
    "total_liabilities": ("負債總計", "負債總額"),
    "equity": ("權益總計", "權益總額"),
    "equity_parent": ("歸屬於母公司業主之權益合計",),
    "bvps": ("每股參考淨值",),
}


def _period_of(r: dict[str, Any]) -> str | None:
    y = parse_int(r.get("年度") or r.get("Year"))
    q = parse_int(r.get("季別") or r.get("Season"))
    if not y or not q or not 1 <= q <= 4:
        return None
    return f"{y + 1911}Q{q}"


def _pick(r: dict[str, Any], fields: dict[str, tuple[str, ...]]) -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for name, keys in fields.items():
        value = None
        for k in keys:
            d = parse_decimal(r.get(k))
            if d is not None:
                value = str(d)
                break
        out[name] = value
    return out


def parse_statements(rows: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    """t187ap06 (kind income_ytd) / t187ap07 (kind balance) rows -> [{code, period, kind, values}]."""
    fields = _INCOME_FIELDS if kind == "income_ytd" else _BALANCE_FIELDS
    out = []
    for raw in rows:
        r = _strip_keys(raw)
        code = _text(r.get("公司代號") or r.get("SecuritiesCompanyCode"))
        period = _period_of(r)
        if not code or period is None:
            continue
        values = _pick(r, fields)
        if all(v is None for v in values.values()):
            continue
        out.append({"code": code, "period": period, "kind": kind, "values": values})
    return out


def parse_profit_analysis(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """t187ap17_L / mopsfin_187ap17_O 營益分析 (percent -> fraction)."""
    out = []
    for raw in rows:
        r = _strip_keys(raw)
        code = _text(r.get("公司代號") or r.get("SecuritiesCompanyCode"))
        period = _period_of(r)
        if not code or period is None:
            continue

        def col(*needles: str, r=r) -> str | None:
            for k, v in r.items():
                if all(n in k for n in needles):
                    d = _pct(v)
                    return str(d) if d is not None else None
            return None

        out.append({"code": code, "period": period, "kind": "margins",
                    "values": {"gross": col("毛利率"), "operating": col("營業利益率"), "net": col("稅後純益率")}})
    return out


_TRADING_MARKERS = ("開始交易", "最後交易")


def parse_holidays(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """holidaySchedule (Name, Date, Weekday, Description) -> [{date, name, description, is_trading_day}].

    The schedule mixes closures with trading-day markers: 「國曆新年開始交易日」「農曆春節前最後交易日」 are
    trading days; 「市場無交易，僅辦理結算交割作業」 is a closure (settlement only, no trading).
    """
    out = []
    for r in rows:
        d = parse_tw_date(r.get("Date"))
        name = _text(r.get("Name"))
        if d is None or not name:
            continue
        description = re.sub(r"<[^>]+>", "", _text(r.get("Description"))).strip()
        out.append({"date": d, "name": name[:100], "description": description,
                    "is_trading_day": any(m in name for m in _TRADING_MARKERS)})
    return out


_NEWS_CODE = re.compile(r"(?:公司代號|股票代號|代號)\s*[：:]?\s*(\d{4,6}[A-Z]?)")


def parse_twse_news(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """/news/newsList 證交所新聞 — Title, Url (www.twse.com.tw content page), Date (ROC). ``code`` is the company
    code when the title names one (「台揚科技股份有限公司（台揚，公司代號：2314）…」), else ``None``."""
    out = []
    for r in rows:
        title, url, d = _text(r.get("Title")), _text(r.get("Url")), parse_tw_date(r.get("Date"))
        if not title or d is None:
            continue
        m = _NEWS_CODE.search(title)
        out.append({"code": m.group(1) if m else None, "date": d, "title": title[:500],
                    "url": url if url.startswith("https://") else None, "key": event_key("twse-news", url or title, d)})
    return out


_FUND_FIELDS = {
    "short_name": "基金簡稱", "name": "基金中文名稱", "english_name": "基金英文名稱", "fund_type": "基金類型",
    "index_name": "標的指數/追蹤指數名稱", "custom_index": "標的指數是否為客製化或需揭露相關資訊之指數",
    "foreign_components": "是否包含國外成分股", "units": "發行單位數/轉換數", "custodian": "保管機構",
    "agent": "總代理人",
}


def parse_fund_profiles(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """t187ap47_L 基金基本資料彙總表 (keys verified live 2026-11-12): 出表日期, 基金代號, 基金簡稱, 基金類型,
    標的指數/追蹤指數名稱, 成立日期, 上市日期, 發行單位數/轉換數, 保管機構 … People's names, phones and
    addresses (基金經理人, 經理公司董事長／發言人…) are deliberately not kept."""
    out = []
    for raw in rows:
        r = _strip_keys(raw)
        code = _text(r.get("基金代號"))
        d = parse_tw_date(r.get("出表日期"))
        if not is_listed_code(code) or d is None:
            continue
        values: dict[str, Any] = {k: _text(r.get(src)) or None for k, src in _FUND_FIELDS.items()}
        for k, src in (("established", "成立日期"), ("listed", "上市日期")):
            day = parse_tw_date(r.get(src))
            values[k] = day.isoformat() if day else None
        units = parse_int(r.get("發行單位數/轉換數"))
        values["units"] = units
        out.append({"code": code, "date": d, "values": values})
    return out


# -- TPEx OpenAPI ----------------------------------------------------------------------------------
def parse_tpex_reference(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """tpex_mainboard_daily_close_quotes -> next trading day's reference price and limits."""
    out = []
    for r in rows:
        code = _text(r.get("SecuritiesCompanyCode"))
        d = parse_tw_date(r.get("Date"))
        ref = _positive(r.get("NextReferencePrice"))
        if not is_listed_code(code) or d is None or ref is None:
            continue
        out.append({"code": code, "last_trading_day": d, "reference_price": ref,
                    "limit_up": _positive(r.get("NextLimitUp")), "limit_down": _positive(r.get("NextLimitDown"))})
    return out


def parse_tpex_peratio(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        code, d = _text(r.get("SecuritiesCompanyCode")), parse_tw_date(r.get("Date"))
        if not is_listed_code(code) or d is None:
            continue
        per = _positive(r.get("PriceEarningRatio"))
        pbr = _positive(r.get("PriceBookRatio"))
        dy = _pct(r.get("YieldRatio"))
        out.append({"code": code, "date": d, "per": per, "pbr": pbr, "dividend_yield": dy})
    return out


def parse_tpex_margin(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        code, d = _text(r.get("SecuritiesCompanyCode")), parse_tw_date(r.get("Date"))
        if not is_listed_code(code) or d is None:
            continue
        out.append({"code": code, "date": d, "margin_balance": parse_int(r.get("MarginPurchaseBalance")),
                    "short_balance": parse_int(r.get("ShortSaleBalance")),
                    "margin_limit": parse_int(r.get("MarginPurchaseQuota"))})
    return out


def _get(r: dict[str, Any], *names: str) -> Any:
    for n in names:
        if n in r:
            return r[n]
    stripped = {k.replace(" ", ""): v for k, v in r.items()}
    for n in names:
        if n.replace(" ", "") in stripped:
            return stripped[n.replace(" ", "")]
    return None


def parse_tpex_institutional(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        code, d = _text(r.get("SecuritiesCompanyCode")), parse_tw_date(r.get("Date"))
        if not is_listed_code(code) or d is None:
            continue
        foreign = parse_int(_get(r, "ForeignInvestorsInclude MainlandAreaInvestors-Difference"))
        trust = parse_int(_get(r, "SecuritiesInvestmentTrustCompanies-Difference"))
        dealer = parse_int(_get(r, "Dealers-Difference"))
        if foreign is None or trust is None or dealer is None:
            continue
        total = parse_int(_get(r, "TotalDifference"))
        out.append({"code": code, "date": d, "foreign_net": foreign, "trust_net": trust, "dealer_net": dealer,
                    "total_net": total if total is not None else foreign + trust + dealer})
    return out


def parse_tpex_qfii(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        code, d = _text(r.get("SecuritiesCompanyCode")), parse_tw_date(r.get("Date"))
        pct = _pct(r.get("PercentageOfSharesOC/FMIHeld"))
        if not is_listed_code(code) or d is None or pct is None:
            continue
        out.append({"code": code, "date": d, "pct": pct, "shares": parse_int(r.get("CurrentlySharesOC/FIHeld"))})
    return out


def parse_tpex_warning(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        code, d = _text(r.get("SecuritiesCompanyCode")), parse_tw_date(r.get("Date"))
        if not code or d is None:
            continue
        out.append({"code": code, "market": "TPEX", "date": d, "end_date": None, "type": "attention",
                    "title": "列為注意股票", "detail": _text(r.get("TradingInformation")), "data": {},
                    "key": event_key("tpex-attention", code, d)})
    return out


def parse_tpex_disposal(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        code, d = _text(r.get("SecuritiesCompanyCode")), parse_tw_date(r.get("Date"))
        if not code or d is None:
            continue
        start, end = _roc_range(r.get("DispositionPeriod"))
        out.append({"code": code, "market": "TPEX", "date": start or d, "end_date": end, "type": "disposition",
                    "title": "處置股票", "detail": _text(r.get("DisposalCondition"))[:2000],
                    "data": {"reason": _text(r.get("DispositionReasons")), "announced": d.isoformat()},
                    "key": event_key("tpex-disposition", code, d, start)})
    return out


def parse_tpex_exright_daily(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """tpex_exright_daily 除權除息計算結果 -> [{code, date, kind, prev_close, ex_quote, reference_price, limits, …}]."""
    out = []
    for r in rows:
        code, d = _text(r.get("SecuritiesCompanyCode")), parse_tw_date(r.get("Date"))
        ref = _positive(r.get("OpeningReferencePrice"))
        if not is_listed_code(code) or d is None or ref is None:
            continue
        cash = parse_decimal(r.get("CashDivdend") or r.get("CashDividend"))
        out.append({"code": code, "date": d, "kind": _text(r.get("ExRightsDiviend"))[:8],
                    "prev_close": _positive(r.get("ClosePriceBeforeExRightsDiviend")),
                    "ex_quote": _positive(r.get("ExRightsDiviendQuote")), "reference_price": ref,
                    "limit_up": _positive(r.get("LimitUp")), "limit_down": _positive(r.get("LimitDown")),
                    "cash_dividend": cash, "stock_dividend": parse_decimal(r.get("StockDividend"))})
    return out


# -- indices ---------------------------------------------------------------------------------------
TAIEX_TR = "發行量加權股價報酬指數"
TPEX_INDEX = "櫃買指數"
TPEX_TR = "櫃買報酬指數"


def parse_mi_index(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """MI_INDEX -> [{name, date, close, change, change_pct}] (漲跌點數 is unsigned; the sign is in 漲跌)."""
    out = []
    for r in rows:
        name, d = _text(r.get("指數")), parse_tw_date(r.get("日期"))
        close = _positive(r.get("收盤指數"))
        if not name or d is None or close is None:
            continue
        points = parse_decimal(r.get("漲跌點數"))
        if points is not None and _text(r.get("漲跌")) == "-":
            points = -abs(points)
        change_pct = _pct(r.get("漲跌百分比")) if parse_decimal(r.get("漲跌百分比")) is not None else None
        out.append({"name": name[:100], "date": d, "close": close, "change": points, "change_pct": change_pct})
    return out


def parse_mfi94u(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """MFI94U (the current month of 發行量加權股價報酬指數) -> [{name, date, close}]."""
    out = []
    for r in rows:
        d, close = parse_tw_date(r.get("Date")), _positive(r.get("TAIEXTotalReturnIndex"))
        if d is not None and close is not None:
            out.append({"name": TAIEX_TR, "date": d, "close": close})
    return out


def parse_tpex_index(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """tpex_index (the current month of 櫃買指數 OHLC) -> [{name, date, open, high, low, close, change}]."""
    out = []
    for r in rows:
        d, close = parse_tw_date(r.get("Date")), _positive(r.get("Close"))
        if d is None or close is None:
            continue
        out.append({"name": TPEX_INDEX, "date": d, "open": _positive(r.get("Open")), "high": _positive(r.get("High")),
                    "low": _positive(r.get("Low")), "close": close, "change": parse_decimal(r.get("Change"))})
    return out


def parse_tpex_reward_index(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """tpex_reward_index -> 櫃買報酬指數 rows (and 櫃買指數 closes) [{name, date, close}]."""
    out = []
    for r in rows:
        d = parse_tw_date(r.get("Date"))
        if d is None:
            continue
        for name, key in ((TPEX_TR, "TPExTotalReturnIndex"), (TPEX_INDEX, "TPExIndex")):
            close = _positive(r.get(key))
            if close is not None:
                out.append({"name": name, "date": d, "close": close})
    return out


def with_changes(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fill ``change`` / ``change_pct`` from the previous row of the same index (multi-day responses)."""
    out, prev = [], {}
    for r in sorted(rows, key=lambda x: (x["name"], x["date"])):
        p = prev.get(r["name"])
        r = {"change": None, "change_pct": None, **r}
        if p is not None:
            if r.get("change") is None:
                r["change"] = r["close"] - p
            if r.get("change_pct") is None and p:
                r["change_pct"] = ((r["close"] - p) / p).quantize(Decimal("0.00000001"))
        prev[r["name"]] = r["close"]
        out.append(r)
    return out


# -- dividends resolved (t187ap45_L) ---------------------------------------------------------------
_HALF = {"上半年": "H1", "下半年": "H2"}


def _dividend_period(kind: str, year: int, start: date | None) -> str:
    """股利所屬年(季)度 -> "2026Q3" / "2026H1" / "2025" (年度)."""
    m = re.search(r"第\s*([1-4])\s*季", kind)
    if m:
        return f"{year}Q{m.group(1)}"
    if kind in _HALF:
        return f"{year}{_HALF[kind]}"
    if start is not None and kind != "年度" and start.month > 1:
        return f"{year}Q{(start.month - 1) // 3 + 1}"
    return str(year)


def parse_dividend_resolutions(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """t187ap45_L 上市公司股利分派情形 -> one row per (company, 股利所屬期間, 期別). NT$ per share, Decimal."""
    out = []
    for raw in rows:
        r = _strip_keys(raw)
        code = _text(r.get("公司代號"))
        year = parse_int(r.get("股利年度"))
        published = parse_tw_date(r.get("出表日期"))
        start, end = _roc_range(r.get("股利所屬期間"))
        if not is_listed_code(code) or not year or published is None:
            continue
        year += 1911
        start = start or date(year, 1, 1)
        kind = _text(r.get("股利所屬年(季)度"))

        def dec(key: str, r=r) -> Decimal:
            return parse_decimal(r.get(key)) or Decimal(0)

        out.append({
            "code": code, "period_start": start, "period_end": end, "seq": parse_int(r.get("期別")) or 1,
            "dividend_year": year, "period": _dividend_period(kind, year, start),
            "progress": re.sub(r"<[^>]+>", "", _text(r.get("決議（擬議）進度")))[:80],
            "board_date": parse_tw_date(r.get("董事會（擬議）股利分派日")),
            "meeting_date": parse_tw_date(r.get("股東會日期")),
            "cash_earnings": dec("股東配發-盈餘分配之現金股利(元/股)"),
            "cash_legal_reserve": dec("股東配發-法定盈餘公積發放之現金(元/股)"),
            "cash_capital_surplus": dec("股東配發-資本公積發放之現金(元/股)"),
            "stock_earnings": dec("股東配發-盈餘轉增資配股(元/股)"),
            "stock_legal_reserve": dec("股東配發-法定盈餘公積轉增資配股(元/股)"),
            "stock_capital_surplus": dec("股東配發-資本公積轉增資配股(元/股)"),
            "cash_total": parse_int(r.get("股東配發-股東配發之現金(股利)總金額(元)")),
            "stock_total_shares": parse_int(r.get("股東配發-股東配股總股數(股)")),
            "published": published,
        })
    return out


# -- company profiles (t187ap03_L, mopsfin_t187ap03_O) ---------------------------------------------
# 產業別 codes of the TWSE / TPEx industry classification (the datasets publish the code only).
INDUSTRY_CODES = {
    "01": "水泥工業", "02": "食品工業", "03": "塑膠工業", "04": "紡織纖維", "05": "電機機械", "06": "電器電纜",
    "08": "玻璃陶瓷", "09": "造紙工業", "10": "鋼鐵工業", "11": "橡膠工業", "12": "汽車工業", "14": "建材營造業",
    "15": "航運業", "16": "觀光餐旅", "17": "金融保險業", "18": "貿易百貨業", "19": "綜合", "20": "其他業",
    "21": "化學工業", "22": "生技醫療業", "23": "油電燃氣業", "24": "半導體業", "25": "電腦及週邊設備業",
    "26": "光電業", "27": "通信網路業", "28": "電子零組件業", "29": "電子通路業", "30": "資訊服務業",
    "31": "其他電子業", "32": "文化創意業", "33": "農業科技業", "34": "電子商務", "35": "綠能環保",
    "36": "數位雲端", "37": "運動休閒", "38": "居家生活", "80": "管理股票", "91": "存託憑證",
}
_PROFILE_KEYS = {  # ours -> (TWSE key, TPEx key)
    "name": ("公司名稱", "CompanyName"), "short_name": ("公司簡稱", "CompanyAbbreviation"),
    "english_short_name": ("英文簡稱", "Symbol"),
    "par_value": ("普通股每股面額", "ParValueOfCommonStock"),
    "foreign_registration": ("外國企業註冊地國", "Registration"),
}


def parse_company_profiles(rows: list[dict[str, Any]], market: str) -> list[dict[str, Any]]:
    """t187ap03_L (``market`` TWSE) / mopsfin_t187ap03_O (TPEX) -> company facts.

    ``values`` also holds the 「關於」 facts (product owner 2026-11-12, decision 6): ``hq`` (縣市 from the address,
    see :func:`company_data.hq_from_address`; the address itself is not kept), ``registered_in`` (KY etc.),
    ``website`` (https), ``auditor`` (簽證會計師事務所, firm only), ``transfer_agent`` (股務代理, name only) and
    ``chairman`` / ``president`` (董事長、總經理 exactly as published). No other person (spokespeople, CPAs), phone,
    fax, e-mail or tax number is read."""
    from forliosa.marketdata import company_data as cd

    tpex = market == "TPEX"
    out = []
    for raw in rows:
        r = _strip_keys(raw)
        code = _text(r.get("SecuritiesCompanyCode" if tpex else "公司代號"))
        d = parse_tw_date(r.get("Date" if tpex else "出表日期"))
        if not is_listed_code(code) or d is None:
            continue
        ind = _text(r.get("SecuritiesIndustryCode" if tpex else "產業別"))
        values: dict[str, Any] = {k: (_text(r.get(keys[1] if tpex else keys[0])).replace("\u3000", " ").strip() or None)
                                  for k, keys in _PROFILE_KEYS.items()}
        if values["foreign_registration"] in ("－", "-"):
            values["foreign_registration"] = None
        if values["par_value"]:
            values["par_value"] = re.sub(r"\s+", "", values["par_value"])
        incorporated = parse_tw_date(r.get("DateOfIncorporation" if tpex else "成立日期"))
        values["incorporated"] = incorporated.isoformat() if incorporated else None
        values["paid_in_capital"] = parse_int(r.get("Paidin.Capital.NTDollars" if tpex else "實收資本額"))
        values["preferred_shares"] = parse_int(r.get("PreferredStock.shares" if tpex else "特別股"))
        values["private_shares"] = parse_int(r.get("PrivateStock.shares" if tpex else "私募股數"))
        values["registered_in"] = cd.registration_country(values["foreign_registration"])
        values["hq"] = cd.hq_from_address(r.get("Address" if tpex else "住址"), market)
        values["website"] = cd.clean_website(r.get("WebAddress" if tpex else "網址"))
        values["auditor"] = cd.clean_name(r.get("AccountingFirm" if tpex else "簽證會計師事務所"))
        values["transfer_agent"] = cd.clean_name(r.get("StockTransferAgent" if tpex else "股票過戶機構"))
        values["chairman"] = _text(r.get("Chairman" if tpex else "董事長")) or None
        values["president"] = _text(r.get("GeneralManager" if tpex else "總經理")) or None
        shares = parse_int(r.get("IssueShares" if tpex else "已發行普通股數或TDR原股發行股數"))
        out.append({"code": code, "date": d, "industry_code": ind[:4] or None, "industry": INDUSTRY_CODES.get(ind),
                    "listed_date": parse_tw_date(r.get("DateOfListing" if tpex else "上市日期")),
                    "shares_outstanding": shares if shares and shares > 0 else None, "values": values})
    return out


def report_date(rows: list[dict[str, Any]], *keys: str) -> date | None:
    """Newest 出表日期 / Date in a dataset (stale-endpoint checks)."""
    dates = [parse_tw_date(_strip_keys(r).get(k)) for r in rows for k in keys]
    found = [d for d in dates if d is not None]
    return max(found) if found else None


# -- TDCC ------------------------------------------------------------------------------------------
def parse_tdcc_distribution(text: str) -> list[dict[str, Any]]:
    """TDCC 1-5 CSV -> [{code, date, level, holders, shares, pct}] (levels 1–17 kept as published)."""
    reader = csv.reader(io.StringIO(text.lstrip("﻿")))
    header = next(reader, None)
    if not header or "證券代號" not in "".join(header):
        raise ValueError(f"TDCC CSV header changed: {header}")
    out = []
    for row in reader:
        if len(row) < 6:
            continue
        code = row[1].strip()
        d = parse_tw_date(row[0])
        level = parse_int(row[2])
        if not is_listed_code(code) or d is None or level is None:
            continue
        pct = parse_decimal(row[5])
        out.append({"code": code, "date": d, "level": level, "holders": parse_int(row[3]) or 0,
                    "shares": parse_int(row[4]) or 0, "pct": (pct / 100) if pct is not None else Decimal(0)})
    return out


def symbol_for(code: str, market: str) -> str:
    return tw_symbol(code, market)
