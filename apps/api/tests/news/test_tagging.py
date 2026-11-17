"""新聞標籤 (產品負責人 2026-11-17, ``forliosa.news.tagging`` / ``tags`` / ``taxonomy``): the job, its checks, the
budget, retries, and what the AI tools show. The model is the fake Messages API (``tests/ai/fake_anthropic.py``)."""

from __future__ import annotations

import json
import logging
import random
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from forliosa.marketdata.catalog import _tw, _us
from forliosa.marketdata.demo import DemoProvider
from forliosa.marketdata.service import MarketData, set_market_data
from forliosa.models import (
    AiUsage,
    CompanyProfile,
    NewsArticle,
    NewsBlockedDomain,
    NewsTag,
    NewsTagState,
    SecCompany,
    SecTicker,
    User,
)
from forliosa.news import normalize, service, tagging, tags, taxonomy
from forliosa.news.normalize import Headline, url_key
from tests.ai.fake_anthropic import Reply, text, thinking

NOW = datetime(2026, 11, 17, 4, 0, tzinfo=UTC)


def head(title: str, url: str, at: datetime = NOW - timedelta(hours=1), outlet: str = "經濟日報",
         domain: str = "money.udn.com") -> Headline:
    return Headline(title=title, url=url, outlet=outlet, domain=domain, published_at=at, source="gdelt")


def answer(*items: dict) -> dict:
    """A fake structured answer: a thinking block, then the JSON text."""
    return {"blocks": [thinking(), text(json.dumps({"items": list(items)}, ensure_ascii=False))]}


def entry(i: int, themes=(), sectors=(), companies=()) -> dict:
    return {"id": i, "themes": list(themes), "sectors": list(sectors), "companies": list(companies)}


def reply(fake, *items: dict, **kw) -> None:
    fake.reply(*answer(*items)["blocks"], **kw)


def cfg(settings, **kw):
    base = {"news_tagging_enabled": True, "news_tagging_monthly_budget_usd": 3.0, "news_tagging_batch_size": 50,
            "news_tagging_max_batches": 4, "news_tagging_days": 7, "news_tagging_min_batch": 1}
    return settings.model_copy(update={**base, **kw})


def sent(fake, i: int = -1) -> list[dict]:
    """The headlines a request sent (parsed back from its user message)."""
    content = fake.requests[i]["body"]["messages"][0]["content"]
    return json.loads(content[content.index("["):])


def state(db: Session, url: str) -> NewsTagState | None:
    return db.get(NewsTagState, url_key(url))


def tag_rows(db: Session, url: str) -> set[tuple[str, str, str | None]]:
    return {(t.kind, t.value, t.relation) for t in db.scalars(select(NewsTag).where(NewsTag.url_key == url_key(url)))}


# -- the vocabulary -------------------------------------------------------------------------------------------
def test_taxonomy_is_fixed_versioned_and_uses_the_official_industries():
    assert taxonomy.TAXONOMY_VERSION >= 1
    assert 25 <= len(taxonomy.THEMES) <= 40
    assert len({t.id for t in taxonomy.THEMES}) == len(taxonomy.THEMES)
    assert len({t.label for t in taxonomy.SECTORS}) == len(taxonomy.SECTORS)  # labels are the model's enum
    # Taiwan sectors are the official 產業別 codes, minus the ones that say nothing about a story
    assert taxonomy.SECTOR_BY_ID["24"].label == "半導體業" and "91" not in taxonomy.SECTOR_BY_ID
    assert taxonomy.sector_id("半導體") == "24" and taxonomy.sector_id("美股半導體") == "us_semis"
    assert taxonomy.theme_id("AI伺服器") == "ai_server" and taxonomy.theme_id("PC/手機") == "pc_phone"
    assert taxonomy.theme_id("不存在") is None and taxonomy.sector_id("") is None
    assert taxonomy.tw_sector_for_industry("24") == "24" and taxonomy.tw_sector_for_industry(None, "航運業") == "15"
    assert taxonomy.tw_sector_for_industry("91") is None


@pytest.mark.parametrize(("sic", "sector"), [("3674", "us_semis"), (7372, "us_tech"), ("2834", "us_health"),
                                             ("6022", "us_financials"), ("4512", "us_industrials"),
                                             ("3711", "us_consumer_disc"), ("1311", "us_energy"),
                                             ("6798", "us_real_estate"), ("4911", "us_utilities"),
                                             ("4813", "us_comm"), ("5331", "us_staples"), ("6324", "us_health"),
                                             ("3826", "us_health"), ("3021", "us_consumer_disc"),
                                             ("4700", "us_consumer_disc"), ("", None), ("x", None)])
def test_sic_codes_map_to_the_us_sectors(sic, sector):
    assert taxonomy.us_sector_for_sic(sic) == sector


