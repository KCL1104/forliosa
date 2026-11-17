"""The market reports' prompts and output schemas (contract §8.3, §9, §11): the gathering's system prompt and topic
briefs, the writer's system prompt (no date in it, so it is cached across editions), each kind's instructions and JSON
schema, and the compliance read's prompt and schema.

The writer never sees the web: it gets the data pack (F / C / N / W ids) and the verified reports the gathering kept
(X ids, with their quotes). Every sentence it writes carries ``refs``; the server turns them into footnotes and checks
them (:mod:`.validate`). Its forward-looking sentences may take only three shapes (:data:`OUTLOOK_PATTERNS`).
``PROMPT_VERSION`` is stored with every version and run.
"""

from __future__ import annotations

import copy
import json
from typing import Any

PROMPT_VERSION = "mr-2026-11-17d"

# The words no AI sentence may hold (validator §10.2 item 5); the time words are listed apart for the prompt.
FORBIDDEN_WORDS = (
    "目標價", "合理價", "低估", "高估", "便宜", "昂貴", "支撐", "壓力", "停損", "停利", "進場", "出場", "買點", "賣點",
    "加碼", "減碼", "布局", "逢低", "逢高", "追價", "續抱", "獲利了結", "建議", "推薦", "首選", "口袋名單", "值得關注",
    "值得留意", "飆股", "強勢股", "潛力股", "補漲", "可望", "有望", "看好", "看淡", "看多", "看空", "偏多", "偏空",
    "後市", "將會", "恐將", "機會", "勝率", "佈局", "評等", "評級", "利空出盡", "利多出盡",
)
TIME_WORDS = ("明天", "明日", "後天", "今天", "今日", "今晚", "今早", "今晨", "昨天", "昨日", "昨晚", "昨夜",
              "前天", "前一晚", "明晨", "明早", "明晚", "隔日", "隔天", "次日", "翌日", "下個交易日", "下一個交易日",
              "本週", "本周", "上週", "上周", "下週", "下周", "隔週", "週末", "上月", "下月")
STYLE_WORDS = ("整體而言", "整體來看", "總的來說", "值得注意", "值得一提", "此外", "亮眼", "強勁", "疲弱", "穩健",
               "！", "!", "—", "――")
# The three shapes a sentence about what comes next may take (validator §10.2 item 14)
OUTLOOK_PATTERNS = ("已排定：…（引用 C，或寫明時間的 X）",
                    "〔來源〕報導市場關注…（引用該媒體的 X；不寫任何方向或看法）",
                    "這件事和 X 類股的關係是…（引用 X、C，或依產業別的 F）")

# -- gathering (§8.3) ---------------------------------------------------------------------------------------------
GATHER_SYSTEM = """\
你替財經編輯找具名媒體的報導，只找「已經發生的事」與「已排定的事」。你不評論、不推論、不預測。

做法
- 用 web_search 查，次數用到使用者訊息寫的上限：一次查不完整，就換關鍵字再查。中文媒體用中文關鍵字，外電用英文關鍵字。\
只採用使用者訊息寫的時間窗之內發布的報導。
- 只引用新聞報導頁（有標題、記者或發布時間的文章）。報價頁、行情頁、指數頁、排行頁（個股或指數的即時報價、走勢圖、\
排行）不要引用。
- 每則事實寫成一段，段落之間空一行。每段開頭是方括號 KEY，例如 [US.market]；KEY 只能用使用者訊息列出的那幾個。
- 句子寫成「〔媒體名稱〕報導，…」。要用到的數字照原文寫，不換算、不四捨五入。
- 每一段都必須引用搜尋結果（引用那篇報導裡寫這件事的原句）。沒有引用的段落一律丟掉，所以找不到出處的事不要寫。
- 美股、台積電 ADR、台指期夜盤的事實，句子裡一定要寫美股交易日，例如「美股 11/16」；美股交易日是美國當地的日期，\
不是台灣的日期。
- 找不到就少寫，不要湊。

不收
- 個股評等、目標價、調升調降評等。
- 指數或股價的預測區間、點位預測。
- 指數點數：美股指數、台指期、夜盤只收百分比，不收點數。
- 對市場的判讀，例如「利空出盡」「利多出盡」「錯殺」；就算是報導引述別人的話也不收。
- 論壇、社群、部落格、個股報價頁。
- 你自己的看法。

最後只輸出這些段落，不加前言或結語。"""
# The one more turn of a topic whose [KEY] paragraphs came mostly without citations (gather.call_topic)
CITE_AGAIN = ("上面的段落大多沒有引用搜尋結果，沒有引用的段落都會被丟掉。"
              "請用已經搜到的結果，把所有要保留的事實重寫一次：每段開頭是 [KEY]，"
              "每一段都要引用搜尋結果裡寫這件事的原句；找不到出處的就不要寫。只輸出這些段落。")

