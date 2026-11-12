"""「相關股票」 (decision 4): benchmark / constituent, affiliates from 董監事持股餘額明細, peers by industry and market
cap, ETF pages by tracked index and holders — through the API under DATA_POLICY=commercial."""

from __future__ import annotations

API = "/api/v1"


def related(client, symbol):
    r = client.get(f"{API}/instruments/{symbol}/related")
    assert r.status_code == 200, r.text
    return r.json()


def test_tsmc_benchmark_affiliate_and_peers(client, stock_archive):
    out = related(client, "2330.TW")
    cards = out["items"]
    assert [(c["symbol"], c["reason"]) for c in cards] == [
        ("0050.TW", "benchmark"), ("3443.TW", "affiliate"), ("2454.TW", "peer"), ("3711.TW", "peer")]
    bench, guc, mtk, _ = cards
    # never "0050 holds this stock": only "your benchmark"
    assert bench["reason_label"] == "你的比較基準" and "持有" not in bench["reason_label"]
    assert guc["name"] == "創意" and guc["reason_label"] == "台積電是其法人董事及大股東"
    assert mtk["name"] == "聯發科" and mtk["reason_label"] == "同為半導體業"
    # a month of archived closes, the latest close and its change
    assert 15 <= len(mtk["sparkline"]) <= 25 and mtk["sparkline"][-1]["t"] == "2026-11-11"
    assert mtk["close"] == mtk["sparkline"][-1]["price"] and mtk["change_pct"] is not None
    assert out["notes"] == ["關係企業依董監事持股餘額明細（2026 年 9 月）"]
    srcs = " ".join(out["sources"])
    assert "〈上市公司董事、監察人持股餘額明細資料〉" in srcs and "〈上市公司基本資料〉" in srcs
    assert "依政府資料開放授權條款第 1 版" in srcs


def test_otc_constituent_card_and_affiliate_holder(client, stock_archive):
    out = related(client, "5347.TWO")
    cards = out["items"]
    assert [(c["symbol"], c["reason"]) for c in cards][:2] == [("006201.TWO", "constituent"),
                                                               ("2330.TW", "affiliate")]
    assert cards[0]["reason_label"] == "富櫃五十成分股（櫃買中心公布）" and cards[0]["name"] == "元大富櫃50"
    assert cards[1]["reason_label"] == "世界的大股東"  # TSMC holds > 10 % of 世界
    assert [c["reason"] for c in cards[2:]] == ["peer", "peer"]
    assert cards[2]["symbol"] == "6488.TWO"  # 環球晶: the closest market cap (TSMC, the leader, is already shown)
    assert "富櫃五十指數成分股" in " ".join(out["sources"])


def test_misc_industry_uses_electronics_and_two_affiliates(client, stock_archive):
    cards = related(client, "2317.TW")["items"]
    assert [c["reason"] for c in cards] == ["benchmark", "affiliate", "affiliate", "peer"]
    assert {c["symbol"] for c in cards[1:3]} == {"2258.TW", "2328.TW"}
    assert all(c["reason_label"] == "鴻海是其法人董事及大股東" or c["reason_label"] == "鴻海是其大股東"
               for c in cards[1:3])
    assert cards[3]["reason_label"] == "電子類、市值相近"


def test_index_benchmark_is_an_index_card(client, stock_archive):
    r = client.patch(f"{API}/me/preferences", json={"benchmark": "^TAIEXTR"})
    assert r.status_code == 200, r.text
    cards = related(client, "2330.TW")["items"]
    bench = cards[0]
    assert (bench["symbol"], bench["is_index"], bench["reason_label"]) == (
        "^TAIEXTR", True, "你的比較基準（指數）")
    assert bench["name"] == "發行量加權股價報酬指數" and bench["notes"] == ["指數不能直接買賣"]


def test_etf_page_same_index_then_most_holders(client, stock_archive):
    out = related(client, "0050.TW")
    assert [(c["symbol"], c["reason"]) for c in out["items"]] == [
        ("006208.TW", "same_index"), ("0056.TW", "same_type"), ("00878.TW", "same_type"), ("00919.TW", "same_type")]
    assert out["items"][1]["reason_label"] == "同為國內股票型、受益人數多"
    # leveraged / inverse ETFs on the same index are another type
    assert "00631L.TW" not in {c["symbol"] for c in out["items"]}
    assert "〈有價證券集中保管個別股票異動月分析表－上市證券〉" in " ".join(out["sources"])


def test_us_and_unknown(client, stock_archive):
    us = related(client, "AAPL")
    assert us["items"] == [] and us["notes"]
    assert client.get(f"{API}/instruments/NOPE.TW/related").status_code == 404


def test_depositary_receipts_never_appear(client, stock_archive, engine):
    from sqlalchemy.orm import Session

    from forliosa.models import CompanyProfile

    with Session(engine) as db:
        mtk = db.get(CompanyProfile, "2454.TW")
        mtk.industry_code = "91"
        db.commit()
    cards = related(client, "2330.TW")["items"]
    assert "2454.TW" not in {c["symbol"] for c in cards}
