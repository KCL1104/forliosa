"""「關於〈公司〉」: company facts and description (product owner 2026-11-12, decisions 6 and 7).

Facts (``GET /instruments/{symbol}/company``)
--------------------------------------------
* Taiwan stocks: TWSE t187ap03_L / TPEx mopsfin_t187ap03_O (archived daily, latest only): 產業別, 成立日期 (and
  「成立 N 年」), 上市／上櫃日期, 總部 (縣市 from the address; KY: the registration country instead), 網站, 實收資本額,
  **董事長 and 總經理 exactly as published**, 簽證會計師事務所, 股務代理, 英文簡稱 — with the dataset's attribution and
  出表日期. The two names are only ever returned by this endpoint: never in AI prompts or AI tool outputs
  (``forliosa.ai`` does not import this module), never joined with board holdings or pledges.
* US stocks: SEC submissions (industry, HQ city / state or country, exchanges, fiscal year end, former names).
* ETFs: t187ap47_L fund basics (type, tracked index, established, listed).

Description
-----------
* ``kind = "wikipedia"``: a zh.wikipedia excerpt (zh-tw variant, cut at a sentence end, **unchanged**), labelled
  「節錄」 with links to the article and CC BY-SA 4.0. Found via Wikidata (ticker on TWSE / TPEx, else the exact
  full name; :mod:`forliosa.marketdata.wikimedia`), refreshed every ``COMPANY_WIKI_REFRESH_DAYS`` (30) with the
  revision id kept. The text is never sent to or rewritten by an AI model.
* ``kind = "ai"``: without an article, 2–3 sentences written by the model from official facts only (industry,
  incorporation and listing dates, HQ, paid-in capital, latest monthly revenue scale, the ESG product-category
  text) — no person's name — labelled 「AI 依公開資料整理」 and regenerated only when those facts change
  (``facts_key``). System-paid (``ai_usage.feature = "company"``), at most ``COMPANY_AI_PER_RUN`` per run.

Refresh: worker job ``company_refresh`` (hourly) for tracked symbols (held, watched, viewed in the last
``NEWS_VIEW_DAYS`` days), at most ``COMPANY_MAX_SYMBOLS_PER_RUN`` per run, one Wikimedia request at a time; a 429 /
403 from Wikimedia pauses the lookups for 6 hours. CLI: ``python -m forliosa.services.company refresh [SYMBOL…]``.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from forliosa.config import Settings, get_settings
from forliosa.datapolicy import labels, source_clause
from forliosa.marketdata import wikimedia as wm
from forliosa.marketdata.base import InstrumentInfo, ProviderUnavailable
from forliosa.marketdata.service import MarketData
from forliosa.models import CompanyDescription, CompanyProfile, EsgProductOutput, FundProfile, MarketEvent
from forliosa.services.instruments import require_instrument
from forliosa.timeutil import TAIPEI, iso_taipei, now_utc, today_taipei

log = logging.getLogger(__name__)

FEATURE = "company"
WIKI_PAUSE = timedelta(hours=6)
AI_LABEL = "AI 依公開資料整理"
WIKI_LABEL = "節錄"
_paused_until: datetime | None = None  # process-wide: after a Wikimedia 429 / 403


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _years_since(d: date | None, today: date) -> int | None:
    if d is None:
        return None
    return today.year - d.year - ((today.month, today.day) < (d.month, d.day))


def _profile_row(db: Session, md: MarketData, symbol: str) -> CompanyProfile | None:
    return db.scalar(select(CompanyProfile).where(CompanyProfile.symbol == symbol,
                                                  source_clause(CompanyProfile.source, md.policy)))


def _iso(v: Any) -> str | None:
    try:
        return date.fromisoformat(str(v)).isoformat() if v else None
    except ValueError:
        return None


# -- description --------------------------------------------------------------------------------------------
def description_out(row: CompanyDescription | None) -> dict[str, Any] | None:
    if row is None or not row.text or row.kind not in ("wikipedia", "ai"):
        return None
    wiki = row.kind == "wikipedia"
    return {
        "kind": row.kind,
        "text": row.text,
        "label": WIKI_LABEL if wiki else AI_LABEL,
        "title": row.title if wiki else None,
        "url": row.url if wiki else None,
        "source": "維基百科" if wiki else None,
        "license": wm.LICENSE if wiki else None,
        "license_url": wm.LICENSE_URL if wiki else None,
        "revision_id": row.revision_id if wiki else None,
        "updated_at": iso_taipei(_aware(row.updated_at)) if row.updated_at else None,
    }


# -- facts ----------------------------------------------------------------------------------------------------
def _empty(info: InstrumentInfo) -> dict[str, Any]:
    return {
        "symbol": info.symbol, "name": info.name, "short_name": info.name, "english_short_name": None,
        "market": info.market, "type": info.type, "industry": info.industry, "incorporated": None,
        "years_since_incorporation": None, "listed_date": None,
        "listing": {"TWSE": "上市", "TPEX": "上櫃"}.get(info.market), "hq": None, "registered_in": None,
        "website": None, "paid_in_capital": None, "chairman": None, "president": None, "auditor": None,
        "transfer_agent": None, "exchanges": [], "fiscal_year_end": None, "former_names": [], "fund": None,
        "description": None, "data_date": None, "sources": [], "notes": [],
    }


def _tw_stock(db: Session, md: MarketData, info: InstrumentInfo, out: dict[str, Any]) -> None:
    row = _profile_row(db, md, info.symbol)
    if row is None:
        out["notes"].append("公司基本資料尚未存檔")
        return
    v = row.values or {}
    today = today_taipei()
    incorporated = _iso(v.get("incorporated"))
    out.update({
        "name": v.get("name") or info.name, "short_name": v.get("short_name") or info.name,
        "english_short_name": v.get("english_short_name"), "industry": row.industry or info.industry,
        "incorporated": incorporated,
        "years_since_incorporation": _years_since(date.fromisoformat(incorporated), today) if incorporated else None,
        "listed_date": row.listed_date, "hq": None if v.get("registered_in") else v.get("hq"),
        "registered_in": v.get("registered_in"), "website": v.get("website"),
        "paid_in_capital": v.get("paid_in_capital"), "chairman": v.get("chairman"), "president": v.get("president"),
        "auditor": v.get("auditor"), "transfer_agent": v.get("transfer_agent"), "data_date": row.date,
        "sources": labels([f"{row.source}/company"]),
    })


def _us_stock(db: Session, info: InstrumentInfo, out: dict[str, Any]) -> None:
    from forliosa.marketdata import sec
    from forliosa.models import SecCompany, SecTicker

    tick = db.get(SecTicker, sec.sec_ticker(info.symbol))
    comp = db.get(SecCompany, tick.cik) if tick else None
    prof = (comp.profile if comp else None) or {}
    if not prof:
        out["notes"].append("SEC 公司資料尚未取得")
        return
    city = (prof.get("city") or "").title() or None
    where = prof.get("state") or (prof.get("country") if prof.get("country") != "United States" else None)
    fye = comp.fiscal_year_end if comp else None
    out.update({
        "name": (comp.name if comp and comp.name else info.name), "industry": prof.get("industry") or info.industry,
        "hq": ", ".join(x for x in (city, where) if x) or None, "exchanges": prof.get("exchanges") or [],
        "fiscal_year_end": f"{fye[:2]}-{fye[2:]}" if fye and len(fye) == 4 else None,
        "former_names": prof.get("former_names") or [],
        "data_date": comp.filings_fetched_at.astimezone(TAIPEI).date() if comp and comp.filings_fetched_at else None,
        "sources": labels(["sec-edgar/submissions"]),
    })


def _etf(db: Session, md: MarketData, info: InstrumentInfo, out: dict[str, Any]) -> None:
    row = db.scalar(select(FundProfile).where(FundProfile.symbol == info.symbol,
                                              source_clause(FundProfile.source, md.policy)))
    if row is None:
        return
    v = row.values or {}
    out.update({
        "name": v.get("name") or info.name, "short_name": v.get("short_name") or info.name,
        "listed_date": _iso(v.get("listed")), "incorporated": _iso(v.get("established")),
        "fund": {"fund_type": v.get("fund_type"), "index_name": html.unescape(v.get("index_name") or "") or None,
                 "custodian": v.get("custodian"), "units": v.get("units")},
        "data_date": row.date, "sources": labels([f"{row.source}/fund"]),
    })


def about(db: Session, md: MarketData, symbol: str) -> dict[str, Any]:
    info = require_instrument(md, symbol)
    out = _empty(info)
    if info.market == "US":
        if info.type == "stock":
            _us_stock(db, info, out)
    elif info.type == "etf":
        _etf(db, md, info, out)
    else:
        _tw_stock(db, md, info, out)
    if info.type == "stock":
        desc = description_out(db.get(CompanyDescription, info.symbol))
        out["description"] = desc
        if desc and desc["kind"] == "wikipedia":
            out["sources"] = [*out["sources"], *labels(["wikipedia/zh"])]
        try:  # the worker looks up the description of recently viewed symbols (symbol + time only)
            from forliosa.news.service import record_view

            record_view(db, info.symbol)
        except SQLAlchemyError:
            db.rollback()
    return out


# -- official facts for the AI description (no person's name, ever) -------------------------------------------
def _yi(amount: Decimal | int | None) -> str | None:
    """NT$ -> 「約 2,593 億元」 / 「約 3.4 億元」 / 「約 8,000 萬元」."""
    if amount is None or amount <= 0:
        return None
    yi = Decimal(amount) / Decimal(100_000_000)
    if yi >= 10:
        return f"約 {int(yi.to_integral_value()):,} 億元"
    if yi >= 1:
        return f"約 {yi.quantize(Decimal('0.1'))} 億元"
    return f"約 {int((Decimal(amount) / 10_000).to_integral_value()):,} 萬元"


def official_facts(db: Session, md: MarketData, info: InstrumentInfo) -> dict[str, str] | None:
    """The facts an AI description may use. Only official open data; 董事長／總經理 are deliberately absent."""
    row = _profile_row(db, md, info.symbol)
    if row is None:
        return None
    v = row.values or {}
    facts: dict[str, str] = {"公司": str(v.get("short_name") or info.name), "全名": str(v.get("name") or "")}
    if row.industry:
        facts["產業別"] = row.industry
    inc = _iso(v.get("incorporated"))
    if inc:
        facts["成立"] = f"{inc[:4]} 年"
    if row.listed_date:
        facts["掛牌"] = f"{row.listed_date.year} 年{'上櫃' if info.market == 'TPEX' else '上市'}"
    if v.get("registered_in"):
        facts["註冊地"] = str(v["registered_in"])
    elif v.get("hq"):
        facts["總部"] = str(v["hq"])
    cap = _yi(v.get("paid_in_capital"))
    if cap:
        facts["實收資本額"] = cap
    rev = db.scalar(select(MarketEvent).where(
        MarketEvent.symbol == info.symbol, MarketEvent.type == "revenue_release",
        source_clause(MarketEvent.source, md.policy)).order_by(MarketEvent.date.desc()).limit(1))
    if rev is not None and (rev.data or {}).get("revenue"):
        amount = _yi(Decimal(str(rev.data["revenue"])) * 1000)  # thousand NT$
        period = str(rev.data.get("period") or "")
        if amount and len(period) == 7:
            facts["最近月營收"] = f"{period[:4]} 年 {int(period[5:])} 月{amount}"
    esg = db.scalar(select(EsgProductOutput).where(EsgProductOutput.symbol == info.symbol,
                                                   source_clause(EsgProductOutput.source, md.policy)))
    if esg is not None:
        facts["依產品類別之產品產量（ESG 揭露）"] = esg.text[:200]
    return facts


def facts_key(facts: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(facts, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _clean_ai_text(text: str, forbidden: list[str]) -> str | None:
    from forliosa.ai.prompts import COMPANY_MAX_CHARS

    s = " ".join((text or "").split()).strip().strip("「」\"")
    if not (20 <= len(s) <= COMPANY_MAX_CHARS) or "http" in s or s.count("。") > 4:
        return None
    if any(name and name in s for name in forbidden):  # never a person's name (none is given; double check)
        return None
    return s


class AiWriter:
    """One non-streaming call per company through the key pool (no tools)."""

    def __init__(self, pool: Any, settings: Settings, costs: Any = None):
        self.pool, self.settings, self.costs = pool, settings, costs

    def write(self, db: Session, facts: dict[str, str]) -> tuple[str, str] | None:
        from forliosa.ai import store
        from forliosa.ai.pricing import CallUsage
        from forliosa.ai.prompts import COMPANY_SYSTEM, company_question

        model = store.model_for(FEATURE, self.settings)
        msgs = [{"role": "user", "content": company_question(facts)}]
        raw, slot = self.pool.call(lambda c: c.messages.with_raw_response.create(
            model=model, max_tokens=400, system=COMPANY_SYSTEM, messages=msgs), costs=self.costs)
        self.pool.observe(slot, raw.headers)
        msg = raw.parse()
        store.record_usage(db, user_id=None, thread_id=None, feature=FEATURE, model=msg.model or model, key_slot=slot,
                           usage=CallUsage.from_sdk(msg.usage), stop_reason=msg.stop_reason)
        text = "".join(getattr(b, "text", "") for b in msg.content if getattr(b, "type", "") == "text")
        return (text, msg.model or model) if msg.stop_reason in ("end_turn", "stop_sequence") else None


def default_ai(settings: Settings) -> AiWriter | None:
    if not settings.company_ai_enabled or settings.company_ai_per_run <= 0:
        return None
    from forliosa.ai import store as ai_store
    from forliosa.ai.keypool import get_key_pool
    from forliosa.db import session_factory

    pool = get_key_pool()
    if not pool.available:
        return None
    with session_factory()() as db:
        costs = ai_store.slot_month_costs(db)
    return AiWriter(pool, settings, costs) if pool.ranked(costs) else None


# -- refresh (worker) ---------------------------------------------------------------------------------------------
@dataclass
class RefreshReport:
    symbols: int = 0
    wiki_lookups: int = 0
    wiki_found: int = 0
    ai_written: int = 0
    paused: bool = False
    errors: list[str] = field(default_factory=list)


def due_symbols(db: Session, settings: Settings, now: datetime) -> list[str]:
    """Tracked Taiwan / US stocks, never looked up first, then the oldest lookup."""
    from forliosa.news.service import tracked

    symbols = tracked(db, settings, now)
    rows = {r.symbol: r for r in db.scalars(select(CompanyDescription).where(CompanyDescription.symbol.in_(symbols)))}
    fresh = timedelta(days=settings.company_wiki_refresh_days)
    # an article checked recently needs nothing; "none" / "ai" rows are revisited (the facts may have changed)
    symbols = [s for s in symbols if s not in rows or rows[s].kind != "wikipedia"
               or now - (_aware(rows[s].checked_at) or now) >= fresh]
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    symbols.sort(key=lambda s: _aware(rows[s].checked_at) or epoch if s in rows else epoch)
    return symbols


def _store(db: Session, symbol: str, now: datetime, **cols: Any) -> CompanyDescription:
    row = db.get(CompanyDescription, symbol)
    if row is None:
        row = CompanyDescription(symbol=symbol, kind="none", checked_at=now, updated_at=now)
        db.add(row)
    changed = any(getattr(row, k) != v for k, v in cols.items() if k in ("text", "kind"))
    for k, v in cols.items():
        setattr(row, k, v)
    if changed:
        row.updated_at = now
    db.commit()
    return row


def refresh_one(db: Session, md: MarketData, info: InstrumentInfo, *, settings: Settings, client: Any,
                ai: AiWriter | None, now: datetime, report: RefreshReport, wiki_open: bool) -> bool:
    """Look up / write one company's description. Returns ``False`` when Wikimedia refused (stop the lookups)."""
    row = db.get(CompanyDescription, info.symbol)
    refresh_every = timedelta(days=settings.company_wiki_refresh_days)
    wiki_due = row is None or now - (_aware(row.checked_at) or now) >= refresh_every
    if wiki_due and wiki_open and client is not None:
        prof = _profile_row(db, md, info.symbol) if info.market != "US" else None
        v = (prof.values or {}) if prof else {}
        names = [str(v.get("short_name") or info.name), str(v.get("name") or "")] if prof else [info.name]
        report.wiki_lookups += 1
        try:
            found = client.lookup(info.code, info.market, names, v.get("name") if prof else None)
        except wm.WikimediaRefused as exc:
            report.paused = True
            report.errors.append(f"wikimedia: {exc}")
            return False
        except ProviderUnavailable as exc:
            report.errors.append(f"{info.symbol}: {exc}")
            return True
        if found is not None:
            article, summary = found
            report.wiki_found += 1
            _store(db, info.symbol, now, kind="wikipedia", text=summary.text, title=summary.title, url=summary.url,
                   revision_id=summary.revision_id, wikidata_id=article.wikidata_id, checked_at=now,
                   facts_key=None, model=None)
        elif row is None or row.kind == "wikipedia":  # never found, or the article is gone
            _store(db, info.symbol, now, kind="none", text=None, title=None, url=None, revision_id=None,
                   wikidata_id=None, checked_at=now)
        else:
            _store(db, info.symbol, now, checked_at=now)
        row = db.get(CompanyDescription, info.symbol)
    # AI only once a lookup found no article (kind "none"), or to rewrite an AI text whose facts changed
    if row is not None and row.kind in ("none", "ai") and info.market != "US" and ai is not None \
            and report.ai_written < settings.company_ai_per_run:
        facts = official_facts(db, md, info)
        if facts is None:
            return True
        key = facts_key(facts)
        if row is not None and row.kind == "ai" and row.facts_key == key:
            return True
        prof = _profile_row(db, md, info.symbol)
        forbidden = [str((prof.values or {}).get(k) or "") for k in ("chairman", "president")] if prof else []
        try:
            got = ai.write(db, facts)
        except Exception as exc:  # no key / API error: keep what we have
            report.errors.append(f"{info.symbol} ai: {type(exc).__name__}")
            return True
        text = _clean_ai_text(got[0], forbidden) if got else None
        if text:
            report.ai_written += 1
            _store(db, info.symbol, now, kind="ai", text=text, title=None, url=None, revision_id=None,
                   wikidata_id=None, facts_key=key, model=got[1] if got else None)
    return True


