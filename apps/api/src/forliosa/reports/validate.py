"""Rule checks of the writer's JSON (contract §10): every sentence against the data pack it was written from.

``validate(output, pack, kind, names)`` returns :class:`Problem` s (``path`` like ``what_happened[1].sentences[0]``,
``code``, ``detail``, ``hard``). Hard problems lead to one revision, then to dropping the section (:func:`drop`);
soft ones are counted (and :func:`tidy` trims what can be trimmed: extra items, unknown sector names).

The checks, in short: refs exist (F / C / N / W in the pack, X among the verified reports); every number matches a
fact the sentence cites (display or value, rounded to the text's decimals; 億 / 兆 / 萬 scaled) **and** the fact's
subject is named next to it (``number_subject_mismatch``: 外資 and 自營商 swapped); a point contribution (Forliosa's
estimate) is marked as one, 「約」 before it or 「估算」 in the sentence (``estimate_unmarked``); the direction (▲ /
漲 / 買超 …) agrees with a signed fact; dates come from the pack or the refs; a weekday matches its date and never
stands alone; no forbidden or time word; only listed stocks and allowed sectors (半導體 with its concentration in the
same paragraph); no fund flow and price move of a stock in one sentence; causes need a report (X / W); forward-looking
sentences take one of the three shapes; position numbers are never a reason; the premarket's headline and its evening
notes do not repeat the previous session; no index points; the chart of the day is on the menu; every watch / tonight
item is an event of the calendar or a report (``item_not_event``); no sentence about what the edition lacks
(``internal_gap``: the page shows missing data itself); no US local time left without its Taipei time; no private-life
detail, whoever reported it (``private_life``); the chips hold institutional investors and fund flows only
(``chips_off_topic``); the weekly uses a calendar row or a report once per section of highlights, this week, themes
and risks (``repeated_fact``), and its risks are still ahead (``risk_not_ahead``); the premarket's and the close's
highlights are the brief's rows (2026-11-27): each names its field (``slot_invalid``), once (``slot_repeated``), 為什麼
and the close's 籌碼 stand on a report (``slot_needs_report``), 貢獻 on a fact (``slot_needs_fact``), every 排定
sentence on a calendar row or a report (``slot_not_event``) — a row that fails goes alone, the others stay.

:func:`drop` takes out what still fails after the revision: given the pack, one sentence (or one item) at a time,
the rest checked again; a section goes as a whole only when what is left still fails.
"""

from __future__ import annotations

import contextlib
import copy
import re
import unicodedata
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from forliosa.reports.calendars import US_LOCAL_TIME, converted_spans, us_times_to_taipei
from forliosa.reports.marketcalc import SECTOR_NAMES
from forliosa.reports.pack import OPTION_METRICS
from forliosa.reports.prompts import (
    BRIEF_ROW_MAX,
    BRIEF_SLOTS,
    COUNTS,
    FORBIDDEN_WORDS,
    LENGTHS,
    OUTPUT_KEYS,
    STYLE_WORDS,
    TIME_WORDS,
)
from forliosa.timeutil import TAIPEI

# Index points (美股指數、台指期、夜盤) never appear, in a gathered report or a sentence (§8.5 item 7, §10.2 item 21):
# any number of points whose closest name before it, in the same sentence, is one of these (any number of digits,
# any distance). The Taiwan names (加權、櫃買 …) take the points after them: those come from the server's data.
POINTS_BANNED = ("道瓊", "Dow", "標準普爾", "標普", "S&P", "那斯達克", "納斯達克", "Nasdaq", "那指", "納指",
                 "費城半導體", "費半", "羅素", "Russell", "VIX", "台指期", "台指", "期指", "小台", "微台", "夜盤")
POINTS_OK = ("加權報酬指數", "加權指數", "加權", "櫃買指數", "櫃買", "大盤", "台股", "集中市場", "上櫃", "類指數",
             "TAIEX", "點數貢獻", "貢獻")
_POINT_NAMES = re.compile("|".join(re.escape(n) for n in sorted((*POINTS_BANNED, *POINTS_OK), key=len,
                                                                 reverse=True)), re.IGNORECASE)
_BANNED_LOWER = {n.lower() for n in POINTS_BANNED}
_POINTS_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?\s*點")
_SENTENCE_END = re.compile(r"[。；;！？!?\n]")
CAUSE = re.compile(r"因為|由於|帶動|拖累|受.{0,10}影響|主因|導致|受惠|受累|推升|壓抑")
OUTLOOK = re.compile(r"將(?!近|軍)|預計|預期|預估|可能|恐(?!慌)|展望|料將|估計|後續|接下來|未來")
# A direction or a view of what comes next (a forward-looking sentence never holds one, whoever said it)
FORECAST = re.compile(r"走高|走低|走揚|走強|走弱|上攻|回檔|回落|漲勢|跌勢|反彈|續漲|續跌|上漲空間|下跌空間"
                      r"|震盪|樂觀|悲觀|可望|有望|看好|看淡|看多|看空|偏多|偏空|轉強|轉弱|止跌|築底|觸底|見頂"
                      r"|多頭|空頭")
VIEW = re.compile(r"可望|有望|看好|看淡|看多|看空|偏多|偏空|樂觀|悲觀|利空出盡|利多出盡")
# A sentence about what this edition lacks (data not open, not licensed, not found): the page shows missing data
# with its own empty states, so the text never says it (dry run 11/17: 「美股收盤價資料這份未開放」 would be daily).
# In the edition's own voice (這份、資料包、授權未確認、未找到報導…): always a gap.
GAP_EDITION = re.compile(
    r"資料包|(?:這|本)份(?:報告)?(?:未|沒|不)|授權(?:未|還沒|尚未|沒有)確認|需要授權|(?:這裡|這段|本段)只(?:引用|列|寫)"
    r"|(?:未|沒有?|找不到|查無)(?:找到|查到)?(?:相關的?)?(?:報導|新聞)"
    r"|(?:未|沒有?)(?:找到|查到)(?:相關的?)?消息|找不到(?:相關的?)?消息")
# Words a named source may also say (「〔鉅亨網〕報導，該公司官方尚未公布投資金額」「主管機關表示尚無相關資料」): a gap
# unless a report the sentence cites (X / W) says something of the kind too
GAP_SOURCED = re.compile(
    r"(?:沒有|未|尚未|還沒|不)開放|(?<!大)(?:暫不|不|未)列(?!入|為|出|於|顛|管|席|車|表|舉|印|隊)"
    r"|(?:未|尚未|沒有|還沒)取得(?:可引用的|相關的?)?(?:資料|數據|報導|消息|行情)|(?:沒有|無|缺少?)(?:相關的?)?資料"
    r"|資料(?:不足|缺)|(?:官方|證交所|櫃買中心|期交所|數字)[^，。；,;]{0,6}(?:尚未|還沒|未)(?:公布|發布)")
GAP = re.compile(f"{GAP_EDITION.pattern}|{GAP_SOURCED.pattern}")
# The fixed sentences the spec asks for where the page has a slot for them (contract §9.3)
GAP_ALLOWED = {"stocks": ("未找到報導",), "stocks_week": ("未找到報導",), "last_week_review": ("未找到報導",),
               "chips": ("上市三大法人尚未取得可引用的報導",)}
# Reports about companies abroad: a two-character name in them may be written as the report has it (三星 is Samsung
# there, not the listed 三星; the writer would otherwise avoid the name). Never a theme's report (its 概念股 are Taiwan
# stocks), never a longer Taiwan name.
NAMED_KEYS = ("CO.", "US.", "ADR.")
FLOW = re.compile(r"買賣超|買超|賣超|淨買|淨賣|持股增減")
P1 = re.compile(r"^已排定[：:]")
P2 = re.compile(r"^〔([^〕]{2,12})〕\s*報導[，,\s]*市場關注")  # the only approved shape: 〔媒體〕報導市場關注…
P3 = re.compile(r"^這件事和.{1,20}類股的關係是")
# Two-character names (鴻海、廣達) are checked only next to a stock's context: many are also plain words
TWO_CHAR_COMMON = frozenset({"統一", "大同", "中華", "台灣", "全新", "國產", "創意", "巨大", "聯合", "精華", "亞太",
                             "全家", "大量", "新興", "國際", "美國", "日本", "中國", "香港", "上海", "世界", "信義",
                             "正道", "大成", "台開", "一詮", "新光", "台火", "東陽", "南港", "永豐", "華南", "第一",
                             "合庫"})
# Plain words that hold a two-character stock name (東南亞 holds 南亞): blanked before the check
PLAIN_PHRASES = ("東南亞", "南亞洲", "中華民國", "台灣地區")
STOCK_CONTEXT = re.compile(r"股|漲|跌|%|法說|除息|除權|營收|[（(]\d|點數|收盤|收在|買超|賣超|帶動|拖累|權值|市值|成交"
                           r"|ADR|財報|EPS|獲利")
# Private life (owner 2026-11-17, N5 option A): an affair, a relationship, health or family is never written, even when
# a named outlet reported it — only the business fact (「黃仁勳辭去輝達執行長」, not 「傳出婚外情後辭去…」).
# These words are always someone's private life:
PRIVATE_LIFE = re.compile(
    r"婚外情|外遇|緋聞|劈腿|不倫|小三|情婦|情夫|戀情|戀愛|交往對象|女友|男友|性醜聞|感情(?:生活|糾紛|問題|狀況|風波)"
    r"|私生活|私人生活|私事|婚變|病情|病況|病倒|家務事|家暴|家庭因素|家庭(?:糾紛|問題|狀況)"
    r"|(?<!財務)(?<!營運)(?<!體質)健康(?:狀況|因素|問題|欠佳|亮紅燈)|身體(?:狀況|不適|因素|微恙)"
    r"|妻子|太太|丈夫|老公|老婆|前妻|前夫|兒子|女兒")
