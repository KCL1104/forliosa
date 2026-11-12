"""SearXNG as a news source: on by default, the queries, parsing SearXNG's JSON (synthetic fixtures), refusals and
an unreachable instance, the pacing gate, the ``searxng-check`` CLI, and the committed deployment files.

No test reaches a SearXNG instance or a search engine: every request goes through ``httpx.MockTransport``.
"""

from __future__ import annotations

import copy
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from forliosa.config import DEFAULT_SEARXNG_ENGINES, SEARXNG_URL_LOCAL, SEARXNG_URL_RAILWAY, Settings
from forliosa.marketdata.http import url_allowed
from forliosa.news import __main__ as cli
from forliosa.news.normalize import make_terms
from forliosa.news.searxng import (
    QueryGate,
    engine_refused,
    parse_searxng,
    published_time,
    query_text,
    relative_age,
)
from forliosa.news.sources import Query, RawItem, SourceBlocked, SourceDown
from forliosa.timeutil import TAIPEI
from tests.news.conftest import ENGINES, FETCHED_AT, FIXTURES, SEARX_URL, make_searx, searx_fixture

NOW = FETCHED_AT
REPO = Path(__file__).resolve().parents[4]
DEPLOY = REPO / "deploy" / "searxng"


def tsmc() -> Query:
    return Query("2330.TW", "2330", "台積電", "TWSE", ("TSMC",), make_terms("台積電", "2330", ["TSMC"]),
                 NOW - timedelta(days=7), NOW)


def nvda() -> Query:
    return Query("NVDA", "NVDA", "NVIDIA", "US", ("NVIDIA",), make_terms("NVIDIA", "NVDA", ["NVIDIA"], ["輝達"]),
                 NOW - timedelta(days=7), NOW)


# -- on by default -------------------------------------------------------------------------------------------------
def test_on_by_default_with_the_service_url_of_each_environment():
    assert Settings(forliosa_env="prod").searxng_url == SEARXNG_URL_RAILWAY == "http://searxng.railway.internal:8080"
    assert Settings(forliosa_env="dev").searxng_url == SEARXNG_URL_LOCAL == "http://localhost:8080"
    assert Settings(forliosa_env="prod", news_searxng_url="http://search.railway.internal:8080/").searxng_url == \
        "http://search.railway.internal:8080"
    # off: NEWS_SEARXNG_ENABLED=false, or NEWS_SEARXNG_URL set but empty
    assert Settings(forliosa_env="prod", news_searxng_enabled=False).searxng_url is None
    assert Settings(forliosa_env="prod", news_searxng_url=" ").searxng_url is None
    s = Settings()
    assert s.news_searxng_engines == list(DEFAULT_SEARXNG_ENGINES)
    assert s.news_searxng_interval_seconds >= 10 and 30 <= s.news_searxng_cache_minutes <= 60
    assert s.news_searxng_skip_gdelt_items == 8
    assert Settings(news_searxng_engines="Bing News, duckduckgo  news").news_searxng_engines == \
        ["bing news", "duckduckgo news"]
    with pytest.raises(ValidationError):
        Settings(news_searxng_interval_seconds=5)  # never closer than 10 s
    with pytest.raises(ValidationError):
        Settings(news_searxng_cache_minutes=10)


# -- queries -------------------------------------------------------------------------------------------------------
def test_queries_are_chinese_for_taiwan_and_english_for_us(clock):
    src = make_searx(clock)
    assert query_text(tsmc()) == "台積電 2330" and query_text(nvda()) == "NVIDIA NVDA"
    assert src.params(tsmc()) == {"q": "台積電 2330", "format": "json", "language": "zh-TW", "time_range": "week",
                                  "safesearch": 0, "pageno": 1, "categories": "news"}
    us = src.params(nvda())
    assert us["q"] == "NVIDIA NVDA" and us["language"] == "en" and us["categories"] == "news"
    # a paused engine is left out: the others are named (categories would add every news engine back)
    src.paused = frozenset({"bing news"})
    p = src.params(tsmc())
    assert p["engines"] == "duckduckgo news,brave.news" and "categories" not in p