def test_the_request_uses_structured_outputs_haiku_low_effort_and_a_cached_prompt(engine, commercial_md, settings,
                                                                                   fake, pool):
    with Session(engine) as db:
        service.store(db, "2330.TW", [head("台積電法說會釋利多 CoWoS 產能倍增", "https://money.udn.com/a/1")], NOW)
        reply(fake, entry(1, ["先進封裝", "財報／法說"], ["半導體業"]))
        res = tagging.run(db, commercial_md, settings=cfg(settings), pool=pool, now=NOW)
    assert res.tagged == 1 and res.calls == 1
    body = fake.requests[0]["body"]
    assert body["model"] == "claude-haiku-5-5"
    assert body["output_config"]["effort"] == "low"
    fmt = body["output_config"]["format"]
    assert fmt["type"] == "json_schema" and fmt["schema"] == tagging.OUTPUT_SCHEMA
    item = fmt["schema"]["properties"]["items"]["items"]
    assert item["properties"]["themes"]["items"]["enum"] == [t.label for t in taxonomy.THEMES]
    assert item["properties"]["sectors"]["items"]["enum"] == [t.label for t in taxonomy.SECTORS]
    assert item["additionalProperties"] is False and set(item["required"]) == {"id", "themes", "sectors", "companies"}
    # cached for an hour: requests come up to NEWS_TAGGING_MAX_WAIT_MINUTES (30) apart
    assert body["system"][0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert not {"temperature", "top_p", "top_k", "tool_choice", "tools", "thinking"} & set(body)
    assert sent(fake) == [{"id": 1, "title": "台積電法說會釋利多 CoWoS 產能倍增", "outlet": "經濟日報",
                           "stocks": ["2330 台積電（半導體業）"]}]


# -- checking the answer ----------------------------------------------------------------------------------------
def test_unknown_tags_are_dropped_and_the_lists_capped(engine, commercial_md, settings, fake, pool):
    url = "https://money.udn.com/a/2"
    with Session(engine) as db:
        service.store(db, "2330.TW", [head("台積電與鴻海 AI 伺服器出貨", url)], NOW)
        reply(fake, entry(1, ["AI 伺服器", "不存在的主題", "先進封裝", "AI 伺服器", "財報／法說", "人事"],
                          ["半導體業", "外星產業", "其他電子業", "電腦及週邊設備業", "美股半導體"]))
        tagging.run(db, commercial_md, settings=cfg(settings), pool=pool, now=NOW)
        rows = tag_rows(db, url)
        st = state(db, url)
    assert {v for k, v, _ in rows if k == "theme"} == {"ai_server", "advanced_packaging", "earnings"}
    assert {v for k, v, _ in rows if k == "sector"} == {"24", "31", "25"}
    assert st.status == "done" and st.taxonomy_version == taxonomy.TAXONOMY_VERSION and st.model == "claude-haiku-5-5"


def test_related_stocks_must_exist_and_match_their_names(engine, commercial_md, settings, fake, pool):
    url = "https://money.udn.com/a/3"
    with Session(engine) as db:
        service.store(db, "2330.TW", [head("台積電、鴻海、聯發科、輝達與 OpenAI 合作", url)], NOW)
        reply(fake, entry(1, ["AI 伺服器"], [], [
            {"name": "鴻海", "code": "2317", "relation": "mentioned"},  # right
            {"name": "台積電", "code": "2330", "relation": "mentioned"},  # the story's own stock
            {"name": "聯發科", "code": "2317", "relation": "mentioned"},  # wrong code, right name -> 2454
            {"name": "Nvidia", "code": "NVDA", "relation": "supply_chain"},  # US, English name
            {"name": "OpenAI", "code": "", "relation": "mentioned"},  # not listed
            {"name": "廣達", "code": "9999", "relation": "weird"},  # unknown code, exact name; bad relation
            {"name": "不存在公司", "code": "1234", "relation": "peer"},  # made up
            {"name": "台達電", "code": "2308", "relation": "peer"},
            {"name": "中華電", "code": "2412", "relation": "peer"},  # sixth: over the cap
        ]))
        tagging.run(db, commercial_md, settings=cfg(settings), pool=pool, now=NOW)
        rows = tag_rows(db, url)
    symbols = [(v, r) for k, v, r in rows if k == "symbol"]
    assert sorted(symbols) == sorted([("2317.TW", "mentioned"), ("2454.TW", "mentioned"), ("NVDA", "supply_chain"),
                                      ("2382.TW", "mentioned"), ("2308.TW", "peer")])


def test_name_and_code_checks():
    assert tagging.name_key("Micron Technology, Inc.") == "microntechnology"
    assert tagging.name_key("康友-KY") == "康友" and tagging.name_key("Sky Harbour") == "skyharbour"
    assert tagging.names_agree("台積", {"台積電"}) and tagging.names_agree("Micron", {"microntechnology"})
    assert not tagging.names_agree("A", {"a"}) and not tagging.names_agree("鴻海", {"台積電"})


def test_a_ticker_written_as_the_name_resolves(engine, commercial_md):
    with Session(engine) as db:
        cat = tagging.Catalog(db, commercial_md)
        assert tagging.resolve_company(cat, "NVDA", "NVDA") == "NVDA"
        assert tagging.resolve_company(cat, "輝達", "NVDA") == "NVDA"  # the catalog's Chinese alias
        assert tagging.resolve_company(cat, "Apple", "") == "AAPL"
        # a name of another market than the code's is not looked up across markets
        assert tagging.resolve_company(cat, "台積電", "AAPL") is None
        assert tagging.resolve_company(cat, "", "2330") is None


# -- what is sent, once per URL ------------------------------------------------------------------------------------
def test_a_url_stored_for_several_symbols_is_tagged_once(engine, commercial_md, settings, fake, pool):
    url = "https://money.udn.com/a/4"
    with Session(engine) as db:
        for sym in ("2330.TW", "2317.TW"):
            service.store(db, sym, [head("台積電、鴻海攜手擴產美國廠", url)], NOW)
        reply(fake, entry(1, ["擴產／資本支出"], ["半導體業"],
                          [{"name": "鴻海", "code": "2317", "relation": "mentioned"}]))
        res = tagging.run(db, commercial_md, settings=cfg(settings), pool=pool, now=NOW)
        rows = tag_rows(db, url)
        assert db.scalar(select(NewsTagState.url_key).where(NewsTagState.url_key == url_key(url)))
    assert res.tagged == 1 and len(fake.requests) == 1
    assert sent(fake)[0]["stocks"] == ["2330 台積電（半導體業）", "2317 鴻海（其他電子業）"]
    assert not any(k == "symbol" for k, _, _ in rows)  # 鴻海 is one of the URL's own stocks


def test_batches_oldest_first_within_the_window(engine, commercial_md, settings, fake, pool):
    with Session(engine) as db:
        heads = [head(f"台積電新聞 {i:03d}", f"https://money.udn.com/b/{i}", at=NOW - timedelta(minutes=500 - i))
                 for i in range(120)]
        heads.append(head("台積電十天前的新聞", "https://money.udn.com/b/old", at=NOW - timedelta(days=10)))
        service.store(db, "2330.TW", heads, NOW)
        for n in (50, 50, 20):
            reply(fake, *[entry(i, ["財報／法說"]) for i in range(1, n + 1)])
        res = tagging.run(db, commercial_md, settings=cfg(settings), pool=pool, now=NOW)
        assert state(db, "https://money.udn.com/b/old") is None  # outside NEWS_TAGGING_DAYS
    assert res.tagged == 120 and res.calls == 3
    assert [len(sent(fake, i)) for i in range(3)] == [50, 50, 20]
    assert sent(fake, 0)[0]["title"] == "台積電新聞 000" and sent(fake, 2)[-1]["title"] == "台積電新聞 119"
    assert len({r["key"] for r in fake.requests}) == 1  # the run stays on one key (its prompt cache)


def test_the_number_of_batches_per_run_is_capped(engine, commercial_md, settings, fake, pool):
    with Session(engine) as db:
        service.store(db, "2330.TW", [head(f"台積電新聞 {i}", f"https://money.udn.com/c/{i}") for i in range(5)], NOW)
        for _ in range(2):
            reply(fake, *[entry(i) for i in range(1, 3)])
        res = tagging.run(db, commercial_md, settings=cfg(settings, news_tagging_batch_size=2,
                                                           news_tagging_max_batches=2), pool=pool, now=NOW)
    assert res.calls == 2 and res.tagged == 4 and res.untagged == 4


def test_hidden_headlines_are_skipped_without_a_call(engine, commercial_md, settings, fake, pool):
    with Session(engine) as db:
        service.store(db, "2330.TW", [
            head("台積電股價走勢", "https://www.cmoney.tw/forum/stock/2330", outlet="CMoney", domain="cmoney.tw"),
            head("台積電被下架的媒體", "https://blocked.example.com/n/1", outlet="X", domain="blocked.example.com")],
            NOW)
        db.add(NewsBlockedDomain(domain="blocked.example.com"))
        db.commit()
        res = tagging.run(db, commercial_md, settings=cfg(settings), pool=pool, now=NOW)
        statuses = {s.status for s in db.scalars(select(NewsTagState))}
    assert res.calls == 0 and res.skipped == 2 and statuses == {"skipped"} and not fake.requests


# -- failures, retries and the budget ----------------------------------------------------------------------------
def test_a_bad_answer_counts_an_attempt_and_gives_up_after_three(engine, commercial_md, settings, fake, pool):
    url = "https://money.udn.com/a/5"
    s = cfg(settings)
    with Session(engine) as db:
        service.store(db, "2330.TW", [head("台積電新聞", url)], NOW)
        at = NOW
        for attempt in range(1, 4):
            fake.reply(thinking(), text("not json"))
            res = tagging.run(db, commercial_md, settings=s, pool=pool, now=at)
            st = state(db, url)
            assert res.failed == 1 and st.status == "failed" and st.attempts == attempt
            assert res.calls == 1
            if attempt < 3:
                assert st.retry_at is not None
                # not asked again before retry_at
                assert tagging.run(db, commercial_md, settings=s, pool=pool, now=at + timedelta(minutes=1)).calls == 0
                at = tagging._aware(st.retry_at) + timedelta(seconds=1)
        assert state(db, url).retry_at is None
        later = tagging.run(db, commercial_md, settings=s, pool=pool, now=NOW + timedelta(days=1))
    assert later.calls == 0 and len(fake.requests) == 3


@pytest.mark.parametrize(("stop", "attempts"), [("refusal", tagging.MAX_ATTEMPTS), ("max_tokens", 1)])
def test_a_refused_or_cut_off_answer_is_not_used(engine, commercial_md, settings, fake, pool, stop, attempts):
    url = "https://money.udn.com/a/6"
    with Session(engine) as db:
        service.store(db, "2330.TW", [head("台積電新聞", url)], NOW)
        reply(fake, entry(1, ["財報／法說"]), stop_reason=stop)
        res = tagging.run(db, commercial_md, settings=cfg(settings), pool=pool, now=NOW)
        st = state(db, url)
        # a headline sent alone and refused gives up at once: the same request would be refused again
        assert st.status == "failed" and st.attempts == attempts and not tag_rows(db, url)
    assert res.failed == 1 and res.tagged == 0


def test_a_headline_missing_from_the_answer_is_retried(engine, commercial_md, settings, fake, pool):
    with Session(engine) as db:
        service.store(db, "2330.TW", [head("台積電甲", "https://money.udn.com/d/1", at=NOW - timedelta(hours=2)),
                                      head("台積電乙", "https://money.udn.com/d/2")], NOW)
        reply(fake, entry(1, ["財報／法說"]), entry(7, ["人事"]))  # id 7 does not exist; id 2 is missing
        res = tagging.run(db, commercial_md, settings=cfg(settings), pool=pool, now=NOW)
        assert state(db, "https://money.udn.com/d/1").status == "done"
        st = state(db, "https://money.udn.com/d/2")
    assert res.tagged == 1 and res.failed == 1 and st.status == "failed" and st.attempts == 1


def test_busy_keys_stop_the_run_without_counting_an_attempt(engine, commercial_md, settings, fake, pool):
    url = "https://money.udn.com/a/7"
    with Session(engine) as db:
        service.store(db, "2330.TW", [head("台積電新聞", url)], NOW)
        for _ in range(4):
            fake.error(429, "rate_limit_error", headers={"retry-after": "30"})
        res = tagging.run(db, commercial_md, settings=cfg(settings), pool=pool, now=NOW)
        assert state(db, url) is None
    assert res.stopped == "busy" and res.failed == 0


@pytest.mark.parametrize(("status", "etype"), [(404, "not_found_error"), (400, "invalid_request_error")])
def test_a_request_level_error_counts_no_attempt_and_is_logged_hourly(engine, commercial_md, settings, fake, pool,
                                                                      caplog, status, etype):
    """A wrong model (404) or a parameter / schema the model does not take (400) is the request's fault, not the
    headlines': the run stops, nothing is counted, and once the setting is fixed everything is tagged."""
    tagging._warned.clear()
    s = cfg(settings)
    with Session(engine) as db:
        service.store(db, "2330.TW", [head(f"台積電新聞 {i}", f"https://money.udn.com/e/{i}") for i in range(3)], NOW)
        with caplog.at_level(logging.WARNING, logger="forliosa.news.tagging"):
            for minutes in (0, 5, 10, 30, 61):  # every run for an hour fails the same way
                fake.error(status, etype, "model: claude-haiku-5-x")
                res = tagging.run(db, commercial_md, settings=s, pool=pool, now=NOW + timedelta(minutes=minutes))
                assert res.stopped == "error" and res.calls == 0 and res.failed == 0 and res.split == 0
        assert db.scalars(select(NewsTagState)).all() == []  # no attempt counted, nothing given up
        assert len(fake.requests) == 5  # one request per run: the error is not retried on the other key
        # logged at the first run and again an hour later, not every five minutes; never the key
        warnings = [r.getMessage() for r in caplog.records if "news tagging stopped" in r.getMessage()]
        assert len(warnings) == 2 and f"{status} {etype}" in warnings[0]
        assert not any("sk-test" in w for w in warnings)
        # the setting is fixed: everything is tagged
        reply(fake, entry(1, ["財報／法說"]), entry(2), entry(3))
        res = tagging.run(db, commercial_md, settings=s, pool=pool, now=NOW + timedelta(minutes=65))
    assert res.tagged == 3 and res.stopped is None


def test_usage_is_recorded_and_the_month_budget_stops_the_job(engine, commercial_md, settings, fake, pool, caplog):
    with Session(engine) as db:
        service.store(db, "2330.TW", [head("台積電新聞", "https://money.udn.com/a/8")], NOW)
        reply(fake, entry(1, ["財報／法說"]), usage={"input_tokens": 4000, "output_tokens": 2000})
        tagging.run(db, commercial_md, settings=cfg(settings), pool=pool, now=NOW)
        usage = db.scalars(select(AiUsage).where(AiUsage.feature == "news_tagging")).one()
        assert usage.user_id is None and usage.key_slot in (1, 2) and Decimal(usage.cost_usd) > 0
        # the month is (nearly) spent: nothing is asked, and the log says so once
        db.add(AiUsage(user_id=None, feature="news_tagging", model="claude-haiku-5-5", cost_usd=Decimal("2.995"),
                       created_at=NOW))
        service.store(db, "2330.TW", [head("台積電新聞二", "https://money.udn.com/a/9")], NOW)
        tagging._budget_logged.clear()
        with caplog.at_level(logging.WARNING, logger="forliosa.news.tagging"):
            first = tagging.run(db, commercial_md, settings=cfg(settings), pool=pool, now=NOW)
            second = tagging.run(db, commercial_md, settings=cfg(settings), pool=pool, now=NOW)
        # a new UTC month starts again
        reply(fake, entry(1))
        december = tagging.run(db, commercial_md, settings=cfg(settings, news_tagging_days=30), pool=pool,
                               now=datetime(2026, 12, 1, 0, 5, tzinfo=UTC))
    assert first.stopped == second.stopped == "budget" and first.calls == second.calls == 0
    assert sum("monthly budget" in r.message for r in caplog.records) == 1
    assert december.calls == 1


def test_a_zero_budget_means_no_tagging(engine, commercial_md, settings, fake, pool):
    with Session(engine) as db:
        service.store(db, "2330.TW", [head("台積電新聞", "https://money.udn.com/a/10")], NOW)
        res = tagging.run(db, commercial_md, settings=cfg(settings, news_tagging_monthly_budget_usd=0), pool=pool,
                          now=NOW)
    assert res.stopped == "budget" and not fake.requests


def test_disabled_tagging_does_nothing_and_has_no_worker_job(engine, commercial_md, settings, fake, pool,
                                                             monkeypatch):
    from forliosa.config import get_settings
    from forliosa.worker import Worker

    with Session(engine) as db:
        service.store(db, "2330.TW", [head("台積電新聞", "https://money.udn.com/a/11")], NOW)
        res = tagging.run(db, commercial_md, settings=cfg(settings, news_tagging_enabled=False), pool=pool, now=NOW)
    assert res.stopped == "disabled" and not fake.requests
    get_settings.cache_clear()
    assert "news_tagging" in [j.name for j in Worker(md=object()).jobs]  # type: ignore[arg-type]
    job = next(j for j in Worker(md=object()).jobs if j.name == "news_tagging")  # type: ignore[arg-type]
    assert job.background and job.due(NOW, NOW - timedelta(minutes=5)) and not job.due(NOW, NOW - timedelta(minutes=4))
    monkeypatch.setenv("NEWS_TAGGING_ENABLED", "false")
    get_settings.cache_clear()
    try:
        assert "news_tagging" not in [j.name for j in Worker(md=object()).jobs]  # type: ignore[arg-type]
    finally:
        monkeypatch.delenv("NEWS_TAGGING_ENABLED")
        get_settings.cache_clear()


def test_no_key_means_no_call(engine, commercial_md, settings):
    with Session(engine) as db:
        service.store(db, "2330.TW", [head("台積電新聞", "https://money.udn.com/a/12")], NOW)
        res = tagging.run(db, commercial_md, settings=cfg(settings), now=NOW)  # the autouse empty pool
    assert res.stopped == "no_key" and res.calls == 0


# -- keeping tags in step with the headlines --------------------------------------------------------------------
def test_tags_go_with_their_headline_and_a_new_vocabulary_tags_again(engine, commercial_md, settings, fake, pool,
                                                                      monkeypatch):
    url = "https://money.udn.com/a/13"
    with Session(engine) as db:
        service.store(db, "2330.TW", [head("台積電新聞", url)], NOW)
        reply(fake, entry(1, ["財報／法說"]))
        tagging.run(db, commercial_md, settings=cfg(settings), pool=pool, now=NOW)
        assert tag_rows(db, url) == {("theme", "earnings", None)}
        # vocabulary bumped: tagged again, the old tags replaced
        monkeypatch.setattr(taxonomy, "TAXONOMY_VERSION", taxonomy.TAXONOMY_VERSION + 1)
        reply(fake, entry(1, ["人事"]))
        res = tagging.run(db, commercial_md, settings=cfg(settings), pool=pool, now=NOW)
        assert res.tagged == 1 and tag_rows(db, url) == {("theme", "management", None)}
        assert state(db, url).taxonomy_version == taxonomy.TAXONOMY_VERSION and state(db, url).attempts == 2
        # the headline is deleted (retention, takedown): its tags and state go at the next run
        db.query(NewsArticle).delete()
        db.commit()
        res = tagging.run(db, commercial_md, settings=cfg(settings), pool=pool, now=NOW)
        assert res.purged == 1 and not tag_rows(db, url) and state(db, url) is None


# -- reading: search, grouping, the AI tools ----------------------------------------------------------------------
def _tagged(db: Session, rows: list[tuple[str, str, str, datetime, set[tuple[str, str, str | None]]]]) -> None:
    """Store headlines and their tags directly (no model)."""
    for symbol, title, url, at, tag_set in rows:
        service.store(db, symbol, [head(title, url, at=at)], NOW)
        for kind, value, rel in tag_set:
            if db.get(NewsTag, (url_key(url), kind, value)) is None:
                db.add(NewsTag(url_key=url_key(url), kind=kind, value=value, relation=rel))
        if db.get(NewsTagState, url_key(url)) is None:
            db.add(NewsTagState(url_key=url_key(url), status="done", model="m", taxonomy_version=1, attempts=1,
                                tagged_at=NOW, updated_at=NOW))
    db.commit()


def _search_rows():
    return [
        ("2330.TW", "台積電 CoWoS 擴產，弘塑受惠", "https://money.udn.com/s/1", NOW - timedelta(hours=1),
         {("theme", "advanced_packaging", None), ("sector", "24", None), ("symbol", "2317.TW", "supply_chain")}),
        ("2317.TW", "鴻海 AI 伺服器出貨創高", "https://money.udn.com/s/2", NOW - timedelta(hours=2),
         {("theme", "ai_server", None), ("sector", "31", None)}),
        ("2603.TW", "長榮貨櫃運價回升", "https://money.udn.com/s/3", NOW - timedelta(days=3),
         {("theme", "shipping", None), ("sector", "15", None)}),
        ("2317.TW", "鴻海十天前的 AI 新聞", "https://money.udn.com/s/4", NOW - timedelta(days=10),
         {("theme", "ai_server", None)}),
        ("^US", "Wall Street falls as Nvidia slides", "https://www.reuters.com/s/5", NOW - timedelta(hours=5),
         {("theme", "market_moves", None), ("sector", "us_semis", None), ("symbol", "NVDA", "mentioned")}),
    ]


def test_search_by_theme_sector_symbol_keyword_and_days(engine, commercial_md, settings):
    with Session(engine) as db:
        _tagged(db, _search_rows())

        def titles(**kw):
            return [x["title"] for x in tags.search(db, commercial_md, now=NOW, settings=settings, **kw)]

        assert titles(theme="ai_server") == ["鴻海 AI 伺服器出貨創高"]
        assert titles(theme="ai_server", days=30) == ["鴻海 AI 伺服器出貨創高", "鴻海十天前的 AI 新聞"]
        assert titles(sector="15") == ["長榮貨櫃運價回升"]
        assert titles(sector="15", days=1) == []
        # a symbol finds what is stored under it and what is tagged with it
        assert titles(symbol="2317.TW") == ["台積電 CoWoS 擴產，弘塑受惠", "鴻海 AI 伺服器出貨創高"]
        assert titles(symbol="NVDA") == ["Wall Street falls as Nvidia slides"]
        assert titles(keyword="cowos") == ["台積電 CoWoS 擴產，弘塑受惠"]
        assert titles(keyword="100%") == []  # LIKE wildcards are escaped
        assert titles(theme="ai_server", sector="24") == []
        assert len(titles()) == 4
        item = tags.search(db, commercial_md, symbol="2317.TW", now=NOW, settings=settings)[0]
        assert item["themes"] == ["先進封裝"] and item["sectors"] == ["半導體業"]
        assert item["related"] == [{"symbol": "2317.TW", "name": "鴻海", "relation": "supply_chain"}]
        assert item["stocks"] == [{"symbol": "2330.TW", "name": "台積電"}]
        assert item["tag_note"] == "主題：先進封裝；類股：半導體業；相關：2317 鴻海（供應鏈）"
        us = tags.search(db, commercial_md, symbol="NVDA", now=NOW, settings=settings)[0]
        assert us["market"] == "美股大盤" and us["stocks"] == []


def test_search_leaves_out_hidden_and_duplicate_headlines(engine, commercial_md, settings):
    with Session(engine) as db:
        _tagged(db, [
            ("2330.TW", "台積電 AI 新聞", "https://money.udn.com/h/1", NOW - timedelta(hours=1),
             {("theme", "ai_server", None)}),
            ("2330.TW", "台積電 AI 新聞", "https://tw.news.yahoo.com/h/1", NOW - timedelta(hours=1),
             {("theme", "ai_server", None)}),  # an aggregator copy of the same story
            ("2330.TW", "台積電論壇", "https://www.cmoney.tw/forum/2330", NOW - timedelta(hours=1),
             {("theme", "ai_server", None)}),  # not news
        ])
        found = tags.search(db, commercial_md, theme="ai_server", now=NOW, settings=settings)
    assert [x["url"] for x in found] == ["https://money.udn.com/h/1"]


def test_news_grouped_by_theme_and_sector_for_the_reports(engine, commercial_md, settings):
    with Session(engine) as db:
        _tagged(db, _search_rows())
        themes = tags.by_topic(db, commercial_md, "theme", NOW - timedelta(days=7), NOW, settings=settings)
        sectors = tags.by_topic(db, commercial_md, "sector", NOW - timedelta(days=7), NOW, per_group=1,
                                settings=settings)
    # equal counts keep the vocabulary's order
    assert [(g["label"], g["count"]) for g in themes] == [("AI 伺服器", 1), ("先進封裝", 1), ("航運", 1),
                                                          ("大盤行情", 1)]
    assert themes[0]["items"][0]["title"] == "鴻海 AI 伺服器出貨創高"  # the 10-day-old one is outside the range
    assert {g["label"]: g["count"] for g in sectors} == {"半導體業": 1, "其他電子業": 1, "航運業": 1, "美股半導體": 1}
    assert all(len(g["items"]) == 1 for g in sectors)


def _ctx(db: Session, md):
    from forliosa.ai.tools import ToolContext

    return ToolContext(db=db, user=db.scalar(select(User).where(User.email == "demo@forliosa.local")), md=md)


def test_search_news_tool(client, engine, commercial_md, monkeypatch):
    from forliosa.ai import tools

    monkeypatch.setattr(tools, "now_utc", lambda: NOW)
    monkeypatch.setattr(tags, "now_utc", lambda: NOW)
    with Session(engine) as db:
        _tagged(db, _search_rows())
        ctx = _ctx(db, commercial_md)
        out = tools.execute(ctx, "search_news", {"theme": "先進封裝", "sector": "", "symbol": "", "keyword": "",
                                                 "days": 7})
        assert not out.is_error
        [block] = out.content
        assert block["type"] == "search_result" and block["source"] == "https://money.udn.com/s/1"
        assert block["content"][0]["text"] == "經濟日報，今天 11/17 11:00：台積電 CoWoS 擴產，弘塑受惠"
        assert block["content"][1]["text"] == ("歸在：2330 台積電；主題：先進封裝；類股：半導體業；"
                                               "相關：2317 鴻海（供應鏈）")
        assert out.outlets == {"https://money.udn.com/s/1": "經濟日報"}
        # by stock name, US market headlines, an empty result and a wrong label
        by_symbol = tools.execute(ctx, "search_news", {"theme": "", "sector": "美股半導體", "symbol": "",
                                                       "keyword": "", "days": 7})
        assert by_symbol.content[0]["content"][1]["text"].startswith("美股大盤；主題：大盤行情")
        none = tools.execute(ctx, "search_news", {"theme": "航運", "sector": "", "symbol": "台積電", "keyword": "",
                                                  "days": 90})
        data = json.loads(none.content)
        assert data["headlines"] == [] and "只保留 30 天" in data["note"] and "web_search" in data["note"]
        assert data["filters"] == {"theme": "航運", "symbol": "2330.TW"}
        bad = tools.execute(ctx, "search_news", {"theme": "火星", "sector": "", "symbol": "", "keyword": "",
                                                 "days": 7})
        assert bad.is_error and "沒有「火星」這個主題" in bad.content
    spec = tools.TOOLS_BY_NAME["search_news"]
    schema = spec.definition()["input_schema"]
    assert schema["required"] == ["theme", "sector", "symbol", "keyword", "days"]  # no new optional parameters
    assert schema["properties"]["theme"]["enum"][0] == "" and "AI 伺服器" in schema["properties"]["theme"]["enum"]
    assert tools.tool_label("search_news", {"theme": "航運", "symbol": "2603"}) == "搜尋新聞「航運、2603」"


def test_get_news_shows_each_media_headlines_tags(client, engine, commercial_md):
    from forliosa.ai import tools

    with Session(engine) as db:
        now = datetime.now(UTC)
        _tagged(db, [("2330.TW", "台積電 CoWoS 擴產", "https://money.udn.com/g/1", now - timedelta(hours=1),
                      {("theme", "advanced_packaging", None), ("sector", "24", None)}),
                     ("2330.TW", "台積電沒有標籤的新聞", "https://money.udn.com/g/2", now - timedelta(hours=2), set())])
        out = tools.execute(_ctx(db, commercial_md), "get_news", {"symbol": "2330"})
    assert not out.is_error
    by_url = {b["source"]: b for b in out.content}
    tagged = by_url["https://money.udn.com/g/1"]["content"]
    assert len(tagged) == 2 and tagged[1]["text"] == "主題：先進封裝；類股：半導體業"
    assert tagged[0]["text"].endswith("：台積電 CoWoS 擴產")  # the headline block a sentence cites is unchanged
    assert len(by_url["https://money.udn.com/g/2"]["content"]) == 1
    assert "classifier" in tools.TOOLS_BY_NAME["get_news"].description


def test_status_counts(engine, commercial_md, settings):
    with Session(engine) as db:
        _tagged(db, _search_rows()[:2])
        service.store(db, "2330.TW", [head("台積電還沒標", "https://money.udn.com/st/1")], NOW)
        out = tagging.status(db, now=NOW, settings=cfg(settings))
    assert out["states"] == {"done": 2} and out["never_tagged_in_window"] == 1 and out["tags"]["theme"] == 2


# -- review fixes (2026-11-17): splitting a failed batch, request errors, cost, family names, US sectors -------------
def _answering(poison: str | None = None, cut_off_over: int | None = None):
    """A responder for the fake: refuses any request holding a headline with ``poison`` in its title, cuts off any
    request of more than ``cut_off_over`` headlines, and otherwise tags every headline 財報／法說."""

    def respond(body: dict) -> Reply:
        content = body["messages"][0]["content"]
        rows = json.loads(content[content.index("["):])
        if poison and any(poison in r["title"] for r in rows):
            return Reply([], "refusal")
        if cut_off_over and len(rows) > cut_off_over:
            return Reply([thinking(), text('{"items": [{"id": 1, "themes": [')], "max_tokens")
        return Reply(answer(*[entry(r["id"], ["財報／法說"]) for r in rows])["blocks"])

    return respond


def test_one_refused_headline_does_not_take_its_batch_down(engine, commercial_md, settings, fake, pool):
    """The batch is halved until the refused headline is sent alone (and given up); the other 119 are all tagged."""
    fake.responder = _answering(poison="POISON")
    s = cfg(settings)
    with Session(engine) as db:
        service.store(db, "2330.TW", [
            head(("POISON " if i == 5 else "") + f"台積電新聞 {i:03d}", f"https://money.udn.com/p/{i}",
                 at=NOW - timedelta(minutes=600 - i)) for i in range(120)], NOW)
        at, results = NOW, []
        for _ in range(12):  # an hour of runs
            results.append(tagging.run(db, commercial_md, settings=s, pool=pool, now=at))
            at += timedelta(minutes=5)
        later = tagging.run(db, commercial_md, settings=s, pool=pool, now=NOW + timedelta(days=1))
        states = {st.url_key: (st.status, st.attempts, st.batch_limit) for st in db.scalars(select(NewsTagState))}
        assert tagging.status(db, now=NOW, settings=s)["gave_up"] == 1
    poison = states.pop(url_key("https://money.udn.com/p/5"))
    assert len(states) == 119 and set(states.values()) == {("done", 1, None)}
    assert poison[:2] == ("failed", tagging.MAX_ATTEMPTS)
    refused = [len(sent(fake, i)) for i in range(len(fake.requests))
               if any("POISON" in r["title"] for r in sent(fake, i))]
    assert refused == [50, 25, 13, 7, 4, 2, 1]  # halved until it is alone; refused alone: given up at once
    assert len(fake.requests) <= 16 and later.calls == 0
    assert sum(r.split for r in results) > 0 and sum(r.failed for r in results) == 1


def test_a_cut_off_batch_is_split_until_the_answers_fit(engine, commercial_md, settings, fake, pool):
    fake.responder = _answering(cut_off_over=20)
    with Session(engine) as db:
        service.store(db, "2330.TW", [head(f"台積電新聞 {i:03d}", f"https://money.udn.com/m/{i}",
                                           at=NOW - timedelta(minutes=100 - i)) for i in range(50)], NOW)
        first = tagging.run(db, commercial_md, settings=cfg(settings), pool=pool, now=NOW)
        second = tagging.run(db, commercial_md, settings=cfg(settings), pool=pool, now=NOW + timedelta(minutes=5))
        states = {(st.status, st.attempts) for st in db.scalars(select(NewsTagState))}
    # run 1: 50 cut off -> halves of 25; 25 cut off -> 13 + 12; 13 tagged; 12 + one of the other half tagged.
    # run 2: the other 24 cut off -> 12 + 12, both tagged
    assert [len(sent(fake, i)) for i in range(len(fake.requests))] == [50, 25, 13, 13, 24, 12, 12]
    assert (first.tagged, first.split, second.tagged, second.split) == (26, 75, 24, 24)
    assert first.failed == second.failed == 0
    assert states == {("done", 1)}  # a split never counts an attempt


def test_retry_failed_gives_the_attempts_back(engine, commercial_md, settings, fake, pool, capsys):
    url = "https://money.udn.com/a/20"
    s = cfg(settings)
    with Session(engine) as db:
        service.store(db, "2330.TW", [head("台積電新聞", url)], NOW)
        reply(fake, entry(1), stop_reason="refusal")
        tagging.run(db, commercial_md, settings=s, pool=pool, now=NOW)
        assert state(db, url).attempts == tagging.MAX_ATTEMPTS
        assert tagging.run(db, commercial_md, settings=s, pool=pool, now=NOW + timedelta(hours=1)).calls == 0
    assert tagging.main(["retry-failed"]) == 0
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1]) == {"reset": 1}
    with Session(engine) as db:
        st = state(db, url)
        assert st.status == "failed" and st.attempts == 0 and st.retry_at is None
        reply(fake, entry(1, ["財報／法說"]))
        res = tagging.run(db, commercial_md, settings=s, pool=pool, now=NOW + timedelta(hours=2))
        assert res.tagged == 1 and state(db, url).status == "done"


