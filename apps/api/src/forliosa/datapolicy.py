"""Data-source policy (``DATA_POLICY``), the source allowlist and the attribution text in ``sources``.

* ``commercial`` (default): only legally commercially usable data — government open data (TWSE / TPEx
  OpenAPI, TDCC open data), shioaji-data's official files and our own archive built from them. Never demo
  data: endpoints return empty data with a 「資料累積中」 note instead.
* ``personal`` (explicit opt-in): demo data fills gaps, and FinMind can be enabled by listing it in
  ``MARKET_DATA_PROVIDERS``; its rows are labelled 「非商用」.
* **Never, in any mode**: the TWSE / TPEx / MIS / MOPS *websites* (their terms forbid automated downloads
  without written consent). Rows archived from them before 2026-11-12 (``twse-web``, ``twse-mis``) are
  ignored by every query.

Attribution: the Open Government Data License v1 (政府資料開放授權條款第 1 版) requires the providing
agency, the dataset name and the year; without it the licence is void from the start. Every ``sources``
entry therefore names its dataset, e.g. 「臺灣證券交易所〈上市個股日本益比、殖利率及股價淨值比〉（2026），
依政府資料開放授權條款第 1 版」. Source *keys* stored with data are provider keys (``twse-openapi`` …); a
key gets its dataset through a *kind* — ``"twse-openapi/valuation"`` — see :func:`tagged` and :data:`DATASETS`.
``GET /meta/attributions`` lists every dataset with the licence notice.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

Policy = Literal["personal", "commercial"]

NON_COMMERCIAL_SUFFIX = "（非商用）"
OGDL = "政府資料開放授權條款第 1 版"
OGDL_URL = "https://data.gov.tw/license"
OGDL_NOTICE = ("此開放資料依政府資料開放授權條款 (Open Government Data License) 進行公眾釋出，"
               "使用者於遵守本條款各項規定之前提下，得利用之。")

TWSE = "臺灣證券交易所"
TPEX = "證券櫃檯買賣中心"
TDCC = "臺灣集中保管結算所"
TWSE_API = "https://openapi.twse.com.tw/v1"
MEETINGS = "公司召開股東常（臨時）會日期、地點及採用電子投票情形等資料彙總表"
TPEX_API = "https://www.tpex.org.tw/openapi/v1"


@dataclass(frozen=True)
class Dataset:
    key: str  # "<provider key>/<kind>"
    agency: str
    title: str
    url: str
    used_for: str


DATASETS: dict[str, Dataset] = {d.key: d for d in (
    Dataset("twse-openapi/price", TWSE, "上市個股日成交資訊", f"{TWSE_API}/exchangeReport/STOCK_DAY_ALL",
            "收盤價、日線、成交量"),
    Dataset("twse-openapi/valuation", TWSE, "上市個股日本益比、殖利率及股價淨值比",
            f"{TWSE_API}/exchangeReport/BWIBBU_ALL", "本益比、殖利率、股價淨值比"),
    Dataset("twse-openapi/reference", TWSE, "上市個股股價升降幅度", f"{TWSE_API}/exchangeReport/TWT84U",
            "參考價、漲跌停"),
    Dataset("twse-openapi/margin", TWSE, "集中市場融資融券餘額", f"{TWSE_API}/exchangeReport/MI_MARGN", "融資融券"),
    Dataset("twse-openapi/ex_dividend", TWSE, "上市股票除權除息預告表", f"{TWSE_API}/exchangeReport/TWT48U_ALL",
            "除權息日、股利"),
    Dataset("twse-openapi/attention", TWSE, "集中市場當日公布注意股票", f"{TWSE_API}/announcement/notice", "注意股票"),
    Dataset("twse-openapi/disposition", TWSE, "集中市場公布處置股票", f"{TWSE_API}/announcement/punish", "處置股票"),
    Dataset("twse-openapi/material_info", TWSE, "上市公司每日重大訊息", f"{TWSE_API}/opendata/t187ap04_L",
            "重大訊息、公告、財報與法說會日期"),
    Dataset("twse-openapi/shareholder_meeting", TWSE, f"上市{MEETINGS}", f"{TWSE_API}/opendata/t187ap41_L", "股東會"),
    Dataset("twse-openapi/revenue", TWSE, "上市公司每月營業收入彙總表", f"{TWSE_API}/opendata/t187ap05_L",
            "月營收公布日"),
    Dataset("twse-openapi/income", TWSE, "上市公司綜合損益表", f"{TWSE_API}/opendata/t187ap06_L_ci", "季報損益"),
    Dataset("twse-openapi/balance", TWSE, "上市公司資產負債表", f"{TWSE_API}/opendata/t187ap07_L_ci", "季報資產負債"),
    Dataset("twse-openapi/margins", TWSE, "上市公司營益分析查詢彙總表", f"{TWSE_API}/opendata/t187ap17_L", "利潤率"),
    Dataset("twse-openapi/calendar", TWSE, "有價證券集中交易市場開（休）市日期",
            f"{TWSE_API}/holidaySchedule/holidaySchedule", "交易日、定期定額扣款日順延"),
    Dataset("twse-openapi/news", TWSE, "證交所新聞", f"{TWSE_API}/news/newsList", "公告"),
    Dataset("twse-openapi/fund", TWSE, "基金基本資料彙總表", f"{TWSE_API}/opendata/t187ap47_L", "ETF 基本資料"),
    Dataset("tpex-openapi/price", TPEX, "上櫃股票行情", f"{TPEX_API}/tpex_mainboard_daily_close_quotes",
            "收盤價、日線、成交量"),
    Dataset("tpex-openapi/valuation", TPEX, "上櫃股票個股本益比、殖利率、股價淨值比",
            f"{TPEX_API}/tpex_mainboard_peratio_analysis", "本益比、殖利率、股價淨值比"),
    Dataset("tpex-openapi/reference", TPEX, "上櫃股票行情", f"{TPEX_API}/tpex_mainboard_daily_close_quotes",
            "參考價、漲跌停（次一交易日）"),
    Dataset("tpex-openapi/margin", TPEX, "上櫃股票融資融券餘額", f"{TPEX_API}/tpex_mainboard_margin_balance",
            "融資融券"),
    Dataset("tpex-openapi/institutional", TPEX, "上櫃股票三大法人買賣明細資訊", f"{TPEX_API}/tpex_3insti_daily_trading",
            "三大法人買賣超"),
    Dataset("tpex-openapi/foreign_holding", TPEX, "上櫃僑外資及陸資持股比例排行表", f"{TPEX_API}/tpex_3insti_qfii",
            "外資持股比率"),
    Dataset("tpex-openapi/ex_dividend", TPEX, "上櫃股票除權除息預告表", f"{TPEX_API}/tpex_exright_prepost",
            "除權息日、股利"),
    Dataset("tpex-openapi/attention", TPEX, "上櫃公布注意股票資訊", f"{TPEX_API}/tpex_trading_warning_information",
            "注意股票"),
    Dataset("tpex-openapi/disposition", TPEX, "上櫃處置有價證券資訊", f"{TPEX_API}/tpex_disposal_information",
            "處置股票"),
    Dataset("tpex-openapi/material_info", TPEX, "上櫃公司每日重大訊息", f"{TPEX_API}/mopsfin_t187ap04_O",
            "重大訊息、公告、財報與法說會日期"),
    Dataset("tpex-openapi/shareholder_meeting", TPEX, f"上櫃{MEETINGS}", f"{TPEX_API}/t187ap41_O", "股東會"),
    Dataset("tpex-openapi/revenue", TPEX, "上櫃公司每月營業收入彙總表", f"{TPEX_API}/mopsfin_t187ap05_O",
            "月營收公布日"),
    Dataset("tpex-openapi/income", TPEX, "上櫃公司綜合損益表", f"{TPEX_API}/mopsfin_t187ap06_O_ci", "季報損益"),
    Dataset("tpex-openapi/balance", TPEX, "上櫃公司資產負債表", f"{TPEX_API}/mopsfin_t187ap07_O_ci", "季報資產負債"),
    Dataset("tpex-openapi/margins", TPEX, "上櫃公司營益分析查詢彙總表", f"{TPEX_API}/mopsfin_187ap17_O", "利潤率"),
    Dataset("tdcc-opendata/distribution", TDCC, "集保戶股權分散表", "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5",
            "大戶持股分級"),
    Dataset("shioaji-data/official",
            "永豐金證券 shioaji-data（彙整臺灣證券交易所、證券櫃檯買賣中心、公開資訊觀測站開放資料）",
            "公司基本資料、每日收盤與市值、月營收、季報", "https://github.com/Sinotrade/shioaji-data",
            "商品主檔、月營收、季報、市值"),
)}

# key -> (label for non-dataset keys, commercially usable)
_SOURCES: dict[str, tuple[str, bool]] = {
    "twse-openapi": (f"{TWSE}〈OpenAPI 開放資料〉", True),
    "tpex-openapi": (f"{TPEX}〈OpenAPI 開放資料〉", True),
    "tdcc-opendata": (f"{TDCC}〈開放資料〉", True),
    "shioaji-data": ("", True),  # labelled through DATASETS["shioaji-data/official"]
    "archive": ("Forliosa 自建存檔（證交所、櫃買中心開放資料）", True),
    "ledger": ("本系統帳本", True),
    "rules": ("Forliosa 規則計算", True),
    "demo": ("示範資料（模擬）", True),
    "finmind": ("FinMind" + NON_COMMERCIAL_SUFFIX, False),
    "yahoo": ("Yahoo Finance" + NON_COMMERCIAL_SUFFIX, False),
    # Removed sources whose rows may still be in an old archive: never served in any mode.
    "twse-mis": ("證交所 MIS 盤中行情・已停用" + NON_COMMERCIAL_SUFFIX, False),
    "twse-web": ("證交所網站資料・已停用" + NON_COMMERCIAL_SUFFIX, False),
}
NEVER_ALLOWED = frozenset({"twse-mis", "twse-web"})
# Provider names (MARKET_DATA_PROVIDERS) that are not commercially usable.
NON_COMMERCIAL_PROVIDERS = frozenset({"finmind", "yahoo"})
_ALIASES = {"twse_openapi": "twse-openapi", "tpex_openapi": "tpex-openapi", "shioaji_data": "shioaji-data",
            "twse_mis": "twse-mis", "jitter": "demo"}


def _key(part: str) -> str:
    part = part.strip().lower().split("/", 1)[0]
    return _ALIASES.get(part, part)


def is_commercial_source(source: str) -> bool:
    """Every part of a composite source (``twse-openapi+shioaji-data``) must be commercially usable."""
    parts = [_key(p) for p in source.split("+") if p.strip()]
    return all(_SOURCES.get(p, ("", False))[1] for p in parts) if parts else True


def allowed(source: str, policy: Policy) -> bool:
    parts = [_key(p) for p in source.split("+") if p.strip()]
    if any(p in NEVER_ALLOWED for p in parts):
        return False
    return policy == "personal" or is_commercial_source(source)


def provider_allowed(name: str, policy: Policy) -> bool:
    return policy == "personal" or name.strip().lower() not in NON_COMMERCIAL_PROVIDERS


def tagged(sources: str | Iterable[str], kind: str) -> list[str]:
    """``"twse-openapi+shioaji_data"`` + ``"price"`` -> ``["twse-openapi/price", "shioaji-data/price"]``."""
    items = sources.split("+") if isinstance(sources, str) else [x for s in sources for x in (s or "").split("+")]
    return [f"{_key(p)}/{kind}" for p in items if p.strip()]


def _year() -> int:
    from forliosa.timeutil import today_taipei

    return today_taipei().year


def attribution(ds: Dataset, year: int | None = None) -> str:
    return f"{ds.agency}〈{ds.title}〉（{year or _year()}），依{OGDL}"


def label(source: str) -> str:
    """User-facing text for a source key, ``key/kind`` names a dataset (licence attribution format)."""
    raw = source.strip()
    key = _key(raw)
    kind = raw.split("/", 1)[1] if "/" in raw else None
    ds = DATASETS.get(f"{key}/{kind}") if kind else None
    if ds is None and key == "shioaji-data":
        ds = DATASETS["shioaji-data/official"]
    if ds is not None:
        return attribution(ds)
    if key in _SOURCES:
        text, commercial = _SOURCES[key]
        if commercial and key in ("twse-openapi", "tpex-openapi", "tdcc-opendata"):
            return f"{text}（{_year()}），依{OGDL}"
        return text
    return raw


def labels(sources: Iterable[str]) -> list[str]:
    """Labels for source keys (composite keys are split on ``+``), de-duplicated in order."""
    out: list[str] = []
    for s in sources:
        for part in (s or "").split("+"):
            if part.strip():
                out.append(label(part))
    return list(dict.fromkeys(out))


def allowed_sources(policy: Policy) -> list[str]:
    """Archive ``source`` values a query may use (exact keys; composite worker rows are matched by parts)."""
    return [k for k, (_, ok) in _SOURCES.items() if k not in NEVER_ALLOWED and (ok or policy == "personal")]


def source_clause(column, policy: Policy):
    """SQL filter for an archive table's ``source`` column under ``policy``.

    Commercial: only commercially usable keys. Personal: anything except the never-allowed sources (rows
    written by the old worker can be composite, e.g. ``twse-mis+shioaji-data``).
    """
    from sqlalchemy import and_, not_

    if policy == "commercial":
        return column.in_(allowed_sources(policy))
    return and_(*[not_(column.contains(k)) for k in sorted(NEVER_ALLOWED)])


def attributions(policy: Policy) -> dict:
    """``GET /meta/attributions``: every dataset this deployment may show, with the licence notice."""
    year = _year()
    items = [{"key": d.key, "agency": d.agency, "dataset": d.title, "url": d.url, "used_for": d.used_for,
              "year": year, "license": OGDL, "license_url": OGDL_URL, "commercial": True,
              "attribution": attribution(d, year)} for d in DATASETS.values()]
    if policy == "personal":
        items.append({"key": "finmind", "agency": "FinMind", "dataset": "FinMind 開放 API（台股資料）",
                      "url": "https://finmind.github.io/", "used_for": "僅在明確設定時：回補、新聞（非商用）",
                      "year": year, "license": "FinMind 使用條款（非商用）", "license_url": "https://finmind.github.io/Disclaimer/",
                      "commercial": False, "attribution": label("finmind")})
    return {
        "policy": policy,
        "notice": [f"{OGDL_NOTICE}", f"政府資料開放授權條款：{OGDL_URL}"],
        "datasets": items,
        "not_used": [
            "臺灣證券交易所網站（T86 三大法人、MI_QFIIS 外資持股等）與基本市況報導 MIS：網站條款禁止未經同意以程式下載",
            "證券櫃檯買賣中心網站歷史查詢、公開資訊觀測站網站：同上，只使用 OpenAPI 版本",
        ],
    }