# -- parsing (synthetic fixtures in SearXNG's JSON format) ---------------------------------------------------------
def test_parse_takes_title_link_time_and_engines_only():
    ans = parse_searxng(searx_fixture("searxng_tsmc_zh_tw_synthetic.json"), NOW)
    assert ans.results == 12 and ans.redirects == 2 and ans.no_date == 1 and ans.unresponsive == []
    assert ans.per_engine == {"bing news": 6, "duckduckgo news": 5, "brave.news": 2}
    by_url = {i.url: i for i in ans.items}
    assert len(ans.items) == 9
    # only title, link and time: no content, thumbnail or engine-specific fields
    assert set(RawItem.__dataclass_fields__) == {"title", "url", "published_at", "date_only", "outlet", "domain"}
    assert "內文摘要" not in repr(ans.items)
    # publishedDate without an offset is UTC (SearXNG's container clock)
    cna = by_url["http://www.cna.com.tw/news/afe/202611120132.aspx?utm_source=rss&utm_medium=news"]
    assert cna.published_at == datetime(2026, 11, 12, 6, 40, tzinfo=UTC) and not cna.date_only
    # Bing News: no publishedDate, the age is in metadata 「3 小時前 | 經濟日報」
    udn = by_url["https://money.udn.com/money/story/5612/9100001?fbclid=IwAR0Forliosa"]
    assert udn.published_at == NOW - timedelta(hours=3) and not udn.date_only
    # 「1 天前」: only the day is known (Taipei midnight)
    cnyes = by_url["https://news.cnyes.com/news/id/6200001"]
    assert cnyes.date_only and cnyes.published_at == datetime(2026, 11, 11, 0, 0, tzinfo=TAIPEI)
    # Brave News: 「5 hours ago」 in pubdate
    assert by_url["https://www.cna.com.tw/amp/news/afe/202611120200.aspx"].published_at == NOW - timedelta(hours=5)
    # search-engine redirects are dropped, never followed
    assert not any("bing.com" in u or "news.google.com" in u for u in by_url)


def test_parse_reports_unresponsive_engines_and_refusals():
    ans = parse_searxng(searx_fixture("searxng_partial_synthetic.json"), NOW)
    assert len(ans.items) == 1 and ans.unresponsive == [("bing news", "Suspended: CAPTCHA"), ("brave.news", "timeout")]
    assert ans.refused == ["bing news"]
    assert engine_refused("Suspended: too many requests") and engine_refused("access denied")
    assert not engine_refused("Suspended: timeout") and not engine_refused("HTTP connection error")
    assert parse_searxng({}).items == [] and parse_searxng({"results": ["x", None]}).results == 0


def test_relative_ages():
    assert relative_age("3 hours ago") == (timedelta(hours=3), False)
    assert relative_age("3h") == (timedelta(hours=3), False)
    assert relative_age("an hour ago") == (timedelta(hours=1), False)
    assert relative_age("45 分鐘前") == (timedelta(minutes=45), False)
    assert relative_age("3小時") == (timedelta(hours=3), False)
    assert relative_age("2 days ago") == (timedelta(days=2), True)
    assert relative_age("yesterday") == relative_age("昨天") == (timedelta(days=1), True)
    for text in ("TVBS", "24/7 Wall St.", "2026", "經濟日報", "", "5m views"):
        assert relative_age(text) is None, text
    # weeks, months, years: older than time_range=week and not datable to the day -> not a usable time
    for text in ("3 weeks ago", "a week ago", "1w", "2 wks", "2 週前", "3 周前", "1 星期前", "經濟日報 2 週前",
                 "1 month ago", "1mo", "2 個月前", "a year ago"):
        assert relative_age(text) is None, text
    assert published_time({"pubdate": "3 weeks ago"}, NOW) is None
    assert published_time({"metadata": "2 週前 | 中央社"}, NOW) is None
    # an ISO time wins; nothing usable -> None
    assert published_time({"publishedDate": "2026-11-12T08:00:00+08:00"}, NOW) == (
        datetime(2026, 11, 12, 0, 0, tzinfo=UTC), False)
    assert published_time({"pubdate": "2026-11-12 08:00:00"}, None) == (datetime(2026, 11, 12, 8, tzinfo=UTC), False)
    assert published_time({"metadata": "經濟日報"}, NOW) is None
    assert published_time({"metadata": "3 小時前"}, None) is None  # a relative age needs the answer's time


