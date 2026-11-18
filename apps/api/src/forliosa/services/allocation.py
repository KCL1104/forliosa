"""持倉配置（帳本「配置」分段；負責人 2026-11-18：第一版全部照建議）: the holdings grouped six ways, concentration
facts and the user's own limits.

Groupings (:data:`GROUPINGS`). Every slice is ``{key, label, value (TWD), weight, is_etf, symbols}``, largest first;
the values add up to the ledger's total market value — the same rows, prices and FX as ``GET /portfolio/holdings``
(:class:`forliosa.services.portfolio.PortfolioState`; a holding without a close is valued at cost, as there):

* ``holding`` 每一檔: one slice per symbol (every account in scope together).
* ``industry`` 產業 (:func:`classify`):
  - Taiwan stocks: the official 產業別 (the catalog's industry, else ``company_profiles``), keyed by its name.
  - US stocks: the 12 US sectors the news tags use (``news.taxonomy.us_sector``: the vocabulary's own ticker list, else
    the SEC SIC code from the company's submissions, US government open data). Keyed by the sector id (``us_semis``).
  - ETFs: a class instead of an industry (:data:`ETF_CLASSES`; :func:`tw_etf_class`, :func:`us_etf_class`) — no ETF
    is looked through (its holdings have no licensed open source; 負責人 2026-11-18, 7A).
  - Anything we cannot tell: ``unclassified`` 未分類 — never folded into a guessed class.
* ``market`` 上市／上櫃／美股, ``account`` the broker accounts, ``currency`` 新台幣／美元, ``type`` 股票／ETF. A US
  fund that SEC's ticker list files as a company (GLD, IBIT, USO …) is typed ETF when its name says so
  (:func:`looks_like_us_fund`) or, for a name we cannot read, when SEC files it under SIC 6221 (commodity and crypto
  pools, :data:`US_FUND_SIC`) — never 美股金融.

Concentration (:func:`concentration`) is facts only: the largest holding, the top 3 / top 5 together, the largest
industry (ETF classes and 未分類 left out: an ETF class is not an industry), every ETF together and — only for the
limits the user set — which stocks / industries are above them. 單一個股上限 counts stocks only (an ETF is not
個股), 單一產業上限 industries only. There is no default limit and no threshold of ours (負責人 2026-11-18, 4A).
The limits are stored in the user's preferences JSON (``users.preferences["allocation_limits"]``), read and written
only through ``/portfolio/allocation`` (a viewer of a read-only delegation sees the owner's limits, cannot change
them).
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from forliosa.api import serialize as ser
from forliosa.datapolicy import source_clause
from forliosa.domain.fees import ZERO
from forliosa.marketdata import sec
from forliosa.marketdata.base import InstrumentInfo, code_of_symbol, market_of_symbol
from forliosa.marketdata.catalog import ETF_CODES, US_ETF_CODES
from forliosa.marketdata.fund_nav import is_etf_code
from forliosa.models import CompanyProfile, FundProfile, SecCompany, SecTicker, User
from forliosa.news import taxonomy as tx
from forliosa.services.ledger_io import preferences_of
from forliosa.timeutil import iso_taipei

if TYPE_CHECKING:
    from forliosa.marketdata.service import MarketData
    from forliosa.services.portfolio import HoldingRow, PortfolioState

GROUPINGS = ("holding", "industry", "market", "account", "currency", "type")
MARKET_LABELS = {"TWSE": "上市", "TPEX": "上櫃", "US": "美股"}
CURRENCY_LABELS = {"TWD": "新台幣", "USD": "美元"}
TYPE_LABELS = {"stock": "股票", "etf": "ETF"}

UNCLASSIFIED = "unclassified"
UNCLASSIFIED_LABEL = "未分類"
ETF_CLASSES: dict[str, str] = {
    "etf_tw_equity": "國內股票型 ETF",
    "etf_foreign_equity": "海外股票型 ETF",
    "etf_bond": "債券 ETF",
    "etf_leveraged": "槓桿／反向 ETF",
    "etf_active": "主動式 ETF",
    "etf_futures": "期貨 ETF",  # 商品、VIX、美元指數期貨（代號 …U）
    "etf_balanced": "平衡型 ETF",  # 股債平衡（代號 …T，2025 起）
    "etf_other": "ETF（未分類）",
}
TOP_N = (3, 5)
LIMIT_KINDS = ("holding", "industry")
LIMIT_MIN, LIMIT_MAX = 0.01, 1.0
PREF_KEY = "allocation_limits"


@dataclass(frozen=True)
class Klass:
    """How one holding is grouped: its type (``stock`` | ``etf``) and its industry slice."""

    type: str
    industry: str
    label: str

    @property
    def is_etf(self) -> bool:
        return self.type == "etf"


def _etf(key: str) -> Klass:
    return Klass("etf", key, ETF_CLASSES[key])


def _stock(key: str | None, label: str | None = None) -> Klass:
    if not key:
        return Klass("stock", UNCLASSIFIED, UNCLASSIFIED_LABEL)
    return Klass("stock", key, label or key)


# -- Taiwan ETFs ----------------------------------------------------------------------------------------------------
def tw_etf_class(code: str, fund_type: str | None = None) -> str:
    """The class of a Taiwan ETF from its code's letter and TWSE t187ap47_L 基金類型 (``fund_profiles``; listed ETFs
    only — an OTC ETF has its letter alone).

    Letters (checked against t187ap47_L on 2026-11-18): L 槓桿、R 反向 (00716R is a futures fund, still 反向),
    U 期貨, B 債券, D 主動式債券 (bond first: what it holds), T 股債平衡, A 主動式股票. Without a letter the
    基金類型 decides: 國內成分 → 國內股票型; 國外成分、境外、連結式 → 海外股票型. A bond ETF listed on TWSE is
    filed as 「國外成分證券指數股票型基金」, so the letter is read first. The built-in ETFs (0050, 0056, 00878 …)
    are all 國內股票型 when no profile is archived (offline, tests). Anything else is ``etf_other``
    (ETF（未分類）)."""
    c = code.strip().upper()
    letter = c[-1] if c[-1:].isalpha() else ""
    t = fund_type or ""
    if letter in ("L", "R") or "槓桿" in t or "反向" in t:
        return "etf_leveraged"
    if letter == "U" or "期貨" in t:
        return "etf_futures"
    if letter in ("B", "D") or "債" in t:
        return "etf_bond"
    if letter == "T" or "平衡" in t:
        return "etf_balanced"
    if letter == "A" or "主動" in t:
        return "etf_active"
    if any(w in t for w in ("國外", "境外", "連結式")):
        return "etf_foreign_equity"
    if "國內" in t or c in ETF_CODES:
        return "etf_tw_equity"
    return "etf_other"


# -- US funds -------------------------------------------------------------------------------------------------------
# SEC's company_tickers.json lists every exchange-traded product that files as its own registrant (commodity, currency
# and crypto trusts, a few unit investment trusts) next to the companies, all as "stocks" (archive listings). Their
# names say what they are; a closed-end fund (「PIMCO Dynamic Income Fund」) is not matched and stays a stock.
_CRYPTO = (r"BITCOIN|ETHEREUM|SOLANA|XRP|LITECOIN|CHAINLINK|STELLAR LUMENS|ZCASH|DOGECOIN|AVALANCHE|CARDANO"
           r"|POLKADOT|HEDERA|SUI|TRON|FILECOIN|LIVEPEER|DECENTRALAND|HORIZEN|BASIC ATTENTION TOKEN|DIGITAL LARGE CAP")
_US_FUND = re.compile(
    r"\bETFS?\b|EXCHANGE[- ]TRADED|\bISHARES\b|\bSPDR\b|\bPROSHARES\b|\bDIREXION\b|CURRENCYSHARES|\bINVESCO DB\b"
    r"|\bINDEX FUNDS?\b|\bCOMMODITY (?:INDEX )?TRUST\b|\bVOLATILITY SHARES\b"
    r"|\bUNITED STATES (?:12 MONTH )?(?:BRENT )?(?:OIL|NATURAL GAS|GASOLINE) FUND\b"
    rf"|\b(?:{_CRYPTO}) FUND\b"
    rf"|\b(?:GOLD|SILVER|PLATINUM|PALLADIUM|{_CRYPTO})(?: (?:CLASSIC|CASH|MINI))?"
    r"(?: & (?:GOLD|SILVER|PLATINUM|PALLADIUM))? TRUST\b"
    # Grayscale's single-asset trusts carry their token in brackets: 「Grayscale Solana Trust (SOL)」
    r"|\bTRUST \((?!THE\))(?-i:[A-Z0-9]{2,6})\)",
    re.IGNORECASE,
)
# SEC files commodity pools and crypto trusts (Grayscale's, Volatility Shares', Franklin's bitcoin trust …) under SIC
# 6221 「Commodity Contracts Brokers & Dealers」, which the news sectors would read as 美股金融: a listing with that SIC
# is a fund whatever its name says.
US_FUND_SIC = "6221"
# 「Ultra-Short Income」「Ultra Short Duration」 are short-term bond funds, not leveraged ones (ProShares' are
# 「Ultra」「UltraPro」「UltraShort」)
_US_LEVERAGED = re.compile(r"\b(?:ULTRAPRO|ULTRASHORT|ULTRA(?![- ]?SHORT)|[1-3](?:\.\d+)?X|LEVERAGED|INVERSE)\b",
                           re.IGNORECASE)
_US_BOND = re.compile(r"\b(?:BONDS?|TREASURY|TREASURIES|T-BILLS?|AGGREGATE|MUNICIPAL|FIXED INCOME)\b", re.IGNORECASE)
_US_ACTIVE = re.compile(r"\bACTIVE\b", re.IGNORECASE)


def looks_like_us_fund(name: str | None) -> bool:
    """A US listing whose name says it is an exchange-traded fund or trust (SPDR Gold Trust, iShares Bitcoin Trust ETF,
    United States Oil Fund, ProShares Trust II …)."""
    return bool(name and _US_FUND.search(name))


def us_etf_class(code: str, name: str | None) -> str:
    """The class of a US ETF: the built-in ones (VOO, QQQ, SPY, DIA, ONEQ, SMH) are equity index funds — 海外股票型
    from a Taiwan investor's side, like 00646 元大S&P500; any other only when its name says 槓桿／反向, 債券 or 主動,
    else ``etf_other`` (a trust's registrant name — 「ProShares Trust II」 — rarely says more)."""
    n = name or ""
    if _US_LEVERAGED.search(n):
        return "etf_leveraged"
    if _US_BOND.search(n):
        return "etf_bond"
    if _US_ACTIVE.search(n):
        return "etf_active"
    if code.upper() in US_ETF_CODES:
        return "etf_foreign_equity"
    return "etf_other"


# -- classification -------------------------------------------------------------------------------------------------
def _fund_types(db: Session, policy: str, symbols: list[str]) -> dict[str, str | None]:
    if not symbols:
        return {}
    rows = db.execute(select(FundProfile.symbol, FundProfile.values).where(
        FundProfile.symbol.in_(symbols), source_clause(FundProfile.source, policy)))
    return {sym: (values or {}).get("fund_type") for sym, values in rows}


def _tw_industries(db: Session, policy: str, symbols: list[str]) -> dict[str, str]:
    if not symbols:
        return {}
    rows = db.execute(select(CompanyProfile.symbol, CompanyProfile.industry).where(
        CompanyProfile.symbol.in_(symbols), source_clause(CompanyProfile.source, policy)))
    return {sym: industry for sym, industry in rows if industry}


def _us_sics(db: Session, codes: list[str]) -> dict[str, str]:
    """SEC SIC codes by SEC ticker spelling (``BRK-B``), from the submissions the daily SEC job keeps for every held
    US stock (``sec_companies.profile["sic"]``). A company never fetched has none."""
    if not codes:
        return {}
    rows = db.execute(select(SecTicker.ticker, SecCompany.profile)
                      .join(SecCompany, SecCompany.cik == SecTicker.cik)
                      .where(SecTicker.ticker.in_(codes)))
    return {ticker: str(sic) for ticker, profile in rows if (sic := (profile or {}).get("sic"))}


def _code(symbol: str, info: InstrumentInfo | None) -> str:
    if info is not None:
        return info.code
    return symbol if market_of_symbol(symbol) == "US" else code_of_symbol(symbol)


def classify(db: Session | None, policy: str, infos: dict[str, InstrumentInfo | None]) -> dict[str, Klass]:
    """Type and industry slice of every symbol (``infos``: symbol → catalog entry, ``None`` when the catalog no longer
    lists it). ``db`` reads the archived profiles (fund types, Taiwan company profiles, SEC SIC codes); without it the
    catalog alone decides (fewer classes, never a wrong one; a US fund whose name says nothing and whose SIC 6221 is not
    read stays an unclassified stock)."""
    tw_etfs: list[str] = []
    tw_bare: list[str] = []
    us_stocks: dict[str, str] = {}  # symbol -> SEC ticker (its SIC: the sector, or a fund filed under 6221)
    kinds: dict[str, str] = {}
    for sym, info in infos.items():
        market = info.market if info is not None else market_of_symbol(sym)
        code = _code(sym, info)
        if market == "US":
            fund = (info is not None and info.type == "etf") or looks_like_us_fund(info.name if info else None)
            kinds[sym] = "us_etf" if fund else "us_stock"
            if not fund and code.upper() not in tx.US_SECTOR_BY_TICKER:
                us_stocks[sym] = sec.sec_ticker(code)  # the news vocabulary's own tickers are companies
        else:
            etf = info.type == "etf" if info is not None else is_etf_code(code)
            kinds[sym] = "tw_etf" if etf else "tw_stock"
            if etf:
                tw_etfs.append(sym)
            elif not (info and info.industry):
                tw_bare.append(sym)
    fund_types = _fund_types(db, policy, tw_etfs) if db is not None else {}
    tw_industry = _tw_industries(db, policy, tw_bare) if db is not None else {}
    sics = _us_sics(db, sorted(set(us_stocks.values()))) if db is not None else {}

    out: dict[str, Klass] = {}
    for sym, info in infos.items():
        code = _code(sym, info)
        match kinds[sym]:
            case "tw_etf":
                out[sym] = _etf(tw_etf_class(code, fund_types.get(sym)))
            case "tw_stock":
                industry = (info.industry if info else None) or tw_industry.get(sym)
                out[sym] = _stock(industry if industry and industry != "ETF" else None)
            case "us_etf":
                out[sym] = _etf(us_etf_class(code, info.name if info else None))
            case _:
                sic = sics.get(us_stocks.get(sym, ""))
                if sic == US_FUND_SIC:
                    out[sym] = _etf(us_etf_class(code, info.name if info else None))
                    continue
                sector = tx.us_sector(code, sic)
                out[sym] = _stock(sector, tx.sector_label(sector) if sector else None)
    return out


# -- limits ---------------------------------------------------------------------------------------------------------
def _limit(value: Any) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return round(v, 4) if LIMIT_MIN <= v <= LIMIT_MAX else None


def limits_of(user: User | None) -> dict[str, float | None]:
    """The user's own limits (fractions: 0.3 = 30%), ``None`` for one not set. Nothing is set by default."""
    raw = preferences_of(user).get(PREF_KEY) if user is not None else None
    raw = raw if isinstance(raw, dict) else {}
    return {k: _limit(raw.get(k)) for k in LIMIT_KINDS}


def set_limits(db: Session, user: User, holding: float | None, industry: float | None) -> dict[str, float | None]:
    """Replace both limits (``None`` clears one). Stored in ``users.preferences`` like the other preferences."""
    limits = {"holding": _limit(holding), "industry": _limit(industry)}
    user = db.merge(user)
    user.preferences = {**preferences_of(user), PREF_KEY: limits}
    db.commit()
    return limits


# -- groupings ------------------------------------------------------------------------------------------------------
def _ratio(v: Decimal, total: Decimal) -> float:
    return ser.ratio(v / total) if total else 0.0


def _slices(values: dict[str, dict[str, Decimal]], labels: dict[str, str], total: Decimal,
            etf_keys: Iterable[str] = ()) -> list[dict[str, Any]]:
    """``values``: slice key → {symbol: TWD}. Largest first (then by key, so equal slices keep one order)."""
    etf = set(etf_keys)
    totals = {k: sum(m.values(), ZERO) for k, m in values.items()}
    out = []
    for key in sorted(values, key=lambda k: (-totals[k], k)):
        members = values[key]
        out.append({
            "key": key, "label": labels.get(key, key), "value": ser.money(totals[key]),
            "weight": _ratio(totals[key], total), "is_etf": key in etf,
            "symbols": [s for s, _ in sorted(members.items(), key=lambda kv: (-kv[1], kv[0]))],
        })
    return out


def _name(r: HoldingRow) -> str:
    return r.info.name if r.info else r.symbol


def groups(state: PortfolioState, klass: dict[str, Klass], total: Decimal) -> dict[str, list[dict[str, Any]]]:
    by: dict[str, dict[str, dict[str, Decimal]]] = {g: defaultdict(lambda: defaultdict(Decimal)) for g in GROUPINGS}
    labels: dict[str, dict[str, str]] = {
        "holding": {}, "industry": {UNCLASSIFIED: UNCLASSIFIED_LABEL, **ETF_CLASSES}, "market": MARKET_LABELS,
        "account": {a.id: a.name for a in state.inp.accounts}, "currency": CURRENCY_LABELS, "type": TYPE_LABELS,
    }
    etf_keys: dict[str, set[str]] = {"holding": set(), "industry": set(ETF_CLASSES), "type": {"etf"}}
    for r in state.rows:
        v = r.market_value
        k = klass[r.symbol]
        info = r.info
        by["holding"][r.symbol][r.symbol] += v
        labels["holding"][r.symbol] = _name(r)
        if k.is_etf:
            etf_keys["holding"].add(r.symbol)
        by["industry"][k.industry][r.symbol] += v
        labels["industry"].setdefault(k.industry, k.label)
        by["market"][info.market if info else market_of_symbol(r.symbol)][r.symbol] += v
        by["currency"][r.currency][r.symbol] += v
        by["type"][k.type][r.symbol] += v
        for acc, av in r.by_account_value.items():
            by["account"][acc][r.symbol] += av
    return {g: _slices(by[g], labels[g], total, etf_keys.get(g, ())) for g in GROUPINGS}


# -- concentration --------------------------------------------------------------------------------------------------
def concentration(rows: Sequence[HoldingRow], klass: dict[str, Klass], total: Decimal,
                  limits: dict[str, float | None]) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda r: (-r.market_value, r.symbol))
    values = [r.market_value for r in ordered]
    industries: dict[str, Decimal] = defaultdict(Decimal)
    labels: dict[str, str] = {}
    etf = ZERO
    for r in ordered:
        k = klass[r.symbol]
        if k.is_etf:
            etf += r.market_value
        elif k.industry != UNCLASSIFIED:
            industries[k.industry] += r.market_value
            labels[k.industry] = k.label
    ranked = sorted(industries.items(), key=lambda kv: (-kv[1], kv[0]))
    top = ordered[0] if ordered and total else None
    over: list[dict[str, Any]] = []
    if (cap := limits.get("holding")) is not None:
        over += [{"kind": "holding", "key": r.symbol, "label": _name(r), "weight": w, "limit": cap}
                 for r in ordered if not klass[r.symbol].is_etf and (w := _ratio(r.market_value, total)) > cap]
    if (cap := limits.get("industry")) is not None:
        over += [{"kind": "industry", "key": key, "label": labels[key], "weight": w, "limit": cap}
                 for key, v in ranked if (w := _ratio(v, total)) > cap]
    return {
        "holdings_count": len(ordered),
        "top_holding": {"symbol": top.symbol, "name": _name(top), "weight": _ratio(top.market_value, total),
                        "is_etf": klass[top.symbol].is_etf} if top else None,
        "top3_weight": _ratio(sum(values[:TOP_N[0]], ZERO), total),
        "top5_weight": _ratio(sum(values[:TOP_N[1]], ZERO), total),
        "top_industry": {"key": ranked[0][0], "label": labels[ranked[0][0]], "weight": _ratio(ranked[0][1], total)}
        if ranked and total else None,
        "etf_weight": _ratio(etf, total),
        "limits": dict(limits),
        "over_limits": over,
    }


