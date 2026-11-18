"""A small archived market for the market-report tests (made-up numbers): two Taiwan sessions, Friday 2026-11-13 and
Monday 2026-11-16, with listed and OTC closes, reference prices, issued shares, indices and sector indices, TAIFEX
positions, the central bank's USD/TWD, Databento ETF closes, FMTQIK and a few announcements."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal as D

import pytest
from sqlalchemy.orm import Session

from forliosa.config import get_settings
from forliosa.models import (
    CompanyProfile,
    FxRate,
    IndexDaily,
    InstitutionalDaily,
    MarketEvent,
    MarketTurnoverDaily,
    PriceDaily,
    ReferencePrice,
    TaifexInstitutional,
    TaifexPutCallRatio,
)
from forliosa.timeutil import TAIPEI

FRI, MON, TUE = date(2026, 11, 13), date(2026, 11, 16), date(2026, 11, 17)

# code: (name, industry code, shares, Friday close, Monday close, Monday value NT$)
TWSE = {
    "2330": ("台積電", "24", 25_932_000_000, "1500", "1430", 120_000_000_000),
    "2454": ("聯發科", "24", 1_600_000_000, "1500", "1440", 30_000_000_000),
    "2317": ("鴻海", "31", 13_900_000_000, "220", "210", 25_000_000_000),
    "2308": ("台達電", "28", 2_600_000_000, "900", "860", 9_000_000_000),
    "1802": ("台玻", "08", 2_900_000_000, "30", "27", 4_000_000_000),  # limit down
    "1101": ("台泥", "01", 7_000_000_000, "25", "25.5", 1_000_000_000),
    "2881": ("富邦金", "17", 13_000_000_000, "90", "91", 6_000_000_000),
    "6669": ("緯穎", "25", 180_000_000, "3000", "3100", 8_000_000_000),
    "3008": ("大立光", "26", 134_000_000, "2500", "2400", 3_000_000_000),
    "4743": ("合一-創", "22", 400_000_000, "100", "110", 2_000_000_000),  # innovation board
    "2455": ("全新", "27", 200_000_000, "50", "55", 1_500_000_000),  # under disposition
    "1213": ("大飲", "02", 100_000_000, "10", "11", 10_000_000),  # altered trading
    "9110": ("越南控-DR", "91", 500_000_000, "2", "2.1", 1_000_000),  # a depositary receipt: not a common stock
}
ETFS = {"0050": ("元大台灣50", "60", "57", 20_000_000_000), "01007T": ("兆豐國泰R2", "10", "10", 1_000_000)}
TPEX = {"6488": ("環球晶", "24", 478_000_000, "400", "380", 2_000_000_000),
        "8069": ("元太", "26", 1_140_000_000, "300", "310", 3_000_000_000),
        "5347": ("世界", "24", 1_640_000_000, "90", "88", 1_000_000_000)}
SECTORS_MON = {"半導體": "-0.0450", "玻璃陶瓷": "-0.0950", "水泥": "0.0200", "金融保險": "0.0110",
               "其他電子": "-0.0455", "電子零組件": "-0.0444", "電腦及週邊設備": "0.0333", "光電": "-0.0400",
               "通信網路": "0.0100", "電子工業": "-0.0420", "機電": "-0.0300"}
# the size and style indices of MI_INDEX (G15; 電子工業 and 金融保險 are above)
STYLE_MON = {"臺灣50指數": "-0.0580", "臺灣中型100指數": "-0.0400", "小型股300指數": "-0.0300",
             "未含電子指數": "-0.0150", "臺灣高股息指數": "-0.0200"}


def ts(d: date, hh: int, mm: int = 0) -> datetime:
    return datetime(d.year, d.month, d.day, hh, mm, tzinfo=TAIPEI)


def seed_market(db: Session) -> None:
    for code, (name, ind, shares, fri, mon, value) in TWSE.items():
        sym = f"{code}.TW"
        db.add(CompanyProfile(symbol=sym, date=FRI, industry_code=ind, industry=None, shares_outstanding=shares,
                              values={"short_name": name, "chairman": "不該出現的名字"}, source="twse-openapi"))
        db.add(PriceDaily(symbol=sym, date=FRI, close=D(fri), volume=1_000_000, value=value, source="twse-openapi"))
        db.add(PriceDaily(symbol=sym, date=MON, close=D(mon), volume=1_000_000, value=value, source="twse-opendata"))
        limit_down = D(fri) * D("0.9")
        db.add(ReferencePrice(symbol=sym, date=MON, reference_price=D(fri), limit_up=D(fri) * D("1.1"),
                              limit_down=limit_down.quantize(D("0.05")) if code == "1802" else limit_down,
                              source="twse-openapi"))
    for code, (name, fri, mon, value) in ETFS.items():
        sym = f"{code}.TW"
        db.add(CompanyProfile(symbol=sym, date=FRI, industry_code=None, industry=None, shares_outstanding=None,
                              values={"short_name": name}, source="twse-openapi"))
        db.add(PriceDaily(symbol=sym, date=FRI, close=D(fri), volume=1_000, value=value, source="twse-openapi"))
        db.add(PriceDaily(symbol=sym, date=MON, close=D(mon), volume=1_000, value=value, source="twse-opendata"))
    for code, (name, ind, shares, fri, mon, value) in TPEX.items():
        sym = f"{code}.TWO"
        db.add(CompanyProfile(symbol=sym, date=FRI, industry_code=ind, industry=None, shares_outstanding=shares,
                              values={"short_name": name}, source="tpex-openapi"))
        db.add(PriceDaily(symbol=sym, date=FRI, close=D(fri), volume=1_000, value=value, source="tpex-openapi"))
        db.add(PriceDaily(symbol=sym, date=MON, close=D(mon), volume=1_000, value=value, source="tpex-openapi"))
        db.add(InstitutionalDaily(symbol=sym, date=MON, foreign_net=1_000_000, trust_net=-200_000,
                                  dealer_net=-100_000, total_net=700_000, source="tpex-openapi"))
    # indices
    for d, close, change, pct in ((FRI, "43675.12", "-100.00", "0.0023"), (MON, "41040.08", "-2635.04", "0.0603")):
        db.add(IndexDaily(name="發行量加權股價指數", date=d, market="TWSE", close=D(close), change=D(change),
                          change_pct=D(pct), source="twse-openapi" if d == FRI else "twse-opendata"))
    db.add(IndexDaily(name="發行量加權股價報酬指數", date=MON, market="TWSE", close=D("94901.06"), change=D("-6000"),
                      change_pct=D("0.0603"), source="twse-opendata"))
    for d, close in ((FRI, "342.41"), (MON, "319.12")):
        db.add(IndexDaily(name="櫃買指數", date=d, market="TPEX", close=D(close), source="tpex-openapi",
                          change=D("-23.29") if d == MON else None))
    for name, pct in SECTORS_MON.items():
        p = D(pct)
        db.add(IndexDaily(name=f"{name}類指數", date=MON, market="TWSE", close=D("100") * (1 + p), change=D("100") * p,
                          change_pct=abs(p), source="twse-opendata"))
        db.add(IndexDaily(name=f"{name}類指數", date=FRI, market="TWSE", close=D("100"), change=D("0"),
                          change_pct=D("0"), source="twse-openapi"))
    for name, pct in STYLE_MON.items():
        p = D(pct)
        db.add(IndexDaily(name=name, date=MON, market="TWSE", close=D("100") * (1 + p), change=D("100") * p,
                          change_pct=abs(p), source="twse-opendata"))
        db.add(IndexDaily(name=name, date=FRI, market="TWSE", close=D("100"), change=D("0"), change_pct=D("0"),
                          source="twse-openapi"))
    db.add(IndexDaily(name="半導體類報酬指數", date=MON, market="TWSE", close=D("200"), change=D("-9"),
                      change_pct=D("0.045"), source="twse-opendata"))
    # TAIFEX positions, P/C, USD/TWD
    for d, oi in ((FRI, -90_000), (MON, -96_787)):
        db.add(TaifexInstitutional(trade_date=d, scope="futures", contract_name="臺股期貨", call_put="",
                                   investor="外資及陸資", contract_code="TX", oi_net=oi, source="taifex-openapi"))
    db.add(TaifexPutCallRatio(trade_date=MON, oi_ratio=D("0.5379"), volume_ratio=D("0.8101"), source="taifex-openapi"))
    db.add(FxRate(pair="USDTWD", date=FRI, rate=D("32.838"), source="cbc-opendata"))
    db.add(FxRate(pair="USDTWD", date=MON, rate=D("32.886"), source="cbc-opendata"))
    # Databento closes (the US sessions of Thursday, Friday and Monday)
    for sym, closes in (("SPY", ("690", "700", "703.5")), ("SMH", ("300", "310", "302")),
                        ("TSM", ("290", "300", "297")), ("DIA", ("470", "471", "470")),
                        ("ONEQ", ("88", "89", "90"))):
        for d, c in zip((date(2026, 11, 12), FRI, MON), closes, strict=True):
            db.add(PriceDaily(symbol=sym, date=d, close=D(c), volume=1000, source="databento-equs"))
    # FMTQIK (official turnover) of Monday: out the next morning
    db.add(MarketTurnoverDaily(date=MON, market="TWSE", trade_value=903_115_129_889, taiex=D("41040.08"),
                               source="twse-openapi"))
    # announcements
    created = datetime(2026, 11, 10, 1, 0, tzinfo=UTC)
    db.add_all([
        MarketEvent(key="disp-2455", symbol="2455.TW", date=date(2026, 11, 11), end_date=date(2026, 11, 17),
                    type="disposition", title="處置股票（第一次處置）", data={}, source="twse-openapi",
                    created_at=created),
        MarketEvent(key="alt-1213", symbol="1213.TW", date=TUE, end_date=None, type="altered_trading",
                    title="變更交易", data={"backlog": True}, source="twse-openapi", created_at=created),
        MarketEvent(key="mi-2330", symbol="2330.TW", date=MON, type="material_info", title="公告本公司董事會決議事項",
                    data={"time": "143005"}, source="twse-openapi",
                    created_at=datetime(2026, 11, 16, 6, 35, tzinfo=UTC)),
        MarketEvent(key="mi-late", symbol="2317.TW", date=MON, type="material_info", title="晚上的公告",
                    data={"time": "173005"}, source="twse-openapi",
                    created_at=datetime(2026, 11, 16, 9, 35, tzinfo=UTC)),
        MarketEvent(key="conf-2317", symbol="2317.TW", date=date(2026, 11, 10), type="material_info",
                    title="本公司受邀參加法人說明會", detail="召開法人說明會之日期：115/11/17",
                    data={"clause": "第12款", "fact_date": "2026-11-17"}, source="twse-openapi", created_at=created),
        MarketEvent(key="ex-0050", symbol="0050.TW", date=TUE, type="ex_dividend", title="除息", data={},
                    source="twse-openapi", created_at=created),
        MarketEvent(key="ex-01007T", symbol="01007T.TW", date=TUE, type="ex_dividend", title="除息", data={},
                    source="twse-openapi", created_at=created),
        MarketEvent(key="ex-2881", symbol="2881.TW", date=TUE, type="ex_dividend", title="除息", data={},
                    source="twse-openapi", created_at=created),
        MarketEvent(key="mi-bond", symbol="24552.TWO", date=MON, end_date=TUE, type="disposition", title="處置",
                    data={}, source="tpex-openapi", created_at=created),
    ])
    db.commit()


@pytest.fixture()
def db(engine):
    with Session(engine) as s:
        yield s


@pytest.fixture()
def market_db(db):
    seed_market(db)
    return db


@pytest.fixture()
def us_on(monkeypatch):
    monkeypatch.setenv("US_PRICE_SOURCE", "databento")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