def refresh(db: Session, md: MarketData, *, settings: Settings | None = None, client: Any = "default",
            ai: Any = "default", symbols: list[str] | None = None,
            now_fn: Callable[[], datetime] = now_utc) -> RefreshReport:
    """One batch (see the module docstring). ``client`` / ``ai`` / ``symbols`` are for tests and the CLI."""
    global _paused_until
    settings = settings or get_settings()
    report = RefreshReport()
    if not settings.company_descriptions_enabled:
        return report
    now = now_fn()
    if client == "default":
        client = wm.WikimediaClient(settings.wikimedia_contact)
    if ai == "default":
        ai = default_ai(settings)
    wiki_open = _paused_until is None or now >= _paused_until
    todo = symbols if symbols is not None else due_symbols(db, settings, now)
    for sym in todo:
        info = md.instrument(sym)
        if info is None or info.type != "stock":
            continue
        report.symbols += 1
        lookups_left = report.wiki_lookups < settings.company_max_symbols_per_run
        if not refresh_one(db, md, info, settings=settings, client=client, ai=ai, now=now, report=report,
                           wiki_open=wiki_open and lookups_left):
            wiki_open = False
            _paused_until = now + WIKI_PAUSE
            log.warning("wikimedia refused; lookups paused until %s", iso_taipei(_paused_until))
    log.info("company descriptions: %s", report)
    return report


def reset_pause() -> None:
    global _paused_until
    _paused_until = None


def main(argv: list[str] | None = None) -> None:
    from forliosa.db import session_factory
    from forliosa.marketdata.service import get_market_data

    parser = argparse.ArgumentParser(description="個股頁「關於」：維基百科節錄或 AI 簡介")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("refresh", help="更新公司簡介（預設：追蹤中的股票）")
    p.add_argument("symbols", nargs="*")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    with session_factory()() as db:
        rep = refresh(db, get_market_data(), symbols=args.symbols or None)
    print(f"  股票 {rep.symbols}、維基查詢 {rep.wiki_lookups}、找到 {rep.wiki_found}、AI 簡介 {rep.ai_written}"
          + ("、維基百科暫停（429／403）" if rep.paused else ""))


if __name__ == "__main__":
    main()
