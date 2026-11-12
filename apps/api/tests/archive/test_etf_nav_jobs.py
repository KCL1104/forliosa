"""證券期貨局〈證券投資信託基金每日淨值〉 (data.gov.tw 11109): the parser on a trimmed live CSV (2026-11-12) and the
``nav`` archive job (ETFs only, idempotent upsert, errors keep the last good date). No network."""

from datetime import date, datetime
from decimal import Decimal as D

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from forliosa.archive import Archiver
from forliosa.datapolicy import DATASETS, attribution, dataset_served, is_commercial_source, label
from forliosa.marketdata import fund_nav as fnav
from forliosa.marketdata.base import ProviderUnavailable
from forliosa.marketdata.http import DEFAULT_LIMITER, HttpStatusError, url_allowed
from forliosa.models import DatasetStatus, EtfNav, PriceDaily
from forliosa.timeutil import TAIPEI
from tests.archive.fakes import FIX, NAV_FIXTURE, NAV_URL, FakeFetcher

EVENING = datetime(2026, 11, 12, 21, 40, tzinfo=TAIPEI)
HEADER = "日期,會員代號,公司名稱,基金統編,基金代號,基金名稱,基金淨值,漲跌,漲跌幅,類型代號,幣別,受益憑證代號"


def raw() -> bytes:
    return (FIX / NAV_FIXTURE).read_bytes()


def csv_bytes(*rows: str, header: str = HEADER) -> bytes:
    return ("﻿" + "\r\n".join([header, *rows]) + "\r\n").encode("utf-8")


# -- parser ------------------------------------------------------------------------------------------------------
def test_live_file_shape_bom_and_etf_rows_only():
    data = raw()
    assert data.startswith(b"\xef\xbb\xbf") and b"\r\n" in data  # UTF-8 BOM, CRLF: the live file untouched
    rows = fnav.parse_nav_csv(data)
    by = {r["code"]: r for r in rows}
    # 13 ETF rows; T0102Y, T0105Y, T0119B (USD), T0336A (NAV "-") and the 0050 feeder fund T05B2A are not ETFs
    assert sorted(by) == sorted(["00996A", "009832", "006201", "00631L", "00632R", "00679B", "00720B", "0056", "0050",
                                 "00981A", "006208", "00919", "00878"])
    assert by["0050"] == {"code": "0050", "date": date(2026, 11, 12), "nav": D("101.04"), "currency": "TWD",
                          "fund_name": "元大台灣卓越50基金"}
    # overseas ETFs carry the previous business day; four decimals are kept
    assert (by["00679B"]["date"], by["00679B"]["nav"]) == (date(2026, 11, 11), D("26.4989"))
    assert by["00981A"]["nav"] == D("24.12") and by["00632R"]["nav"] == D("10.5")
    assert by["00878"]["fund_name"] == "國泰台灣高股息傘型基金之台灣ESG永續高股息ETF基金"
    assert [r["code"] for r in rows] == sorted(by)


def test_bad_rows_are_skipped_and_a_broken_file_is_an_error():
    rows = fnav.parse_nav_csv(csv_bytes(
        "20261112,A0005,元大投信,1,DDE02,元大台灣卓越50基金,-,-,-,AH11,TWD,0050",  # no NAV that day
        "20261111,A0005,元大投信,1,DDE02,元大台灣卓越50基金,100.5,0,0,AH11,TWD,0050",
        "20261112,A0005,元大投信,1,DDE07,元大台灣高股息基金,52.22,0,0,AH11,TWD,0056",
        "20261111,A0005,元大投信,1,DDE07,元大台灣高股息基金,52.00,0,0,AH11,TWD,0056",  # listed twice: newest wins
        "2026111X,A0005,元大投信,1,DDE09,元大富櫃50基金,35.82,0,0,AH11,TWD,006201",  # bad date
        "20261112,A0005,元大投信,1,DDE09,元大台灣50單日反向1倍基金,0,0,0,AH13,TWD,00632R",  # zero NAV
        "20261112,A0005,元大投信,1,DDO01,元大台灣卓越50ETF連結基金,61.88,0,0,AK11,TWD,T05B2A",
    ))
    assert [(r["code"], r["date"], r["nav"]) for r in rows] == [
        ("0050", date(2026, 11, 11), D("100.5")), ("0056", date(2026, 11, 12), D("52.22"))]
    with pytest.raises(ProviderUnavailable, match="空的"):
        fnav.parse_nav_csv(b"")
    with pytest.raises(ProviderUnavailable, match="空的"):
        fnav.parse_nav_csv(b"\xef\xbb\xbf\r\n")
    with pytest.raises(ProviderUnavailable, match=r"欄位不符.*受益憑證代號"):
        fnav.parse_nav_csv(csv_bytes("20261112,A,B,1,D,E,101.04,0,0,AH11,TWD,0050",
                                     header=HEADER.replace("受益憑證代號", "證券代號")))
    with pytest.raises(ProviderUnavailable, match="沒有任何 ETF"):
        fnav.parse_nav_csv(csv_bytes("20261112,A0001,兆豐投信,1,DDO01,兆豐第一基金,53.79,0,0,AA1,TWD,T0102Y"))


