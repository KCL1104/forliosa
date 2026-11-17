"""Rule checks of the writer's JSON (contract §10): every sentence against the data pack it was written from.

``validate(output, pack, kind, names)`` returns :class:`Problem` s (``path`` like ``what_happened[1].sentences[0]``,
``code``, ``detail``, ``hard``). Hard problems lead to one revision, then to dropping the section (:func:`drop`);
soft ones are counted (and :func:`tidy` trims what can be trimmed: extra items, unknown sector names).

The checks, in short: refs exist (F / C / N / W in the pack, X among the verified reports); every number matches a
fact the sentence cites (display or value, rounded to the text's decimals; 億 / 兆 / 萬 scaled) **and** the fact's
subject is named next to it (``number_subject_mismatch``: 外資 and 自營商 swapped); the direction (▲ / 漲 / 買超 …)
agrees with a signed fact; dates come from the pack or the refs; a weekday matches its date and never stands alone;
no forbidden or time word; only listed stocks and allowed sectors (半導體 with its concentration in the same
paragraph); no fund flow and price move of a stock in one sentence; causes need a report (X / W); forward-looking
sentences take one of the three shapes; position numbers are never a reason; the premarket's headline does not
repeat the previous session; no index points; the chart of the day is on the menu.
"""

from __future__ import annotations

import contextlib
import re
import unicodedata
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from forliosa.reports.marketcalc import SECTOR_NAMES
from forliosa.reports.pack import OPTION_METRICS
from forliosa.reports.prompts import COUNTS, FORBIDDEN_WORDS, LENGTHS, OUTPUT_KEYS, STYLE_WORDS, TIME_WORDS

# Index points (美股指數、台指期、夜盤) never appear, in a gathered report or a sentence (§8.5 item 7, §10.2 item 21)
INDEX_POINTS = re.compile(r"(道瓊|標普|S&P|那斯達克|Nasdaq|費城半導體|費半|VIX|台指期|期指|夜盤)"
                          r".{0,12}\d{1,3}(?:,?\d{3})+(?:\.\d+)?\s*點", re.IGNORECASE)
CAUSE = re.compile(r"因為|由於|帶動|拖累|受.{0,10}影響|主因|導致|受惠|受累|推升|壓抑")
OUTLOOK = re.compile(r"將(?!近|軍)|預計|預期|預估|可能|恐(?!慌)|展望|料將|估計|後續|接下來|未來")
FLOW = re.compile(r"買賣超|買超|賣超|淨買|淨賣|持股增減")
P1 = re.compile(r"^已排定[：:]")
P2 = re.compile(r"^〔([^〕]{2,12})〕\s*(?:報導|指出)")
P3 = re.compile(r"^這件事和.{1,20}類股的關係是")
WEEKDAYS = "一二三四五六日"
SIGNED_METRICS = frozenset({
    "index_change", "index_pct", "tr_pct", "otc_change", "otc_pct", "sector_pct", "stock_pct", "stock_contrib",
    "us_pct", "futures_oi_change", "week_pct", "week_points", "mcap_change_est", "reference_pct", "otc_inst_total",
    "otc_inst_foreign", "otc_inst_trust", "otc_inst_dealer",
})
# Sections whose every sentence must take one of the three shapes
PATTERN_ONLY = ("watch", "tonight", "themes", "risks")
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