# -- the instance: on the wire, unreachable, refusing --------------------------------------------------------------
def test_source_asks_only_our_instance_with_an_honest_client(fake_searx, clock):
    fake_searx.answers = [searx_fixture("searxng_tsmc_zh_tw_synthetic.json")]
    src = make_searx(clock)
    items = src.fetch(tsmc())
    assert len(items) == 9 and src.last is not None and src.last_asked == ENGINES
    req = fake_searx.searches[0]
    assert str(req.url).startswith(f"{SEARX_URL}/search?")
    assert fake_searx.params() == {"q": "台積電 2330", "format": "json", "language": "zh-TW", "time_range": "week",
                                   "safesearch": "0", "pageno": "1", "categories": "news"}
    assert req.headers["user-agent"].startswith("forliosa/") and "Mozilla" not in req.headers["user-agent"]
    assert not url_allowed(f"{SEARX_URL}/search")  # not on the global allowlist: only this source's fetcher
    assert src.fetcher.extra_allowed == (f"{SEARX_URL}/search", f"{SEARX_URL}/healthz")


@pytest.mark.parametrize("answer, error", [
    (httpx.ConnectError("connection refused"), SourceDown),  # not running / DNS / no private network
    (httpx.ReadTimeout("timed out"), SourceDown),
    (503, SourceDown),
    (500, SourceDown),
    (lambda r: httpx.Response(200, content=b"<html>not json</html>"), SourceDown),
    (429, SourceBlocked),  # our own instance refusing: limiter on
    (403, SourceBlocked),  # JSON output not enabled in settings.yml
])
def test_unreachable_or_refusing_instance(fake_searx, clock, answer, error):
    fake_searx.answers = [answer]
    with pytest.raises(error):
        make_searx(clock).fetch(tsmc())
    assert len(fake_searx.searches) == 1  # no retry: the service pauses the source instead


def test_every_engine_failing_pauses_searxng(fake_searx, clock):
    fake_searx.answers = [searx_fixture("searxng_all_down_synthetic.json")]
    src = make_searx(clock)
    with pytest.raises(SourceDown):
        src.fetch(tsmc())
    assert src.last is not None and len(src.last.unresponsive) == 3  # still booked engine by engine
    fake_searx.answers = [searx_fixture("searxng_all_refused_synthetic.json")]
    with pytest.raises(SourceBlocked):
        src.fetch(tsmc())
    src.paused = frozenset(ENGINES)
    n = len(fake_searx.searches)
    with pytest.raises(SourceBlocked):  # every engine paused: not asked at all
        src.fetch(tsmc())
    assert len(fake_searx.searches) == n
    # some engines down, results from the others: a normal answer
    fake_searx.answers = [searx_fixture("searxng_partial_synthetic.json")]
    src.paused = frozenset()
    assert len(src.fetch(tsmc())) == 1
    # no engine list configured (NEWS_SEARXNG_ENGINES empty): categories=news, judged by what SearXNG reports
    bare = make_searx(clock, engines=())
    assert len(bare.fetch(tsmc())) == 1 and fake_searx.params()["categories"] == "news"
    fake_searx.answers = [searx_fixture("searxng_all_down_synthetic.json")]
    with pytest.raises(SourceDown):
        bare.fetch(tsmc())


def test_health_check(fake_searx, clock):
    assert make_searx(clock).health() == (True, "OK")
    fake_searx.health = b"starting"
    assert make_searx(clock).health() == (False, "回應不是 OK")


def test_health_check_unreachable(clock):  # the autouse transport refuses every connection
    assert make_searx(clock).health() == (False, "無法連線")


# -- pacing --------------------------------------------------------------------------------------------------------
def test_queries_are_at_least_ten_seconds_apart(fake_searx, clock):
    src = make_searx(clock)
    for _ in range(3):
        src.fetch(tsmc())
    assert len(fake_searx.searches) == 3 and clock.sleeps == [10.0, 10.0]
    clock.t += 25  # a pause longer than the interval: no wait
    src.fetch(tsmc())
    assert clock.sleeps == [10.0, 10.0]


