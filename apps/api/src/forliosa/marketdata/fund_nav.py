"""Parser for 金融監督管理委員會證券期貨局〈證券投資信託基金每日淨值〉 (data.gov.tw dataset 11109, 政府資料開放授權條款
第 1 版, updated daily). The dataset's only resource is a CSV hosted by SITCA (中華民國證券投資信託暨顧問商業同業公會).

Checked live on 2026-11-12 (a trimmed copy is ``tests/archive/fixtures/sitca_nav_live_20261112.csv``):

* ``GET https://www.sitca.org.tw/MemberK0000/F/03/nav.csv`` answers ``application/octet-stream``: UTF-8 with a BOM,
  CRLF line ends, no quoting, about 500 KB and 3,676 rows — **one row per fund (share class), the latest NAV only**.
  The file was regenerated at 20:19 and again at 22:01 Taipei that evening.
* Columns: 日期, 會員代號, 公司名稱, 基金統編, 基金代號, 基金名稱, 基金淨值, 漲跌, 漲跌幅, 類型代號, 幣別, 受益憑證代號.
  ``日期`` is Gregorian ``YYYYMMDD``. Funds valued on overseas markets carry the **previous business day** (on
  2026-11-12: 3,183 rows dated 2026-11-11, 493 dated 2026-11-12; 00679B, 00720B are dated 2026-11-11).
* ``受益憑證代號`` is filled on every row. For ETFs it is the exchange trading code (0050, 006208, 00878, 00981A,
  00679B, 00632R …: ``00`` + 2–4 digits + an optional letter); other funds have codes such as ``T0102Y``.
  244 rows had an ETF code, none twice, all in TWD (類型代號 AH11 domestic equity ETF, AH13 leveraged / inverse,
  AH21–AH25 overseas, AL11 / AL21 active ETFs).
* ``基金淨值`` is ``-`` for share classes without a NAV that day (172 rows, none of them ETFs).
* Coverage (compared with the exchanges' close files that evening): 214 of 246 TWSE-listed ``00`` codes and 27 of 118
  TPEx-listed ones have a row. Missing: futures ETFs (``…U``, 期貨信託基金), foreign-currency trading lines (``…K``) and
  most OTC bond ETFs (00687B, 00694B …) — those simply have no NAV here.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import date
from decimal import Decimal
from typing import Any

from forliosa.marketdata.base import ProviderUnavailable, parse_decimal, parse_tw_date

NAV_URL = "https://www.sitca.org.tw/MemberK0000/F/03/nav.csv"
SOURCE = "sfb-opendata"  # 金融監督管理委員會證券期貨局 (datapolicy source key)
NAV_DATASET = f"{SOURCE}/nav"  # datapolicy.DATASETS key
ETF_CODE = re.compile(r"^00\d{2,4}[A-Z]?$")  # Taiwan ETF trading codes (stocks are 1101–9999, ETNs 02…, REITs 01…)

COLUMNS = ("日期", "基金名稱", "基金淨值", "幣別", "受益憑證代號")


def is_etf_code(code: str) -> bool:
    return bool(ETF_CODE.match(code.strip().upper()))


def parse_nav_csv(raw: bytes) -> list[dict[str, Any]]:
    """nav.csv -> ``[{code, date, nav, currency, fund_name}]`` for rows with an ETF trading code and a positive NAV.

    Other funds (``T0102Y`` …) and rows whose NAV is ``-`` are skipped. A missing column (renamed upstream), an empty
    file or one without a single parseable ETF row raises :class:`ProviderUnavailable`, so the archive job records an
    error instead of a 0-row success that would leave ``dataset_status`` looking current.
    A code listed twice keeps its newest date (never seen on 2026-11-12).
    """
    text = raw.decode("utf-8-sig", errors="replace")
    if not text.strip():
        raise ProviderUnavailable("〈證券投資信託基金每日淨值〉回應是空的")
    reader = csv.DictReader(io.StringIO(text))
    fields = {(f or "").strip() for f in reader.fieldnames or []}
    missing = [c for c in COLUMNS if c not in fields]
    if missing:
        raise ProviderUnavailable(f"〈證券投資信託基金每日淨值〉欄位不符（找不到 {'、'.join(missing)}）")
    out: dict[str, dict[str, Any]] = {}
    for row in reader:
        r = {(k or "").strip(): (v or "").strip() for k, v in row.items() if isinstance(v, str)}
        code = r.get("受益憑證代號", "").upper()
        if not is_etf_code(code):
            continue
        d: date | None = parse_tw_date(r.get("日期"))
        nav: Decimal | None = parse_decimal(r.get("基金淨值"))
        if d is None or nav is None or nav <= 0:
            continue
        currency = r.get("幣別", "").upper()
        item = {"code": code, "date": d, "nav": nav,
                "currency": currency if re.fullmatch(r"[A-Z]{3}", currency) else None,
                "fund_name": r.get("基金名稱", "")[:200]}
        old = out.get(code)
        if old is None or d > old["date"]:
            out[code] = item
    if not out:
        raise ProviderUnavailable("〈證券投資信託基金每日淨值〉沒有任何 ETF 的淨值（受益憑證代號或淨值欄位可能改了）")
    return sorted(out.values(), key=lambda x: x["code"])