def test_a_trickle_waits_for_a_fuller_batch(engine, commercial_md, settings, fake, pool):
    """Fewer than NEWS_TAGGING_MIN_BATCH fresh headlines wait until the oldest was stored NEWS_TAGGING_MAX_WAIT_MINUTES
    ago; a full batch goes at once; a retry never waits."""
    s = cfg(settings, news_tagging_min_batch=20, news_tagging_max_wait_minutes=30)
    with Session(engine) as db:
        service.store(db, "2330.TW", [head(f"台積電新聞 {i}", f"https://money.udn.com/w/{i}") for i in range(3)], NOW)
        for minutes in (0, 5, 29):
            res = tagging.run(db, commercial_md, settings=s, pool=pool, now=NOW + timedelta(minutes=minutes))
            assert res.stopped == "waiting" and res.calls == 0
        assert not fake.requests
        reply(fake, entry(1), entry(2), entry(3))
        assert tagging.run(db, commercial_md, settings=s, pool=pool, now=NOW + timedelta(minutes=31)).tagged == 3
        # 20 new ones: no waiting
        later = NOW + timedelta(minutes=40)
        service.store(db, "2330.TW", [head(f"台積電新聞二 {i}", f"https://money.udn.com/w2/{i}", at=later)
                                      for i in range(20)], later)
        reply(fake, *[entry(i) for i in range(1, 21)])
        assert tagging.run(db, commercial_md, settings=s, pool=pool, now=later).tagged == 20
        # a failed one is asked again when due, alone
        service.store(db, "2330.TW", [head("台積電新聞三", "https://money.udn.com/w3/1", at=later)], later)
        fake.reply(thinking(), text("not json"))
        assert tagging.run(db, commercial_md, settings=s, pool=pool, now=later + timedelta(minutes=31)).failed == 1
        reply(fake, entry(1))
        res = tagging.run(db, commercial_md, settings=s, pool=pool, now=later + timedelta(minutes=47))
    assert res.tagged == 1 and len(sent(fake)) == 1


