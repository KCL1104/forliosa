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


def _fact(start, end, val, fy, fp, form, filed, accn):
    """One companyfacts entry (``start`` None for an instant)."""
    e = {"end": end, "val": val, "fy": fy, "fp": fp, "form": form, "filed": filed, "accn": accn}
    return {**e, "start": start} if start else e


def _raw(**tags):
    """companyfacts with us-gaap ``tag=[entries]`` (unit from the tag: EPS USD/shares, counts shares, else USD)."""
    def unit(tag):
        return "USD/shares" if tag.startswith("EarningsPerShare") else "shares" if "Shares" in tag else "USD"
    return {"cik": 1045810, "entityName": "Test Corp",
            "facts": {"us-gaap": {t: {"units": {unit(t): rows}} for t, rows in tags.items()}}}


# A calendar-year company splits 10-for-1 after its Q3 10-Q (EPS 5.00 a quarter) and before its 10-K: the 10-K
# reports the year on the new basis (2.00) and restates the year before; the next Q1 10-Q restates last year's Q1.
SPLIT_AFTER_Q3 = _raw(
    EarningsPerShareDiluted=[
        _fact("2024-01-01", "2024-12-31", 18.0, 2024, "FY", "10-K", "2025-02-20", "k24"),
        _fact("2025-01-01", "2025-03-31", 5.0, 2025, "Q1", "10-Q", "2025-05-01", "q125"),
        _fact("2025-04-01", "2025-06-30", 5.0, 2025, "Q2", "10-Q", "2025-08-01", "q225"),
        _fact("2025-01-01", "2025-06-30", 10.0, 2025, "Q2", "10-Q", "2025-08-01", "q225"),
        _fact("2025-07-01", "2025-09-30", 5.0, 2025, "Q3", "10-Q", "2025-11-01", "q325"),
        _fact("2025-01-01", "2025-09-30", 15.0, 2025, "Q3", "10-Q", "2025-11-01", "q325"),
        _fact("2025-01-01", "2025-12-31", 2.0, 2025, "FY", "10-K", "2026-02-20", "k25"),
        _fact("2024-01-01", "2024-12-31", 1.8, 2025, "FY", "10-K", "2026-02-20", "k25"),
        _fact("2026-01-01", "2026-03-31", 0.6, 2026, "Q1", "10-Q", "2026-05-01", "q126"),
        _fact("2025-01-01", "2025-03-31", 0.5, 2026, "Q1", "10-Q", "2026-05-01", "q126"),
    ],
    Revenues=[
        _fact("2024-01-01", "2024-12-31", 1800, 2024, "FY", "10-K", "2025-02-20", "k24"),
        _fact("2025-01-01", "2025-03-31", 500, 2025, "Q1", "10-Q", "2025-05-01", "q125"),
        _fact("2025-04-01", "2025-06-30", 500, 2025, "Q2", "10-Q", "2025-08-01", "q225"),
        _fact("2025-07-01", "2025-09-30", 500, 2025, "Q3", "10-Q", "2025-11-01", "q325"),
        _fact("2025-01-01", "2025-12-31", 2000, 2025, "FY", "10-K", "2026-02-20", "k25"),
        _fact("2024-01-01", "2024-12-31", 1800, 2025, "FY", "10-K", "2026-02-20", "k25"),
        _fact("2026-01-01", "2026-03-31", 600, 2026, "Q1", "10-Q", "2026-05-01", "q126"),
        _fact("2025-01-01", "2025-03-31", 500, 2026, "Q1", "10-Q", "2026-05-01", "q126"),
    ],
)


def test_a_split_between_the_q3_report_and_the_10k_keeps_eps_on_one_basis():
    facts = sec.trim_facts(SPLIT_AFTER_Q3, TODAY)
    # no share counts tagged: EPS finds it (two periods agree), pinned to the first report on the new basis
    assert facts["splits"] == [["2026-02-20", "10"]]
    qs = {p.label: p for p in sec.summarize(facts, "quarterly")}
    assert [qs[f"FY2025Q{n}"].values["eps"] for n in (1, 2, 3)] == [D("0.5")] * 3
    # Q4 = the 10-K year (new basis) − nine months (old basis, converted): not 2.00 − 15.00 = −13.00
    assert qs["FY2025Q4"].values["eps"] == D("0.5") and "eps" in qs["FY2025Q4"].derived
    assert qs["FY2026Q1"].values["eps"] == D("0.6")
    years = {p.label: p.values["eps"] for p in sec.summarize(facts, "annual")}
    assert years == {"FY2024": D("1.8"), "FY2025": D("2.0")}


