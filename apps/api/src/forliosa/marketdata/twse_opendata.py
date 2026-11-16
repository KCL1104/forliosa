"""TWSE's data.gov.tw download links: the same-day close (``www.twse.com.tw/exchangeReport/…?response=open_data``).

The OpenAPI copies of these datasets (``openapi.twse.com.tw``) are rebuilt once a night, around 05:20 the next
morning; the download links TWSE registered on data.gov.tw serve the same official data shortly after the close
(TWSE: 「收盤後約13:50」). Product owner 2026-11-16 (CLAUDE.md): only these two exact URLs, no date parameters, on
trading days from 13:45 at most every 10 minutes, stop once the day is in, stop on a redirect / 403 / 429 —
``forliosa.closes`` does the polling; this module only parses.

Format, read from the live files on 2026-11-16 15:00 Taipei (tests/marketdata/fixtures/*open_data_live_20261116.csv):

* ``text/csv;charset=utf-8``, no BOM, one header line, every value quoted, ``\\n`` line ends.
* ``Content-Disposition: attachment; filename="STOCK_DAY_ALL_20261116.csv"`` / ``"MI_INDEX_IND_20261116.csv"``.
* STOCK_DAY_ALL: ``日期,證券代號,證券名稱,成交股數,成交金額,開盤價,最高價,最低價,收盤價,漲跌價差,成交筆數`` — the
  OpenAPI JSON's ``Date, Code, Name, TradeVolume, TradeValue, OpeningPrice, HighestPrice, LowestPrice, ClosingPrice,
  Change, Transaction`` in the same order; ``日期`` is ROC (``1151116``) on every row. A security that did not trade
  has empty prices (and ``漲跌價差`` ``0.0000``).
* MI_INDEX (大盤統計, the index table): ``日期,指數/報酬指數,收盤指數,漲跌(+/-),漲跌點數,漲跌百分比(%),特殊處理註記``
  — the OpenAPI's ``日期, 指數, 收盤指數, 漲跌, 漲跌點數, 漲跌百分比, 特殊處理註記``; ``漲跌點數`` has thousands
  separators. A few 報酬指數 rows have no value yet in the afternoon file and carry the index name in the first column
  (``"臺灣50報酬指數","","","","",""``): they have no date and are skipped.

The data date is read from the file itself — every row's ``日期`` (all rows must agree) and the file name in
``Content-Disposition`` (when sent, it must agree too) — never from the clock: yesterday's file can never be stored
as today's (:func:`file_date`).
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Mapping
from datetime import date
from typing import Any

from forliosa.marketdata.base import ProviderUnavailable, parse_tw_date

STOCK_DAY_ALL_URL = "https://www.twse.com.tw/exchangeReport/STOCK_DAY_ALL?response=open_data"
MI_INDEX_URL = "https://www.twse.com.tw/exchangeReport/MI_INDEX?response=open_data"
SOURCE = "twse-opendata"  # prices_daily / index_daily rows from these two files (datapolicy: OGDL, data.gov.tw)
PRICE_DATASET = "twse-opendata/price"  # dataset_status: the newest session stored from STOCK_DAY_ALL
INDEX_DATASET = "twse-opendata/index"  # dataset_status: the newest session stored from MI_INDEX
ACCEPT_CSV = {"Accept": "text/csv, */*;q=0.1"}

# CSV header -> the OpenAPI field name its parser reads (forliosa.marketdata.twse / opendata).
STOCK_DAY_ALL_COLUMNS = {
    "日期": "Date", "證券代號": "Code", "證券名稱": "Name", "成交股數": "TradeVolume", "成交金額": "TradeValue",
    "開盤價": "OpeningPrice", "最高價": "HighestPrice", "最低價": "LowestPrice", "收盤價": "ClosingPrice",
    "漲跌價差": "Change", "成交筆數": "Transaction",
}
MI_INDEX_COLUMNS = {
    "日期": "日期", "指數/報酬指數": "指數", "收盤指數": "收盤指數", "漲跌(+/-)": "漲跌", "漲跌點數": "漲跌點數",
    "漲跌百分比(%)": "漲跌百分比", "特殊處理註記": "特殊處理註記",
}
_FILENAME_DATE = re.compile(r'filename\*?=[^;]*?(\d{8})\.csv', re.IGNORECASE)


def _rows(raw: bytes, columns: Mapping[str, str], what: str) -> list[dict[str, Any]]:
    """CSV -> rows keyed by the OpenAPI field names. A renamed or missing column raises before anything is stored."""
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ProviderUnavailable(f"證交所 {what} 不是 UTF-8 CSV") from exc
    reader = csv.reader(io.StringIO(text))
    header = [h.strip() for h in next(reader, [])]
    missing = [c for c in columns if c not in header]
    if missing:
        raise ProviderUnavailable(f"證交所 {what} 欄位不符（缺少 {'、'.join(missing)}）")
    index = {columns[h]: i for i, h in enumerate(header) if h in columns}
    out = []
    for values in reader:
        if not values or not any(v.strip() for v in values):
            continue
        out.append({key: (values[i].strip() if i < len(values) else "") for key, i in index.items()})
    return out


def stock_day_all_rows(raw: bytes) -> list[dict[str, Any]]:
    """STOCK_DAY_ALL CSV -> OpenAPI-shaped rows (``parse_stock_day_all`` / ``parse_listed_etfs`` read them)."""
    return _rows(raw, STOCK_DAY_ALL_COLUMNS, "個股日成交資訊")


def mi_index_rows(raw: bytes) -> list[dict[str, Any]]:
    """MI_INDEX CSV -> OpenAPI-shaped rows (``opendata.parse_mi_index`` reads them)."""
    return _rows(raw, MI_INDEX_COLUMNS, "每日收盤行情（大盤統計）")


def disposition_date(content_disposition: str | None) -> date | None:
    """``attachment; filename="STOCK_DAY_ALL_20261116.csv"`` -> 2026-11-16 (``None`` without a dated file name)."""
    found = _FILENAME_DATE.search(content_disposition or "")
    if not found:
        return None
    try:
        return date.fromisoformat(f"{found.group(1)[:4]}-{found.group(1)[4:6]}-{found.group(1)[6:]}")
    except ValueError:
        return None


def file_date(rows: list[dict[str, Any]], date_key: str, content_disposition: str | None = None) -> date:
    """The one trading day a file holds: every dated row must carry the same ``日期`` and the file name (when sent) the
    same date. Raises :class:`ProviderUnavailable` when the rows disagree, none is dated or the name says otherwise —
    the caller then stores nothing."""
    days = {d for d in (parse_tw_date(r.get(date_key)) for r in rows) if d is not None}
    if not days:
        raise ProviderUnavailable("證交所下載檔沒有日期")
    if len(days) > 1:
        raise ProviderUnavailable(f"證交所下載檔的日期不一致：{', '.join(sorted(d.isoformat() for d in days))}")
    day = days.pop()
    named = disposition_date(content_disposition)
    if named is not None and named != day:
        raise ProviderUnavailable(f"證交所下載檔的檔名日期 {named} 和內容 {day} 不同")
    return day
