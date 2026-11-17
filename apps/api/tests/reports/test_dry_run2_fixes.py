"""Fixes from the second dry run (2026-11-17): an international outlet written with its Chinese name (〔彭博〕 for a
Bloomberg page) is the cited outlet in the approved 「〔媒體〕報導市場關注…」 shape, and the premarket's evening table
shows the USD/TWD change that the number strip already shows."""

from __future__ import annotations

import copy

import pytest

from forliosa.reports import pack, validate
from tests.reports.conftest import MON, TUE, ts
from tests.reports.helpers import INST_X, close_output, p, s, with_web

BLOOMBERG_X = {**INST_X, "id": "X003", "topic": "RISK", "key": "RISK.1", "subject": "輝達",
               "claim": "〔Bloomberg〕報導，輝達執行長黃仁勳辭職。", "outlet": "Bloomberg",
               "title": "Nvidia CEO resigns", "url": "https://www.bloomberg.com/news/articles/2026-11-16/nvidia-ceo",
               "numbers": [], "quote": "Nvidia CEO Jensen Huang resigned"}


@pytest.fixture()
def close_pack(market_db, us_on):
    built = pack.build(market_db, "close", MON, cutoff=ts(MON, 15, 40), now=ts(MON, 16))
    return with_web(built.pack, copy.deepcopy(INST_X), copy.deepcopy(BLOOMBERG_X))


def tonight_codes(pk, text, ref):
    out = close_output(pk)
    out["tonight"][0]["para"] = p(s(text, ref))
    return {x.code for x in validate.validate(out, pk, "close") if x.hard and x.path.startswith("tonight")}


@pytest.mark.parametrize("written", ["彭博", "彭博社", "Bloomberg"])
def test_a_chinese_name_of_an_international_outlet_is_that_outlet(close_pack, written):
    assert "outlook_pattern" not in tonight_codes(close_pack, f"〔{written}〕報導市場關注輝達執行長辭職後的人事安排。",
                                                  "X003")


def test_the_outlet_must_still_be_the_cited_one(close_pack):
    # 〔路透〕 is Reuters: a Bloomberg page does not stand for it, nor 〔彭博〕 for a 中央社 one
    assert "outlook_pattern" in tonight_codes(close_pack, "〔路透〕報導市場關注輝達執行長辭職後的人事安排。", "X003")
    assert "outlook_pattern" in tonight_codes(close_pack, "〔彭博〕報導市場關注外資賣超後的動向。", "X001")


def test_known_chinese_names_map_to_the_stored_outlet_names():
    assert validate._same_outlet("彭博", "Bloomberg") and validate._same_outlet("路透社", "Reuters")
    assert validate._same_outlet("華爾街日報", "The Wall Street Journal")
    assert validate._same_outlet("鉅亨", "鉅亨網") and validate._same_outlet("中央社", "中央社")
    assert not validate._same_outlet("彭博", "Reuters")


def test_the_evening_table_shows_the_usd_twd_change(market_db, us_on):
    built = pack.build(market_db, "premarket", TUE, cutoff=ts(TUE, 6, 55), now=ts(TUE, 7))
    rows = {r["cells"]["item"]["text"]: r["cells"] for r in built.blocks["tables"]["T_evening"]["rows"]}
    fx = rows["美元兌新台幣（央行）"]
    assert fx["value"]["text"] == "32.886" and fx["change"]["text"] == "+0.048"
    strip = next(n for n in built.blocks["numbers"] if n["key"] == "usdtwd")
    assert strip["change"] == fx["change"]["text"]