def test_split_overview_eps_ttm_and_note(client, clock):
    """Through the API: the last four quarters add up on one basis, and the notes say what was converted."""
    fake = FakeSecClient(facts={1045810: SPLIT_AFTER_Q3})
    sec_svc.set_sec_client(fake)
    f = client.get(f"{API}/instruments/NVDA/financials").json()
    assert f["periods"] == ["FY2025Q1", "FY2025Q2", "FY2025Q3", "FY2025Q4", "FY2026Q1"]
    assert f["income"]["eps"] == [0.5, 0.5, 0.5, 0.5, 0.6]
    assert ("EPS 與稀釋平均股數都以目前的股數為準：2026-02-20 起申報的財報反映 1 股拆成 10 股；"
            "更早申報、後來沒有重編的數字已依分割比例換算") in f["notes"]
    ov = client.get(f"{API}/instruments/NVDA/overview").json()
    assert ov["eps_ttm"] == 2.1  # 0.5 + 0.5 + 0.5 + 0.6, not 5 + 5 − 13 + 0.6


def test_nvidia_splits_from_live_filings(client, fake):
    """NVIDIA split 4-for-1 (2021) and 10-for-1 (2024); 10-Ks restate three years, so FY2019 was last reported on
    the pre-2021 basis and FY2022 on the pre-2024 basis."""
    facts = sec.trim_facts(load("sec_companyfacts_nvda_live_20261112.json"), TODAY)
    assert facts["splits"] == [["2021-08-20", "4"], ["2024-08-28", "10"]]
    years = {p.label: p for p in sec.summarize(facts, "annual")}
    eps = {k: p.values["eps"] for k, p in years.items()}
    assert eps["FY2019"] == D("6.63") / 40 and eps["FY2020"] == D("1.13") / 10 and eps["FY2022"] == D("3.85") / 10
    assert eps["FY2023"] == D("0.17") and eps["FY2026"] == D("4.9")  # reported on today's basis
    assert years["FY2019"].values["diluted_shares"] == 625_000_000 * 40
    assert years["FY2022"].values["diluted_shares"] == 2_535_000_000 * 10
    a = client.get(f"{API}/instruments/NVDA/financials?period=annual").json()
    assert a["periods"][0] == "FY2017" and a["income"]["eps"][a["periods"].index("FY2022")] == 0.385
    shares = [v for v in a["shares"]["diluted_average"] if v is not None]
    assert max(shares) / min(shares) < 1.1  # one basis: no 10x or 40x jumps
    assert any(n.startswith("EPS 與稀釋平均股數都以目前的股數為準：2021-08-20 起申報的財報反映 1 股拆成 4 股、"
                            "2024-08-28 起申報的財報反映 1 股拆成 10 股") for n in a["notes"])
    # Apple's quarters start after its 2020 split: nothing to say
    q = client.get(f"{API}/instruments/AAPL/financials").json()
    assert not any("分割" in n for n in q["notes"])


def _shares(val_old, val_new, *, old_filed="2025-08-01", new_filed="2026-08-01", form="10-Q"):
    """A quarter reported on ``old_filed`` and again a year later as the comparative."""
    return [_fact("2025-04-01", "2025-06-30", val_old, 2025, "Q2", "10-Q", old_filed, "a"),
            _fact("2025-04-01", "2025-06-30", val_new, 2026, "Q2", form, new_filed, "b")]


def test_find_splits_reads_share_counts_first():
    find = sec.find_splits
    # one period of share counts is enough; a reverse split is a ratio below one
    assert find(_raw(WeightedAverageNumberOfDilutedSharesOutstanding=_shares(100_000_000, 300_000_000)),
                TODAY) == [["2026-08-01", "3"]]
    assert find(_raw(WeightedAverageNumberOfSharesOutstandingBasic=_shares(800_000, 100_000)),
                TODAY) == [["2026-08-01", "1/8"]]
    assert find(_raw(WeightedAverageNumberOfDilutedSharesOutstanding=_shares(100, 150)), TODAY) == [
        ["2026-08-01", "3/2"]]
    # small changes, odd ratios and an amendment repeating the original figures are not splits
    assert find(_raw(WeightedAverageNumberOfDilutedSharesOutstanding=_shares(100, 105)), TODAY) == []
    assert find(_raw(WeightedAverageNumberOfDilutedSharesOutstanding=_shares(100, 137)), TODAY) == []
    assert find(_raw(WeightedAverageNumberOfDilutedSharesOutstanding=_shares(300, 100, form="10-Q/A")), TODAY) == []
    # EPS alone: one period could be a restatement for other reasons; two that agree are a split
    eps_one = [_fact("2025-04-01", "2025-06-30", 2.0, 2025, "Q2", "10-Q", "2025-08-01", "a"),
               _fact("2025-04-01", "2025-06-30", 1.0, 2026, "Q2", "10-Q", "2026-08-01", "b")]
    eps_two = [*eps_one, _fact("2025-01-01", "2025-06-30", 4.0, 2025, "Q2", "10-Q", "2025-08-01", "a"),
               _fact("2025-01-01", "2025-06-30", 2.0, 2026, "Q2", "10-Q", "2026-08-01", "b")]
    assert find(_raw(EarningsPerShareDiluted=eps_one), TODAY) == []
    assert find(_raw(EarningsPerShareDiluted=eps_two), TODAY) == [["2026-08-01", "2"]]
    # … unless the share count did not move over the same window
    steady = _shares(100_000_000, 100_000_000, old_filed="2025-05-01", new_filed="2026-09-01")
    assert find(_raw(EarningsPerShareDiluted=eps_two, WeightedAverageNumberOfDilutedSharesOutstanding=steady),
                TODAY) == []


