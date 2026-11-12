"""Parsers for the stock-page datasets of 2026-11-12 (decisions 4, 6 and 8 in PRODUCT.md「個股頁補強」).

Every field name was read from a live response on 2026-11-12 (trimmed copies are the test fixtures in
``tests/archive/fixtures``). Parsers are pure: rows in, plain dicts out (ready for the archive upserts).

* TWSE ``/opendata/t187ap11_L`` / TPEx ``mopsfin_t187ap11_O`` 董監事持股餘額明細 (monthly, 資料年月 "11509",
  出表日期 "1151020"): 公司代號, 職稱 (「董事本人」「大股東本人」「董事之法人代表人」…), 姓名, 目前持股 ….
  :func:`parse_board_links` keeps **only** rows whose 職稱 contains 「本人」 and whose 姓名 is exactly the full name
  (公司名稱) of a listed or OTC company: a company sitting on another company's board or holding > 10 %. Every other
  row is a natural person (or a representative) and is dropped inside the loop — never stored, counted by name or
  logged. 設質 (pledge) columns are not read.
* TPEx ``tpex50_constituents`` 富櫃五十指數成分股 (daily): Date (ROC), SecuritiesCompanyCode, CompanyName.
* TDCC ``getOD.ashx?id=2-22`` (TWSE) / ``id=2-23`` (TPEx) 有價證券集中保管個別股票異動月分析表 (CSV, the latest
  month only): 資料年月 ("11510"), 股票代號 (space padded), 股票名稱, 本月底保管千股數, 前月底保管千股數, 增減數額,
  增減百分比, 發行千股數, 集保股東戶數. The same row can appear twice (006201 on 2026-11-12): kept once.
* TWSE ``/fund/MI_QFIIS_sort_20`` 集中市場外資及陸資持股前 20 名彙總表 (daily, **no date field**): Rank, Code, Name,
  ShareNumber (發行股數), AvailableShare, SharesHeld, AvailableInvestPer, SharesHeldPer (%), Upperlimit (%).
* TWSE ``/opendata/t187ap46_L_14`` / TPEx ``t187ap46_O_14`` 企業 ESG 資訊揭露－產品品質與安全 (yearly): 報告年度
  (ROC), 公司代號, 依產品類別之產品產量 (free text, e.g. 「達1,500萬片十二吋晶圓約當量」).
* Company profile helpers for t187ap03_L / mopsfin_t187ap03_O (used by ``opendata.parse_company_profiles``):
  :func:`hq_from_address` (Chinese 住址 -> 縣市; TPEx's English Address only when the mapping is certain),
  :func:`clean_website`, :func:`clean_name` (``html.unescape`` + CJK compatibility ideographs).
"""

from __future__ import annotations

import csv
import html
import io
import re
import unicodedata
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from forliosa.marketdata.base import parse_decimal, parse_int, parse_tw_date

_STOCK_CODE = re.compile(r"^\d{4}$")
_FUND_OR_STOCK = re.compile(r"^(\d{4}|00\d{2,4}[A-Z]?)$")
_ROLE_ORDER = ("董事長", "副董事長", "常務董事", "董事", "監察人", "大股東")


def _strip_keys(row: Mapping[str, Any]) -> dict[str, Any]:
    return {str(k).strip(): v for k, v in row.items()}


def _text(value: Any) -> str:
    return str(value or "").replace("　", " ").strip()


def company_name_key(name: Any) -> str:
    """Normalise a company's full name for exact matching: whitespace (incl. full-width) removed, NFKC for the
    CJK compatibility ideographs only; nothing else is changed."""
    s = re.sub(r"\s+", "", str(name or "").replace("　", ""))
    return "".join(unicodedata.normalize("NFKC", c) if "豈" <= c <= "﫿" else c for c in s)


def roc_period(value: Any) -> str | None:
    """'11509' -> '2026-09'."""
    s = str(value or "").strip()
    if not (s.isdigit() and len(s) in (5, 6)):
        return None
    year, month = int(s[:-2]) + 1911, int(s[-2:])
    return f"{year:04d}-{month:02d}" if 1 <= month <= 12 else None


# -- 董監事持股餘額明細 -> company ↔ company links ---------------------------------------------------------------
def _role(title: str) -> str:
    return title.replace("本人", "").strip()


