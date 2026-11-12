"""SEC EDGAR (docs/handoff.md §3.1): US financials from XBRL company facts, 8-K / 10-Q / 10-K events from
submissions, the cache tables and the worker job. Trimmed live responses (2026-11-12) serve every request: no test
reaches the network, and the contact address used here is a placeholder."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal as D

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from forliosa.archive import SEC_DISABLED, Archiver
from forliosa.marketdata import sec
from forliosa.marketdata.http import DEFAULT_LIMITER, HttpFetcher, HttpStatusError, RateLimiter, url_allowed
from forliosa.models import DatasetStatus, SecCompany, SecFiling, SecTicker
from forliosa.services import sec as sec_svc
from forliosa.timeutil import TAIPEI, today_taipei
from tests.archive.fakes import NOW, FakeSecClient, load

API = "/api/v1"
FAKE_EMAIL = "ops@example.com"
TODAY = date(2026, 11, 12)
AAPL_CIK = 320193
YEAR = today_taipei().year  # attribution year (the licence notice names the current year)
SEC_FACTS_LABEL = f"美國證券交易委員會（SEC）〈EDGAR XBRL 財報數據（companyfacts）〉（{YEAR}），美國政府公開資料"
SEC_FILINGS_LABEL = f"美國證券交易委員會（SEC）〈EDGAR 公司申報清單（submissions）〉（{YEAR}），美國政府公開資料"


@pytest.fixture()
def clock(monkeypatch):
    """Freeze "now" for the SEC cache and the events window (the fixtures are from 2026-11-12)."""
    state = {"now": datetime(2026, 11, 12, 12, 0, tzinfo=TAIPEI)}
    monkeypatch.setattr(sec_svc, "_now", lambda: state["now"])
    import forliosa.services.stock as stock

    monkeypatch.setattr(stock, "today_taipei", lambda: state["now"].date())
    return state


@pytest.fixture()
def fake(clock):
    client = FakeSecClient()
    sec_svc.set_sec_client(client)
    return client


# -- parsing ----------------------------------------------------------------------------------------------
def test_trim_facts_keeps_periodic_reports_one_value_per_period():
    raw = load("sec_companyfacts_aapl_live_20261112.json")
    facts = sec.trim_facts(raw, TODAY)
    assert "AccountsPayableCurrent" not in facts["tags"]  # only the tags Forliosa shows
    rows = facts["tags"]["RevenueFromContractWithCustomerExcludingAssessedTax"]["USD"]
    keys = [(r[0], r[1]) for r in rows]
    assert len(keys) == len(set(keys))
    fy2025 = next(r for r in rows if (r[0], r[1]) == ("2024-09-29", "2025-09-27"))
    # value from the latest filing, fiscal labels from the first report of the period (10-K for FY2025)
    assert fy2025[2] == 416161000000 and (fy2025[3], fy2025[4]) == (2025, "FY") and fy2025[5] == "2026-11-03"
    assert sec.shares_outstanding(raw) == (14532182000, date(2026, 10, 23))


def test_quarterly_summary_uses_fiscal_periods_and_derives_q4():
    facts = sec.trim_facts(load("sec_companyfacts_aapl_live_20261112.json"), TODAY)
    qs = {p.label: p for p in sec.summarize(facts, "quarterly")}
    q1, q4 = qs["FY2026Q1"], qs["FY2026Q4"]
    assert (q1.start, q1.end) == (date(2025, 9, 28), date(2025, 12, 27))
    assert q1.values["revenue"] == D(143756000000) and q1.values["eps"] == D("2.84") and not q1.derived
    # Q4: the 10-K reports the year only -> fiscal year minus nine months; EPS is an approximation
    assert (q4.start, q4.end) == (date(2026, 6, 28), date(2026, 9, 26))
    assert q4.values["revenue"] == D(478834000000) - D(364357000000)
    assert q4.values["eps"] == D("2.10") and {"revenue", "eps", "operating"} <= q4.derived
    assert q4.values["diluted_shares"] is None  # average share counts are never derived
    # 10-Q cash flows are year-to-date: Q2 = six months - Q1
    assert qs["FY2026Q2"].values["operating"] == D(28702000000) and "operating" in qs["FY2026Q2"].derived
    assert q4.values["total_assets"] == D(404548000000) and q4.values["total_liabilities"] == D(292455000000)
    labels = [p.label for p in sec.summarize(facts, "quarterly")]
    assert labels == sorted(labels, key=lambda s: (int(s[2:6]), int(s[-1])))


def test_annual_summary_and_january_fiscal_year_end():
    facts = sec.trim_facts(load("sec_companyfacts_aapl_live_20261112.json"), TODAY)
    years = {p.label: p for p in sec.summarize(facts, "annual")}
    fy = years["FY2026"]
    assert (fy.start, fy.end) == (date(2025, 9, 28), date(2026, 9, 26))
    assert fy.values["revenue"] == D(478834000000) and fy.values["eps"] == D("8.98")
    assert fy.values["net_income"] == D(132175000000)
    # NVIDIA's fiscal year ends in late January: the year ending 2026-01-25 is its fiscal 2026
    nvda = sec.trim_facts(load("sec_companyfacts_nvda_live_20261112.json"), TODAY)
    n = {p.label: p for p in sec.summarize(nvda, "annual")}
    assert n["FY2026"].end == date(2026, 1, 25)
    nq = [p for p in sec.summarize(nvda, "quarterly") if p.fiscal_year == 2027]
    assert [p.label for p in nq][:2] == ["FY2027Q1", "FY2027Q2"] and nq[1].end == date(2026, 7, 26)


def test_liabilities_fall_back_to_liabilities_and_equity_minus_equity():
    facts = {"v": 1, "tags": {
        "LiabilitiesAndStockholdersEquity": {"USD": [[None, "2026-06-30", 500, 2026, "FY", "2026-08-01"]]},
        "StockholdersEquity": {"USD": [[None, "2026-06-30", 200, 2026, "FY", "2026-08-01"]]},
        "Revenues": {"USD": [["2025-07-01", "2026-06-30", 1000, 2026, "FY", "2026-08-01"]]},
    }}
    (fy,) = sec.summarize(facts, "annual")
    assert fy.label == "FY2026" and fy.values["total_liabilities"] == 300


def test_submissions_keep_8k_10q_10k_with_titles_and_links():
    meta, rows = sec.parse_submissions(load("sec_submissions_aapl_live_20261112.json"))
    assert meta == {"name": "Apple Inc.", "fiscal_year_end": "0926"}
    assert rows and {r["form"] for r in rows} <= set(sec.FILING_FORMS)
    assert {"10-K", "10-Q", "8-K", "8-K/A"} <= {r["form"] for r in rows}
    ten_k = next(r for r in rows if r["form"] == "10-K")
    assert ten_k["filing_date"] == date(2026, 11, 3) and ten_k["report_date"] == date(2026, 9, 26)
    assert sec.filing_title("10-K", "") == "10-K 年度報告"
    assert sec.filing_detail("10-K", ten_k["report_date"], "") == "會計年度截至 2026-09-26"
    assert sec.filing_url(AAPL_CIK, ten_k["accession"], ten_k["primary_document"]) == (
        "https://www.sec.gov/Archives/edgar/data/320193/000032019326000026/aapl-20260926.htm")
    assert sec.filing_title("8-K", "2.02,9.01") == "8-K 營運結果與財務狀況"
    assert sec.filing_title("8-K/A", "5.02") == "8-K/A 董事或高階主管異動、薪酬安排（修正）"
    assert sec.filing_title("8-K", "9.01") == "8-K 財務報表與附件"
    assert sec.filing_detail("8-K", date(2026, 11, 2), "2.02,9.01") == (
        "申報項目：2.02 營運結果與財務狀況、9.01 財務報表與附件；事件日期 2026-11-02")
    assert sec.parse_tickers(load("sec_company_tickers_live_20261112.json"))[0] == {
        "ticker": "AAPL", "cik": AAPL_CIK, "title": "Apple Inc."}
    assert sec.sec_ticker("brk.b") == "BRK-B"


# -- HTTP: allowlist, limiter, User-Agent ---------------------------------------------------------------------
def test_only_the_three_sec_datasets_are_allowed_and_share_one_rate_budget():
    assert url_allowed("https://www.sec.gov/files/company_tickers.json")
    assert url_allowed("https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json")
    assert url_allowed("https://data.sec.gov/submissions/CIK0000320193.json")
    for url in ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany",
                "https://www.sec.gov/Archives/edgar/data/320193/000032019326000026/aapl-20260926.htm",
                "https://efts.sec.gov/LATEST/search-index?q=apple"):
        assert not url_allowed(url)
    assert DEFAULT_LIMITER.interval_for("data.sec.gov") == DEFAULT_LIMITER.interval_for("www.sec.gov") <= 0.25
    slept: list[float] = []
    limiter = RateLimiter(per_host={"sec.gov": 0.25})
    limiter._clock = lambda: 100.0
    limiter._sleep = slept.append
    limiter.wait("data.sec.gov")
    limiter.wait("www.sec.gov")  # same budget: the second host waits too
    assert slept == [0.25]


def test_client_declares_the_user_agent_and_maps_statuses():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if "CIK0000000001" in str(request.url):
            return httpx.Response(404)
        if "CIK0000000002" in str(request.url):
            return httpx.Response(403)
        return httpx.Response(200, json={"cik": 320193, "facts": {}})

    limiter = RateLimiter()
    fetcher = HttpFetcher(retries=0, limiter=limiter, user_agent=sec.user_agent(FAKE_EMAIL),
                          client=httpx.Client(transport=httpx.MockTransport(handler),
                                              headers={"User-Agent": sec.user_agent(FAKE_EMAIL)}))
    client = sec.SecClient(FAKE_EMAIL, fetcher=fetcher)
    assert client.company_facts(AAPL_CIK) == {"cik": 320193, "facts": {}}
    assert seen[0].headers["User-Agent"] == f"Forliosa/1.0 {FAKE_EMAIL}"
    assert client.submissions(1) is None  # 404: SEC has nothing for this company
    with pytest.raises(HttpStatusError) as exc:
        client.company_facts(2)
    assert sec.is_refusal(exc.value) and FAKE_EMAIL not in str(exc.value)
    assert FAKE_EMAIL not in repr(client)
    for bad in ("", "no-at-sign", "a b@example.com", "x@y.com\r\nX-Evil: 1", "<ops@example.com>"):
        assert not sec.valid_contact(bad)
        with pytest.raises(ValueError):
            sec.SecClient(bad)


def test_contact_email_is_a_secret_setting(monkeypatch):
    from forliosa.config import Settings

    s = Settings(_env_file=None, sec_contact_email=FAKE_EMAIL)
    assert FAKE_EMAIL not in repr(s) and FAKE_EMAIL not in str(s.model_dump())
    assert s.sec_contact_email.get_secret_value() == FAKE_EMAIL
    # tests never build a real client, even when the environment has an address
    monkeypatch.setenv("SEC_CONTACT_EMAIL", FAKE_EMAIL)
    sec_svc.reset_sec_state()
    assert sec_svc.sec_client() is None


# -- API: financials and events ---------------------------------------------------------------------------------
def test_us_financials_from_sec_in_usd(client, fake):
    f = client.get(f"{API}/instruments/AAPL/financials").json()
    assert f["currency"] == "USD" and f["amount_unit"] == 1
    assert f["periods"][-1] == "FY2026Q4" and f["period_ends"][-1] == "2026-09-26"
    assert len(f["periods"]) == len(f["income"]["revenue"]) == len(f["period_ends"]) <= 12
    i = f["periods"].index("FY2026Q1")
    assert f["income"]["revenue"][i] == 143756000000 and f["income"]["eps"][i] == 2.84
    assert f["margins"]["gross"][i] == round(69231000000 / 143756000000, 6)
    assert f["cashflow"]["free_cash_flow"][i] == 53925000000 - 2373000000  # operating - capex
    assert f["shares"]["outstanding"] == 14532182000 and f["shares"]["outstanding_as_of"] == "2026-10-23"
    assert f["sources"] == [SEC_FACTS_LABEL]
    assert any("FY2026Q1 是 2025-09-28 至 2025-12-27" in n for n in f["notes"])
    assert any(n.startswith("金額單位：美元") for n in f["notes"])
    a = client.get(f"{API}/instruments/AAPL/financials?period=annual").json()
    assert a["periods"][-1] == "FY2026" and a["income"]["eps"][-1] == 8.98
    # served from the cache: one ticker map + one companyfacts fetch for both calls
    assert fake.calls == ["tickers", f"facts:{AAPL_CIK}"]
    # Taiwan responses carry the unit too
    tw = client.get(f"{API}/instruments/2330/financials").json()
    assert tw["currency"] == "TWD" and tw["amount_unit"] == 1000 and tw["shares"] is None
    # the overview reads the cache (no fetch): diluted EPS of the last four quarters and the cover-page shares
    ov = client.get(f"{API}/instruments/AAPL/overview").json()
    assert ov["eps_ttm"] == 8.98 and ov["shares_outstanding"] == 14532182000 and SEC_FACTS_LABEL in ov["sources"]
    assert fake.calls == ["tickers", f"facts:{AAPL_CIK}"]


def test_stale_cache_is_refreshed_and_failures_serve_the_cache(client, fake, clock):
    client.get(f"{API}/instruments/AAPL/financials")
    clock["now"] += timedelta(hours=25)
    fake.fail = HttpStatusError("data.sec.gov 回應 HTTP 503", 503)
    f = client.get(f"{API}/instruments/AAPL/financials").json()
    assert f["periods"] and any(n.startswith(sec_svc.UNAVAILABLE_NOTE) and "2026-11-12 12:00" in n
                                for n in f["notes"])
    calls = len(fake.calls)
    client.get(f"{API}/instruments/AAPL/financials")
    assert len(fake.calls) == calls  # a failed company is not retried for a few minutes
    fake.fail = None
    sec_svc._retry_after.clear()
    f = client.get(f"{API}/instruments/AAPL/financials").json()
    assert fake.calls[-1] == f"facts:{AAPL_CIK}" and not any("無法連線" in n for n in f["notes"])


def test_a_refusal_pauses_every_sec_request(client, fake, caplog):
    fake.fail = HttpStatusError("www.sec.gov 回應 HTTP 403", 403)
    with caplog.at_level(logging.WARNING):
        f = client.get(f"{API}/instruments/AAPL/financials").json()
    assert f["periods"] == [] and f["notes"] == [sec_svc.REFUSED_NOTE]
    fake.fail = None
    client.get(f"{API}/instruments/NVDA/financials")
    assert fake.calls == ["tickers"]  # nothing else is tried while paused
    assert FAKE_EMAIL not in caplog.text


def test_disabled_sec_is_an_honest_empty_state(client, clock):
    sec_svc.set_sec_client(None)
    f = client.get(f"{API}/instruments/AAPL/financials").json()
    assert f["periods"] == [] and f["notes"] == [sec_svc.DISABLED_NOTE] and f["currency"] == "USD"
    assert not [e for e in client.get(f"{API}/instruments/AAPL/events").json() if e["type"] == "sec_filing"]


def test_etfs_and_unknown_companies(client, fake):
    voo = client.get(f"{API}/instruments/VOO/financials").json()
    assert voo["periods"] == [] and voo["notes"] == ["ETF 沒有財務報表資料"] and fake.calls == []
    msft = client.get(f"{API}/instruments/MSFT/financials")
    assert msft.status_code == 404  # not in Forliosa's instrument list


def test_us_events_list_filings_with_links(client, fake):
    evs = client.get(f"{API}/instruments/AAPL/events").json()
    filings = [e for e in evs if e["type"] == "sec_filing"]
    assert filings and all(e["url"].startswith("https://www.sec.gov/Archives/edgar/data/320193/") for e in filings)
    ten_k = next(e for e in filings if e["form"] == "10-K")
    assert ten_k["date"] == "2026-11-03" and ten_k["title"] == "10-K 年度報告"
    assert ten_k["detail"] == "會計年度截至 2026-09-26" and not ten_k["mine"]
    assert ten_k["sources"] == [SEC_FILINGS_LABEL]
    earnings = next(e for e in filings if e["form"] == "8-K" and e["date"] == "2026-11-02")
    assert earnings["title"] == "8-K 營運結果與財務狀況"
    dates = [e["date"] for e in evs]
    assert dates == sorted(dates, reverse=True)
    assert "submissions:320193" in fake.calls
    client.get(f"{API}/instruments/AAPL/events")
    assert fake.calls.count("submissions:320193") == 1


def test_held_us_stock_marks_reports_as_mine(client, fake):
    acc = client.post(f"{API}/accounts", json={"name": "Firstrade", "broker": "Firstrade", "currency": "USD"}).json()
    r = client.post(f"{API}/transactions", json={"account_id": acc["id"], "symbol": "AAPL", "type": "buy",
                                                 "trade_date": "2026-05-04", "quantity": 10, "price": "200"})
    assert r.status_code == 201, r.text
    mine = client.get(f"{API}/instruments/AAPL/events?mine=true").json()
    forms = {e["form"] for e in mine if e["type"] == "sec_filing"}
    assert {"10-K", "10-Q"} <= forms
    assert all(e["date"] >= "2026-11-05" for e in mine if e.get("form") == "8-K")  # 8-Ks: only the last 7 days


def test_ai_tools_read_us_financials_and_filings(client, fake, engine):
    import json

    from forliosa.ai.tools import ToolContext, execute
    from forliosa.marketdata.service import get_market_data
    from forliosa.models import User

    with Session(engine) as db:
        me = db.scalar(select(User).where(User.email == "demo@forliosa.local"))
        ctx = ToolContext(db=db, user=me, md=get_market_data())
        fin = json.loads(execute(ctx, "get_financials", {"symbol": "AAPL", "period": "quarterly"}).content)
        assert fin["units"].startswith("金額單位美元") and "monthly_revenue_last_6" not in fin
        assert fin["periods"][-1] == "FY2026Q4" and fin["period_ends"][-1] == "2026-09-26"
        evs = json.loads(execute(ctx, "get_events", {"symbol": "AAPL", "mine_only": False}).content)
        assert any(e.get("form") == "10-K" for e in evs["recent"])


# -- worker job ------------------------------------------------------------------------------------------------
def test_sec_archive_job_refreshes_tracked_us_stocks(client, engine, clock):
    acc = client.post(f"{API}/accounts", json={"name": "Firstrade", "broker": "Firstrade", "currency": "USD"}).json()
    for sym in ("AAPL", "VOO"):
        client.post(f"{API}/transactions", json={"account_id": acc["id"], "symbol": sym, "type": "buy",
                                                 "trade_date": "2026-05-04", "quantity": 1, "price": "200"})
    fake = FakeSecClient()
    with Session(engine) as db:
        results = Archiver(db, None, "commercial", now_fn=lambda: NOW, sec_client=fake).run(["sec"])  # type: ignore[arg-type]
        assert [(r.name, r.error) for r in results] == [("sec edgar", None)]
        assert fake.calls == ["tickers", f"facts:{AAPL_CIK}", f"submissions:{AAPL_CIK}"]  # the ETF is skipped
        assert db.scalar(select(func.count()).select_from(SecTicker)) == 7
        comp = db.get(SecCompany, AAPL_CIK)
        assert comp.name == "Apple Inc." and comp.fiscal_year_end == "0926" and comp.facts["tags"]
        assert db.scalar(select(func.count()).select_from(SecFiling)) > 10
        assert db.get(DatasetStatus, "sec-edgar/submissions").data_date == date(2026, 11, 9)
        assert db.get(DatasetStatus, "sec-edgar/companyfacts").data_date == date(2026, 11, 3)
        # fresh: the next run fetches nothing
        Archiver(db, None, "commercial", now_fn=lambda: NOW, sec_client=fake).run(["sec"])  # type: ignore[arg-type]
        assert len(fake.calls) == 3
        # a refusal ends the job with an error
        clock["now"] += timedelta(days=2)
        refused = FakeSecClient(fail=HttpStatusError("www.sec.gov 回應 HTTP 429", 429))
        res = Archiver(db, None, "commercial", now_fn=lambda: NOW, sec_client=refused).run(["sec"])  # type: ignore[arg-type]
        assert res[0].error and "429" in res[0].error and refused.calls == ["tickers"]
        # without SEC_CONTACT_EMAIL the job is skipped, not failed
        sec_svc.set_sec_client(None)
        res = Archiver(db, None, "commercial", now_fn=lambda: NOW).run(["sec"])  # type: ignore[arg-type]
        assert [(r.name, r.error) for r in res] == [(SEC_DISABLED, None)]


def test_attributions_list_sec_with_its_own_licence():
    from forliosa.datapolicy import DATASETS, attributions, dataset_served, label

    meta = attributions("commercial")
    sec_rows = [d for d in meta["datasets"] if d["key"].startswith("sec-edgar/")]
    assert {d["key"] for d in sec_rows} == {"sec-edgar/companyfacts", "sec-edgar/submissions", "sec-edgar/tickers"}
    assert all(d["commercial"] and d["license_status"] == "public" for d in sec_rows)
    assert all(d["license_url"] == "https://www.sec.gov/about/webmaster-frequently-asked-questions" for d in sec_rows)
    assert any("EDGAR" in n for n in meta["notice"])
    assert dataset_served("sec-edgar/companyfacts", "commercial", confirmed=False)
    assert label("sec-edgar/tickers").endswith("美國政府公開資料")
    assert DATASETS["twse-openapi/price"].commercial and not DATASETS["taifex-openapi/fx"].commercial