# -- walking the output ---------------------------------------------------------------------------------------------
def _para_sentences(para: Any, path: str, key: str, sub: str = "") -> Iterator[Sentence]:
    for j, s in enumerate((para or {}).get("sentences") or [] if isinstance(para, dict) else []):
        if isinstance(s, dict):
            yield Sentence(f"{path}.sentences[{j}]", key, path, str(s.get("text") or ""),
                           [str(r) for r in s.get("refs") or []], sub)


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
                yield from _para_sentences(item.get("para"), f"{base}.para", key)


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
    strip: set[str] = field(default_factory=set)
    year: int = 2026

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
    with contextlib.suppress(KeyError, ValueError):
        c.year = date.fromisoformat(pack["edition_date"]).year
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
    c.other_names = sorted({n for n in names if n and len(n) >= 3 and n not in allowed
                            and not any(n in a for a in allowed) and n not in known}, key=len, reverse=True)
    return c


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
        matched_f = [c.facts[r] for r in s.refs if r in c.facts
                     and any(_close_to(n, v) for v in _fact_candidates(c.facts[r]))]
        matched_x = [r for r in s.refs if not r.startswith("F") and any(
            _close_to(n, m.value) for t in _ref_texts(c, r) for m in numbers(t, c.blank))]
        if not matched_f and not matched_x:
            out.append(Problem(s.path, "number_unsourced", _num_text(s.text, n)))
            continue
        clause = _clause_at(text, n.start)
        scope = clause if any(sub in clause for sub in subjects_here) else text
        if matched_f:
            if not any(_subject_in(scope, f) for f in matched_f) and not matched_x:
                out.append(Problem(s.path, "number_subject_mismatch",
                                   f"{_num_text(s.text, n)} 對到 {matched_f[0].get('subject')}"))
                continue
            signed = [f for f in matched_f if f.get("metric") in SIGNED_METRICS
                      and isinstance(f.get("value"), (int, float)) and f["value"] != 0]
            if n.sign and signed and all((1 if f["value"] > 0 else -1) != n.sign for f in signed):
                out.append(Problem(s.path, "direction_mismatch", f"{_num_text(s.text, n)}"))
        elif matched_x:
            # a report's own statement decides whose number it is (an article's passage often holds several)
            by_claim = [r for r in matched_x if r in c.web and any(
                _close_to(n, m.value) for m in numbers(str(c.web[r].get("claim") or ""), c.blank))]
            pool = by_claim or [r for r in matched_x if r in c.web]
            subs = [c.web[r].get("subject") for r in pool if c.web[r].get("subject")]
            if subs and len(subs) == len(pool) and not any(normalize(x) in scope for x in subs):
                out.append(Problem(s.path, "number_subject_mismatch", f"{_num_text(s.text, n)} 對到 {subs[0]}"))


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
    text = normalize(s.text)
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


_OUTLET_ALIASES = {"自由財經": "自由時報", "鉅亨": "鉅亨網", "anue": "鉅亨網", "cna": "中央社"}


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
    if INDEX_POINTS.search(text):
        out.append(Problem(s.path, "index_points", INDEX_POINTS.search(text).group(0)))  # type: ignore[union-attr]
    _check_numbers(c, s, text, out)
    _check_dates(c, s, out)
    # stocks: codes in parentheses and Taiwan names not on the list
    for m in re.finditer(r"[（(]\s*(\d{4,6}[A-Z]?)\s*[)）]", text):
        if m.group(1) not in c.stock_names:
            out.append(Problem(s.path, "stock_not_allowed", m.group(1)))
    if c.other_names:
        t = _blank(text, [*c.stock_names.values(), *(f.get("subject") or "" for f in c.facts.values())])
        for name in c.other_names:
            if name in t:
                out.append(Problem(s.path, "stock_not_allowed", name))
                t = t.replace(name, "＿")
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
    if (must or OUTLOOK.search(text)) and not _pattern_ok(c, s, text):
        out.append(Problem(s.path, "outlook_pattern", "句型不符" if must else OUTLOOK.search(text).group(0)))  # type: ignore[union-attr]
    if s.key in OPTION_REASON and (s.key != "themes" or s.sub == "why"):
        for r in s.refs:
            f = c.facts.get(r)
            if f and f.get("metric") in OPTION_METRICS:
                out.append(Problem(s.path, "options_as_reason", r))
    if c.kind == "premarket" and s.key == "highlights":
        for r in s.refs:
            f = c.facts.get(r)
            if f and f.get("group") == "prev_session":
                out.append(Problem(s.path, "repeats_close_report", r))
    return out