# These are someone's private life unless their clause is about a business or the economy (「住院醫療險」「就醫人次」
# 「結婚率」「配偶扣除額」「收案對象為罹患肥胖症的患者」: :data:`NOT_PRIVATE`)
PRIVATE_IF_PERSONAL = re.compile(r"罹患|罹癌|住院|就醫|開刀|動手術|離婚|再婚|結婚|訂婚|婚姻|懷孕|配偶|子女")
NOT_PRIVATE = re.compile(r"患者|病患|病人|族群|人數|人次|新藥|藥證|藥物|臨床|適應症|收案|試驗|醫療險|保險|壽險"
                         r"|保單|理賠|給付|健保|醫材|醫療院所|市場|產業|商機|扣除額|免稅額|稅|[婚院醫孕育]率|對數|登記|津貼|補助"
                         r"|開刀房|手術房|設備|需求|件數|少子化|人口")
_PRIVATE_CLAUSE = re.compile(r"[，,；;。！？!?\n]")


def private_life(text: str) -> str | None:
    """The private-life detail ``text`` writes (:data:`PRIVATE_LIFE`, or :data:`PRIVATE_IF_PERSONAL` in a clause
    without :data:`NOT_PRIVATE`); ``None`` when it writes none."""
    if (m := PRIVATE_LIFE.search(text)) is not None:
        return m.group(0)
    for clause in _PRIVATE_CLAUSE.split(text):
        if (m := PRIVATE_IF_PERSONAL.search(clause)) is not None and not NOT_PRIVATE.search(clause):
            return m.group(0)
    return None


# The weekly's sections where one calendar row or report is used once at most (N3: one fact repeated in the
# highlights, this week and three themes); the unit is an item (a highlight, a theme, a risk) or a summary sentence
ONCE_PER_SECTION = ("highlights", "summary", "themes", "risks")
# A report that speaks of what is still ahead or pending (the weekly's risks list only those, N3)
AHEAD = re.compile(r"將(?!近|軍)|預計|預定|排定|即將|仍待|待(?:審|議|表決|決定|公布|裁決|批准)|審議|審理中|研議"
                   r"|擬(?!定)|可能|恐(?!慌)|若(?!干)|是否|屆時|下週|下周|下個?月|明年|年底前|月底前|考驗|計畫於"
                   r"|規劃於|訂於|訂在")
# The chips section is about institutional investors and fund flows only (N3): no exchange rate, no settlement day
CHIPS_KEYS = ("chips", "chips_week")
CHIPS_OFF_METRICS = frozenset({"fx_close", "fx_change", "pc_ratio_oi", "pc_ratio_vol"})
CHIPS_OFF = re.compile(r"匯率|兌新台幣|新台幣兌|美元兌|升值|貶值|結算日|結算價|最後結算|P\s*/\s*C|賣權買權比"
                       r"|未平倉比(?:率|值)?(?![前上較])")


def index_points(text: str) -> str | None:
    """The first points figure of a US index, the TAIEX futures or the night session in ``text`` (else ``None``)."""
    t = normalize(text)
    for sent in _SENTENCE_END.split(t):
        names = [(m.start(), m.group(0).lower()) for m in _POINT_NAMES.finditer(sent)]
        if not names:
            continue
        for m in _POINTS_NUM.finditer(sent):
            before = [n for pos, n in names if pos < m.start()]
            if before and before[-1] in _BANNED_LOWER:
                start = max(pos for pos, n in names if pos < m.start())
                return sent[start:m.end()]
    return None
WEEKDAYS = "一二三四五六日"
SIGNED_METRICS = frozenset({
    "index_change", "index_pct", "tr_pct", "otc_change", "otc_pct", "sector_pct", "stock_pct", "stock_contrib",
    "us_pct", "futures_oi_change", "week_pct", "week_points", "mcap_change_est", "reference_pct", "otc_inst_total",
    "otc_inst_foreign", "otc_inst_trust", "otc_inst_dealer", "sector_contrib_est", "index_range_pct", "style_pct",
})
# Point contributions are Forliosa's estimates, never official numbers: a sentence citing one writes 「約」 before it or
# 「估算」 somewhere in it (the prompts ask for 「約 −494 點（估算）」)
ESTIMATE_MARKED_METRICS = frozenset({"sector_contrib_est", "stock_contrib"})
# Sections whose every sentence must take one of the three shapes
PATTERN_ONLY = ("watch", "tonight", "themes", "risks")
STOCK_KEYS = ("stocks", "stocks_week")  # one item per stock (its first sentence names it)
OPTION_REASON = ("watch", "themes", "risks")  # themes: only ``why``
MULT = {"兆": 10 ** 12, "億": 10 ** 8, "萬": 10 ** 4}


@dataclass
class Problem:
    path: str
    code: str
    detail: str = ""
    hard: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {"path": self.path, "code": self.code, "detail": self.detail, "hard": self.hard}

    @property
    def key(self) -> str:
        """The output key the path is under (``what_happened``, ``title``, ``chart_of_day`` …)."""
        return re.split(r"[\[.]", self.path, maxsplit=1)[0]


@dataclass
class Sentence:
    path: str
    key: str  # output key
    para: str  # the paragraph's path (same-paragraph checks)
    text: str
    refs: list[str]
    sub: str = ""  # themes: why | events | relation
    symbol: str = ""  # a stock item's symbol (its sentences are about that stock)


# -- walking the output ---------------------------------------------------------------------------------------------
def _para_sentences(para: Any, path: str, key: str, sub: str = "", symbol: str = "") -> Iterator[Sentence]:
    for j, s in enumerate((para or {}).get("sentences") or [] if isinstance(para, dict) else []):
        if isinstance(s, dict):
            yield Sentence(f"{path}.sentences[{j}]", key, path, str(s.get("text") or ""),
                           [str(r) for r in s.get("refs") or []], sub, symbol)


def sentences(output: dict[str, Any], kind: str) -> Iterator[Sentence]:
    """Every AI sentence with its path (not the title; see :func:`title_text`)."""
    for key in OUTPUT_KEYS[kind]:
        v = output.get(key)
        if key == "title" or v is None:
            continue
        if key == "chart_of_day":
            if isinstance(v, dict) and v.get("code") not in (None, "none"):
                yield from _para_sentences(v.get("caption"), "chart_of_day.caption", key)
            continue
        if key == "summary":
            yield from _para_sentences(v, "summary", key)
            continue
        for i, item in enumerate(v if isinstance(v, list) else []):
            base = f"{key}[{i}]"
            if not isinstance(item, dict):
                continue
            if "sentences" in item:
                yield from _para_sentences(item, base, key)
            elif key == "themes":
                for sub in ("why", "events", "relation"):
                    yield from _para_sentences(item.get(sub), f"{base}.{sub}", key, sub)
            else:
                symbol = str(item.get("symbol") or "") if key in STOCK_KEYS else ""
                # a brief row (the premarket's and the close's highlights): its field rides on its sentences
                slot = str(item.get("slot") or "") if key == "highlights" else ""
                yield from _para_sentences(item.get("para"), f"{base}.para", key, slot, symbol)


def ai_text_chars(output: dict[str, Any], kind: str) -> int:
    return len(str(output.get("title") or "")) + sum(len(s.text) for s in sentences(output, kind))


# -- numbers -----------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Num:
    value: float  # absolute, scaled by 兆 / 億 / 萬
    tol: float  # half a unit of the last written digit (scaled)
    sign: int  # +1 / -1 from ▲▼ or the words before it; 0 none
    unit: str
    start: int
    approx: bool


_DATES = (re.compile(r"\d{4}-\d{1,2}-\d{1,2}"), re.compile(r"(?<![\d.])\d{1,2}/\d{1,2}(?![\d/])"),
          re.compile(r"\d{1,2}\s*月\s*\d{1,2}\s*日"), re.compile(r"\d{1,2}:\d{2}"),
          re.compile(r"\d{4}\s*年"), re.compile(r"(?<![\d.])\d{1,2}\s*月(?!\s*\d)"),
          re.compile(r"[（(]\s*\d{4,6}[A-Z]?\s*[)）]"), re.compile(r"[QH]\d|\d[QH]"),
          re.compile(r"第\s*\d+"), re.compile(r"\d+\s*(?:個月|個交易日|天|週|周|季|年度|年)"),
          re.compile(r"前\s*(?:3|5|10|20|50|100|200|300)(?!\d)"),
          re.compile(r"(?<![\d.])(?:3|5|10|100|200|300)\s*(?=名|大(?!漲|跌)|檔權值)"),
          re.compile(r"(?<![\d.])[1-5]\s*(?=檔|項|個|件|則|種|段)"))
_NUM = re.compile(r"(?P<sign>[+\-▲▼])?\s*(?P<num>\d+(?:\.\d+)?)\s*(?P<mult>兆|億|萬)?"
                  r"\s*(?P<unit>%|點|美元|元|家|口|張|倍|則|檔)?")
_DIRECTION = re.compile(r"漲跌|漲停|跌停|上漲|下跌|漲|跌|增加|減少|增|減|買超|賣超|淨買|淨賣|上升|下降|▲|▼")
_DIR_SIGN = {"上漲": 1, "漲": 1, "增加": 1, "增": 1, "買超": 1, "淨買": 1, "上升": 1, "▲": 1,
             "下跌": -1, "跌": -1, "減少": -1, "減": -1, "賣超": -1, "淨賣": -1, "下降": -1, "▼": -1}
_CLAUSE = re.compile(r"[，,；;、。：:]")


def normalize(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "").replace("−", "-").replace("–", "–")
    return re.sub(r"(?<=\d),(?=\d{3})", "", t)


def _blank(text: str, tokens: Iterable[str]) -> str:
    for tok in sorted({t for t in tokens if t}, key=len, reverse=True):
        if tok in text:
            text = text.replace(tok, "＿" * len(tok))
    return text