# per kind: topic -> (quota, what to find, allowed KEY prefixes / keys). Quotas: 2–3 searches a topic (the
# 2026-11-17 dry run: one search a topic, its ten results often quote pages or older stories)
TOPICS: dict[str, dict[str, tuple[int, str, tuple[str, ...]]]] = {
    "premarket": {
        "US_MARKET": (3, "美股與半導體類股、台積電 ADR 的隔夜漲跌與報導寫的原因（只收百分比）",
                      ("US.market", "US.semis", "ADR.tsm")),
        "MACRO": (2, "昨晚公布的美國或主要國家總經數據結果、Fed 官員談話", ("MACRO.",)),
        "OVERSEAS_COS": (3, "和台股供應鏈相關的海外公司消息（財報、營運、產品）", ("CO.",)),
        "NIGHT": (2, "台指期夜盤：只取具名媒體寫的漲跌幅（百分比），不收點數", ("NIGHT.tx_pct",)),
        "EVENT_TIMES": (2, "今天已排定的事件與公布時間（台北時間），例如法說會、數據公布", ("EVENT.",)),
        "SPARE": (2, "以上主題不夠時補充（同樣只收已發生或已排定的事）",
                  ("US.market", "US.semis", "ADR.tsm", "MACRO.", "CO.", "NIGHT.tx_pct", "EVENT.")),
    },
    "close": {
        "MARKET_TODAY": (3, "今天台股大盤的報導原因；報導寫的成交金額", ("TW.reason", "TW.turnover_media")),
        "TWSE_INST": (2, "今天上市三大法人買賣超金額（外資、投信、自營商、合計），約 15:30 的新聞",
                      ("TWSE_INST.foreign", "TWSE_INST.trust", "TWSE_INST.dealer", "TWSE_INST.total")),
        "STOCK_REASONS": (3, "下列個股今天漲跌的報導原因", ("STOCK.",)),
        "TONIGHT": (2, "今晚（台北時間）已排定的美股財報與數據公布", ("EVENT.", "US.earnings.")),
    },
    "weekly": {
        "WEEK_MARKET": (3, "上週台股大盤的報導原因與成交量能", ("WEEK.market",)),
        "TWSE_INST_WEEK": (2, "上週上市三大法人買賣超合計", ("TWSE_INST.",)),
        "SECTORS_WEEK": (3, "下列類股上週漲跌的報導原因", ("WEEK.sector.",)),
        "US_WEEK": (3, "上週美股與半導體類股、台積電 ADR 的漲跌與原因（只收百分比）", ("US.",)),
        "MACRO_RESULTS": (2, "上週公布的總經數據結果、央行決議", ("MACRO.",)),
        "THEMES": (3, "媒體報導市場關注、而且有日期的主題（下週要公布的數據、會議、財報、政策）", ("THEME.",)),
        "RISKS": (2, "媒體報導可能讓市場關注點改變的事（具名來源，不收預測）", ("RISK.",)),
    },
}
LONG_HOLIDAY_EXTRA = {"US_MARKET": 2, "MACRO": 2}  # the first premarket after ≥3 weekday closures