def test_runs_stay_on_the_key_slot_that_holds_the_cached_prompt(engine, commercial_md, settings, fake, pool):
    """Caches are per workspace: a run starts on the slot of the last tagging request (not the cheapest slot this
    month), unless that slot is cooling down."""
    s = cfg(settings)
    with Session(engine) as db:
        for n in range(3):
            service.store(db, "2330.TW", [head(f"台積電新聞 {n}", f"https://money.udn.com/k/{n}")], NOW)
            if n == 2:  # the slot hit a rate limit: the next run moves
                first = pool.get(db.scalar(select(AiUsage.key_slot).where(AiUsage.feature == "news_tagging")))
                first.cooldown_until, first.cooldown_hard = pool.clock() + 60, True
            reply(fake, entry(1), usage={"input_tokens": 500, "output_tokens": 3000})
            tagging.run(db, commercial_md, settings=s, pool=pool, now=NOW + timedelta(minutes=30 * n))
    keys = fake.keys_used
    assert keys[0] == keys[1] != keys[2]
    assert all(r["body"]["system"][0]["cache_control"]["ttl"] == "1h" for r in fake.requests)


def test_one_hour_cache_writes_cost_twice_the_input_price(engine, commercial_md, settings, fake, pool):
    from anthropic.types import Usage

    from forliosa.ai.pricing import CallUsage, estimate_cost

    m = "claude-haiku-5-5"
    assert estimate_cost(m, CallUsage(cache_creation_input_tokens=10_000)) == Decimal("0.00125")
    assert estimate_cost(m, CallUsage(cache_creation_input_tokens=10_000,
                                      cache_creation_1h_input_tokens=10_000)) == Decimal("0.002")
    usage = Usage.model_validate({"input_tokens": 1, "output_tokens": 1, "cache_creation_input_tokens": 5911,
                                  "cache_read_input_tokens": 0,
                                  "cache_creation": {"ephemeral_1h_input_tokens": 5911,
                                                     "ephemeral_5m_input_tokens": 0}})
    assert CallUsage.from_sdk(usage).cache_creation_1h_input_tokens == 5911
    with Session(engine) as db:
        service.store(db, "2330.TW", [head("台積電新聞", "https://money.udn.com/a/21")], NOW)
        reply(fake, entry(1), usage={"input_tokens": 0, "output_tokens": 0, "cache_creation_input_tokens": 5911,
                                     "cache_creation": {"ephemeral_1h_input_tokens": 5911,
                                                        "ephemeral_5m_input_tokens": 0}})
        tagging.run(db, commercial_md, settings=cfg(settings), pool=pool, now=NOW)
        row = db.scalars(select(AiUsage).where(AiUsage.feature == "news_tagging")).one()
    assert Decimal(row.cost_usd) == Decimal("0.001182")  # 5,911 × US$0.10 / 1M × 2