def numbers(text: str, blank: Iterable[str] = ()) -> list[Num]:
    """The numbers of a sentence (NFKC, thousands separators removed), without dates, times, stock codes in
    parentheses, counted periods and the list rules' constants; names that carry digits are blanked first."""
    t = _blank(normalize(text), (normalize(b) for b in blank if b and re.search(r"\d", b)))
    for rx in _DATES:
        t = rx.sub(lambda m: "＃" * len(m.group(0)), t)
    out = []
    for m in _NUM.finditer(t):
        raw = m.group("num")
        nd = len(raw.split(".", 1)[1]) if "." in raw else 0
        mult = MULT.get(m.group("mult") or "", 1)
        sign = {"+": 1, "-": -1, "▲": 1, "▼": -1}.get(m.group("sign") or "", 0)
        if sign == 0:
            sign = _direction(t[max(0, m.start() - 8):m.start()])
        before = t[max(0, m.start() - 3):m.start()]
        out.append(Num(float(raw) * mult, 0.5 * (10 ** -nd) * mult, sign, m.group("unit") or "", m.start(),
                       "約" in before))
    return out


def _direction(before: str) -> int:
    """The sign the closest direction word before a number gives it (within its clause)."""
    clause = _CLAUSE.split(before)[-1]
    found = list(_DIRECTION.finditer(clause))
    return _DIR_SIGN.get(found[-1].group(0), 0) if found else 0


def _close_to(n: Num, candidate: float) -> bool:
    return abs(n.value - abs(candidate)) <= n.tol * (1 + 1e-9) + 1e-9 * max(1.0, abs(candidate))


_UNIT_FAMILY = {"檔": "家"}


def unit_ok(written: str, fact_unit: str | None) -> bool:
    """The unit written after a number fits the fact's (億元 / 兆元 are 元 once 億 / 兆 scaled the number; 檔 = 家). A
    number written without a unit, or a fact without one, is not judged here."""
    base = re.sub(r"^[兆億萬]", "", str(fact_unit or ""))
    if not written or not base:
        return True
    return _UNIT_FAMILY.get(written, written) == _UNIT_FAMILY.get(base, base)


def _fact_candidates(f: dict[str, Any]) -> list[float]:
    vals = [x.value for x in numbers(str(f.get("display") or ""))]
    v = f.get("value")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        vals.append(abs(v) * 100 if f.get("unit") == "%" else abs(v))
    return vals


# -- the pack as the validator reads it ------------------------------------------------------------------------------
@dataclass
class Ctx:
    pack: dict[str, Any]
    kind: str
    facts: dict[str, dict[str, Any]] = field(default_factory=dict)
    web: dict[str, dict[str, Any]] = field(default_factory=dict)
    cal: dict[str, dict[str, Any]] = field(default_factory=dict)
    filings: dict[str, dict[str, Any]] = field(default_factory=dict)
    research: dict[str, dict[str, Any]] = field(default_factory=dict)
    stock_names: dict[str, str] = field(default_factory=dict)  # code -> name
    stock_symbols: dict[str, dict[str, Any]] = field(default_factory=dict)
    sectors: dict[str, dict[str, Any]] = field(default_factory=dict)
    allowed_dates: set[tuple[int, int]] = field(default_factory=set)
    blank: list[str] = field(default_factory=list)  # names with digits (元大台灣50, S&P 500 ETF)
    other_names: list[str] = field(default_factory=list)  # Taiwan names not on the list (≥3 characters)
    other_short: list[str] = field(default_factory=list)  # two-character ones (checked next to a stock's context)
    known: list[str] = field(default_factory=list)  # names blanked before the check (listed, subjects, outlets)
    subjects: set[str] = field(default_factory=set)  # the facts' subjects and the listed names (normalized)
    strip: set[str] = field(default_factory=set)
    year: int = 2026
    day: date = date(2026, 6, 30)  # the edition date (the year of a US date)

    def ref(self, rid: str) -> dict[str, Any] | None:
        for table in (self.facts, self.web, self.cal, self.filings, self.research):
            if rid in table:
                return table[rid]
        return None


def _md(iso: str | None) -> tuple[int, int] | None:
    if not iso:
        return None
    try:
        d = date.fromisoformat(str(iso)[:10])
    except ValueError:
        return None
    return d.month, d.day


def context(pack: dict[str, Any], kind: str, names: Iterable[str] = ()) -> Ctx:
    c = Ctx(pack, kind)
    c.facts = {f["id"]: f for f in pack.get("facts") or []}
    c.web = {x["id"]: x for x in pack.get("web") or []}
    c.cal = {x["id"]: x for x in pack.get("calendar") or []}
    c.filings = {x["id"]: x for x in pack.get("filings") or []}
    c.research = {x["id"]: x for x in pack.get("research") or []}
    for s in pack.get("stocks") or []:
        c.stock_names[str(s["code"])] = str(s["name"])
        c.stock_symbols[str(s["symbol"])] = s
    c.sectors = {s["name"]: s for s in pack.get("sectors") or []}
    c.strip = set(pack.get("strip") or [])
    c.day = edition_day(pack)
    c.year = c.day.year
    for lst in (pack.get("dates") or {}).values():
        for iso in lst:
            if (md := _md(iso)) is not None:
                c.allowed_dates.add(md)
    for key in ("period", "next_period"):
        p = pack.get(key) or {}
        for iso in (p.get("start"), p.get("end")):
            if (md := _md(iso)) is not None:
                c.allowed_dates.add(md)
    if (md := _md(pack.get("edition_date"))) is not None:
        c.allowed_dates.add(md)
    tokens = [*c.stock_names.values(), *SECTOR_NAMES]
    for f in c.facts.values():
        tokens += [f.get("subject") or "", *(f.get("aliases") or [])]
    c.blank = [t for t in tokens if t and re.search(r"\d", t)]
    known = set(tokens) | {x.get("outlet") or "" for x in c.web.values()}
    allowed = set(c.stock_names.values())
    names = [n for n in names if n]
    c.other_names = sorted({n for n in names if len(n) >= 3 and n not in allowed
                            and not any(n in a for a in allowed) and n not in known}, key=len, reverse=True)
    c.other_short = sorted({n for n in names if len(n) == 2 and n not in allowed and n not in known
                            and n not in TWO_CHAR_COMMON and not any(n in a for a in allowed)})
    c.known = sorted({k for k in known if k}, key=len, reverse=True)
    c.subjects = {normalize(x) for x in (*c.stock_names.values(), *(f.get("subject") or "" for f in c.facts.values()))
                  if len(x or "") >= 2}
    return c


def edition_day(pack: dict[str, Any] | None) -> date:
    """The pack's edition date (today in Taipei without a pack): the year a written US date falls in."""
    with contextlib.suppress(KeyError, ValueError, TypeError):
        return date.fromisoformat(str((pack or {})["edition_date"])[:10])
    return datetime.now(TAIPEI).date()


def other_stocks(c: Ctx, text: str, sources: Iterable[str] = ()) -> list[str]:
    """Taiwan names off the stock list in ``text`` (normalized): every one of three characters or more; a
    two-character one only next to a stock's context (股、漲、跌、法說、營收 …), once the listed names, the facts'
    subjects, the outlets and the sector names are blanked. A two-character name that the cited report of a company
    abroad has in its own words (``sources``: 三星 in a Samsung story) is that company: it may be written."""
    out: list[str] = []
    said = [normalize(x) for x in sources if x]
    t = _blank(text, [*c.stock_names.values(), *(f.get("subject") or "" for f in c.facts.values()), *c.known,
                      *SECTOR_NAMES, *PLAIN_PHRASES])
    for name in c.other_names:
        if name in t:
            out.append(name)
            t = t.replace(name, "＿" * len(name))
    for name in c.other_short:
        if any(name in x for x in said):
            continue
        for m in re.finditer(re.escape(name), t):
            around = t[max(0, m.start() - 4):m.start()] + t[m.end():m.end() + 8]
            if STOCK_CONTEXT.search(around):
                out.append(name)
                break
    return out


def named_sources(c: Ctx, refs: Iterable[str]) -> list[str]:
    """The words of the cited reports whose topic is a company abroad (:data:`NAMED_KEYS`)."""
    out: list[str] = []
    for r in refs:
        x = c.web.get(r)
        if x is not None and str(x.get("key") or "").startswith(NAMED_KEYS):
            out += [str(x.get("claim") or ""), str(x.get("title") or "")]
    return out


def gap_phrase(key: str, text: str, sourced: Iterable[str] = ()) -> str | None:
    """A passage of ``text`` (normalized) that tells what the edition lacks, other than the fixed sentence the spec
    asks for in ``key`` (:data:`GAP_ALLOWED`). ``sourced``: the texts of the reports the sentence cites — when one of
    them says something of the kind (:data:`GAP_SOURCED`), those words are the report's, not the edition's."""
    t = _blank(text, (normalize(x) for x in GAP_ALLOWED.get(key, ())))
    if (m := GAP_EDITION.search(t)) is not None:
        return m.group(0)
    m = GAP_SOURCED.search(t)
    if m is None or any(GAP_SOURCED.search(normalize(x)) for x in sourced if x):
        return None
    return m.group(0)


def report_texts(c: Ctx, refs: Iterable[str]) -> list[str]:
    """The words of the cited reports (X claims and quotes, W quotes)."""
    return [t for r in refs if r[:1] in ("X", "W") for t in _ref_texts(c, r)]


def _blank_converted(c: Ctx, text: str, whole: bool) -> str:
    """``text`` with the program's 「美東 …（台北 …）」 passages blanked: only their Taipei part (``whole=False``, the
    date checks: that date is the conversion, not a sourced one) or all of it (the US local time check)."""
    for start, end, ts, te in reversed(converted_spans(text, c.day)):
        a, b = (start, end) if whole else (ts, te)
        text = text[:a] + "＃" * (b - a) + text[b:]
    return text


def us_local_time(c: Ctx, text: str, refs: Iterable[str] = ()) -> str | None:
    """A US local time with a clock left without its Taipei time (the page shows Taipei times). The title of a cited
    calendar row is the server's own (its row carries the Taipei time): copied as it is, it is not one."""
    own = [normalize(str(c.cal[r].get("title") or "")) for r in refs if r in c.cal]
    m = US_LOCAL_TIME.search(_blank_converted(c, _blank(text, own), True))
    return m.group(0) if m else None


