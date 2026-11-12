"""Data-source policy (``DATA_POLICY``), the source allowlist and the attribution text in ``sources``.

* ``commercial`` (default): only legally commercially usable data — government open data (TWSE / TPEx
  OpenAPI, TDCC open data, the central bank's 銀行間新臺幣對美元收盤匯率), shioaji-data's official files and our
  own archive built from them. Never demo data: endpoints return empty data with a 「資料累積中」 note instead.
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

Licence status (``Dataset.license_status``, from docs/research/open-data-inventory.md and its catalog):

* ``ogdl`` — the agency publishes the dataset under the OGDL (TWSE swagger links data.gov.tw/license; TPEx,
  TDCC, the TAIFEX institutional / large-trader / put-call datasets and the central bank's 銀行間新臺幣對美元
  收盤匯率 — data.gov.tw 7232 — have matching data.gov.tw OGDL datasets). Served normally, with attribution.
* ``conditional`` — presumed OGDL (same OpenAPI, same agency) but no individual data.gov.tw dataset was found:
  TAIFEX 期貨／選擇權每日交易行情, 每日外幣參考匯率, 選擇權大額交易人, 最後結算價, 保證金, 股票期貨／選擇權標的.
  They are **archived**, but under ``commercial`` they are **not served** until the owner sets
  ``TAIFEX_CONDITIONAL_CONFIRMED=true`` after TAIFEX confirms in writing (:func:`dataset_served`). Under
  ``personal`` (non-commercial, explicit opt-in) they are served. TAIFEX's 每日外幣參考匯率 is archived but no
  longer used at all: USD/TWD comes from the central bank (product owner 2026-11-12).
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
TAIFEX = "臺灣期貨交易所"
CBC = "中央銀行"
TWSE_API = "https://openapi.twse.com.tw/v1"
MEETINGS = "公司召開股東常（臨時）會日期、地點及採用電子投票情形等資料彙總表"
TPEX_API = "https://www.tpex.org.tw/openapi/v1"
TAIFEX_API = "https://openapi.taifex.com.tw/v1"
CBC_API = "https://cpx.cbc.gov.tw/api/OpenData"

LicenseStatus = Literal["ogdl", "conditional"]
CONDITIONAL_NOTE = ("期交所 OpenAPI 的這個資料集在 data.gov.tw 沒有找到對應的政府資料開放授權條款資料集，"
                    "已存檔，但在期交所書面確認可商用前不顯示（TAIFEX_CONDITIONAL_CONFIRMED）")


@dataclass(frozen=True)
class Dataset:
    key: str  # "<provider key>/<kind>"
    agency: str
    title: str
    url: str
    used_for: str
    license_status: LicenseStatus = "ogdl"
    basis: str = ""  # why the licence status (e.g. "data.gov.tw 11592")


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
    Dataset("twse-openapi/index", TWSE, "每日收盤行情-大盤統計資訊", f"{TWSE_API}/exchangeReport/MI_INDEX",
            "指數收盤（含發行量加權股價報酬指數，績效基準 ^TAIEXTR）"),
    Dataset("twse-openapi/total_return", TWSE, "發行量加權股價報酬指數", f"{TWSE_API}/indicesReport/MFI94U",
            "績效基準 ^TAIEXTR（第一次存檔回補本月）"),
    Dataset("twse-openapi/dividend_resolution", TWSE, "上市公司股利分派情形", f"{TWSE_API}/opendata/t187ap45_L",
            "董事會／股東會決議的股利（盈餘、法定盈餘公積、資本公積分列）"),
    Dataset("twse-openapi/company", TWSE, "上市公司基本資料", f"{TWSE_API}/opendata/t187ap03_L",
            "已發行股數、市值、產業別、上市日期"),
    Dataset("tpex-openapi/company", TPEX, "上櫃股票基本資料", f"{TPEX_API}/mopsfin_t187ap03_O",
            "已發行股數、市值、產業別、上櫃日期"),
    Dataset("tpex-openapi/exright", TPEX, "上櫃股票除權除息計算結果表", f"{TPEX_API}/tpex_exright_daily",
            "除權息日的官方參考價、漲跌停"),
    Dataset("tpex-openapi/index", TPEX, "櫃買指數歷史資料", f"{TPEX_API}/tpex_index", "櫃買指數"),
    Dataset("tpex-openapi/total_return", TPEX, "櫃買指數與報酬指數之收市指數", f"{TPEX_API}/tpex_reward_index",
            "績效基準 ^TPEXTR（櫃買報酬指數）"),
    Dataset("tdcc-opendata/distribution", TDCC, "集保戶股權分散表", "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5",
            "大戶持股分級"),
    # -- TAIFEX OpenAPI (open-data-inventory §12). OGDL where a data.gov.tw dataset was found (search
    # summaries), otherwise conditional: archived, served under commercial only after TAIFEX confirms.
    Dataset("taifex-openapi/institutional_general", TAIFEX, "三大法人-總表-依日期",
            f"{TAIFEX_API}/MarketDataOfMajorInstitutionalTradersGeneralBytheDate", "期貨市場三大法人總表",
            basis="data.gov.tw 11592"),
    Dataset("taifex-openapi/institutional_fut_opt", TAIFEX, "三大法人-區分期貨與選擇權二類-依日期",
            f"{TAIFEX_API}/MarketDataOfMajorInstitutionalTradersDividedByFuturesAndOptionsBytheDate",
            "三大法人期貨、選擇權分計", basis="data.gov.tw 11594"),
    Dataset("taifex-openapi/institutional_futures", TAIFEX, "三大法人-區分各期貨契約-依日期",
            f"{TAIFEX_API}/MarketDataOfMajorInstitutionalTradersDetailsOfFuturesContractsBytheDate",
            "三大法人臺指期等各契約未平倉", basis="data.gov.tw 11596"),
    Dataset("taifex-openapi/institutional_options", TAIFEX, "三大法人-區分各選擇權契約-依日期",
            f"{TAIFEX_API}/MarketDataOfMajorInstitutionalTradersDetailsOfOptionsContractsBytheDate",
            "三大法人臺指選擇權等各契約未平倉", basis="data.gov.tw 11598"),
    Dataset("taifex-openapi/institutional_calls_puts", TAIFEX, "三大法人-選擇權買賣權分計-依日期",
            f"{TAIFEX_API}/MarketDataOfMajorInstitutionalTradersDetailsOfCallsAndPutsBytheDate",
            "三大法人選擇權買權、賣權分計", basis="data.gov.tw 11600"),
    Dataset("taifex-openapi/large_traders_futures", TAIFEX, "期貨大額交易人未沖銷部位資料",
            f"{TAIFEX_API}/OpenInterestOfLargeTradersFutures", "前五／前十大交易人淨部位",
            basis="data.gov.tw 11337／11338"),
    Dataset("taifex-openapi/put_call_ratio", TAIFEX, "臺指選擇權Put/Call比", f"{TAIFEX_API}/PutCallRatio",
            "Put/Call 比", basis="data.gov.tw 11322"),
    Dataset("taifex-openapi/futures_daily", TAIFEX, "期貨每日交易行情", f"{TAIFEX_API}/DailyMarketReportFut",
            "期貨行情（一般與盤後交易時段）", "conditional", "data.gov.tw 未找到個別資料集"),
    Dataset("taifex-openapi/options_daily", TAIFEX, "選擇權每日交易行情", f"{TAIFEX_API}/DailyMarketReportOpt",
            "選擇權行情", "conditional", "data.gov.tw 未找到個別資料集"),
    Dataset("taifex-openapi/large_traders_options", TAIFEX, "選擇權大額交易人未沖銷部位資料",
            f"{TAIFEX_API}/OpenInterestOfLargeTradersOptions", "選擇權前五／前十大交易人", "conditional",
            "data.gov.tw 11337／11338 是否涵蓋選擇權待核對"),
    Dataset("taifex-openapi/fx", TAIFEX, "每日外幣參考匯率", f"{TAIFEX_API}/DailyForeignExchangeRates",
            "只存檔（USD/TWD 換算改用中央銀行〈銀行間新臺幣對美元收盤匯率〉）", "conditional",
            "data.gov.tw 未找到個別資料集"),
    Dataset("taifex-openapi/final_settlement", TAIFEX, "最後結算價", f"{TAIFEX_API}/FinalSettlementPrice",
            "期貨、選擇權最後結算價", "conditional", "data.gov.tw 28825／30853 是否為同一資料待核對"),
    Dataset("taifex-openapi/margins_index", TAIFEX, "保證金一覽表-股價指數類",
            f"{TAIFEX_API}/IndexFuturesAndOptionsMargining", "指數期貨、選擇權保證金", "conditional",
            "data.gov.tw 未找到個別資料集"),
    Dataset("taifex-openapi/margins_stock", TAIFEX, "保證金一覽表-股票類", f"{TAIFEX_API}/SingleStockFuturesMargining",
            "股票期貨保證金", "conditional", "data.gov.tw 未找到個別資料集"),
    Dataset("taifex-openapi/margins_etf", TAIFEX, "保證金一覽表-股票類(ETF)",
            f"{TAIFEX_API}/SingleStockFuturesETFMargining", "ETF 期貨保證金", "conditional",
            "data.gov.tw 未找到個別資料集"),
    Dataset("taifex-openapi/ssf_list", TAIFEX, "股票期貨交易標的", f"{TAIFEX_API}/SSFLists",
            "個股是否有股票期貨", "conditional", "data.gov.tw 未找到個別資料集"),
    Dataset("taifex-openapi/sso_list", TAIFEX, "股票選擇權交易標的", f"{TAIFEX_API}/SSOLists",
            "個股是否有股票選擇權", "conditional", "data.gov.tw 未找到個別資料集"),
    # -- 中央銀行 (data.gov.tw 7232): the whole daily history since 2008 in one JSON array (marketdata/cbc.py).
    Dataset("cbc-opendata/fx", CBC, "銀行間新臺幣對美元收盤匯率", f"{CBC_API}/FTDOpenData_Day",
            "美股換算新台幣", basis="data.gov.tw 7232"),
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
    "taifex-openapi": (f"{TAIFEX}〈OpenAPI 開放資料〉", True),
    "cbc-opendata": (f"{CBC}〈開放資料〉", True),
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
        if commercial and key in ("twse-openapi", "tpex-openapi", "tdcc-opendata", "taifex-openapi", "cbc-opendata"):
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


@dataclass(frozen=True)
class StaleDataset:
    """An endpoint whose data stopped updating (checked live; the weekly archive check refreshes the date)."""

    key: str
    agency: str
    title: str
    url: str
    last_updated: str  # ISO date of the newest data seen (static value from the 2026-11-12 check)
    used: bool
    note: str


STALE_DATASETS: tuple[StaleDataset, ...] = (
    StaleDataset("twse-openapi/breadth", TWSE, "集中市場漲跌證券數統計表", f"{TWSE_API}/opendata/twtazu_od",
                 "2026-06-05", False, "出表日期停在 1150605，疑似停止更新；Forliosa 不使用"),
    StaleDataset("twse-openapi/pledge", TWSE, "上市公司董事、監察人質權設定占董事及監察人實際持有股數彙總表",
                 f"{TWSE_API}/opendata/t187ap09_L", "2026-08-19", False,
                 "出表日期 1150819，不定期更新或已停更；含個人姓名，Forliosa 目前不使用"),
    StaleDataset("tpex-openapi/dividend_resolution", TPEX, "上櫃股利分派情形-董事會通過",
                 f"{TPEX_API}/mopsfin_t187ap39_O", "2021-08-04", False,
                 "已停更（出表日期 1100804，股利年度 107–110）；上櫃股票的股利只能用除權息預告與除權息計算結果"),
    StaleDataset("tpex-openapi/statements_blank", TPEX, "上櫃公司資產負債表（保險業、異業）",
                 f"{TPEX_API}/mopsfin_t187ap07_O_ins", "2021-06-16", True,
                 "金融、金控、保險、異業產業別只回一列空白（出表日期 1100616）；存檔略過空白列，不覆蓋既有資料"),
    StaleDataset("taifex-openapi/final_settlement", TAIFEX, "最後結算價", f"{TAIFEX_API}/FinalSettlementPrice",
                 "2025-12-05", True, "2026-11-12 回應中最新的最後結算日是 2025-12-05；仍每週存檔，但不當成最新資料"),
)


def conditional_confirmed() -> bool:
    from forliosa.config import get_settings

    return bool(get_settings().taifex_conditional_confirmed)


def dataset_served(key: str, policy: Policy, confirmed: bool | None = None) -> bool:
    """May data from dataset ``key`` (``"taifex-openapi/fx"``) be shown to users under ``policy``?

    OGDL datasets: always (with attribution). ``conditional`` datasets: under ``personal`` yes; under
    ``commercial`` only when ``TAIFEX_CONDITIONAL_CONFIRMED=true`` (the owner has TAIFEX's confirmation).
    """
    ds = DATASETS.get(key)
    if ds is None or ds.license_status == "ogdl" or policy == "personal":
        return True
    return conditional_confirmed() if confirmed is None else confirmed


def _item(d: Dataset, year: int, served: bool, confirmed: bool, status: dict[str, dict]) -> dict:
    st = status.get(d.key) or {}
    return {"key": d.key, "agency": d.agency, "dataset": d.title, "url": d.url, "used_for": d.used_for,
            "year": year, "license": OGDL, "license_url": OGDL_URL,
            "license_status": d.license_status, "license_basis": d.basis or None,
            "commercial": d.license_status == "ogdl" or confirmed, "served": served,
            "last_updated": st.get("data_date"), "last_fetched": st.get("fetched_at"),
            "attribution": attribution(d, year)}


def attributions(policy: Policy, confirmed: bool | None = None, status: dict[str, dict] | None = None) -> dict:
    """``GET /meta/attributions``: every dataset this deployment shows, with the licence notice.

    ``datasets`` are the datasets served under ``policy`` (each with ``license_status`` and, when the archive has
    fetched it, ``last_updated`` = the newest data date seen). ``conditional`` lists datasets that are archived
    but not shown yet (licence awaiting TAIFEX's confirmation); ``stale`` lists endpoints that stopped updating.
    ``status`` maps dataset keys to ``{"data_date", "fetched_at"}`` (table ``dataset_status``).
    """
    year = _year()
    confirmed = conditional_confirmed() if confirmed is None else confirmed
    status = status or {}
    items, pending = [], []
    for d in DATASETS.values():
        served = dataset_served(d.key, policy, confirmed)
        (items if served else pending).append(_item(d, year, served, confirmed, status))
    for item in pending:
        item["note"] = CONDITIONAL_NOTE
    if policy == "personal":
        items.append({"key": "finmind", "agency": "FinMind", "dataset": "FinMind 開放 API（台股資料）",
                      "url": "https://finmind.github.io/", "used_for": "僅在明確設定時：回補、新聞（非商用）",
                      "year": year, "license": "FinMind 使用條款（非商用）", "license_url": "https://finmind.github.io/Disclaimer/",
                      "license_status": "non_commercial", "license_basis": None, "commercial": False, "served": True,
                      "last_updated": None, "last_fetched": None, "attribution": label("finmind")})
    stale = []
    for s in STALE_DATASETS:
        st = status.get(s.key) or {}
        stale.append({"key": s.key, "agency": s.agency, "dataset": s.title, "url": s.url,
                      "last_updated": st.get("data_date") or s.last_updated, "checked_at": st.get("fetched_at"),
                      "used": s.used, "note": s.note})
    return {
        "policy": policy,
        "taifex_conditional_confirmed": confirmed,
        "notice": [f"{OGDL_NOTICE}", f"政府資料開放授權條款：{OGDL_URL}"],
        "datasets": items,
        "conditional": pending,
        "stale": stale,
        "not_used": [
            "臺灣證券交易所網站（T86 三大法人、MI_QFIIS 外資持股等）與基本市況報導 MIS：網站條款禁止未經同意以程式下載",
            "證券櫃檯買賣中心網站歷史查詢、公開資訊觀測站網站：同上，只使用 OpenAPI 版本",
            "臺灣期貨交易所網站（歷史行情查詢等）：只使用 OpenAPI（openapi.taifex.com.tw/v1）",
            "期交所每筆成交資料（TimeAndSalesData、OptionsTimeAndSalesData、價差每筆成交）：檔案數百 MB，不下載",
        ],
    }