# -- whole output -------------------------------------------------------------------------------------------------
def _check_title(c: Ctx, title: str) -> list[Problem]:
    out: list[Problem] = []
    text = normalize(title)
    if not text:
        return [Problem("title", "count_out_of_range", "沒有標題")]
    for w in (*FORBIDDEN_WORDS, *TIME_WORDS):
        if w in text:
            out.append(Problem("title", "forbidden_word", w))
    if INDEX_POINTS.search(text):
        out.append(Problem("title", "index_points"))
    pool = [f for f in c.facts.values()]
    for n in numbers(title, c.blank):
        hits = [f for f in pool if any(_close_to(n, v) for v in _fact_candidates(f))]
        if not hits:
            hits_x = [x for x in c.web.values() if any(_close_to(n, m.value)
                                                       for m in numbers(str(x.get("quote") or ""), c.blank))]
            if not hits_x:
                out.append(Problem("title", "number_unsourced", _num_text(title, n)))
            continue
        if c.kind == "premarket" and all(f.get("group") == "prev_session" for f in hits):
            out.append(Problem("title", "repeats_close_report", _num_text(title, n)))
    for md in _dates_in(text):
        if md not in c.allowed_dates:
            out.append(Problem("title", "date_not_sourced", f"{md[0]}/{md[1]}"))
    for m in _LONE_WD.finditer(text):
        out.append(Problem("title", "weekday_mismatch", m.group(0)))
    for m in re.finditer(r"[（(]\s*(\d{4,6}[A-Z]?)\s*[)）]", text):
        if m.group(1) not in c.stock_names:
            out.append(Problem("title", "stock_not_allowed", m.group(1)))
    if not 12 <= len(title) <= 48:
        out.append(Problem("title", "too_long" if len(title) > 48 else "count_out_of_range", str(len(title)),
                           hard=False))
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
        if n > para_max * 1.25:
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
    for key in ("watch", "tonight", "themes"):
        for i, item in enumerate(output.get(key) or []):
            for sec in (item or {}).get("sectors") or []:
                if sec not in SECTOR_NAMES:
                    out.append(Problem(f"{key}[{i}].sectors", "sector_unknown", str(sec), hard=False))
            ref = (item or {}).get("time_ref")
            if key != "themes" and ref and ref not in c.cal:
                out.append(Problem(f"{key}[{i}].time_ref", "bad_ref", str(ref)))
    for i, item in enumerate(output.get("last_week_review") or []):
        ref = (item or {}).get("ref")
        if ref and ref not in c.cal:
            out.append(Problem(f"last_week_review[{i}]", "bad_ref", str(ref)))
    return out


def validate(output: dict[str, Any], pack: dict[str, Any], kind: str, names: Iterable[str] = ()) -> list[Problem]:
    """Every problem of ``output`` (the writer's JSON) against ``pack``."""
    c = context(pack, kind, names)
    out: list[Problem] = []
    out += _check_title(c, str(output.get("title") or ""))
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
    return out


def mentions_anthropic(output: dict[str, Any], kind: str) -> bool:
    texts = [str(output.get("title") or ""), *(s.text for s in sentences(output, kind))]
    return any(re.search(r"anthropic|claude", t, re.IGNORECASE) for t in texts)


# -- trimming and dropping -------------------------------------------------------------------------------------------
def tidy(output: dict[str, Any], kind: str) -> dict[str, Any]:
    """Soft fixes in a copy: extra items cut to the maximum, unknown sector names removed, ``time_ref`` that is not a
    calendar id kept as given (the validator flags it)."""
    import copy

    out = copy.deepcopy(output)
    for key, (_lo, hi) in COUNTS[kind].items():
        if isinstance(out.get(key), list) and len(out[key]) > hi:
            out[key] = out[key][:hi]
    for key in ("watch", "tonight", "themes"):
        for item in out.get(key) or []:
            if isinstance(item, dict):
                item["sectors"] = [s for s in item.get("sectors") or [] if s in SECTOR_NAMES]
    return out


ITEM_LEVEL = {"stock_item_mismatch"}


@dataclass
class Dropped:
    output: dict[str, Any]
    sections: dict[str, list[str]]  # output key -> reasons (codes)
    title_bad: bool
    highlights_bad: bool
    chart_dropped: bool
    items_dropped: dict[str, list[int]]


def drop(output: dict[str, Any], problems: list[Problem], kind: str) -> Dropped:
    """Remove what still has hard problems: a stock item alone, the chart of the day alone, otherwise the whole
    section (output key). Title and highlights are only flagged (the caller puts the rule-made ones instead)."""
    import copy

    out = copy.deepcopy(output)
    sections: dict[str, list[str]] = {}
    items: dict[str, list[int]] = {}
    title_bad = highlights_bad = chart_dropped = False
    hard = [p for p in problems if p.hard]
    for p in hard:
        if p.code in ITEM_LEVEL:
            m = re.match(r"(\w+)\[(\d+)\]", p.path)
            if m:
                items.setdefault(m.group(1), []).append(int(m.group(2)))
            continue
        if p.key == "title":
            title_bad = True
        elif p.key == "highlights":
            highlights_bad = True
        elif p.key == "chart_of_day":
            chart_dropped = True
        else:
            sections.setdefault(p.key, [])
            if p.code not in sections[p.key]:
                sections[p.key].append(p.code)
    for key, idx in items.items():
        if key in sections:
            continue
        keep = [x for i, x in enumerate(out.get(key) or []) if i not in set(idx)]
        out[key] = keep
    for key in sections:
        out[key] = {"sentences": []} if key == "summary" else []
    if chart_dropped and isinstance(out.get("chart_of_day"), dict):
        out["chart_of_day"] = {"code": "none", "period": "none", "set": "none", "caption": {"sentences": []}}
    return Dropped(out, sections, title_bad, highlights_bad, chart_dropped, items)


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