def test_only_the_nav_file_is_allowlisted_with_its_attribution():
    assert url_allowed(fnav.NAV_URL) and fnav.NAV_URL == NAV_URL
    assert not url_allowed("https://www.sitca.org.tw/ROC/Industry/IN2629.aspx")
    assert not url_allowed("https://www.sitca.org.tw/MemberK0000/F/03/")
    assert DEFAULT_LIMITER.interval_for("www.sitca.org.tw") == 2.0
    ds = DATASETS[fnav.NAV_DATASET]
    assert (ds.agency, ds.title, ds.license_status, ds.basis, ds.url) == (
        "金融監督管理委員會證券期貨局", "證券投資信託基金每日淨值", "ogdl", "data.gov.tw 11109", fnav.NAV_URL)
    assert attribution(ds, 2026) == (
        "金融監督管理委員會證券期貨局〈證券投資信託基金每日淨值〉（2026），依政府資料開放授權條款第 1 版")
    assert label("sfb-opendata/nav") == attribution(ds)
    assert is_commercial_source(fnav.SOURCE) and dataset_served(fnav.NAV_DATASET, "commercial")


# -- archive job -------------------------------------------------------------------------------------------------
def run(db, fetcher=None, only=("nav",)):
    return Archiver(db, fetcher or FakeFetcher(), "commercial", now_fn=lambda: EVENING).run(list(only))


def close(db, symbol: str, d: date, price: str, source: str) -> None:
    db.add(PriceDaily(symbol=symbol, date=d, close=D(price), source=source))
    db.commit()


def navs(db) -> dict[tuple[str, date], EtfNav]:
    return {(r.symbol, r.date): r for r in db.scalars(select(EtfNav))}


def test_job_keeps_known_etfs_only_and_is_idempotent(engine, market):
    with Session(engine) as db:
        # official closes tell the job which 00… codes trade where (TPEx ETFs are .TWO); a FinMind row does not count
        close(db, "00679B.TWO", date(2026, 11, 11), "26.61", "tpex-openapi")
        close(db, "006201.TWO", date(2026, 11, 12), "36.03", "tpex-openapi")
        close(db, "00632R.TW", date(2026, 11, 12), "10.26", "finmind")
        results = run(db)
        assert [(r.name, r.error) for r in results] == [("sfb etf nav 11109", None)]
        first = navs(db)
        # instrument master ETFs (0050, 0056, 00878, 006208, 00919) + the two with archived OpenAPI closes
        assert sorted(s for s, _ in first) == sorted(["0050.TW", "0056.TW", "006201.TWO", "00679B.TWO", "006208.TW",
                                                      "00878.TW", "00919.TW"])
        row = first[("00679B.TWO", date(2026, 11, 11))]
        assert (row.nav, row.currency, row.fund_name, row.source) == (
            D("26.4989"), "TWD", "元大美國政府20年期(以上)債券基金", "sfb-opendata")
        assert first[("0050.TW", date(2026, 11, 12))].nav == D("101.04")
        status = db.get(DatasetStatus, "sfb-opendata/nav")
        assert (status.data_date, status.rows) == (date(2026, 11, 12), 7)

        run(db)  # the 08:10 catch-up reads the same file: nothing new
        assert db.scalar(select(func.count()).select_from(EtfNav)) == 7


def test_a_corrected_nav_overwrites_and_a_new_day_adds_a_row(engine, market):
    class Edited(FakeFetcher):
        def __init__(self, text: bytes):
            super().__init__()
            self.text = text

        def get_bytes(self, url, params=None, headers=None):
            self.calls.append(url)
            return self.text

    with Session(engine) as db:
        run(db)
        fixed = raw().replace(b",101.04,", b",101.05,")
        run(db, Edited(fixed))
        assert navs(db)[("0050.TW", date(2026, 11, 12))].nav == D("101.05")
        nxt = raw().decode("utf-8").replace("20261112,A0005,元大投信,98764389", "20261113,A0005,元大投信,98764389")
        run(db, Edited(nxt.replace(",101.04,", ",102.00,").encode("utf-8")))
        rows = sorted((d, r.nav) for (s, d), r in navs(db).items() if s == "0050.TW")
        assert rows == [(date(2026, 11, 12), D("101.05")), (date(2026, 11, 13), D("102.00"))]


def test_a_broken_or_refused_download_records_an_error_and_keeps_the_last_date(engine, market):
    class Broken(FakeFetcher):
        def __init__(self, exc=None, body=b""):
            super().__init__()
            self.exc, self.body = exc, body

        def get_bytes(self, url, params=None, headers=None):
            self.calls.append(url)
            if self.exc:
                raise self.exc
            return self.body

    with Session(engine) as db:
        run(db)
        before = db.get(DatasetStatus, "sfb-opendata/nav").fetched_at
        renamed = csv_bytes("20261113,A,B,1,D,E,101.04,0,0,AH11,TWD,0050", header=HEADER.replace("基金淨值", "淨值"))
        for fetcher in (Broken(body=renamed), Broken(HttpStatusError("www.sitca.org.tw 回應 HTTP 429", 429))):
            results = run(db, fetcher)
            assert results[0].error and fetcher.calls == [NAV_URL]  # one request, never retried here
        assert db.get(DatasetStatus, "sfb-opendata/nav").fetched_at == before
        assert db.scalar(select(func.count()).select_from(EtfNav)) == 5  # master ETFs from the first run


def test_every_group_run_includes_nav_after_the_prices(engine, market):
    """A full run archives prices before the NAV job, so a fresh deployment's first evening already knows the
    listed ETFs with an OpenAPI close (00878 is in STOCK_DAY_ALL of the fixtures)."""
    with Session(engine) as db:
        fetcher = FakeFetcher()
        results = Archiver(db, fetcher, "commercial", now_fn=lambda: EVENING).run(["twse", "nav"])
        names = [r.name for r in results]
        assert names.index("sfb etf nav 11109") > names.index("twse prices")
        assert ("00878.TW", date(2026, 11, 12)) in navs(db)