class _FamilyProvider(DemoProvider):
    """Taiwan companies of one family share the start of their names (南亞 / 南亞科, 台塑 / 台塑化, 中華 / 中華電)."""

    def instruments(self):
        return [*super().instruments(),
                _tw("1303", "南亞", "TWSE", "stock", "塑膠工業"), _tw("2408", "南亞科", "TWSE", "stock", "半導體業"),
                _tw("1301", "台塑", "TWSE", "stock", "塑膠工業"), _tw("6505", "台塑化", "TWSE", "stock", "油電燃氣業"),
                _tw("2204", "中華", "TWSE", "stock", "汽車工業"), _tw("2002", "中鋼", "TWSE", "stock", "鋼鐵工業"),
                _tw("2013", "中鋼構", "TWSE", "stock", "鋼鐵工業")]


@pytest.fixture()
def family_md(market):
    md = MarketData([_FamilyProvider()], policy="commercial")
    set_market_data(md)
    yield md
    set_market_data(market)


def test_a_family_name_beats_a_code_whose_stock_only_shares_its_start(engine, family_md, settings, fake, pool):
    cases = {
        ("南亞科", "1303"): "2408.TW", ("台塑化", "1301"): "6505.TW", ("中華電", "2204"): "2412.TW",
        ("中鋼構", "2002"): "2013.TW", ("南亞", "2408"): "1303.TW",
        # right codes, short names and other mismatches keep working
        ("南亞科", "2408"): "2408.TW", ("南亞", "1303"): "1303.TW", ("台積", "2330"): "2330.TW",
        ("聯發科", "2317"): "2454.TW", ("南亞科", ""): "2408.TW",
    }
    with Session(engine) as db:
        cat = tagging.Catalog(db, family_md)
        assert {c: tagging.resolve_company(cat, *c) for c in cases} == cases
        # with the company profiles' full names (production): 中華電信 written with 2204 中華汽車 is 2412
        for sym, short, full in (("2204.TW", "中華", "中華汽車工業股份有限公司"),
                                 ("2412.TW", "中華電", "中華電信股份有限公司")):
            db.add(CompanyProfile(symbol=sym, date=date(2026, 11, 16), source="twse", fetched_at=NOW,
                                  values={"short_name": short, "name": full}))
        db.flush()
        cat = tagging.Catalog(db, family_md)
        assert tagging.resolve_company(cat, "中華電信", "2204") == "2412.TW"
        assert tagging.resolve_company(cat, "中華汽車", "2204") == "2204.TW"
        # end to end: a DRAM story naming 南亞科 with 1303 is stored with 2408
        url = "https://money.udn.com/fam/1"
        service.store(db, "2330.TW", [head("記憶體報價大漲 南亞科受惠", url)], NOW)
        reply(fake, entry(1, ["記憶體"], ["半導體業"], [{"name": "南亞科", "code": "1303", "relation": "mentioned"}]))
        tagging.run(db, family_md, settings=cfg(settings), pool=pool, now=NOW)
        assert ("symbol", "2408.TW", "mentioned") in tag_rows(db, url)


