"""新聞標籤 (產品負責人 2026-11-17, ``forliosa.news.tagging`` / ``tags`` / ``taxonomy``): the job, its checks, the
budget, retries, and what the AI tools show. The model is the fake Messages API (``tests/ai/fake_anthropic.py``)."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from forliosa.models import AiUsage, NewsArticle, NewsBlockedDomain, NewsTag, NewsTagState, User
from forliosa.news import service, tagging, tags, taxonomy
from forliosa.news.normalize import Headline, url_key
from tests.ai.fake_anthropic import text, thinking

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
            "news_tagging_max_batches": 4, "news_tagging_days": 7}
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
                                             ("4813", "us_comm"), ("", None), ("x", None)])
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
    assert body["system"][0]["cache_control"] == {"type": "ephemeral"}
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


@pytest.mark.parametrize("stop", ["refusal", "max_tokens"])
def test_a_refused_or_cut_off_answer_is_not_used(engine, commercial_md, settings, fake, pool, stop):
    url = "https://money.udn.com/a/6"
    with Session(engine) as db:
        service.store(db, "2330.TW", [head("台積電新聞", url)], NOW)
        reply(fake, entry(1, ["財報／法說"]), stop_reason=stop)
        res = tagging.run(db, commercial_md, settings=cfg(settings), pool=pool, now=NOW)
        assert state(db, url).status == "failed" and not tag_rows(db, url)
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


def test_a_bad_request_counts_an_attempt_and_stops_the_run(engine, commercial_md, settings, fake, pool):
    with Session(engine) as db:
        service.store(db, "2330.TW", [head(f"台積電新聞 {i}", f"https://money.udn.com/e/{i}") for i in range(3)], NOW)
        fake.error(400, "invalid_request_error", "schema too complex")
        res = tagging.run(db, commercial_md, settings=cfg(settings, news_tagging_batch_size=1), pool=pool, now=NOW)
        failed = db.scalars(select(NewsTagState).where(NewsTagState.status == "failed")).all()
    assert res.stopped == "error" and res.calls == 0 and len(failed) == 1 and len(fake.requests) == 1


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