# -- sentence checks -----------------------------------------------------------------------------------------------
def _subject_in(text: str, f: dict[str, Any]) -> bool:
    return any(s and normalize(s) in text for s in (f.get("subject"), *(f.get("aliases") or [])))


def _subjects(c: Ctx, refs: list[str]) -> list[str]:
    out: list[str] = []
    for r in refs:
        x = c.ref(r)
        if x is None:
            continue
        if r.startswith("F"):
            out += [x.get("subject") or "", *(x.get("aliases") or [])]
        elif r.startswith("X") and x.get("subject"):
            out.append(x["subject"])
    return [normalize(s) for s in out if s]


def _clause_at(text: str, pos: int) -> str:
    start = max((m.end() for m in _CLAUSE.finditer(text, 0, pos)), default=0)
    m = _CLAUSE.search(text, pos)
    return text[start:m.start() if m else len(text)]


def _ref_texts(c: Ctx, r: str) -> list[str]:
    x = c.ref(r)
    if x is None:
        return []
    if r.startswith("X"):
        return [str(x.get("quote") or ""), str(x.get("claim") or "")]
    if r.startswith("W"):
        return [*(str(q) for q in x.get("quotes") or []), *(str(s.get("title") or "") for s in x.get("sources") or [])]
    if r.startswith("C"):
        return [str(x.get("title") or ""), str(x.get("note") or ""), str(x.get("time_taipei") or "")]
    if r.startswith("N"):
        return [str(x.get("title") or "")]
    return []


def _check_numbers(c: Ctx, s: Sentence, text: str, out: list[Problem]) -> None:
    nums = numbers(s.text, c.blank)
    if not nums:
        return
    subjects_here = _subjects(c, s.refs)
    for n in nums:
        by_value = [c.facts[r] for r in s.refs if r in c.facts
                    and any(_close_to(n, v) for v in _fact_candidates(c.facts[r]))]
        matched_f = [f for f in by_value if unit_ok(n.unit, f.get("unit"))]
        matched_x = [r for r in s.refs if not r.startswith("F") and any(
            _close_to(n, m.value) for t in _ref_texts(c, r) for m in numbers(t, c.blank))]
        if by_value and not matched_f and not matched_x:  # 4.67% written as 元, 6.03% as 點
            out.append(Problem(s.path, "unit_mismatch",
                               f"{_num_text(s.text, n)} 對到 {by_value[0].get('display') or by_value[0].get('unit')}"))
            continue
        if not matched_f and not matched_x:
            out.append(Problem(s.path, "number_unsourced", _num_text(s.text, n)))
            continue
        clause = _clause_at(text, n.start)
        scope = clause if any(sub in clause for sub in subjects_here) else text
        if matched_f:
            if not any(_subject_in(scope, f) for f in matched_f) and not matched_x \
                    and not _the_items_stock(c, s, matched_f, clause):
                out.append(Problem(s.path, "number_subject_mismatch",
                                   f"{_num_text(s.text, n)} 對到 {matched_f[0].get('subject')}"))
                continue
            signed = [f for f in matched_f if f.get("metric") in SIGNED_METRICS
                      and isinstance(f.get("value"), (int, float)) and f["value"] != 0]
            if n.sign and signed and all((1 if f["value"] > 0 else -1) != n.sign for f in signed):
                out.append(Problem(s.path, "direction_mismatch", f"{_num_text(s.text, n)}"))
            if not matched_x and not n.approx and "估算" not in s.text and all(
                    f.get("estimate") and f.get("metric") in ESTIMATE_MARKED_METRICS for f in matched_f):
                out.append(Problem(s.path, "estimate_unmarked", _num_text(s.text, n)))
        elif matched_x:
            # a report's own statement decides whose number it is (an article's passage often holds several)
            by_claim = [r for r in matched_x if r in c.web and any(
                _close_to(n, m.value) for m in numbers(str(c.web[r].get("claim") or ""), c.blank))]
            pool = by_claim or [r for r in matched_x if r in c.web]
            subs = [c.web[r].get("subject") for r in pool if c.web[r].get("subject")]
            if subs and len(subs) == len(pool) and not any(normalize(x) in scope for x in subs):
                out.append(Problem(s.path, "number_subject_mismatch", f"{_num_text(s.text, n)} 對到 {subs[0]}"))


def _the_items_stock(c: Ctx, s: Sentence, facts: list[dict[str, Any]], clause: str) -> bool:
    """In a stock item every sentence is about that stock: its number needs no name of its own (「成交金額 1,354.7
    億元」 in 台積電's item), unless the clause names another subject."""
    st = c.stock_symbols.get(s.symbol) if s.symbol else None
    if st is None:
        return False
    name, code = normalize(str(st["name"])), str(st["code"])
    if not any(normalize(str(f.get("subject") or "")) == name or code in (f.get("aliases") or []) for f in facts):
        return False
    return not any(o in clause for o in c.subjects - {name, code})


def _num_text(text: str, n: Num) -> str:
    t = normalize(text)
    return t[n.start:n.start + 12].strip()


_DATE_MD = re.compile(r"(?<![\d.])(\d{1,2})/(\d{1,2})(?![\d/])|(\d{1,2})\s*月\s*(\d{1,2})\s*日|\d{4}-(\d{2})-(\d{2})")
_DATE_WD = re.compile(r"(?<![\d.])(\d{1,2})/(\d{1,2})\s*[（(]\s*([一二三四五六日])\s*[)）]")
_LONE_WD = re.compile(r"(?:週|周|星期|禮拜)[一二三四五六日天]")


def _dates_in(text: str) -> list[tuple[int, int]]:
    out = []
    for m in _DATE_MD.finditer(normalize(text)):
        g = m.groups()
        mo, d = (g[0], g[1]) if g[0] else (g[2], g[3]) if g[2] else (g[4], g[5])
        try:
            out.append((int(mo), int(d)))
        except (TypeError, ValueError):
            continue
    return out


def _ref_dates(c: Ctx, refs: list[str]) -> set[tuple[int, int]]:
    out: set[tuple[int, int]] = set()
    for r in refs:
        x = c.ref(r)
        if x is None:
            continue
        for key in ("date", "published_at", "session", "us_session"):
            if (md := _md(x.get(key))) is not None:
                out.add(md)
        for t in _ref_texts(c, r):
            out.update(_dates_in(t))
    return out


def _weekday_of(c: Ctx, mo: int, d: int) -> int | None:
    best = None
    for y in (c.year - 1, c.year, c.year + 1):
        try:
            x = date(y, mo, d)
        except ValueError:
            continue
        ed = date.fromisoformat(c.pack.get("edition_date") or f"{c.year}-06-30")
        if best is None or abs((x - ed).days) < abs((best - ed).days):
            best = x
    return best.weekday() if best else None


def _check_dates(c: Ctx, s: Sentence, out: list[Problem]) -> None:
    text = _blank_converted(c, normalize(s.text), False)  # the server's Taipei date of a sourced US time
    allowed = c.allowed_dates | _ref_dates(c, s.refs)
    for md in _dates_in(text):
        if md not in allowed:
            out.append(Problem(s.path, "date_not_sourced", f"{md[0]}/{md[1]}"))
    for m in _DATE_WD.finditer(text):
        wd = _weekday_of(c, int(m.group(1)), int(m.group(2)))
        if wd is not None and WEEKDAYS[wd] != m.group(3):
            out.append(Problem(s.path, "weekday_mismatch", m.group(0)))
    for m in _LONE_WD.finditer(text):
        out.append(Problem(s.path, "weekday_mismatch", f"只寫星期：{m.group(0)}"))


def _sector_mentions(text: str) -> list[str]:
    found, t = [], text
    for name in sorted(SECTOR_NAMES, key=len, reverse=True):
        rx = re.compile(re.escape(name) + r"(?:類|股|族群)")
        if rx.search(t):
            found.append(name)
            t = rx.sub("＿", t)
    return found


# The written outlet (lower case) -> the outlet name the gathering stores. International outlets are often written
# with their Chinese names (〔彭博〕 for a Bloomberg page: the 2026-11-17 second dry run dropped two sentences).
_OUTLET_ALIASES = {
    "自由財經": "自由時報", "鉅亨": "鉅亨網", "anue": "鉅亨網", "cna": "中央社", "中央通訊社": "中央社",
    "彭博": "Bloomberg", "彭博社": "Bloomberg", "彭博新聞社": "Bloomberg", "彭博資訊": "Bloomberg",
    "路透": "Reuters", "路透社": "Reuters", "美聯社": "AP", "美國聯合通訊社": "AP",
    "華爾街日報": "The Wall Street Journal", "金融時報": "Financial Times", "英國金融時報": "Financial Times",
    "紐約時報": "The New York Times", "日經": "Nikkei Asia", "日經亞洲": "Nikkei Asia", "日本經濟新聞": "Nikkei Asia",
    "南華早報": "South China Morning Post", "富比世": "Forbes", "財星": "Fortune", "財星雜誌": "Fortune",
    "巴倫週刊": "Barron's", "巴倫周刊": "Barron's", "霸榮週刊": "Barron's", "霸榮周刊": "Barron's",
    "市場觀察": "MarketWatch", "商業內幕": "Business Insider", "美國有線電視新聞網": "CNN",
}


def _same_outlet(written: str, outlet: str) -> bool:
    a = _OUTLET_ALIASES.get(written.strip(), written.strip()).lower()
    b = outlet.strip().lower()
    return bool(a and b) and (a == b or (len(a) >= 2 and (a in b or b in a)))


