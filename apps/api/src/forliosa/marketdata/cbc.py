"""Parser for the central bank's open data: 中央銀行〈銀行間新臺幣對美元收盤匯率〉 (data.gov.tw dataset 7232,
政府資料開放授權條款第 1 版; the figures come from 台北外匯經紀公司).

Checked live on 2026-11-12 (a trimmed copy is ``tests/archive/fixtures/cbc_ftd_day_live_20261112.json``):

* ``GET https://cpx.cbc.gov.tw/api/OpenData/FTDOpenData_Day`` answers ``application/json`` (about 190 KB) with the
  **whole history in one array**, oldest first: ``[{"日期": "20080102", "NTD_USD": "32.443"}, …]`` — 4,686 business
  days from 2008-01-02 to 2026-11-12. The day's rate is published the same afternoon (2026-11-12's was there at
  17:12 Taipei). There are no query parameters, so every fetch is a full backfill.
* ``日期`` is Gregorian ``YYYYMMDD``; ``NTD_USD`` is TWD per 1 USD as a string with one to three decimals
  (``"32.86"``, ``"32.889"``). No missing values were seen.
* ``FTDOpenData_Month`` (key ``西元年月``) gives monthly averages; ``FTDOpenData_Year`` is documented as yearly
  averages but on 2026-11-12 returned the same monthly rows under the key ``西元年``. Neither is used.
* TAIFEX's 每日外幣參考匯率 USD/NTD column is the same number: all 27 days of the 2026-11-12 TAIFEX fixture
  (2026-10-01 … 2026-11-11) match this series exactly.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from forliosa.marketdata.base import ProviderUnavailable, parse_decimal, parse_tw_date

CBC_OPENDATA = "https://cpx.cbc.gov.tw/api/OpenData"
FX_DAY_URL = f"{CBC_OPENDATA}/FTDOpenData_Day"
SOURCE = "cbc-opendata"
FX_DATASET = f"{SOURCE}/fx"  # datapolicy.DATASETS key
PAIR = "USDTWD"


def parse_fx_day(rows: Any) -> list[dict[str, Any]]:
    """FTDOpenData_Day -> ``[{date, pair: "USDTWD", rate}]`` sorted by date (one row per day).

    Rows without a date or a positive rate are skipped. Every valid answer is the whole history since 2008, so an
    empty array (an upstream glitch) or one in which no row parses (the fields were renamed) raises
    :class:`ProviderUnavailable`: the archive job records an error instead of a 0-row success that would erase the
    dataset's last date.
    """
    if not isinstance(rows, list):
        raise ProviderUnavailable("中央銀行 FTDOpenData_Day 格式不符（不是陣列）")
    if not rows:
        raise ProviderUnavailable("中央銀行 FTDOpenData_Day 回應是空的（正常回應是 2008 年起的完整歷史）")
    out: dict[date, dict[str, Any]] = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        d = parse_tw_date(r.get("日期"))
        rate = parse_decimal(r.get("NTD_USD"))
        if d is None or rate is None or rate <= 0:
            continue
        out[d] = {"date": d, "pair": PAIR, "rate": rate}
    if not out:
        raise ProviderUnavailable("中央銀行 FTDOpenData_Day 欄位不符（找不到 日期／NTD_USD）")
    return [out[d] for d in sorted(out)]