# -- entry points ---------------------------------------------------------------------------------------------------
@dataclass
class Computed:
    total: Decimal
    klass: dict[str, Klass]
    groups: dict[str, list[dict[str, Any]]]
    concentration: dict[str, Any]


def compute(state: PortfolioState, md: MarketData) -> Computed:
    total = sum((r.market_value for r in state.rows), ZERO)
    klass = classify(state.db, md.policy, {r.symbol: r.info for r in state.rows})
    return Computed(total, klass, groups(state, klass, total),
                    concentration(state.rows, klass, total, limits_of(state.user)))


SUMMARY_KEYS = {"by_market": "market", "by_industry": "industry", "by_currency": "currency", "by_type": "type",
                "by_account": "account"}


def summary_parts(state: PortfolioState, md: MarketData) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """``/portfolio/summary``'s ``allocation`` (the five ``by_*`` lists, ``{key, label, value, weight}``) and
    ``concentration`` — the same numbers as ``/portfolio/allocation``."""
    c = compute(state, md)
    alloc = {name: [{k: s[k] for k in ("key", "label", "value", "weight")} for s in c.groups[g]]
             for name, g in SUMMARY_KEYS.items()}
    return alloc, c.concentration


def fx_rates(state: PortfolioState) -> dict[str, float]:
    """The rates behind the TWD values, only for the foreign currencies held in this scope (``{"USD": 32.47}``): the
    same :meth:`FxBook.latest` the holdings use."""
    currencies = sorted({r.currency for r in state.rows if r.currency != "TWD"})
    return {cur: ser.price(state.fx.latest(cur)) or 0.0 for cur in currencies}


def allocation(state: PortfolioState, md: MarketData, account_id: str | None, can_edit_limits: bool) -> dict[str, Any]:
    """``GET /portfolio/allocation``."""
    c = compute(state, md)
    return {
        "as_of": iso_taipei(state.as_of),
        "account_id": account_id,
        "market_value": ser.money(c.total),
        "fx": fx_rates(state),
        "groups": c.groups,
        "concentration": c.concentration,
        "valued_at_cost": [r.symbol for r in state.rows if r.price is None],
        "can_edit_limits": can_edit_limits,
        "is_demo": state.is_demo,
    }