def _pattern_ok(c: Ctx, s: Sentence, text: str) -> bool:
    kinds = {r[0] for r in s.refs}
    if P1.match(text):
        return bool(kinds & {"C", "X"})
    if (m := P2.match(text)) is not None:
        outlet = m.group(1).strip().lower()  # 〔鉅亨〕 and 鉅亨網 are the same outlet
        return any(r in c.web and _same_outlet(outlet, str(c.web[r].get("outlet") or "")) for r in s.refs)
    if P3.match(text):
        return bool(kinds & {"C", "X", "F"})
    return False


def check_sentence(c: Ctx, s: Sentence, para_refs: set[str]) -> list[Problem]:
    out: list[Problem] = []
    text = normalize(s.text)
    if not s.refs:
        out.append(Problem(s.path, "no_refs"))
    for r in s.refs:
        if c.ref(r) is None:
            out.append(Problem(s.path, "bad_ref", r))
    for w in (*FORBIDDEN_WORDS, *TIME_WORDS):
        if w in text:
            out.append(Problem(s.path, "forbidden_word", w))
    for w in STYLE_WORDS:
        if w in text or w in s.text:
            out.append(Problem(s.path, "style_word", w, hard=False))
    if re.search(r"[*_#`]|\[[^\]]*\]\(", s.text):
        out.append(Problem(s.path, "style_word", "markdown", hard=False))
    if (pts := index_points(text)) is not None:
        out.append(Problem(s.path, "index_points", pts))
    _check_numbers(c, s, text, out)
    _check_dates(c, s, out)
    # stocks: codes in parentheses and Taiwan names not on the list
    for m in re.finditer(r"[（(]\s*(\d{4,6}[A-Z]?)\s*[)）]", text):
        if m.group(1) not in c.stock_names:
            out.append(Problem(s.path, "stock_not_allowed", m.group(1)))
    for name in other_stocks(c, text, named_sources(c, s.refs)):
        out.append(Problem(s.path, "stock_not_allowed", name))
    if (gap := gap_phrase(s.key, text, report_texts(c, s.refs))) is not None:
        out.append(Problem(s.path, "internal_gap", gap))
    if (us := us_local_time(c, text, s.refs)) is not None:
        out.append(Problem(s.path, "us_local_time", us))
    if (private := private_life(text)) is not None:
        out.append(Problem(s.path, "private_life", private))
    if (s.key in CHIPS_KEYS or (s.key == "highlights" and s.sub == "chips")) \
            and (off := chips_off_topic(c, text, s.refs)) is not None:
        out.append(Problem(s.path, "chips_off_topic", off))
    # sectors
    for name in _sector_mentions(text):
        sec = c.sectors.get(name)
        if sec is None or not sec.get("text_eligible"):
            out.append(Problem(s.path, "sector_not_allowed", name))
        elif sec.get("concentration_fact") and name == "半導體" and sec["concentration_fact"] not in para_refs:
            out.append(Problem(s.path, "sector_not_allowed", "半導體沒有帶集中度"))
    # a stock's fund flow and its move in one sentence
    if FLOW.search(text) and any(n.unit == "%" for n in numbers(s.text, c.blank)) and (
            any(name in text for name in c.stock_names.values())
            or any(normalize(f"（{code}）") in text for code in c.stock_names)):
        out.append(Problem(s.path, "flow_and_move"))
    if CAUSE.search(text) and not any(r[0] in "XW" for r in s.refs):
        out.append(Problem(s.path, "cause_without_source", CAUSE.search(text).group(0)))  # type: ignore[union-attr]
    must = s.key in PATTERN_ONLY
    ahead = OUTLOOK.search(text)
    if (must or ahead) and not _pattern_ok(c, s, text):
        out.append(Problem(s.path, "outlook_pattern", "句型不符" if must or ahead is None else ahead.group(0)))
    elif (must or ahead) and (fc := FORECAST.search(text)) is not None:
        # the right shape, but a direction or a view inside it (轉述別人的看法也不行)
        out.append(Problem(s.path, "outlook_pattern", f"方向：{fc.group(0)}"))
    if s.key in OPTION_REASON and (s.key != "themes" or s.sub == "why"):
        for r in s.refs:
            f = c.facts.get(r)
            if f and f.get("metric") in OPTION_METRICS:
                out.append(Problem(s.path, "options_as_reason", r))
    if c.kind == "premarket" and s.key in ("highlights", "evening_notes"):
        # the previous session's numbers were in the close report; 「昨晚才到的資料」 holds only what came after it
        for r in s.refs:
            f = c.facts.get(r)
            if f and f.get("group") == "prev_session":
                out.append(Problem(s.path, "repeats_close_report", r))
    return out


def chips_off_topic(c: Ctx, text: str, refs: Iterable[str]) -> str | None:
    """What a chips sentence holds besides institutional investors and fund flows: the exchange rate, the options'
    P/C ratio or the futures' settlement day (a fact, a calendar row or the words of one)."""
    for r in refs:
        f = c.facts.get(r)
        if f is not None and f.get("metric") in CHIPS_OFF_METRICS:
            return f"{r} {f.get('subject') or f.get('metric')}"
        row = c.cal.get(r)
        if row is not None and row.get("kind") == "settlement":
            return f"{r} 結算日"
    m = CHIPS_OFF.search(text)
    return m.group(0) if m else None


def _units(output: dict[str, Any], key: str) -> Iterator[tuple[str, list[Sentence]]]:
    """The units of :data:`ONCE_PER_SECTION`: each highlight, theme or risk with its sentences; each summary
    sentence alone."""
    if key == "summary":
        for s in _para_sentences(output.get("summary"), "summary", key):
            yield s.path, [s]
        return
    for i, item in enumerate(output.get(key) or []):
        if not isinstance(item, dict):
            continue
        base = f"{key}[{i}]"
        if key == "themes":
            yield base, [s for sub in ("why", "events", "relation")
                         for s in _para_sentences(item.get(sub), f"{base}.{sub}", key, sub)]
        else:
            yield base, list(_para_sentences(item, base, key))


def _repeated_facts(output: dict[str, Any]) -> list[Problem]:
    """The weekly: a calendar row (C) or a report (X) in more than one highlight, summary sentence, theme or risk — the
    repeats after its first unit in that section (``repeated_fact``; each section may use it once)."""
    out: list[Problem] = []
    for key in ONCE_PER_SECTION:
        first: dict[str, str] = {}
        for unit, sents in _units(output, key):
            used = {r for s in sents for r in s.refs if r[:1] in ("C", "X")}
            for r in sorted(used):
                if r not in first:
                    first[r] = unit
                    continue
                for s in sents:
                    if r in s.refs:
                        out.append(Problem(s.path, "repeated_fact", f"{r} 已在 {first[r]} 用過"))
    return out


def _row_ahead(c: Ctx, row: dict[str, Any]) -> bool:
    """A calendar row still ahead when the edition is published: a day after the edition's (a weekly's Sunday), or
    that day after its cut-off (16:30) — a row of the reviewed week or of the weekend before the edition is past."""
    try:
        day = date.fromisoformat(str(row.get("date"))[:10])
    except (ValueError, TypeError):
        return False
    if day != c.day:
        return day > c.day
    m = re.match(r"\s*(\d{1,2}):(\d{2})", str(row.get("time_taipei") or ""))
    with contextlib.suppress(KeyError, ValueError, TypeError):
        cut = datetime.fromisoformat(str(c.pack["cutoff"])).astimezone(TAIPEI)
        return m is not None and (int(m.group(1)), int(m.group(2))) > (cut.hour, cut.minute)
    return False


def _later(c: Ctx, text: str, after: date) -> bool:
    """``text`` names a date (M/D, M月D日, ISO) after ``after`` (the year nearest the edition date)."""
    for mo, d in _dates_in(text):
        best = None
        for y in (c.year - 1, c.year, c.year + 1):
            with contextlib.suppress(ValueError):
                x = date(y, mo, d)
                if best is None or abs((x - c.day).days) < abs((best - c.day).days):
                    best = x
        if best is not None and best > after:
            return True
    return False


def _risks_not_ahead(c: Ctx, output: dict[str, Any]) -> list[Problem]:
    """The weekly's risks list only what is still ahead or pending when the edition is published (N3): each risk
    needs a calendar row after the edition's cut-off (:func:`_row_ahead`), or a report that speaks of something ahead
    (:data:`AHEAD`), or a date after the edition's day in the sentence or the report — an already published CPI, a
    ground stop already ordered (美股 11/20 收盤後, 台北 11/21: the weekend before a Sunday edition is past too) is news
    of the week, not a risk (``risk_not_ahead``, the item goes)."""
    out: list[Problem] = []
    for unit, sents in _units(output, "risks"):
        refs = [r for s in sents for r in s.refs]
        ahead = any(_later(c, normalize(s.text), c.day) for s in sents)
        for r in refs:
            if ahead:
                break
            row = c.cal.get(r)
            if row is not None:
                ahead = _row_ahead(c, row)
                continue
            x = c.web.get(r)
            if x is not None:
                claim = normalize(str(x.get("claim") or ""))
                ahead = bool(AHEAD.search(claim)) or _later(c, claim, c.day)
        if sents and not ahead:
            out.append(Problem(unit, "risk_not_ahead", "只放之後才會發生或還沒有結果的事"))
    return out


# -- whole output -------------------------------------------------------------------------------------------------
HEADING_KEYS = {"watch": "event", "tonight": "event", "themes": "theme"}


def headings(output: dict[str, Any], kind: str) -> Iterator[tuple[str, str]]:
    """The AI's own headings with their paths: the title, and each item's name (``watch`` / ``tonight`` ``event``,
    the weekly ``themes`` ``theme``) — shown in bold on the page, so checked like the title."""
    if output.get("title") is not None:
        yield "title", str(output.get("title") or "")
    for key, field_ in HEADING_KEYS.items():
        if key not in OUTPUT_KEYS[kind]:
            continue
        for i, item in enumerate(output.get(key) or []):
            if isinstance(item, dict) and str(item.get(field_) or "").strip():
                yield f"{key}[{i}].{field_}", str(item[field_])