def parse_board_links(rows: list[dict[str, Any]], companies: Mapping[str, tuple[str, str]]) -> list[dict[str, Any]]:
    """t187ap11_L / mopsfin_t187ap11_O -> ``[{code, holder_code, holder_market, roles, shares, period, data_date}]``.

    ``companies`` maps :func:`company_name_key` of every listed / OTC company's full name to ``(code, market)``.
    A row is kept only when its 職稱 contains 「本人」 and its 姓名 is one of those names (and not the company
    itself). Natural persons' rows are skipped without reading anything else from them.
    """
    links: dict[tuple[str, str, str], dict[str, Any]] = {}
    for raw in rows:
        r = _strip_keys(raw)
        title = _text(r.get("職稱"))
        if "本人" not in title:
            continue
        holder = companies.get(company_name_key(r.get("姓名")))
        if holder is None:
            continue  # a natural person (or an unlisted company): never kept
        code = _text(r.get("公司代號"))
        period = roc_period(r.get("資料年月"))
        published = parse_tw_date(r.get("出表日期"))
        if not _STOCK_CODE.match(code) or period is None or published is None or holder[0] == code:
            continue
        key = (code, holder[0], period)
        link = links.setdefault(key, {"code": code, "holder_code": holder[0], "holder_market": holder[1],
                                      "roles": set(), "shares": None, "period": period, "data_date": published})
        link["roles"].add(_role(title))
        shares = parse_int(r.get("目前持股"))
        if shares is not None and (link["shares"] is None or shares > link["shares"]):
            link["shares"] = shares
    out = []
    for link in links.values():
        roles = sorted(link["roles"], key=lambda x: (_ROLE_ORDER.index(x) if x in _ROLE_ORDER else 99, x))
        out.append({**link, "roles": "、".join(roles)[:100]})
    return out


