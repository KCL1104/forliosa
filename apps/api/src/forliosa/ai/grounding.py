"""Server-side grounding check for chat answers that used web search or web fetch.

The system prompt tells the model to state only facts backed by tool results or cited web sources. This check
catches what slips through: after a turn that used ``web_search`` / ``web_fetch``, every sentence of the answer
that overlaps no cited text block and reads like a factual news claim is listed in a ``grounding`` SSE event
(and stored with the answer), so the UI can mark it 「無來源」.

"Reads like a news claim" is a heuristic: a strong news verb (宣布, 批准, 收購, 簽署 …), or a weaker one (通過,
發布, 投資, 降息 …) together with a date or a named actor (董事會, 公司, 央行, a Latin-script name such as
OpenAI, a 「quoted」 name). Numbers that came from our own tools carry no citation by design, so plain price /
holding sentences are never flagged. Offsets are Unicode code-point offsets into the answer text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_STRONG = re.compile(r"宣布|宣佈|批准|核准|決議|收購|併購|簽署|簽約|簽訂|斥資|注資|入股|得標|裁員|起訴|裁罰|罰款|"
                     r"下市|任命|辭任|接任|停產|擴產|設廠|announc|approv|acquir|merger", re.IGNORECASE)
_WEAK = re.compile(r"通過|發布|發表|推出|公告|公布|增資|減資|上調|下修|調升|調降|升息|降息|出售|成立|合併|投資|"
                   r"合作|結盟|invest|launch|sign", re.IGNORECASE)
_DATE = re.compile(r"\d{1,4}\s*[/年月-]\s*\d{1,2}|\d{1,2}\s*月\s*\d{1,2}\s*日|昨天|今天|今日|昨日|上週|本週|"
                   r"上個月|本月|日前|近日|稍早|(?<!\d)(?:19|20)\d{2}(?!\d)")
_ACTOR = re.compile(r"董事會|股東會|公司|集團|政府|主管機關|金管會|央行|聯準會|法院|交易所|執行長|董事長|"
                    r"(?<![A-Za-z0-9])[A-Z][A-Za-z0-9&.\-]+|「[^」]{1,30}」")
_SENTENCE = re.compile(r"[^。！？!?；;\n]+[。！？!?；;]*")

REASON = "uncited_news_claim"


@dataclass(frozen=True)
class Segment:
    """One text block of the answer: ``[start, end)`` in the answer text, and whether it carries citations."""

    start: int
    end: int
    cited: bool


def sentences(text: str) -> list[tuple[int, int]]:
    out = []
    for m in _SENTENCE.finditer(text):
        a, b = m.start(), m.end()
        while a < b and text[a].isspace():
            a += 1
        while b > a and text[b - 1].isspace():
            b -= 1
        if b > a:
            out.append((a, b))
    return out


def check(text: str, segments: list[Segment]) -> list[dict[str, Any]]:
    """Uncited sentences that look like news claims: ``[{index, start, end, text, reason, signals}]``."""
    cited = [(s.start, s.end) for s in segments if s.cited]
    out: list[dict[str, Any]] = []
    for i, (a, b) in enumerate(sentences(text)):
        if any(ca < b and a < cb for ca, cb in cited):
            continue
        sentence = text[a:b]
        strong, weak = _STRONG.search(sentence), _WEAK.search(sentence)
        date, actor = _DATE.search(sentence), _ACTOR.search(sentence)
        if not (strong or (weak and (date or actor))):
            continue
        signals = [f"verb:{(strong or weak).group(0)}"]  # type: ignore[union-attr]
        if date:
            signals.append("date")
        if actor:
            signals.append(f"actor:{actor.group(0)}")
        out.append({"index": i, "start": a, "end": b, "text": sentence, "reason": REASON, "signals": signals})
    return out