def _heading_refs(c: Ctx, raw: str) -> list[str]:
    """A heading has no refs: the facts and verified reports its numbers match stand for them."""
    refs: list[str] = []
    for n in numbers(raw, c.blank):
        refs += [fid for fid, f in c.facts.items() if any(_close_to(n, v) for v in _fact_candidates(f))]
        refs += [xid for xid, x in c.web.items() if any(
            _close_to(n, m.value) for t in (x.get("quote"), x.get("claim")) for m in numbers(str(t or ""), c.blank))]
    return list(dict.fromkeys(refs))


def item_refs(output: dict[str, Any], path: str) -> list[str]:
    """An item's own refs (its ``time_ref`` and every sentence's), for the checks of its name."""
    m = re.match(r"(\w+)\[(\d+)\]", path)
    if m is None:
        return []
    items = output.get(m.group(1)) or []
    item = items[int(m.group(2))] if int(m.group(2)) < len(items) and isinstance(items[int(m.group(2))], dict) else {}
    refs = [str(item.get("time_ref") or "")]
    for sub in ("para", "why", "events", "relation"):
        for s in ((item.get(sub) or {}).get("sentences") or []) if isinstance(item.get(sub), dict) else []:
            refs += [str(r) for r in (s or {}).get("refs") or []]
    return [r for r in dict.fromkeys(refs) if r]


def _check_heading(c: Ctx, path: str, raw: str, own_refs: list[str] | None = None) -> list[Problem]:
    """The title and the items' names: the sentence checks that apply without refs (words, index points, every
    number against a fact or report with its subject, direction and unit, dates, stocks, sectors, causes) and no
    forward-looking word at all. An item's name may also use its item's own refs (``own_refs``: its date, its
    report)."""
    title = path == "title"
    out: list[Problem] = []
    text = normalize(raw)
    if not text:
        return [Problem(path, "count_out_of_range", "沒有標題")] if title else []
    for w in (*FORBIDDEN_WORDS, *TIME_WORDS):
        if w in text:
            out.append(Problem(path, "forbidden_word", w))
    if (pts := index_points(text)) is not None:
        out.append(Problem(path, "index_points", pts))
    own = [r for r in own_refs or [] if c.ref(r) is not None]
    refs = list(dict.fromkeys([*_heading_refs(c, raw), *own]))
    _check_numbers(c, Sentence(path, path.split("[", 1)[0], path, raw, refs), text, out)
    if c.kind == "premarket" and title:
        for n in numbers(raw, c.blank):
            hits = [f for f in c.facts.values() if any(_close_to(n, v) for v in _fact_candidates(f))]
            if hits and all(f.get("group") == "prev_session" for f in hits):
                out.append(Problem(path, "repeats_close_report", _num_text(raw, n)))
    allowed = c.allowed_dates | _ref_dates(c, own)
    for md in _dates_in(_blank_converted(c, text, False)):
        if md not in allowed:
            out.append(Problem(path, "date_not_sourced", f"{md[0]}/{md[1]}"))
    for m in _LONE_WD.finditer(text):
        out.append(Problem(path, "weekday_mismatch", m.group(0)))
    for m in re.finditer(r"[（(]\s*(\d{4,6}[A-Z]?)\s*[)）]", text):
        if m.group(1) not in c.stock_names:
            out.append(Problem(path, "stock_not_allowed", m.group(1)))
    for name in other_stocks(c, text, named_sources(c, own)):
        out.append(Problem(path, "stock_not_allowed", name))
    if (gap := gap_phrase("", text, report_texts(c, own))) is not None:
        out.append(Problem(path, "internal_gap", gap))
    if (us := us_local_time(c, text, own)) is not None:
        out.append(Problem(path, "us_local_time", us))
    if (private := private_life(text)) is not None:
        out.append(Problem(path, "private_life", private))
    for name in _sector_mentions(text):
        sec = c.sectors.get(name)
        if sec is None or not sec.get("text_eligible"):
            out.append(Problem(path, "sector_not_allowed", name))
    if (ahead := OUTLOOK.search(text) or FORECAST.search(text)) is not None:
        out.append(Problem(path, "outlook_pattern", f"標題不寫之後的事：{ahead.group(0)}"))
    if (cause := CAUSE.search(text)) is not None and not any(r[0] in "XW" for r in refs):
        out.append(Problem(path, "cause_without_source", cause.group(0)))
    if title and not 12 <= len(raw) <= 48:
        out.append(Problem(path, "too_long" if len(raw) > 48 else "count_out_of_range", str(len(raw)), hard=False))
    return out


def _check_counts(output: dict[str, Any], kind: str) -> list[Problem]:
    out = []
    for key, (lo, hi) in COUNTS[kind].items():
        n = len(output.get(key) or [])
        if not lo <= n <= hi:
            out.append(Problem(key, "count_out_of_range", f"{n}（{lo}–{hi}）", hard=False))
    return out


def _check_lengths(output: dict[str, Any], kind: str) -> list[Problem]:
    para_max, total_max = LENGTHS[kind]
    out = []
    by_para: dict[str, int] = {}
    for s in sentences(output, kind):
        by_para[s.para] = by_para.get(s.para, 0) + len(s.text)
    for p, n in by_para.items():
        if n > para_max * 1.25 or (kind in BRIEF_SLOTS and p.startswith("highlights[") and n > BRIEF_ROW_MAX):
            out.append(Problem(p, "too_long", str(n), hard=False))
    total = ai_text_chars(output, kind)
    if total > total_max * 1.25:
        out.append(Problem("total", "too_long", str(total), hard=False))
    return out


def _check_chart(c: Ctx, output: dict[str, Any]) -> list[Problem]:
    ch = output.get("chart_of_day")
    if not isinstance(ch, dict) or ch.get("code") in (None, "none"):
        return []
    menu = {m["code"]: m for m in c.pack.get("charts_menu") or [] if m.get("available")}
    m = menu.get(ch.get("code"))
    if m is None:
        return [Problem("chart_of_day", "chart_invalid", str(ch.get("code")))]
    if ch.get("period") not in (*m.get("periods", []), "none"):
        return [Problem("chart_of_day", "chart_invalid", f"period {ch.get('period')}")]
    if ch.get("code") == "G5" and ch.get("set") not in (m.get("sets") or []):
        return [Problem("chart_of_day", "chart_invalid", f"set {ch.get('set')}")]
    return []


def _check_items(c: Ctx, output: dict[str, Any], kind: str) -> list[Problem]:
    out: list[Problem] = []
    for key in ("stocks", "stocks_week"):
        for i, item in enumerate(output.get(key) or []):
            sym = str((item or {}).get("symbol") or "")
            st = c.stock_symbols.get(sym)
            first = next(iter(((item or {}).get("para") or {}).get("sentences") or []), {}) or {}
            text = normalize(str(first.get("text") or ""))
            if st is None:
                out.append(Problem(f"{key}[{i}]", "stock_item_mismatch", f"{sym} 不在名單"))
            elif not text.startswith(normalize(f"{st['name']}（{st['code']}）")):
                out.append(Problem(f"{key}[{i}]", "stock_item_mismatch",
                                   f"第一句要以「{st['name']}（{st['code']}）」開頭"))
    for key in ("watch", "tonight"):
        if key not in OUTPUT_KEYS[kind]:
            continue
        for i, item in enumerate(output.get(key) or []):
            # an item is a real event: the calendar's (C) or a report's (X), not 「台股 11/17（二）開盤」 made up from F
            if isinstance(item, dict) and not any(r in c.cal or r in c.web for r in item_refs(output, f"{key}[{i}]")):
                out.append(Problem(f"{key}[{i}]", "item_not_event", "time_ref 或 refs 要有行事曆（C）或報導（X）"))
    for key in ("watch", "tonight", "themes"):
        for i, item in enumerate(output.get(key) or []):
            for sec in (item or {}).get("sectors") or []:
                if sec not in SECTOR_NAMES:
                    out.append(Problem(f"{key}[{i}].sectors", "sector_unknown", str(sec), hard=False))
            ref = (item or {}).get("time_ref")
            if key != "themes" and ref and ref not in c.cal:
                out.append(Problem(f"{key}[{i}].time_ref", "bad_ref", f"time_ref 只能填 C 編號或空字串，收到「{ref}」"))
    for i, item in enumerate(output.get("last_week_review") or []):
        ref = (item or {}).get("ref")
        if ref and ref not in c.cal:
            out.append(Problem(f"last_week_review[{i}]", "bad_ref", str(ref)))
    return out


def _check_brief(c: Ctx, output: dict[str, Any], kind: str) -> list[Problem]:
    """The brief's rows (the premarket's and the close's highlights): each fills one of the writer's fields of the
    kind, a field once; 為什麼 stands on a report (X / W), the close's 籌碼 on a report too (the listed institutions
    have no open data), 貢獻 on at least one fact, and every 排定 sentence on a calendar row or a report. Each problem
    takes its row alone (:data:`ITEM_LEVEL`). A field is taken by the first row that stands on what it needs: a row
    that goes for its content does not make the next row of its field a repeat (that one would go with it)."""
    slots = BRIEF_SLOTS.get(kind)
    if slots is None:
        return []
    out: list[Problem] = []
    seen: set[str] = set()
    for i, row in enumerate(output.get("highlights") or []):
        if not isinstance(row, dict):
            continue
        path, slot = f"highlights[{i}]", str(row.get("slot") or "")
        if slot not in slots:
            out.append(Problem(path, "slot_invalid", slot or "沒有 slot"))
            continue
        if slot in seen:
            out.append(Problem(path, "slot_repeated", slot))
            continue
        para = row.get("para") if isinstance(row.get("para"), dict) else {}
        per = [[str(r) for r in x.get("refs") or []] for x in para.get("sentences") or [] if isinstance(x, dict)]
        refs = [r for one in per for r in one]
        if slot == "why" and not any(r[:1] in ("X", "W") and c.ref(r) is not None for r in refs):
            out.append(Problem(path, "slot_needs_report", "為什麼要引用報導"))
        elif slot == "chips" and kind == "close" and not any(r in c.web for r in refs):
            out.append(Problem(path, "slot_needs_report", "上市三大法人只能引用報導"))
        elif slot == "drivers" and not any(r in c.facts for r in refs):
            out.append(Problem(path, "slot_needs_fact", "貢獻至少引用一筆 F"))
        elif slot == "scheduled" and (not per or any(not any(r in c.cal or r in c.web for r in one) for one in per)):
            out.append(Problem(path, "slot_not_event", "排定的每一句都要引用行事曆（C）或報導（X）"))
        else:
            seen.add(slot)
    return out