def test_one_query_at_a_time():
    gate = QueryGate(0.0)
    inside, peak = 0, 0
    lock = threading.Lock()

    def query():
        nonlocal inside, peak
        with gate.turn():
            with lock:
                inside += 1
                peak = max(peak, inside)
            time.sleep(0.01)
            with lock:
                inside -= 1

    threads = [threading.Thread(target=query) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert peak == 1


# -- CLI -----------------------------------------------------------------------------------------------------------
def test_searxng_check_prints_counts_per_engine_without_secrets(fake_searx, capsys):
    fake_searx.answers = [searx_fixture("searxng_partial_synthetic.json")]
    assert cli.main(["searxng-check", "台積電", "--url", "http://admin:s3cr3t-token@searxng.test:8080"]) == 0
    out = capsys.readouterr().out
    assert "SearXNG：http://searxng.test:8080" in out and "s3cr3t" not in out and "admin" not in out
    assert "健康檢查（/healthz）：OK" in out
    assert "duckduckgo news" in out and "Suspended: CAPTCHA（拒絕" in out and "timeout（暫時錯誤）" in out
    assert fake_searx.params()["q"] == "台積電" and fake_searx.params()["language"] == "zh-TW"


def test_searxng_check_unreachable_and_off(capsys, monkeypatch):
    assert cli.main(["searxng-check", "台積電", "--url", "http://searxng.test:8080"]) == 1
    assert "無法連線" in capsys.readouterr().out
    monkeypatch.setenv("NEWS_SEARXNG_ENABLED", "false")
    from forliosa.config import get_settings

    get_settings.cache_clear()
    try:
        assert cli.main(["searxng-check", "台積電"]) == 1
        assert "SearXNG 已關閉" in capsys.readouterr().out
    finally:
        monkeypatch.delenv("NEWS_SEARXNG_ENABLED")
        get_settings.cache_clear()


# -- deployment files ----------------------------------------------------------------------------------------------
def test_settings_yml_is_private_json_news_only_and_matches_the_engine_list():
    yaml = pytest.importorskip("yaml")
    cfg = yaml.safe_load((DEPLOY / "settings.yml").read_text(encoding="utf-8"))
    keep = cfg["use_default_settings"]["engines"]["keep_only"]
    assert sorted(keep) == sorted(DEFAULT_SEARXNG_ENGINES)  # Settings.news_searxng_engines default
    engines = {e["name"]: e for e in cfg["engines"]}
    assert set(engines) == set(keep)
    for e in engines.values():
        assert e.get("disabled") is False and e.get("inactive", False) is False
        assert e.get("time_range_support") in (None, True)
    # no Google News (redirect links), no news site queried directly (reuters, wikinews, tagesschau …)
    assert not {"google news", "reuters", "wikinews", "tagesschau", "yahoo news"} & set(keep)
    server = cfg["server"]
    assert server["limiter"] is False and server["public_instance"] is False and server["image_proxy"] is False
    assert server["secret_key"] == "ultrasecretkey"  # replaced by SEARXNG_SECRET; SearXNG refuses to start without
    assert set(cfg["search"]["formats"]) == {"html", "json"}
    assert cfg["search"]["default_lang"] == "zh-TW" and cfg["ui"]["default_locale"] == "en"
    out = cfg["outgoing"]
    assert 0 < out["request_timeout"] <= out["max_request_timeout"] <= 10
    assert "proxies" not in out and "source_ips" not in out and not out.get("using_tor_proxy")  # never another IP
    assert cfg["valkey"]["url"] is False


def pinned_image() -> tuple[str, str, str]:
    """(image, tag, digest) of the ``FROM`` line in deploy/searxng/Dockerfile."""
    dockerfile = (DEPLOY / "Dockerfile").read_text(encoding="utf-8")
    base = next(line.split()[1] for line in dockerfile.splitlines() if line.startswith("FROM "))
    name, _, digest = base.partition("@")
    image, _, tag = name.partition(":")
    return image, tag, digest


def _update_dict(default: dict, user: dict) -> dict:
    """searx/settings_loader.py ``update_dict``: how SearXNG merges an ``engines:`` entry into the default one (a
    mapping merged into a string leaves the string)."""
    for k, v in user.items():
        default[k] = _update_dict(default.get(k, {}), v) if isinstance(v, dict) else v
    return default


def unresolved_networks(cfg: dict, defaults: list[dict]) -> list[str]:
    """The ``network: <name>`` references SearXNG cannot resolve after merging ``cfg`` into the release's default
    engines (searx/settings_loader.py ``update_settings``: keep_only, then the ``engines:`` overrides) —
    searx/network/network.py ``initialize`` raises ``KeyError`` for each and the instance never starts. A name
    resolves to ``ipv4`` / ``ipv6``, an ``outgoing.networks`` entry, or a loaded engine with its own network."""
    keep = cfg["use_default_settings"]["engines"]["keep_only"]
    engines = [copy.deepcopy(e) for e in defaults if e["name"] in keep]
    by_name = {e["name"]: e for e in engines}
    for user in cfg.get("engines") or []:
        if user["name"] in by_name:
            _update_dict(by_name[user["name"]], user)
        else:
            engines.append(user)
    networks = {"ipv4", "ipv6", *((cfg.get("outgoing") or {}).get("networks") or {})}
    networks |= {e["name"] for e in engines if not isinstance(e.get("network"), str)}
    return [f"{e['name']} -> {e['network']}" for e in engines
            if isinstance(e.get("network"), str) and e["network"] not in networks]


def test_settings_yml_starts_with_the_pinned_release_engine_networks():
    """brave.news shares the network of the engine "brave" (``network: brave``), which keep_only removes: without
    ``outgoing.networks.brave`` SearXNG stopped at start-up with ``KeyError: 'brave'``."""
    yaml = pytest.importorskip("yaml")
    cfg = yaml.safe_load((DEPLOY / "settings.yml").read_text(encoding="utf-8"))
    _, tag, _ = pinned_image()
    excerpt = FIXTURES / f"searxng_default_engines_{tag}.yml"
    assert excerpt.exists(), (f"the Dockerfile pins {tag}: copy that release's default definitions of the kept "
                              f"engines (searx/settings.yml) into {excerpt.name}")
    release = yaml.safe_load(excerpt.read_text(encoding="utf-8"))
    assert release["version"] == tag and tag.endswith("-" + release["commit"][:9])
    defaults = release["engines"]
    keep = cfg["use_default_settings"]["engines"]["keep_only"]
    assert set(keep) <= {e["name"] for e in defaults}  # every kept engine is in the excerpt
    assert unresolved_networks(cfg, defaults) == []
    # the start-up failure this guards against
    without = copy.deepcopy(cfg)
    del without["outgoing"]["networks"]
    assert unresolved_networks(without, defaults) == ["brave.news -> brave"]
    # overriding the reference under engines: does not replace the string
    without["engines"] = [*without["engines"], {"name": "brave.news", "network": {}}]
    assert unresolved_networks(without, defaults) == ["brave.news -> brave"]
    # the network entry adds nothing: no proxy, no other source address
    assert cfg["outgoing"]["networks"] == {"brave": {}}


def test_dockerfile_pins_a_release_and_compose_stays_on_localhost():
    dockerfile = (DEPLOY / "Dockerfile").read_text(encoding="utf-8")
    image, tag, digest = pinned_image()
    assert image == "docker.io/searxng/searxng" and tag and tag != "latest" and digest.startswith("sha256:")
    released = datetime.strptime(tag.split("-")[0], "%Y.%m.%d").replace(tzinfo=UTC)
    assert released <= datetime(2026, 11, 12, tzinfo=UTC) - timedelta(days=14)  # ≥ 2 weeks old when pinned
    assert "COPY settings.yml /etc/searxng/settings.yml" in dockerfile
    compose = (DEPLOY / "docker-compose.yml").read_text(encoding="utf-8")
    assert '"127.0.0.1:8080:8080"' in compose and "0.0.0.0" not in compose and "SEARXNG_SECRET" in compose
    railway = (DEPLOY / "railway.toml").read_text(encoding="utf-8")
    assert 'healthcheckPath = "/healthz"' in railway
    # SearXNG listens on 8080 whatever $PORT says: the service's PORT variable must be 8080 for the health check
    assert "PORT=8080 (required" in railway


def test_compose_reads_the_settings_yml_in_the_repo_after_every_edit():
    """The image declares /etc/searxng a VOLUME: without a bind mount, a recreated container got the previous one's
    anonymous volume and kept reading the settings.yml of the first build."""
    yaml = pytest.importorskip("yaml")
    compose = yaml.safe_load((DEPLOY / "docker-compose.yml").read_text(encoding="utf-8"))
    service = compose["services"]["searxng"]
    assert "./settings.yml:/etc/searxng/settings.yml:ro" in service["volumes"]
    assert service["ports"] == ["127.0.0.1:8080:8080"]