# The companies the US sector hints name, with their SEC SIC codes (EDGAR submissions, 2026-11): several sit in an
# SIC range of another sector, which US_SECTOR_BY_TICKER overrides.
REAL_SIC = {"NVDA": "3674", "AMD": "3674", "AVGO": "3674", "MU": "3674", "AMAT": "3674", "AAPL": "3571",
            "MSFT": "7372", "ORCL": "7372", "DELL": "3571", "GOOGL": "7370", "META": "7370", "NFLX": "7841",
            "T": "4813", "AMZN": "5961", "TSLA": "3711", "NKE": "3021", "WMT": "5331", "COST": "5331", "KO": "2080",
            "LLY": "2834", "PFE": "2834", "UNH": "6324", "JPM": "6021", "V": "7389", "BA": "3721", "CAT": "3531",
            "XOM": "2911", "CVX": "2911"}


def test_every_company_a_us_sector_hint_names_gets_that_sector():
    """The prompt's brackets (a stock's sector) and the sector hints never disagree about a company."""
    named = [t for examples in taxonomy.US_SECTOR_EXAMPLES.values() for t, _ in examples]
    assert len(named) == len(set(named))  # no company in two hints
    for sector, examples in taxonomy.US_SECTOR_EXAMPLES.items():
        hint = taxonomy.SECTOR_BY_ID[sector].hint
        for ticker, name in examples:
            assert name in hint
            assert taxonomy.us_sector(ticker, REAL_SIC[ticker]) == sector, ticker
            assert taxonomy.us_sector(ticker) == sector  # without SEC data too