def validate(output: dict[str, Any], pack: dict[str, Any], kind: str, names: Iterable[str] = ()) -> list[Problem]:
    """Every problem of ``output`` (the writer's JSON) against ``pack``."""
    c = context(pack, kind, names)
    out: list[Problem] = []
    if output.get("title") is None:
        out.append(Problem("title", "count_out_of_range", "沒有標題"))
    for path, raw in headings(output, kind):
        out += _check_heading(c, path, raw, item_refs(output, path))
    para_refs: dict[str, set[str]] = {}
    sents = list(sentences(output, kind))
    for s in sents:
        para_refs.setdefault(s.para, set()).update(s.refs)
    strip_by_para: dict[str, set[str]] = {}
    for s in sents:
        out += check_sentence(c, s, para_refs.get(s.para, set()))
        strip_by_para.setdefault(s.para, set()).update(r for r in s.refs if r in c.strip)
    for p, refs in strip_by_para.items():
        if len(refs) >= 3:
            out.append(Problem(p, "repeats_strip", str(len(refs)), hard=False))
    out += _check_counts(output, kind)
    out += _check_lengths(output, kind)
    out += _check_chart(c, output)
    out += _check_items(c, output, kind)
    out += _check_brief(c, output, kind)
    if kind == "weekly":
        out += _repeated_facts(output)
        out += _risks_not_ahead(c, output)
    return out


def mentions_anthropic(output: dict[str, Any], kind: str) -> bool:
    texts = [*(t for _p, t in headings(output, kind)), *(s.text for s in sentences(output, kind))]
    return any(re.search(r"anthropic|claude", t, re.IGNORECASE) for t in texts)


# -- trimming and dropping -------------------------------------------------------------------------------------------
_C_ID = re.compile(r"C\d{3,}")


def _sentence_dicts(node: Any) -> Iterator[dict[str, Any]]:
    """Every sentence dict under ``node`` (paragraphs, items, the chart's caption)."""
    if isinstance(node, dict):
        for s in node["sentences"] if isinstance(node.get("sentences"), list) else []:
            if isinstance(s, dict):
                yield s
        for k, v in node.items():
            if k != "sentences":
                yield from _sentence_dicts(v)
    elif isinstance(node, list):
        for v in node:
            yield from _sentence_dicts(v)


# A number of four digits or more without thousands separators (「43675.12 點」「9997.16 億元」, copied from a report):
# written with them (the house format, as the server's numbers are) when it has decimals or a unit after it — never a
# year, a date, a time, a code (0050, 2330) or a name's digits (羅素 2000)
_BARE_NUMBER = re.compile(r"(?<![\d.,/:\-A-Za-z&＿])(?P<int>[1-9]\d{3,})(?P<dec>\.\d+)?(?!\.?\d|[,/:\-A-Za-z])")
# The unit after it, never the first character of another word (元旦、元月、元宇宙、人形、人工、人力、家電、筆電、
# 萬聖節、兆豐、張忠謀、口罩: 「2026人形機器人展」 stays as it is): 人、家、筆、件、張、口 only before a character
# that is not Chinese (or as 人次、家公司), the others unless such a word starts there
_NUMBER_UNIT = re.compile(r"\s*(?:%|％|個百分點|(?:兆|億|萬)(?=美元|元|張|股|人|口|家|戶|[^\u3400-\u9fff]|$)"
                          r"|點(?![燈名評])|美元|元(?![旦月宇年素老首帥氣件宵]|大(?!關))|檔(?![期案])|倍"
                          r"|人次|家(?:公司|企業|廠商|業者)|筆交易|[人家筆件張口](?![\u3400-\u9fff]))")
# Clauses of a headline are separated with 「，」 (the house style of the rule-made headlines: 「加權指數 ▼2.31%，收
# 40,092.11 點」), never with a space between two Chinese characters (「…週漲3,973.48點 黃仁勳…」)
_CLAUSE_SPACE = re.compile(r"(?<=[\u3400-\u9fff」』])[ \u3000]+(?=[\u3400-\u9fff「『〔])")
_NOT_FOUND_ONLY = re.compile(r"^(?:個股的?)?(?:漲跌)?(?:原因)?(?:皆|都|仍|目前)?(?:未|沒有?)找到"
                             r"(?:相關的?)?(?:報導|新聞)[。.]?$")
_NOT_FOUND_CLAUSE = re.compile(r"[，,；;]\s*(?:漲跌)?(?:原因)?(?:未|沒有?)找到(?:相關的?)?(?:報導|新聞)"
                               r"(?=[。.]?$)")


def house_numbers(text: str, codes: Iterable[str] = ()) -> str:
    """``text`` with :data:`_BARE_NUMBER` numbers written with thousands separators, decimals kept (43675.12 →
    43,675.12; 9997.16 億元 → 9,997.16 億元): one without decimals only before a unit (:data:`_NUMBER_UNIT`), a year
    and month (「2026.11」) only before one; ``codes``: stock codes left as they are."""
    skip = {str(x) for x in codes}

    def fix(m: re.Match[str]) -> str:
        whole, dec = m.group("int"), m.group("dec") or ""
        unit = _NUMBER_UNIT.match(m.string, m.end()) is not None
        if not dec and (whole in skip or not unit):
            return m.group(0)
        if dec and not unit and 1900 <= int(whole) <= 2100 and len(dec) <= 3 and 1 <= int(dec[1:]) <= 12:
            return m.group(0)  # a year and a month (「2026.11營收」)
        return f"{int(whole):,}{dec}"

    return _BARE_NUMBER.sub(fix, text)


def headline_clauses(text: str) -> str:
    """A headline's clauses separated with 「，」 instead of a space (:data:`_CLAUSE_SPACE`)."""
    return _CLAUSE_SPACE.sub("，", text)


def _stock_items_cite_reports(output: dict[str, Any], key: str) -> bool:
    return any(str(r)[:1] in ("X", "W") for it in output.get(key) or [] if isinstance(it, dict)
               for s in _sentence_dicts(it.get("para")) for r in s.get("refs") or [])


def stocks_without_reasons(output: dict[str, Any], kind: str) -> str | None:
    """The stock section's key when it has items and none of them gives a reason (no report, X or W, cited): the page
    then says it once for the section (:data:`prompts.STOCKS_NOT_FOUND`), not in every item."""
    for key in STOCK_KEYS:
        if key not in OUTPUT_KEYS[kind]:
            continue
        items = [it for it in output.get(key) or [] if isinstance(it, dict) and any(_sentence_dicts(it.get("para")))]
        if items and not _stock_items_cite_reports(output, key):
            return key
    return None


def not_found_only(text: str) -> bool:
    """A sentence that only says no report was found (「未找到報導。」「漲跌原因未找到報導。」)."""
    return bool(_NOT_FOUND_ONLY.match(normalize(text).strip()))


def without_not_found(sentences: list[Any]) -> list[Any]:
    """A stock item's sentences without 「未找到報導」: a sentence of its own after the first goes, the clause ending a
    sentence (「…跌 4.00%，未找到報導。」) is cut (that sentence copied). For a stock section where no item gives a
    reason: :func:`tidy` and the page (``assemble``, after :func:`drop` took the last reason out) both use it."""
    kept = []
    for j, sent in enumerate(sentences):
        text = str(sent.get("text") or "") if isinstance(sent, dict) else ""
        if j > 0 and not_found_only(text):
            continue
        if text:
            cut = _NOT_FOUND_CLAUSE.sub("", text.rstrip())
            if cut != text.rstrip():
                sent = {**sent, "text": cut if cut.endswith(("。", ".")) else f"{cut}。"}
        kept.append(sent)
    return kept


def _drop_not_found(output: dict[str, Any], key: str) -> None:
    """No stock has a reason: each item's 「未找到報導」 goes (:func:`without_not_found`)."""
    for it in output.get(key) or []:
        para = it.get("para") if isinstance(it, dict) else None
        if isinstance(para, dict) and isinstance(para.get("sentences"), list):
            para["sentences"] = without_not_found(para["sentences"])