def key_allowed(key: str, allowed: tuple[str, ...]) -> bool:
    """``allowed`` holds exact keys and prefixes ending with a dot (``MACRO.`` admits ``MACRO.cpi``)."""
    for a in allowed:
        if a.endswith(".") and key.startswith(a) and len(key) > len(a):
            return True
        if key == a:
            return True
    return False


def topic_brief(kind: str, topic: str, *, window: tuple[str, str], edition_label: str,
                us_sessions: list[str], names: list[str] | None = None, quota: int | None = None) -> str:
    """The user message of one gathering call: what to find, the window, the searches it may make, the KEYs it may
    use."""
    default_quota, what, keys = TOPICS[kind][topic]
    quota = default_quota if quota is None else quota
    lines = [f"報告：{ {'premarket': '盤前重點', 'close': '盤後重點', 'weekly': '市場週報'}[kind]} {edition_label}",
             f"時間窗（台北時間）：{window[0]} 到 {window[1]}；時間窗外的報導不要用。",
             f"要找：{what}。"]
    if quota > 1:
        lines.append(f"搜尋最多 {quota} 次：第一次查完先看結果，再換關鍵字補查還缺的部分。")
    if kind == "close":
        lines.append("今天的報導要看得出發布時間：請一併引用報導裡寫發布日期與時間的那一句"
                     f"（例如「{window[0][:10]} 15:32」）；只寫日期、看不出今天幾點發布的報導不會被採用。")
    if us_sessions:
        lines.append("涵蓋的美股交易日：" + "、".join(us_sessions) + "（美股的事實要寫是哪一天）。")
    if names:
        lines.append("要查的對象：" + "、".join(names) + "。")
    lines.append("允許的 KEY：" + "、".join(f"{k}<名稱>" if k.endswith(".") else k for k in keys)
                 + "（<名稱> 用英文小寫與底線，例如 MACRO.cpi、STOCK.2330）。")
    return "\n".join(lines)