@pytest.mark.parametrize(("ticker", "sic", "sector"), [
    ("GOOGL", "7370", "us_comm"), ("META", "7370", "us_comm"), ("DJT", "7370", "us_comm"), ("DIS", "7990", "us_comm"),
    ("WMT", "5331", "us_staples"), ("TGT", "5331", "us_staples"), ("V", "7389", "us_financials"),
    ("MA", "7389", "us_financials"), ("PYPL", "7389", "us_financials"), ("NKE", "3021", "us_consumer_disc"),
    ("UNH", "6324", "us_health"), ("TMO", "3826", "us_health"), ("BKNG", "4700", "us_consumer_disc"),
    ("UAL", "4512", "us_industrials"), ("ZZZZ", "5331", "us_staples"), ("ZZZZ", None, None)])
def test_us_sectors_follow_the_vocabulary_not_raw_sic(ticker, sic, sector):
    assert taxonomy.us_sector(ticker, sic) == sector


class _UsProvider(DemoProvider):
    def instruments(self):
        return [*super().instruments(), _us("GOOGL", "Alphabet Inc.", "stock", "通訊服務", ("谷歌",)),
                _us("V", "Visa Inc.", "stock", "金融", ())]


def test_the_prompt_names_a_us_stocks_vocabulary_sector(engine, market):
    md = MarketData([_UsProvider()], policy="commercial")
    set_market_data(md)
    try:
        with Session(engine) as db:
            for ticker, cik, sic in (("GOOGL", 1652044, "7370"), ("V", 1403161, "7389")):
                db.add(SecTicker(ticker=ticker, cik=cik, title=ticker))
                db.add(SecCompany(cik=cik, name=ticker, facts={}, profile={"sic": sic}))
            db.commit()
            cat = tagging.Catalog(db, md)
            assert cat.describe("GOOGL") == "GOOGL Alphabet Inc.（美股通訊服務）"
            assert cat.describe("V") == "V Visa Inc.（美股金融）"
    finally:
        set_market_data(market)
    assert "美國公司是美股類股" in tagging.SYSTEM_PROMPT