def tidy(output: dict[str, Any], kind: str, pack: dict[str, Any] | None = None) -> dict[str, Any]:
    """Soft fixes in a copy: extra items cut to the maximum; unknown sector names removed; an item's ``time_ref``
    that is not a calendar id (a date or a time the writer put there) replaced by the calendar id its sentences cite,
    else emptied; a US local time with a date written with its Taipei time (「美東 11/18 14:00（台北 11/19 03:00）」,
    converted here, never by the model); numbers copied from a report written in the house format with thousands
    separators (:func:`house_numbers`); the title's clauses separated with 「，」 (:func:`headline_clauses`); when no
    stock item gives a reason, their 「未找到報導」 taken out (the page says it once for the section,
    :func:`stocks_without_reasons`). ``pack``: the calendar ids, the stock codes and the edition date (without it, any
    ``C001`` form is taken as an id and today gives the year)."""
    out = copy.deepcopy(output)
    for key, (_lo, hi) in COUNTS[kind].items():
        if isinstance(out.get(key), list) and len(out[key]) > hi:
            out[key] = out[key][:hi]
    cal = {str(x.get("id")) for x in pack.get("calendar") or []} if pack is not None else None

    def is_cal(rid: str) -> bool:
        return rid in cal if cal is not None else bool(_C_ID.fullmatch(rid))

    for key in ("watch", "tonight", "themes"):
        for item in out.get(key) or []:
            if not isinstance(item, dict):
                continue
            item["sectors"] = [s for s in item.get("sectors") or [] if s in SECTOR_NAMES]
            ref = str(item.get("time_ref") or "").strip()
            if key != "themes" and ref and not is_cal(ref):
                cited = [str(r) for s in _sentence_dicts(item.get("para")) for r in s.get("refs") or []
                         if is_cal(str(r))]
                item["time_ref"] = cited[0] if cited else ""
    day = edition_day(pack)
    codes = [str(x.get("code") or "") for x in (pack or {}).get("stocks") or []]
    for s in _sentence_dicts(out):
        if isinstance(s.get("text"), str):
            s["text"] = house_numbers(us_times_to_taipei(s["text"], day), codes)
    if isinstance(out.get("title"), str):
        out["title"] = headline_clauses(house_numbers(us_times_to_taipei(out["title"], day), codes))
    for key, field_ in HEADING_KEYS.items():
        for item in (out.get(key) or []) if key in OUTPUT_KEYS[kind] else []:
            if isinstance(item, dict) and isinstance(item.get(field_), str):
                item[field_] = house_numbers(us_times_to_taipei(item[field_], day), codes)
    if (key := stocks_without_reasons(out, kind)) is not None:
        _drop_not_found(out, key)
    return out


# the item goes, never its section (a brief row with the wrong field or without what its field stands on)
ITEM_LEVEL = {"stock_item_mismatch", "item_not_event", "risk_not_ahead", "slot_invalid", "slot_repeated",
              "slot_needs_report", "slot_needs_fact", "slot_not_event"}
_SENT_PATH = re.compile(r"^(?P<key>\w+)(?:\[(?P<i>\d+)\])?(?:\.(?P<sub>para|why|events|relation|caption))?"
                        r"\.sentences\[(?P<j>\d+)\]$")
_ITEM_PATH = re.compile(r"^(?P<key>\w+)\[(?P<i>\d+)\]")
NO_CHART = {"code": "none", "period": "none", "set": "none", "caption": {"sentences": []}}


@dataclass
class Dropped:
    output: dict[str, Any]
    sections: dict[str, list[str]]  # output key -> reasons (codes): the sections taken out as a whole
    title_bad: bool
    highlights_bad: bool
    chart_dropped: bool
    items_dropped: dict[str, list[int]]
    sentences: list[dict[str, Any]] = field(default_factory=list)  # {path, codes, text} of each sentence taken alone


def drop(output: dict[str, Any], problems: list[Problem], kind: str, pack: dict[str, Any] | None = None,
         names: Iterable[str] = ()) -> Dropped:
    """Remove what still has hard problems. Title and highlights are only flagged when they fail (the caller puts the
    rule-made ones instead).

    With the ``pack``: a failing sentence goes alone (a stock item's first sentence, an item's name or ``time_ref``
    take their item with them; a paragraph or item left empty goes too), and what is left is checked again (the
    sentence that went may have carried the semiconductor concentration another one needs), up to three rounds; a
    section that still fails then goes as a whole. Highlights fail only when fewer than the minimum are left.

    Without the pack (nothing could check what is left): a stock item alone, the chart of the day alone, otherwise the
    whole section."""
    d = Dropped(copy.deepcopy(output), {}, False, False, False, {})
    hard = [p for p in problems if p.hard]
    if pack is not None:
        names = list(names)
        for _ in range(3):
            if not hard:
                break
            _drop_parts(d, hard, kind)
            hard = [p for p in validate(d.output, pack, kind, names) if p.hard and not _replaced(d, p)]
    _drop_sections(d, hard, kind)
    return d


def _replaced(d: Dropped, p: Problem) -> bool:
    return (p.key == "title" and d.title_bad) or (p.key == "highlights" and d.highlights_bad) \
        or (p.key == "chart_of_day" and d.chart_dropped)


def _note_section(d: Dropped, key: str, codes: Iterable[str]) -> None:
    reasons = d.sections.setdefault(key, [])
    reasons += [c for c in dict.fromkeys(codes) if c not in reasons]


def _drop_chart(d: Dropped) -> None:
    d.chart_dropped = True
    if isinstance(d.output.get("chart_of_day"), dict):
        d.output["chart_of_day"] = copy.deepcopy(NO_CHART)


def _drop_sections(d: Dropped, hard: list[Problem], kind: str) -> None:
    """A stock item alone, the chart of the day alone, title and highlights flagged, otherwise the whole section."""
    out = d.output
    sections: dict[str, list[str]] = {}
    items: dict[str, list[int]] = {}
    for p in hard:
        if p.code in ITEM_LEVEL:
            if (m := _ITEM_PATH.match(p.path)) is not None:
                items.setdefault(m.group("key"), []).append(int(m.group("i")))
            continue
        if p.key == "title":
            d.title_bad = True
        elif p.key == "highlights":
            d.highlights_bad = True
        elif p.key == "chart_of_day":
            _drop_chart(d)
        elif p.key in OUTPUT_KEYS[kind]:
            sections.setdefault(p.key, []).append(p.code)
    for key, idx in items.items():
        if key in sections:
            continue
        out[key] = [x for i, x in enumerate(out.get(key) or []) if i not in set(idx)]
        d.items_dropped.setdefault(key, []).extend(sorted(set(idx)))
    for key, codes in sections.items():
        out[key] = {"sentences": []} if key == "summary" else []
        _note_section(d, key, codes)


def _empty(key: str, item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    if "sentences" in item:
        return not item.get("sentences")
    if key == "themes":  # a theme stands on its reason (why)
        return not (item.get("why") or {}).get("sentences")
    return not (item.get("para") or {}).get("sentences")


def _drop_parts(d: Dropped, hard: list[Problem], kind: str) -> None:
    """One round of :func:`drop` with the pack: sentences (and the items they take with them) out of ``d.output``."""
    out = d.output
    whole: dict[str, list[str]] = {}
    items: dict[str, dict[int, list[str]]] = {}
    sents: dict[str, dict[tuple[int | None, str | None], dict[int, list[str]]]] = {}
    for p in hard:
        if p.key == "title":
            d.title_bad = True
            continue
        if p.key not in OUTPUT_KEYS[kind]:
            continue
        m = _SENT_PATH.match(p.path)
        if m is not None and p.code not in ITEM_LEVEL:
            i = int(m.group("i")) if m.group("i") is not None else None
            j = int(m.group("j"))
            if p.key in STOCK_KEYS and j == 0 and i is not None:  # the sentence that names the stock
                items.setdefault(p.key, {}).setdefault(i, []).append(p.code)
            else:
                sents.setdefault(p.key, {}).setdefault((i, m.group("sub")), {}).setdefault(j, []).append(p.code)
            continue
        mi = _ITEM_PATH.match(p.path)
        if mi is not None:  # an item's name or time_ref, a stock item's symbol, a review's ref
            items.setdefault(p.key, {}).setdefault(int(mi.group("i")), []).append(p.code)
            continue
        whole.setdefault(p.key, []).append(p.code)

    def take(container: Any, path: str, marks: dict[int, list[str]]) -> None:
        if not isinstance(container, dict):
            return
        kept = []
        for j, s in enumerate(container.get("sentences") or []):
            if j in marks:
                d.sentences.append({"path": f"{path}.sentences[{j}]", "codes": list(dict.fromkeys(marks[j])),
                                    "text": str((s or {}).get("text") or "") if isinstance(s, dict) else ""})
            else:
                kept.append(s)
        container["sentences"] = kept

    for key in dict.fromkeys([*whole, *items, *sents]):
        codes = [*whole.get(key, []), *(c for v in items.get(key, {}).values() for c in v),
                 *(c for v in sents.get(key, {}).values() for cs in v.values() for c in cs)]
        if key == "chart_of_day":
            ch = out.get("chart_of_day")
            if key in whole or not isinstance(ch, dict):
                _drop_chart(d)
                continue
            for marks in sents.get(key, {}).values():
                take(ch.get("caption"), "chart_of_day.caption", marks)
            if not (ch.get("caption") or {}).get("sentences"):
                _drop_chart(d)
            continue
        if key in whole:
            out[key] = {"sentences": []} if key == "summary" else []
            if key == "highlights":
                d.highlights_bad = True
            else:
                _note_section(d, key, codes)
            continue
        if key == "summary":
            for marks in sents.get(key, {}).values():
                take(out.get("summary"), "summary", marks)
            if not (out.get("summary") or {}).get("sentences"):
                out["summary"] = {"sentences": []}
                _note_section(d, key, codes)
            continue
        rows = out.get(key) if isinstance(out.get(key), list) else []
        kept = []
        for i, it in enumerate(rows):
            if i in items.get(key, {}):
                d.items_dropped.setdefault(key, []).append(i)
                continue
            for (ii, sub), marks in sents.get(key, {}).items():
                if ii == i and isinstance(it, dict):
                    take(it if sub is None else it.get(sub), f"{key}[{i}]" + (f".{sub}" if sub else ""), marks)
            if _empty(key, it):
                d.items_dropped.setdefault(key, []).append(i)
                continue
            kept.append(it)
        out[key] = kept
        if key == "highlights":
            if len(kept) < COUNTS[kind]["highlights"][0]:
                d.highlights_bad = True
        elif rows and not kept:
            _note_section(d, key, codes)


def ai_sections_left(output: dict[str, Any], kind: str) -> int:
    """AI sections with text left (title, highlights and the chart of the day not counted)."""
    n = 0
    for key in OUTPUT_KEYS[kind]:
        if key in ("title", "highlights", "chart_of_day"):
            continue
        v = output.get(key)
        if key == "summary":
            n += bool((v or {}).get("sentences"))
        elif v:
            n += 1
    return n


def counts(problems: list[Problem]) -> dict[str, int]:
    out: dict[str, int] = {}
    for p in problems:
        out[p.code] = out.get(p.code, 0) + 1
    return out
