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
* ``mopsfin_t187ap04_O`` 重大訊息 — 發言日期, SecuritiesCompanyCode, 主旨, 說明.
* ``mopsfin_t187ap06_O_*`` (Year, Season, SecuritiesCompanyCode + the same Chinese line items),
  ``mopsfin_t187ap07_O_*`` (公司代號 …), ``mopsfin_187ap17_O`` (Year, 季別, 毛利率, 營業利益率, 稅後純益率),
  ``t187ap41_O`` (公司代號, 開會日期).

TDCC open data ``https://opendata.tdcc.com.tw/getOD.ashx?id=1-5`` (CSV, current week only):
資料日期, 證券代號 (space padded), 持股分級 (1–15, 16 = 差異數調整, 17 = 合計), 人數, 股數, 占集保庫存數比例%.

TWSE website (not the OpenAPI; **personal policy only**, see CONTRACT_NOTES):
* ``/rwd/zh/fund/T86?date=YYYYMMDD&selectType=ALLBUT0999&response=json`` 三大法人買賣超日報 — ``fields`` +
  ``data`` arrays (2330 2026-11-11: 6,038,319 + 0 + 2,385,276 + 148,895 = 8,572,490 shares).
* ``/rwd/zh/fund/MI_QFIIS?date=…`` 外資及陸資持股統計 — 全體外資及陸資持股比率 (percent number).
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
        out.append({"code": code, "market": market, "date": d, "end_date": None, "type": "material_info",
                    "title": title, "detail": _text(r.get("說明"))[:2000],
                    "data": {"time": _text(r.get("發言時間")), "clause": _text(r.get("符合條款"))},
                    "key": event_key("material", market, code, d, _text(r.get("發言時間")), title)})
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
    "revenue": ("營業收入", "淨收益", "收益合計", "收入"),
    "gross_profit": ("營業毛利（毛損）淨額", "營業毛利（毛損）"),
    "operating_income": ("營業利益（損失）",),
    "pretax_income": ("稅前淨利（淨損）", "繼續營業單位稅前損益", "繼續營業單位稅前淨利（淨損）"),
    "net_income": ("本期淨利（淨損）", "本期稅後淨利（淨損）"),
    "net_income_parent": ("淨利（淨損）歸屬於母公司業主",),
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


# -- TWSE website (personal policy only) -----------------------------------------------------------
def _table(payload: dict[str, Any]) -> tuple[date | None, list[str], list[list[Any]]]:
    if not isinstance(payload, dict) or payload.get("stat") not in ("OK", "ok"):
        return None, [], []
    return parse_tw_date(payload.get("date")), [str(f).strip() for f in payload.get("fields") or []], \
        list(payload.get("data") or [])


def parse_t86(payload: dict[str, Any]) -> list[dict[str, Any]]:
    d, fields, data = _table(payload)
    if d is None or not data:
        return []
    col = {name: i for i, name in enumerate(fields)}
    foreign_ex, foreign_dealer = "外陸資買賣超股數(不含外資自營商)", "外資自營商買賣超股數"
    need = ("證券代號", foreign_ex, foreign_dealer, "投信買賣超股數", "自營商買賣超股數", "三大法人買賣超股數")
    if any(n not in col for n in need):
        raise ValueError(f"T86 欄位改變：{fields}")
    out = []
    for row in data:
        code = _text(row[col["證券代號"]])
        if not is_listed_code(code):
            continue
        foreign = (parse_int(row[col[foreign_ex]]) or 0) + (parse_int(row[col[foreign_dealer]]) or 0)
        trust = parse_int(row[col["投信買賣超股數"]]) or 0
        dealer = parse_int(row[col["自營商買賣超股數"]]) or 0
        total = parse_int(row[col["三大法人買賣超股數"]])
        out.append({"code": code, "date": d, "foreign_net": foreign, "trust_net": trust, "dealer_net": dealer,
                    "total_net": total if total is not None else foreign + trust + dealer})
    return out


def parse_mi_qfiis(payload: dict[str, Any]) -> list[dict[str, Any]]:
    d, fields, data = _table(payload)
    if d is None or not data:
        return []
    col = {name: i for i, name in enumerate(fields)}
    if "證券代號" not in col or "全體外資及陸資持股比率" not in col:
        raise ValueError(f"MI_QFIIS 欄位改變：{fields}")
    out = []
    for row in data:
        code = _text(row[col["證券代號"]])
        pct = parse_decimal(row[col["全體外資及陸資持股比率"]])
        if not is_listed_code(code) or pct is None:
            continue
        shares = parse_int(row[col["全體外資及陸資持有股數"]]) if "全體外資及陸資持有股數" in col else None
        out.append({"code": code, "date": d, "pct": pct / 100, "shares": shares})
    return out


def symbol_for(code: str, market: str) -> str:
    return tw_symbol(code, market)