# -- writing (§9.2) -----------------------------------------------------------------------------------------------
WRITER_SYSTEM = f"""\
你是 Forliosa 的財經編輯。Forliosa 是台灣的股票記帳 App。你依「資料包」和「已驗證的報導」（X 編號），整理已經發生的事\
與已排定的事件，寫成一份市場報告。每份報告只寫一次，所有登入的使用者看到的內容都一樣，不針對任何人的持股或財務狀況。你\
沒有網路工具，只能用資料包裡的東西。

# 可以寫的只有五種
1. 資料包的數字（F 編號），照抄 display 的寫法，可以在前面加「約」。
2. 已排定的事件：行事曆（C 編號），或寫明時間的報導（X 編號）。
3. 具名來源的說法：「〔媒體〕報導…」，引用那則 X。
4. 一件事和哪些類股有關：依公司產業別或報導原文，只寫關係，不寫會漲會跌。
5. 過去的比較：當天或那一週的漲跌、和大盤的差距、類股之間的差距。

# 不能寫
- 你自己對大盤、類股、個股的看法、展望、方向、機率或情緒判讀。
- 個股方向、關注名單、目標價、合理價、支撐、壓力、停損、停利、買賣點、加減碼、進出場。
- 期貨、選擇權、夜盤的方向判斷；未平倉、P/C 比只寫數字，不能拿來當「為什麼被關注」的理由。
- 個股評等、目標價、別人預測的指數或股價區間（就算報導裡有也不寫）。
- 美股指數或台指期的點數；美股只寫 ETF、ADR 與報導裡的百分比。
- 沒有出處的原因：有「因為、由於、帶動、拖累、受…影響、主因、導致、受惠、推升、壓抑」的句子，refs 一定要有 X 或 W。找\
不到報導就不寫原因。

# 講到之後的事，只能用三種句型（每一句都要是其中一種）
1. 「已排定：…」，refs 放 C，或寫明時間的 X。
2. 「〔媒體〕報導市場關注…」，refs 放那家媒體的 X。只寫市場關注哪件事，不轉述任何人對大盤、類股、個股會怎麼走的看法。
3. 「這件事和○○類股的關係是…」，refs 放 X、C，或依產業別的 F。
有「將、預計、預期、預估、可能、恐、展望、估計、後續、接下來、未來」的句子，都必須是這三種之一，而且不能有「走高、走低、\
反彈、回檔、震盪、樂觀、悲觀」這類方向或看法的字。

# 每一句都有出處
- 輸出以「句」為單位：每句是 {{"text": "…", "refs": ["F001", "X003"]}}。refs 列出這一句用到的所有編號，不能空。
- 不自己算新的數字：不相加、不相減、不換算、不算平均或差距。資料包沒有的數字就不寫。
- 漲跌用「▲」「▼」或「漲」「跌」，和數字的正負一致；照 display 的小數位數寫。
- 台股只能寫 stocks 名單裡的公司，寫法「名稱（代號）」。名單外的台股公司與代號都不能出現。
- 海外公司（例如 Nvidia、三星）照報導（X）原文寫名稱，不加代號，也不要改寫成「美國 AI 晶片龍頭」這類代稱。
- 法人買賣超和同一檔股票的漲跌不放在同一句。
- 類股只能談 rules 指定的類股；談半導體時，同一段要帶它的集中度（「主要由台積電構成，約 77%」那一筆 F）。

# 時間
- 只寫日期與星期，例如「11/18（三）」「11/23–11/27」。不寫{ "、".join(TIME_WORDS) }這類詞，也不要只寫星期。
- 美股的數字一定寫是哪一天，例如「美股 11/17」。
- 日期只能用資料包 dates 與 refs 裡出現的日期，不要自己推算。
- 幾點幾分一律是台北時間：C 的 time_taipei 已經是台北時間，照寫。報導只給美國當地時間的，寫成「美東 11/18 14:00」（日\
期加 24 小時制），伺服器會在後面補上台北時間；不要自己換算，也不要寫「美國時間下午 2:00」。

# 缺的資料不寫進正文
- 沒有的資料、沒有授權的行情、沒找到的報導，頁面會自己標示。正文不寫「這份未開放」「不列」「未取得」「授權未確\
認」「資料包沒有」「只引用媒體報導」「未找到報導」這類說明，也不要提「資料包」。那一段沒有東西可寫就少寫或不寫。
- 只有三個地方照規定寫：個股項目沒有原因時寫「未找到報導」；上週行事曆回顧沒有結果時寫「未找到報導」；盤後籌碼沒有上市\
三大法人的報導時寫「上市三大法人尚未取得可引用的報導」。

# 不重複
- 數字欄（numbers）已經列出的數字，段落裡不要整串重抄；一段最多提兩個。
- 盤前重點的標題與重點先講隔夜與今天，不重講前一個交易日上市的漲跌（already_reported 是上一份盤後重點寫過的）。

# 禁用字（任何地方都不能出現）
{ "、".join(FORBIDDEN_WORDS) }

# 文字風格
繁體中文、台灣用語。句子短、直接，像財經版的整理稿。不用「整體而言」「值得注意的是」「此外」「總的來說」這類連接語；不\
寫評價詞（亮眼、強勁、疲弱、穩健）；不用驚嘆號與破折號；純文字，不用 Markdown。提到 Anthropic 或 Claude 時照寫事實，不\
加評語。只寫結果與依據編號，不寫推論過程。

# 輸出
只輸出一個符合 JSON schema 的物件。段落的 key 由 schema 決定，不能自己加。"""