# -- 富櫃五十指數成分股 -------------------------------------------------------------------------------------
def parse_tpex50_constituents(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for raw in rows:
        r = _strip_keys(raw)
        code = _text(r.get("SecuritiesCompanyCode"))
        d = parse_tw_date(r.get("Date"))
        if _STOCK_CODE.match(code) and d is not None:
            out.append({"code": code, "date": d})
    return out


# -- TDCC 2-22 / 2-23: 集保股東戶數 ---------------------------------------------------------------------------
def parse_tdcc_holders(text: str) -> list[dict[str, Any]]:
    """TDCC 2-22 / 2-23 CSV -> ``[{code, period, holders, custody_k_shares, issued_k_shares}]`` (one per code)."""
    reader = csv.reader(io.StringIO(text.lstrip("﻿")))
    header = next(reader, None)
    if not header or "集保股東戶數" not in "".join(header):
        raise ValueError(f"TDCC 2-22/2-23 CSV header changed: {header}")
    out: dict[str, dict[str, Any]] = {}
    for row in reader:
        if len(row) < 9:
            continue
        code = row[1].strip()
        period = roc_period(row[0])
        holders = parse_int(row[8])
        if not _FUND_OR_STOCK.match(code) or period is None or holders is None:
            continue
        out.setdefault(code, {"code": code, "period": period, "holders": holders,
                              "custody_k_shares": parse_int(row[3]), "issued_k_shares": parse_int(row[7])})
    return list(out.values())


# -- 外資及陸資持股前 20 名 -----------------------------------------------------------------------------------
def _pct(value: Any) -> Decimal | None:
    d = parse_decimal(value)
    return d / 100 if d is not None else None


def parse_qfii_top20(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """MI_QFIIS_sort_20 -> ``[{code, rank, pct, shares, issued_shares, available_pct, limit_pct}]`` (fractions)."""
    out = []
    for raw in rows:
        r = _strip_keys(raw)
        code = _text(r.get("Code"))
        rank = parse_int(r.get("Rank"))
        pct = _pct(r.get("SharesHeldPer"))
        if not _FUND_OR_STOCK.match(code) or rank is None or pct is None:
            continue
        out.append({"code": code, "rank": rank, "pct": pct, "shares": parse_int(r.get("SharesHeld")),
                    "issued_shares": parse_int(r.get("ShareNumber")),
                    "available_pct": _pct(r.get("AvailableInvestPer")), "limit_pct": _pct(r.get("Upperlimit"))})
    return out


# -- ESG 產品類別 ---------------------------------------------------------------------------------------------
_NA = {"", "N/A", "NA", "無", "不適用", "-", "－"}


def parse_esg_products(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """t187ap46_L_14 / t187ap46_O_14 -> ``[{code, year, text, date}]`` (only rows with a product text)."""
    out = []
    for raw in rows:
        r = _strip_keys(raw)
        code = _text(r.get("公司代號"))
        text = str(r.get("依產品類別之產品產量") or "").replace("\r\n", "\n").strip()
        year = parse_int(r.get("報告年度"))
        d = parse_tw_date(r.get("出表日期"))
        if not _STOCK_CODE.match(code) or text.upper() in _NA or year is None or d is None:
            continue
        out.append({"code": code, "year": year + 1911 if year < 1911 else year, "text": text[:500], "date": d})
    return out


# -- company profile helpers (t187ap03_L / mopsfin_t187ap03_O) -----------------------------------------------
def clean_name(value: Any) -> str | None:
    """Firm names as published, with HTML entities decoded (「冠恆&#32852;合」 -> 「冠恆聯合」) and CJK compatibility
    ideographs mapped to the unified ones; whitespace trimmed."""
    s = html.unescape(str(value or "")).replace("　", " ")
    s = "".join(unicodedata.normalize("NFKC", c) if "豈" <= c <= "﫿" else c for c in s)
    s = re.sub(r"\s+", " ", s).strip()
    return s or None


_HOST = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")


def clean_website(value: Any) -> str | None:
    """'www.acc.com.tw ' / 'Http://www.x.com.tw/' -> 'https://www.acc.com.tw' / 'https://www.x.com.tw'.

    Always ``https://``; the host lower-cased; a trailing slash on an empty path dropped; anything that does not
    look like a host name -> ``None``."""
    s = re.sub(r"\s+", "", str(value or "")).replace("：", ":")
    if not s or s in ("－", "-", "無"):
        return None
    s = re.sub(r"^(https?)?:?//", "", s, flags=re.IGNORECASE)
    host, _, rest = s.partition("/")
    host = host.lower().rstrip(".")
    if ":" in host or not _HOST.match(host) or "." not in host:
        return None
    path = ("/" + rest) if rest else ""
    if path in ("/", ""):
        path = ""
    return f"https://{host}{path}"[:300]


_POSTAL = re.compile(r"^[\s(（]*\d{3,6}[)）]?\s*")
_COUNTRY_PREFIX = re.compile(r"^(中華民國|台灣省|臺灣省|台灣|臺灣)")
_PARK = re.compile(r"^(?P<city>新竹[市縣]?)?(?P<park>科學(?:工業)?園區)")
_OTHER_PARK = re.compile(r"^(\S{2,4}科學(?:工業)?園區)")
_CITY = re.compile(r"^(\S\S[縣市])")

# English (TPEx Address) -> 縣市; only names that are unambiguous on their own.
_EN_PLACES: tuple[tuple[re.Pattern[str], str], ...] = tuple((re.compile(p), zh) for p, zh in (
    (r"new\s*taipei", "新北市"),
    (r"taipei\s*(county|hsien)", "新北市"),
    (r"(?<!new )taipei\s*city", "台北市"),
    (r"tao\s*-?\s*yuan", "桃園市"),
    (r"tai\s*-?\s*chung", "台中市"),
    (r"tai\s*-?\s*nan", "台南市"),
    (r"kaohsiung", "高雄市"),
    (r"keelung|chi\s*lung", "基隆市"),
    (r"hsin\s*-?\s*chu\s*city", "新竹市"),
    (r"hsin\s*-?\s*chu\s*(county|hsien)", "新竹縣"),
    (r"chia\s*-?\s*yi\s*city", "嘉義市"),
    (r"chia\s*-?\s*yi\s*(county|hsien)", "嘉義縣"),
    (r"miao\s*-?\s*li", "苗栗縣"),
    (r"chang\s*-?\s*hua", "彰化縣"),
    (r"nan\s*-?\s*tou", "南投縣"),
    (r"yun\s*-?\s*lin", "雲林縣"),
    (r"ping\s*-?\s*tung", "屏東縣"),
    (r"\b(yi|i)\s*-?\s*lan\b", "宜蘭縣"),
    (r"hua\s*-?\s*lien", "花蓮縣"),
    (r"tai\s*-?\s*tung", "台東縣"),
    (r"peng\s*-?\s*hu", "澎湖縣"),
    (r"kinmen", "金門縣"),
))
_EN_HSINCHU_PARK = re.compile(r"hsin\s*-?\s*chu\s*science|science[\s-]*(based)?[\s-]*(indust\w*)?[\s-]*park")
_EN_HSINCHU = re.compile(r"hsin\s*-?\s*chu")


def _hq_zh(address: str) -> str | None:
    a = _POSTAL.sub("", address.replace("巿", "市").strip())
    a = _COUNTRY_PREFIX.sub("", a).strip()
    m = _PARK.match(a)
    if m and (m.group("city") or "").startswith("新竹"):
        return "新竹科學園區"
    m = _OTHER_PARK.match(a)
    if m:
        return m.group(1)
    m = _CITY.match(a)
    return m.group(1) if m else None


def _hq_en(address: str) -> str | None:
    a = re.sub(r"\s+", " ", address.replace("　", " ")).lower()
    found = {zh for pattern, zh in _EN_PLACES if pattern.search(a)}
    hsinchu_park = bool(_EN_HSINCHU_PARK.search(a)) and bool(_EN_HSINCHU.search(a))
    if hsinchu_park and found <= {"新竹市", "新竹縣"}:
        return "新竹科學園區"
    return found.pop() if len(found) == 1 else None  # none or several places: not certain


def hq_from_address(address: Any, market: str) -> str | None:
    """Headquarters 縣市 from the published address: TWSE 住址 (Chinese) -> its leading 縣市 (「新竹科學園區」 as
    is); TPEx Address (English) -> only when exactly one unambiguous city / county (or the Hsinchu Science Park)
    is named. Foreign (KY) addresses give ``None`` (the registration country is shown instead)."""
    s = str(address or "").strip()
    if not s:
        return None
    if re.search(r"[一-鿿]", s):
        return _hq_zh(s)
    if market != "TPEX":
        return None
    return _hq_en(s)


def registration_country(value: Any) -> str | None:
    """外國企業註冊地國 'KY 開曼群島   ' -> '開曼群島'; '－' -> None."""
    s = _text(value)
    if not s or s in ("－", "-"):
        return None
    s = re.sub(r"^[A-Z]{2}\s+", "", s).strip()
    return s or None
