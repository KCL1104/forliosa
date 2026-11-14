"""Read actual release dates out of archived 重大訊息 (material information).

Patterns were taken from the live TWSE ``t187ap04_L`` / TPEx ``mopsfin_t187ap04_O`` responses of 2026-11-12:

* **Financial report** (``earnings``): 符合條款 第31款 — 「公告本公司董事會通過115年第三季合併財務報告」. The 說明
  carries 「財務報告或年度自結財務資訊報導期間 起訖日期(XXX/XX/XX~XXX/XX/XX): 115/01/01~115/09/30」, which gives
  the period; titles alone use 「115年第3季」「一百一十五年第三季」「115年度第三季」「114年度」(annual = Q4).
  The announcement date (發言日期) is the day the board approved and published the report.
* **Investor conference** (``investor_conference``, 法說會): 第12款 — titles vary (「公告本公司召開法人說明會」,
  「本公司受邀參加Daiwa Investment Conference Singapore 2026」); 事實發生日 and 「召開法人說明會之日期：115/11/23」
  are the conference date (a range 「115/11/12 ~ 115/11/13」 starts on its first day).
* **Monthly revenue** (``revenue_release``): 「公告本公司115年10月合併營收情形」 (第53款).

Corrections (「更正…」) never count as a release: the original announcement is the release date.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from forliosa.marketdata.base import parse_tw_date

EARNINGS_CLAUSE = "31"
CONFERENCE_CLAUSE = "12"
REPORT_WORDS = ("財務報告", "財報", "財務報表")
CONFERENCE_WORDS = ("法人說明會", "法說會", "投資人說明會", "業績發表會")
_CN_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_ROC_DATE = r"(\d{2,3})\s*/\s*(\d{1,2})\s*/\s*(\d{1,2})"
# ROC year (115, 一百一十五) or a Gregorian year (2026: KY companies often write those). The lookbehind keeps the "026"
# inside "2026" from being read as ROC year 26 (= 1937; 2026-11-14 review).
_YEAR = r"(?<![0-9])([0-9]{4}|[0-9]{2,3}|[一二三四五六七八九十百〇零]+)"


@dataclass(frozen=True)
class Release:
    kind: str  # earnings | investor_conference | revenue_release
    date: date  # earnings / revenue: announcement date; conference: the conference date
    period: str | None  # "2026Q3" | "2026-10" | None


def _clause(value: str | None) -> str:
    m = re.search(r"\d+", value or "")
    return m.group(0) if m else ""


def cn_number(text: str) -> int | None:
    """'115' / '一百一十五' / '十二' -> int (up to 999)."""
    text = text.strip()
    if text.isdigit():
        return int(text)
    total, current = 0, 0
    for ch in text:
        if ch in _CN_DIGITS:
            current = _CN_DIGITS[ch]
        elif ch == "十":
            total += (current or 1) * 10
            current = 0
        elif ch == "百":
            total += (current or 1) * 100
            current = 0
        else:
            return None
    total += current
    return total or None


def _year(token: str) -> int | None:
    """A year in a title: four digits are Gregorian (2026), anything shorter is ROC (115 → 2026)."""
    n = cn_number(token)
    if not n:
        return None
    return n if n >= 1912 else n + 1911


def report_period(title: str, detail: str, announced: date) -> str | None:
    """The quarter a financial-report announcement is about ("2026Q3")."""
    m = re.search(rf"{_ROC_DATE}\s*[~～]\s*{_ROC_DATE}", detail or "")
    if m:  # reporting period "115/01/01~115/09/30": the quarter of its end date
        try:
            end = date(int(m.group(4)) + 1911, int(m.group(5)), int(m.group(6)))
            return f"{end.year}Q{(end.month - 1) // 3 + 1}"
        except ValueError:
            pass
    quarter_words = {"一": 1, "二": 2, "三": 3, "四": 4, "1": 1, "2": 2, "3": 3, "4": 4}
    m = re.search(rf"{_YEAR}\s*年度?\s*(?:第\s*([一二三四1-4])\s*季|(上半年))", title)
    if m:
        year = _year(m.group(1))
        q = 2 if m.group(3) else quarter_words[m.group(2)]
        return f"{year}Q{q}" if year else None
    m = re.search(rf"{_YEAR}\s*年度", title)
    if m and "季" not in title and (year := _year(m.group(1))):
        return f"{year}Q4"  # 年度財務報告
    m = re.search(r"第\s*([一二三四1-4])\s*季", title)
    if m:  # no year: the latest such quarter that ended before the announcement
        q = quarter_words[m.group(1)]
        year = announced.year if (q - 1) * 3 + 3 < announced.month else announced.year - 1
        return f"{year}Q{q}"
    return None


def revenue_period(title: str) -> str | None:
    m = re.search(rf"{_YEAR}\s*年\s*([0-9]{{1,2}}|[一二三四五六七八九十]+)\s*月份?", title)
    if not m:
        return None
    year, month = _year(m.group(1)), cn_number(m.group(2))
    if not year or not month or not 1 <= month <= 12:
        return None
    return f"{year}-{month:02d}"


def conference_date(detail: str, fact_date: str | None, announced: date) -> date:
    if fact_date:
        try:
            return date.fromisoformat(fact_date)
        except ValueError:
            pass
    for label in ("召開法人說明會之日期", "事實發生日"):
        m = re.search(rf"{label}\s*[:：]\s*{_ROC_DATE}", detail or "")
        if m:
            d = parse_tw_date(f"{m.group(1)}/{m.group(2)}/{m.group(3)}")
            if d is not None:
                return d
    return announced


def classify(title: str, detail: str, data: dict | None, announced: date) -> Release | None:
    """A material-information row -> the release it announces, or ``None`` for anything else."""
    data = data or {}
    clause = _clause(data.get("clause"))
    if "更正" in title:
        return None
    if clause == CONFERENCE_CLAUSE or any(w in title for w in CONFERENCE_WORDS):
        return Release("investor_conference", conference_date(detail, data.get("fact_date"), announced), None)
    is_report = any(w in title for w in REPORT_WORDS) and any(w in title for w in ("董事會", "通過", "承認"))
    if (clause == EARNINGS_CLAUSE or is_report) and "自結" not in title:
        return Release("earnings", announced, report_period(title, detail, announced))
    if ("營收" in title or "營業收入" in title) and (period := revenue_period(title)):
        return Release("revenue_release", announced, period)
    return None