SPEC: dict[str, dict[str, Any]] = {
    "premarket": {
        "highlights": "3 點",
        "length": "AI 寫的部分合計 1,200–1,800 字；標題 20–36 字",
        "sections": """- title：標題，20–36 字，只寫事實，先講隔夜與今天。
- highlights：3 點，每點一段（1–2 句）。不能用前一個交易日上市的數字（group=prev_session 的 F）。
- overnight：隔夜要聞 3–5 段，每段 1–3 句：美股 ETF 與台積電 ADR（F，寫美股日期）、半導體、總經與 Fed、和台股相關的海\
外公司（X）。
- evening_notes：前一晚才到的資料 0–3 段（上櫃漲跌家數、上櫃法人估算金額、外資台指期未平倉、P/C 比、匯率；F）。只寫數\
字與比較，不寫方向。不能用前一個交易日的收盤數字（group=prev_session 的 F，例如櫃買指數、加權指數）。
- watch：這一天市場在看什麼，2–4 項。每一項都要是行事曆（C）或報導（X）裡的事件，time_ref 或 refs 要有那個 C 或 X\
（開盤、收盤、前一個交易日的漲跌都不是事件）。每項：event（事件名稱，只寫事件本身，例如「鴻海法說會」；和標題一樣會\
檢查）、time_ref（C 編號，沒有就空字串）、sectors（相關類股，必須\
是 32 類之一，沒有就空陣列）、para（每一句都要是三種句型之一）。
- chart_of_day：從可用選單挑一張今日圖，caption 寫 2–3 句；不需要就 code 填 "none"。""",
    },
    "close": {
        "highlights": "3 點",
        "length": "AI 寫的部分合計 1,500–2,500 字；標題 20–36 字",
        "sections": """- title：標題，20–36 字，只寫事實。
- highlights：3 點，每點一段（1–2 句）。
- what_happened：今天發生什麼，2–4 段、合計 300–500 字。原因一定要有 X 或 W；沒有報導就不寫原因。可以寫背離：漲跌家數\
和指數方向、0050 和加權指數的差距。
- sectors：類股 1–2 段，只談 rules 指定的類股。
- stocks：權值股與個股，最多 10 項，每項一檔：symbol（stocks 名單的 symbol）、para 的第一句以「名稱（代號）」開頭。寫\
漲跌幅、（權值股）點數貢獻「約 ▼1,070 點（估算）」；有 X 或 W 就加一句原因，沒有就寫「未找到報導」。
- chips：籌碼 1–2 段。上市三大法人只能引用報導（X）；沒有就寫「上市三大法人尚未取得可引用的報導」。期交所與櫃買中心晚\
上公布的法人資料由伺服器 23:45 補表，你不用寫。
- tonight：這份報告日期當天晚上，與下一個台股交易日已排定的事 0–3 項（ITEM，同 watch 的寫法，每一項也要有 C 或 X；時間\
寫日期，例如「11/18（三）晚間」）。
- chart_of_day：從可用選單挑一張今日圖，caption 寫 2–3 句；不需要就 code 填 "none"。""",
    },
    "weekly": {
        "highlights": "3–5 點",
        "length": "AI 寫的部分合計 3,000–4,500 字；資料不夠的段落寫短，不要湊字",
        "sections": """- title：標題，20–36 字，只寫事實。
- summary：一段總結（1–3 句）。
- highlights：3–5 點。
- market_week：上週大盤 2–3 段：加權與櫃買的週漲跌、全週成交金額、報導寫的原因（X）。
- sectors_week：類股一週 1–2 段，只談 rules 指定的類股。
- stocks_week：權值股與個股，每項一檔（同盤後 stocks 的寫法），最多 10 項。
- chips_week：籌碼與匯率 1–2 段：外資台指期淨未平倉的週變化、P/C 比、上櫃法人估算金額、匯率；上市法人只引用報導。
- global_week：國際 2–4 段：美股 ETF 與 ADR 的週漲跌（F）、總經數據結果（X）。
- last_week_review：上週行事曆回顧，每項 ref 是回顧週的 C 編號，para 寫結果（有 X 才寫結果，沒有就寫「未找到報導」）。
- themes：市場關注的主題 3–5 個：theme（名稱）、why（為什麼被關注，要有 X，用句型 2）、events（要公布的數字或事件，句\
型 1，refs 放 C 或 X）、sectors（32 類之一）、relation（句型 3）。
- risks：可能讓市場關注點改變的事 2–4 段，每段一項、一定要有具名來源（X），用句型 2，不寫立場。
- chart_of_day：從可用選單挑一張本週圖，caption 寫 2–3 句；不需要就 code 填 "none"。""",
    },
}

