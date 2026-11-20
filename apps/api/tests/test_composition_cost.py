"""Cost of a five-year ledger (asset-composition prototype, ``docs/proposals/asset-composition.md``〈已知問題〉).

Estimated buy dates move an imported holding's buy from the import day back up to five years, so the ledger's
performance replay and the group board run over years instead of days. This measures, on a local SQLite database:

* the ledger page's reads — ``/portfolio/summary``, ``/portfolio/holdings`` and ``/portfolio/performance`` for every
  range — for one user with 20 holdings and five years of history (and, for comparison, the same 20 holdings all
  bought on the last close: the import before buy dates were estimated);
* a 50-member group board (``/groups/{id}/leaderboard``), every member with a comparable five-year ledger;

each cold (a fresh ``MarketData`` and empty ``perfcache``: a process that just started) and warm (the same request
again), as the median of a few runs: milliseconds, SQL statements and response size.

Opt-in (slow, ~1–2 min): ``FORLIOSA_BENCH=1 uv run pytest tests/test_composition_cost.py -s``. With
``FORLIOSA_BENCH_OUT=path.json`` the numbers are also written as JSON.
"""

from __future__ import annotations

import json
import os
import statistics
import time

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from forliosa import perfcache
from forliosa.marketdata.archive_provider import ArchiveProvider
from forliosa.marketdata.demo import DemoProvider
from forliosa.marketdata.service import MarketData, set_market_data
from tests.composition_fixture import (
    add_accounts,
    build_archive,
    build_group,
    five_year_ledger,
    imported_today_ledger,
    store_ledger,
)

pytestmark = pytest.mark.skipif(os.environ.get("FORLIOSA_BENCH") != "1",
                                reason="opt-in benchmark: FORLIOSA_BENCH=1 (see the module docstring)")

API = "/api/v1"
RANGES = ("1D", "5D", "MTD", "1M", "3M", "6M", "YTD", "1Y", "ALL")
COLD_RUNS = 3
WARM_RUNS = 5


def _facade(engine) -> MarketData:
    return MarketData([ArchiveProvider("commercial", session_fn=lambda: Session(engine), us_prices=True),
                       DemoProvider()], policy="commercial")


class Counter:
    def __init__(self, engine):
        self.n = 0
        self.engine = engine
        event.listen(engine, "after_cursor_execute", self._count)

    def _count(self, *_a, **_k):
        self.n += 1

    def close(self):
        event.remove(self.engine, "after_cursor_execute", self._count)


def _measure(client, engine, counter: Counter, url: str) -> dict:
    def once(cold: bool) -> tuple[float, int, int]:
        if cold:
            set_market_data(_facade(engine))
            perfcache.clear_all()
        before = counter.n
        t0 = time.perf_counter()
        r = client.get(url)
        ms = (time.perf_counter() - t0) * 1000
        assert r.status_code == 200, (url, r.text[:300])
        return ms, counter.n - before, len(r.content)

    cold = [once(True) for _ in range(COLD_RUNS)]
    once(False)
    warm = [once(False) for _ in range(WARM_RUNS)]
    med = statistics.median
    return {"url": url, "cold_ms": round(med(x[0] for x in cold)), "cold_queries": round(med(x[1] for x in cold)),
            "warm_ms": round(med(x[0] for x in warm)), "warm_queries": round(med(x[1] for x in warm)),
            "bytes": cold[0][2]}


@pytest.fixture()
def bench(engine, market, monkeypatch):
    from forliosa.config import get_settings

    monkeypatch.setenv("PRICE_HISTORY_SOURCE", "yahoo")
    monkeypatch.setenv("US_PRICE_SOURCE", "databento")
    get_settings.cache_clear()
    archive = build_archive(engine)
    md = _facade(engine)
    set_market_data(md)
    yield archive
    set_market_data(market)
    get_settings.cache_clear()


def test_cost_of_a_five_year_ledger(engine, client, other_client, bench):
    archive = bench
    t0 = time.perf_counter()
    me = client.get(f"{API}/me").json()["id"]
    other = other_client.get(f"{API}/me").json()["id"]
    with Session(engine) as db:
        tw, us = add_accounts(db, me)
        tw2, us2 = add_accounts(db, other)
        db.commit()
    store_ledger(engine, five_year_ledger(archive, me, tw, us, seed=1))
    store_ledger(engine, imported_today_ledger(archive, other, tw2, us2))
    gid = build_group(engine, archive, me, members=50)
    gid_today = build_group(engine, archive, other, members=50, five_years=False, first_member=100)
    setup_s = time.perf_counter() - t0

    counter = Counter(engine)
    results: dict[str, list[dict]] = {"five_year": [], "imported_today": [], "group": [], "group_imported_today": []}
    try:
        urls = ["/portfolio/summary", "/portfolio/holdings", *[f"/portfolio/performance?range={r}" for r in RANGES]]
        for who, c in (("five_year", client), ("imported_today", other_client)):
            for u in urls:
                results[who].append(_measure(c, engine, counter, f"{API}{u}"))
        for period in ("month", "year"):
            results["group"].append(_measure(client, engine, counter,
                                             f"{API}/groups/{gid}/leaderboard?period={period}"))
            results["group_imported_today"].append(_measure(other_client, engine, counter,
                                                            f"{API}/groups/{gid_today}/leaderboard?period={period}"))
    finally:
        counter.close()

    if os.environ.get("FORLIOSA_BENCH_PROFILE") == "1":  # where the time goes (warm), top functions by own time
        import cProfile
        import pstats

        set_market_data(_facade(engine))
        for url in (f"{API}/portfolio/performance?range=ALL", f"{API}/groups/{gid}/leaderboard?period=year"):
            client.get(url)  # warm
            prof = cProfile.Profile()
            prof.runcall(client.get, url)
            print(f"\n== {url}")
            pstats.Stats(prof).sort_stats("tottime").print_stats(15)

    set_market_data(_facade(engine))
    perf = client.get(f"{API}/portfolio/performance?range=ALL")
    series = perf.json()["series"] if perf.status_code == 200 else []
    meta = {"setup_seconds": round(setup_s, 1), "days": len(archive.days), "archive_start": str(archive.archive_start),
            "all_points": len(series), "first_point": series[0]["t"] if series else None}
    lines = [f"setup {meta}", "| ledger | request | cold ms | cold SQL | warm ms | warm SQL | bytes |",
             "|---|---|---:|---:|---:|---:|---:|"]
    for who, rows in results.items():
        for r in rows:
            url = r["url"].removeprefix(API).replace(gid, "{id}").replace(gid_today, "{id}")
            lines.append(f"| {who} | {url} | {r['cold_ms']} | {r['cold_queries']} | "
                         f"{r['warm_ms']} | {r['warm_queries']} | {r['bytes']} |")
    print("\n" + "\n".join(lines))
    out = os.environ.get("FORLIOSA_BENCH_OUT")
    if out:
        with open(out, "w", encoding="utf-8") as f:
            json.dump({"meta": meta, "results": results}, f, ensure_ascii=False, indent=2)
    assert series and len(series) > 1000  # the replay really covers about five years