def test_first_10k_with_three_years_names_each_year_by_itself():
    """A new registrant's first 10-K (FY2025) brings 2023 and 2024 along; companyfacts labels all three fy=2025."""
    raw = _raw(Revenues=[
        _fact("2023-01-01", "2023-12-31", 100, 2025, "FY", "10-K", "2026-03-01", "k25"),
        _fact("2024-01-01", "2024-12-31", 200, 2025, "FY", "10-K", "2026-03-01", "k25"),
        _fact("2025-01-01", "2025-12-31", 300, 2025, "FY", "10-K", "2026-03-01", "k25"),
        _fact("2026-01-01", "2026-03-31", 90, 2026, "Q1", "10-Q", "2026-05-01", "q126"),
        _fact("2025-01-01", "2025-03-31", 70, 2026, "Q1", "10-Q", "2026-05-01", "q126"),
    ])
    facts = sec.trim_facts(raw, TODAY)
    rows = facts["tags"]["Revenues"]["USD"]
    assert [(r[1], r[3]) for r in rows] == [("2023-12-31", 2023), ("2024-12-31", 2024), ("2025-03-31", 2025),
                                            ("2025-12-31", 2025), ("2026-03-31", 2026)]
    assert [p.label for p in sec.summarize(facts, "annual")] == ["FY2023", "FY2024", "FY2025"]
    # the 10-Q's comparative quarter is Q1 of fiscal 2025 (not "FY2026Q1" next to a "FY2027Q1")
    quarters = {p.label: p.values["revenue"] for p in sec.summarize(facts, "quarterly")}
    assert quarters == {"FY2025Q1": 70, "FY2026Q1": 90}


def test_facts_from_an_older_version_are_fetched_again(client, fake, engine):
    client.get(f"{API}/instruments/AAPL/financials")
    with Session(engine) as db:
        comp = db.get(SecCompany, AAPL_CIK)
        comp.facts = {**comp.facts, "v": 1}
        db.commit()
    client.get(f"{API}/instruments/AAPL/financials")
    assert fake.calls.count(f"facts:{AAPL_CIK}") == 2
    with Session(engine) as db:
        assert db.get(SecCompany, AAPL_CIK).facts["v"] == sec.FACTS_VERSION


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
    profile = meta.pop("profile")
    assert meta == {"name": "Apple Inc.", "fiscal_year_end": "0926"}
    # 「關於」 facts: industry, HQ city / state, exchanges, former names (no street address, phone or EIN)
    assert (profile["industry"], profile["city"], profile["state"], profile["country"], profile["exchanges"]) == (
        "Electronic Computers", "CUPERTINO", "CA", "United States", ["Nasdaq"])
    assert profile["former_names"][1] == {"name": "APPLE COMPUTER INC", "from": "1994-01-26", "to": "2007-01-04"}
    tsm = sec.parse_profile(load("sec_submissions_tsm_meta_live_20261112.json"))
    assert (tsm["city"], tsm["state"], tsm["country"], tsm["exchanges"]) == ("HSINCHU", None, "Taiwan", ["NYSE", "OTC"])
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
        # the per-period share counts are cut with the periods (8 for the model, more in the API)
        api = client.get(f"{API}/instruments/AAPL/financials").json()
        assert len(fin["periods"]) == 8 < len(api["periods"])
        assert len(fin["shares"]["diluted_average"]) == len(fin["periods"])
        first = api["periods"].index(fin["periods"][0])
        assert fin["periods"][0] == "FY2025Q1"
        assert fin["shares"]["diluted_average"] == api["shares"]["diluted_average"][first:]
        assert fin["shares"]["diluted_average"][0] == 15150865000 and fin["shares"]["outstanding"] == 14532182000
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