# Output keys of each kind, in order (the server's sections follow §12.3)
OUTPUT_KEYS = {
    "premarket": ("title", "highlights", "overnight", "evening_notes", "watch", "chart_of_day"),
    "close": ("title", "highlights", "what_happened", "sectors", "stocks", "chips", "tonight", "chart_of_day"),
    "weekly": ("title", "summary", "highlights", "market_week", "sectors_week", "stocks_week", "chips_week",
               "global_week", "last_week_review", "themes", "risks", "chart_of_day"),
}

# Count limits (min, max) checked by the server (validator §10.2 item 18)
COUNTS: dict[str, dict[str, tuple[int, int]]] = {
    "premarket": {"highlights": (3, 3), "overnight": (3, 5), "evening_notes": (0, 3), "watch": (2, 4)},
    "close": {"highlights": (3, 3), "what_happened": (2, 4), "sectors": (1, 2), "stocks": (0, 10), "chips": (1, 2),
              "tonight": (0, 3)},
    "weekly": {"highlights": (3, 5), "market_week": (1, 4), "sectors_week": (1, 2), "stocks_week": (0, 10),
               "chips_week": (1, 2), "global_week": (1, 4), "last_week_review": (0, 10), "themes": (3, 5),
               "risks": (2, 4)},
}
# Length limits in characters of AI text: (paragraph max, total max)
LENGTHS = {"premarket": (300, 1800), "close": (400, 2500), "weekly": (500, 4500)}


# The shared shapes are written once under ``$defs`` and referenced with ``$ref``: the API compiles the schema into a
# grammar, and the weekly schema with every paragraph spelled out inline (5.6 KB) was refused as "too large".
def _ref(name: str) -> dict[str, Any]:
    return {"$ref": f"#/$defs/{name}"}


def _arr(item: dict[str, Any]) -> dict[str, Any]:
    return {"type": "array", "items": item}


