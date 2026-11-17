"""``available_at`` (contract §6.4): a pack only takes rows that existed at its cut-off, so an edition rebuilt from the
command line never uses what was published later (the sample's 15:55 report drew the next morning's FMTQIK)."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from forliosa.reports import pack, timing
from tests.reports.conftest import MON, ts


def test_fixed_rules():
    d = MON
    assert timing.available_at("twse-opendata/price", d) == ts(d, 14)
    assert timing.available_at("twse-openapi/turnover", d) == ts(date(2026, 11, 17), 5, 45)  # FMTQIK: next morning
    assert timing.available_at("twse-openapi/turnover", date(2026, 11, 13)) == ts(MON, 5, 45)  # over the weekend
    assert timing.available_at("tpex-openapi/price", d) == ts(d, 23, 40)
    assert timing.available_at("tpex-openapi/index", d) == ts(d, 14, 30)
    assert timing.available_at("taifex-openapi/put_call_ratio", d) == ts(d, 21, 45)
    assert timing.available_at("cbc-opendata/fx", d) == ts(d, 17)
    assert timing.available_at("twse-openapi/margin", d) == ts(date(2026, 11, 17), 5, 45)  # conservative
    # a US session: its close (16:00 New York = 05:00 Taipei in winter) plus an hour
    assert timing.available_at("databento-equs/price", MON) == ts(date(2026, 11, 17), 6)


def test_openapi_closes_stand_for_the_same_day_download_only_while_it_is_polled():
    assert timing.available_at("twse-openapi/price", MON, opendata_on=True) == ts(MON, 14)
    assert timing.available_at("twse-openapi/price", MON, opendata_on=False) == ts(date(2026, 11, 17), 5, 45)
    assert timing.available_at("twse-openapi/total_return", MON, opendata_on=True) == ts(date(2026, 11, 17), 5, 45)


def test_stamped_rows_use_their_own_time_and_unknown_datasets_are_late(caplog):
    created = datetime(2026, 11, 16, 6, 35, tzinfo=UTC)
    assert timing.available_at("market_events", MON, created) == ts(MON, 14, 35)
    with pytest.raises(ValueError):
        timing.available_at("manual-calendar", MON)
    assert timing.available_at("someone-new/thing", MON) == ts(date(2026, 11, 17), 5, 45)
    assert "no availability rule" in caplog.text


def test_a_close_rebuilt_later_never_takes_the_next_mornings_fmtqik(market_db):
    """The 15:40 cut-off of 11/16 takes our own sum (an estimate); the 06:40 table run of 11/17 takes FMTQIK."""
    built = pack.build(market_db, "close", MON, cutoff=ts(MON, 15, 40), policy="commercial",
                       now=ts(date(2026, 11, 20), 10))
    metrics = {f["metric"]: f for f in built.pack["facts"]}
    assert "turnover" not in metrics and metrics["turnover_est"]["estimate"]
    assert metrics["turnover_est"]["dataset"] == "rules:turnover_sum"
    later = pack.build(market_db, "close", MON, cutoff=ts(date(2026, 11, 17), 6, 40), policy="commercial")
    metrics = {f["metric"]: f for f in later.pack["facts"]}
    assert metrics["turnover"]["display"] == "9,031 億元" and not metrics["turnover"]["estimate"]
    # the TPEx closes of 11/16 (out at 23:40) are not in the 15:40 pack's OTC list either
    assert not any(s["market"] == "TPEX" for s in built.pack["stocks"])