def test_an_industry_sector_adds_its_theme_so_a_theme_search_finds_it(engine, commercial_md, settings, fake, pool):
    """「金融股的新聞都選」 is not left to the model: a bank's outage filed under 事故／資安 and 金融保險業 (or
    美股金融) also gets 金融; 航運業 gets 航運. The model's own three themes stay."""
    with Session(engine) as db:
        service.store(db, "2330.TW", [head(f"新聞 {i}", f"https://money.udn.com/f/{i}",
                                           at=NOW - timedelta(minutes=10 - i)) for i in range(4)], NOW)
        reply(fake, entry(1, ["事故／資安"], ["金融保險業"]), entry(2, ["事故／資安"], ["美股金融"]),
              entry(3, ["事故／資安"], ["航運業"]), entry(4, ["AI 伺服器", "先進封裝", "財報／法說"], ["金融保險業"]))
        tagging.run(db, commercial_md, settings=cfg(settings), pool=pool, now=NOW)
        themes = {i: {v for k, v, _ in tag_rows(db, f"https://money.udn.com/f/{i}") if k == "theme"} for i in range(4)}
        found = [x["title"] for x in tags.search(db, commercial_md, theme="finance", now=NOW, settings=settings)]
    assert themes == {0: {"incidents", "finance"}, 1: {"incidents", "finance"}, 2: {"incidents", "shipping"},
                      3: {"ai_server", "advanced_packaging", "earnings", "finance"}}
    assert sorted(found) == ["新聞 0", "新聞 1", "新聞 3"]


def test_by_topic_does_not_compare_every_pair_of_a_big_group(engine, commercial_md, settings, monkeypatch):
    """A week of a busy theme: counting and picking the newest few must not run the pairwise near-duplicate check
    over the whole group (1,500 headlines took ~15 s that way)."""
    rng = random.Random(7)
    n = 1500
    with Session(engine) as db:
        for i in range(n):
            u = f"https://money.udn.com/money/story/{i}"
            title = "".join(chr(rng.randrange(0x4E00, 0x9FA5)) for _ in range(20))
            db.add(NewsArticle(symbol="2330.TW", url_key=url_key(u), url=u, title=title, outlet="經濟日報",
                               domain="money.udn.com", published_at=NOW - timedelta(minutes=i), source="gdelt",
                               fetched_at=NOW))
            db.add(NewsTag(url_key=url_key(u), kind="theme", value="market_moves"))
        # an exact copy under another URL counts once
        u = "https://money.udn.com/money/story/copy"
        db.add(NewsArticle(symbol="2330.TW", url_key=url_key(u), url=u, title=title, outlet="經濟日報",
                           domain="money.udn.com", published_at=NOW - timedelta(minutes=n), source="gdelt",
                           fetched_at=NOW))
        db.add(NewsTag(url_key=url_key(u), kind="theme", value="market_moves"))
        db.commit()
        calls = 0
        real = normalize.similar_titles

        def counting(a: str, b: str) -> bool:
            nonlocal calls
            calls += 1
            return real(a, b)

        monkeypatch.setattr(normalize, "similar_titles", counting)
        groups = tags.by_topic(db, commercial_md, "theme", NOW - timedelta(days=7), NOW + timedelta(minutes=1),
                               settings=settings)
    assert [(g["label"], g["count"], len(g["items"])) for g in groups] == [("大盤行情", n, 5)]
    assert groups[0]["items"][0]["url"] == "https://money.udn.com/money/story/0"
    assert calls < 500  # the whole group pairwise would be about n² / 2 ≈ 1.1 million