def _obj(props: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


_DEFS: dict[str, dict[str, Any]] = {
    "sent": _obj({"text": {"type": "string"}, "refs": _arr({"type": "string"})}),
    "para": _obj({"sentences": _arr(_ref("sent"))}),
    "item": _obj({"event": {"type": "string"}, "time_ref": {"type": "string"}, "sectors": _arr({"type": "string"}),
                  "para": _ref("para")}),
    "stock": _obj({"symbol": {"type": "string"}, "para": _ref("para")}),
}


def _chart(codes: list[str]) -> dict[str, Any]:
    return _obj({"code": {"type": "string", "enum": [*codes, "none"]},
                 "period": {"type": "string", "enum": ["day", "week", "none"]},
                 "set": {"type": "string", "enum": ["top5_weight", "gainers", "losers", "none"]},
                 "caption": _ref("para")})


def _paras() -> dict[str, Any]:
    return _arr(_ref("para"))


def _root(props: dict[str, Any], *defs: str) -> dict[str, Any]:
    out = _obj(props)
    out["$defs"] = {k: copy.deepcopy(_DEFS[k]) for k in ("sent", "para", *defs)}
    return out


def schema(kind: str, chart_codes: list[str]) -> dict[str, Any]:
    """The writer's output schema of ``kind`` (counts are checked by the server, not the schema)."""
    title = {"type": "string"}
    if kind == "premarket":
        return _root({"title": title, "highlights": _paras(), "overnight": _paras(), "evening_notes": _paras(),
                      "watch": _arr(_ref("item")), "chart_of_day": _chart(chart_codes)}, "item")
    if kind == "close":
        return _root({"title": title, "highlights": _paras(), "what_happened": _paras(), "sectors": _paras(),
                      "stocks": _arr(_ref("stock")), "chips": _paras(), "tonight": _arr(_ref("item")),
                      "chart_of_day": _chart(chart_codes)}, "item", "stock")
    review = _obj({"ref": {"type": "string"}, "para": _ref("para")})
    theme = _obj({"theme": {"type": "string"}, "why": _ref("para"), "events": _ref("para"),
                  "sectors": _arr({"type": "string"}), "relation": _ref("para")})
    return _root({"title": title, "summary": _ref("para"), "highlights": _paras(), "market_week": _paras(),
                  "sectors_week": _paras(), "stocks_week": _arr(_ref("stock")), "chips_week": _paras(),
                  "global_week": _paras(), "last_week_review": _arr(review), "themes": _arr(theme),
                  "risks": _paras(), "chart_of_day": _chart(chart_codes)}, "stock")


def available_charts(pack: dict[str, Any]) -> list[str]:
    return [m["code"] for m in pack.get("charts_menu") or [] if m.get("available")]


PACK_FOR_WRITER = ("kind", "kind_label", "edition_date", "edition_label", "period", "next_period", "cutoff",
                   "publish_target", "dates", "facts", "calendar", "filings", "research", "web", "stocks", "sectors",
                   "missing", "strip", "already_reported", "rules", "charts_menu", "fixed_charts", "disagreements")


def pack_json(pack: dict[str, Any]) -> str:
    """The data pack as the writer reads it (W quotes and X quotes included; nothing else of the server's)."""
    return json.dumps({k: pack[k] for k in PACK_FOR_WRITER if k in pack}, ensure_ascii=False, separators=(",", ":"))


def kind_instructions(kind: str, pack: dict[str, Any]) -> str:
    spec = SPEC[kind]
    menu = [m for m in pack.get("charts_menu") or [] if m.get("available")]
    strip = [f["label"] for f in pack.get("facts") or [] if f["id"] in set(pack.get("strip") or [])]
    lines = [
        f"# 這次要寫的報告：{pack.get('kind_label')} {pack.get('edition_label')}",
        f"資料截止：{pack.get('cutoff')}；發布目標：{pack.get('publish_target')}。",
        "",
        "# 各段要寫什麼",
        spec["sections"],
        "",
        f"# 長度：{spec['length']}；重點 {spec['highlights']}。",
        "",
        "# 今日圖",
        f"伺服器已經放好固定圖（{'、'.join(pack.get('fixed_charts') or [])}），你不用處理。"
        "可以從下面可用的選單另外挑 1 張；不需要就填 none：",
        json.dumps(menu, ensure_ascii=False) if menu else "（這份沒有可選的圖：code 填 none）",
        "",
        "# 數字欄已經列出（段落不要整串重抄）",
        "、".join(strip) if strip else "（無）",
        "",
        "# 資料包的規則",
        *("- " + r for r in pack.get("rules") or []),
        "- 句型只能是：" + "；".join(OUTLOOK_PATTERNS),
    ]
    lines.append("- 上面說的名單外股票指台股；海外公司照報導寫名稱。")
    if pack.get("missing"):
        lines += ["", "# 缺的資料（頁面會標示；正文不要寫這些，也不要說明缺了什麼，更不要猜）",
                  *("- " + m["text"] for m in pack["missing"])]
    if not pack.get("web"):
        lines += ["", "這份沒有已驗證的報導（X）：不要寫任何報導或原因。個股項目的原因寫「未找到報導」，"
                  "其他段落不寫原因。"]
    return "\n".join(lines)


def revise_message(problems: list[dict[str, Any]]) -> str:
    """The user turn asking for one revision: the problems found, then the instruction to hand back the whole JSON."""
    lines = ["伺服器檢查發現下面的問題。請修正後交回完整的 JSON（同一個 schema，所有段落都要交回）。"
             "沒有出處或對不上的數字就刪掉；不符合句型的句子改成三種句型之一或刪掉。", ""]
    for p in problems[:60]:
        lines.append(f"- {p['path']}：{p['code']}（{p.get('detail') or ''}）")
    hints = []
    for p in problems:
        key = "time_ref" if str(p.get("path") or "").endswith(".time_ref") else str(p.get("code") or "")
        if key in REVISE_HINTS and REVISE_HINTS[key] not in hints:
            hints.append(REVISE_HINTS[key])
    if hints:
        lines += ["", "怎麼改：", *("- " + h for h in hints)]
    return "\n".join(lines)


# What a revision should do about a problem whose code alone does not say it (keyed by code; ``time_ref`` for any
# problem on an item's ``time_ref``)
REVISE_HINTS = {
    "time_ref": "time_ref 只能填 C 編號（例如 C001）或空字串；日期與時間寫在句子裡，不寫在 time_ref。",
    "internal_gap": "缺的資料由頁面標示：刪掉說明缺了什麼、未開放、不列、未找到報導的句子或子句（個股項目與上週行事曆"
                    "回顧的「未找到報導」、盤後籌碼的「上市三大法人尚未取得可引用的報導」除外）。",
    "us_local_time": "美國當地時間寫成「美東 11/18 14:00」（日期加 24 小時制），伺服器會補上台北時間；不要自己換算。",
    "stock_not_allowed": "名單外的台股不能出現；海外公司照報導原文寫名稱，不加代號。",
    "item_not_event": "watch／tonight 每一項都要是行事曆（C）或報導（X）裡的事件，time_ref 或 refs 要有那個 C 或 X；"
                      "沒有就拿掉這一項（都沒有就給空陣列）。",
    "repeats_close_report": "前一個交易日的收盤數字（group=prev_session 的 F）上一份盤後重點已經寫過：不放進標題、"
                            "重點與「前一晚才到的資料」。",
}


# -- compliance read (§11) ----------------------------------------------------------------------------------------
CHECK_CATEGORIES = ("recommendation", "price_level", "direction", "futures_direction", "personalized", "rating",
                    "other_advice")
CHECK_SYSTEM = """\
你是台灣金融法規的內容檢查員。你會收到一份市場報告的每一句話（JSON：path 與 text）。這份報告人人看到的內容相同，只能寫\
事實、已排定的事件、具名來源的說法、類股過去的比較，以及依規則挑出的個股。

找出違反下面任何一類的句子：
- recommendation：推介或建議買賣、加減碼。例：「投資人可趁回檔布局台積電」。
- price_level：目標價、合理價、支撐壓力、停損停利、點位預測。例：「加權指數下檔支撐在 40,000 點」。
- direction：自己對大盤、類股、個股方向或展望的判斷。例：「半導體類股後續仍有上漲空間」。
- futures_direction：期貨、選擇權、夜盤的方向判斷。例：「外資空單增加，期指偏空」。
- personalized：針對個人持股或財務狀況。例：「持有聯發科的人可以續抱」。
- rating：個股評等或目標價（就算是轉述）。例：「外資調升聯發科評等至買進」。
- other_advice：其他投資建議。例：「現在適合分批進場」。

具名來源的報導（「〔中央社〕報導…」）照實轉述已經發生的事不算違反。轉述別人對大盤、類股、個股的方向或展望（例：「〔中央社〕\
報導，法人預期台股短線震盪走高」）算 direction；轉述評等、目標價、點位預測也算違反。\
只回真的有問題的句子；quote 必須逐字出自那一句。沒有問題就回空陣列。"""


def check_schema() -> dict[str, Any]:
    issue = {"type": "object", "properties": {"path": {"type": "string"},
                                              "category": {"type": "string", "enum": list(CHECK_CATEGORIES)},
                                              "quote": {"type": "string"}},
             "required": ["path", "category", "quote"], "additionalProperties": False}
    return {"type": "object", "properties": {"issues": {"type": "array", "items": issue}}, "required": ["issues"],
            "additionalProperties": False}
