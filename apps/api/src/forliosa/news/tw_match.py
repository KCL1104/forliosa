"""Which headlines are about a Taiwan stock (產品負責人 2026-11-17: 收緊台股新聞比對).

Why
---
A Taiwan stock's headline used to need only its short name or code anywhere in the title. Over the GDELT bulk files of
24 hours (2026-11-16 04:00 to 11-17 04:00 UTC, 4,970 headlines of Taiwanese sites) matched against every listed name,
two of three matches were something else that shares the name: a year (「2027台海」: 2027 大成鋼), a place (台南,
南港, 信義), an everyday word (全國, 世界, 全台, 統一, 冠軍, 全新, 安心, 幸福), a longer word (大洋洲: 大洋, 東南亞:
南亞, 九合一: 合一, 聯合國: 聯合, 京華城: 華城), another company (中華電信: 中華, 聯發科: 聯發, SK海力士: 力士) or
an acronym (APEC: 富鼎). Numbers: apps/api/CONTRACT_NOTES.md 「2026-11-17 台股新聞比對收緊」.

When a title is about the stock (:func:`relevant`)
---------------------------------------------------
Only the headline is searched (:func:`headline`): not what follows 「 | 」 (a section, column, author or tags:
「| 大台北」「| 雲嘉南」), unless that part is a story of its own (a digest), and not a column label at the start
(「早安世界》」).

* **Its code with stock context** (:func:`code_mentioned`): in brackets (「台積電(2330)」「（2330）」「(2330.TW)」),
  next to the company's name (「2330台積電」), after 「股票代號」, or with an exchange suffix (「2330.TW」); an ETF
  code (00…: 「0050」「00878」「0050股價」「00919月配息」) also bare. Never a year, an amount, a percentage, a date, a
  time or part of a longer number (「2027年」「2027台海」「3000點」「1500元」「2,330」「2026-2030」).
* **Its official name** (:func:`official_forms`, from the company profile's 公司名稱: 統一企業, 南亞塑膠, 台灣大哥大,
  信義房屋, 創意電子, 華城電機, 台灣大車隊): counts on its own, standing free like a name.
* **Its name standing on its own** (:func:`free_positions`): not inside a longer listed name or official name (聯合再生
  is not 聯合, 南亞科 not 南亞, 中華電 not 中華, 統一超商 not 統一, 台灣大車隊 not 台灣大, 華電聯網 not 華電: the
  longest name wins) or an everyday word, place or phrase of :data:`WORDS` (大洋洲, 東南亞, 九合一, 聯合國, 聯合航空,
  京華城, 海力士, 鼎泰豐…), and not straddling one or another listed name (「常廣明年」: 廣明 straddles 明年;
  「輝達新加坡」: 達新; 「中美晶片」: 中美晶).
* **A short name needs more** (:func:`needs_context`: two Chinese characters or fewer, 「-KY」 not counted): the code
  as above, a finance word near it (:data:`FINANCE_CUES` within :data:`CUE_WINDOW` characters: 「南電、景碩苦吞跌停」
  「華紙法說會」「陽明Q3EPS」), another listed name right next to it (「信驊、創意等」「緯創 廣達 鴻海」), or a finance
  page (:func:`is_finance_page`: 自由財經, ETtoday財經雲, 經濟日報, 鉅亨, 非凡, 中央社 產經／證券／財經訊息平台, a
  title ending in 「| 股市」「- 財經」).
* **An everyday word, place or person's name** (:data:`GENERIC_NAMES`, any length: 統一, 全國, 台南, 太空梭…): only
  the code, its official name, a finance word right after it (a period such as 「前3季」 in between is fine:
  「統一前3季EPS」) or right before it across a column mark (「焦點股》南亞」「《鋼鐵股》三星」), or another listed
  name next to it together with a finance word near it (「信驊、創意等逾10檔跌停」); a finance page is not enough
  (「兩岸統一貨幣」 in ETtoday財經雲), nor a finance word that belongs to another word before it (「集團幸福職場」
  「品牌冠軍」).
* **A name in Latin letters**: an English alias (TSMC, APEC) counts in an English headline by the case rules of
  :func:`forliosa.news.normalize.is_relevant`, never on its own in a Chinese one (APEC, TOP, Alpha, USI there are
  something else). A company whose own short name is in Latin letters (GOGOLOOK, TPK-KY, M31, 91APP*-KY) is named so
  in Chinese headlines too: there its name (without 「-KY」, any case) counts like a Chinese name, with more evidence
  when it has four characters or fewer (「TPK-KY 10月營收」「M31前三季EPS」).

The lists were first built from what the 24 hours matched (2026-11-17) and corrected after the review of 2026-11-17
on more real hours. On hours they had not seen, about 93–95 % of the matches kept were right (not the 100 % of the hours
they were built from): new everyday words keep turning up, so the lists need topping up from real data. Numbers:
apps/api/CONTRACT_NOTES.md 「2026-11-17 台股新聞比對收緊」.
"""

from __future__ import annotations

import functools
import re
from collections.abc import Callable, Collection, Iterable, Mapping
from urllib.parse import urlsplit

from forliosa.news.outlets import host_of, on_domain

# A finance word next to a short name makes it the company (2026-11-17, measured on 24 h of headlines): prices and
# trading, results, the board and shareholders, orders and capacity, listing.
FINANCE_CUES: tuple[str, ...] = (
    "股", "漲停", "跌停", "漲幅", "跌幅", "大漲", "大跌", "上漲", "下跌", "收漲", "收跌", "翻紅", "翻黑",
    "重挫", "挫", "飆", "亮燈", "鎖死", "創高", "新高", "大盤", "台股", "權值", "市值", "成交", "買超",
    "賣超", "外資", "投信", "自營商", "法人", "主力", "目標價", "評等", "降評", "升評", "買進", "賣出",
    "減碼", "加碼", "營收", "營運", "業績", "財報", "季報", "年報", "EPS", "每股", "毛利", "淨利", "獲利",
    "虧損", "盈餘", "賺", "虧", "法說", "除息", "除權", "配息", "股利", "股息", "填息", "增資", "減資",
    "董事", "董座", "總經理", "執行長", "獨董", "經理", "股東", "訂單", "接單", "轉單", "出貨", "產能",
    "擴產", "擴廠", "投產", "量產", "廠房", "新廠", "工廠", "建案", "施工", "工地", "上市", "上櫃", "興櫃",
    "掛牌", "下市", "停止買賣", "重訊", "併購", "收購", "合併", "入股", "持股", "子公司", "集團", "公司",
    "旗下", "品牌", "商機", "市占", "檔", "族群", "概念", "金控", "證券",
)
CUE_WINDOW = 8  # characters between a short name and the finance word
HEADLINE_PART = 10  # a part after 「 | 」 this long is a headline (a digest's story), not a section or column
LATIN_FREE = 5  # a Latin-letter own name this long (GOGOLOOK, LINEPAY, 91APP) needs no more evidence
# Finance sections in the page title's tail (udn 「| 股市」「| 產經」, 中時 「- 財經」, 三立 「| 財經」, ETtoday 財經雲,
# 中央社 「產經」「證券」, 新頭殼 「財經」, 非凡 「金融」「理財」, 風傳媒 「下班經濟學」).
FINANCE_SECTIONS = frozenset({
    "財經", "產經", "證券", "股市", "金融", "理財", "台股", "美股", "基金", "期貨", "產業", "經濟",
    "ETtoday財經雲", "財經雲", "下班經濟學", "股市要聞", "個股情報", "產業綜合", "科技產業", "金融要聞",
    "財經焦點", "台股雜談", "存股族愛ETF", "產業動態", "全球財經", "財經新聞", "經濟日報", "工商時報",
})
# Sites that are finance or industry news throughout, and finance sections by URL (中央社 afe 產經, asc 證券,
# business 財經訊息平台; TVBS /money/; 中時 realtimenews …-260410 財經; udn story categories 7238–7241 產經,
# 7251/7252/12806/123006 股市).
FINANCE_DOMAINS = (
    "ec.ltn.com.tw", "finance.ettoday.net", "money.udn.com", "ctee.com.tw", "cnyes.com", "moneydj.com",
    "tw.stock.yahoo.com", "news.ustv.com.tw", "wealth.com.tw", "businesstoday.com.tw", "businessweekly.com.tw",
    "digitimes.com.tw", "moneyweekly.com.tw", "technews.tw", "bnext.com.tw",
)
_FINANCE_PATH = re.compile(
    r"(?:cna\.com\.tw/(?:news/(?:afe|asc)|business)/|tvbs\.com\.tw/money/|chinatimes\.com/\w+/\d+-260410\b"
    r"|udn\.com/news/story/(?:7238|7239|7240|7241|7251|7252|12806|123006)/)", re.IGNORECASE)
# Everyday words, places and phrases that contain or straddle a stock's name (measured 2026-11-17: each one matched a
# stock that the headline was not about). Longer listed and official names need not be listed: every one is checked.
# A word here must not be a listed company's own full name (中華電信 is 中華電's, 長榮航空 長榮航's).
WORDS = frozenset({
    # longer words around a name
    "大洋洲", "大洋流", "東南亞", "九合一", "五合一", "房地合一", "京華城", "聯合國", "聯合報", "聯合航空",
    "聯合政府", "聯合聲明", "聯合文件", "聯合徵才", "聯合年會", "聯合參展", "聯合成果", "聯合壟斷", "雙聯",
    "中華民國", "中華大學", "中華海洋", "中華金門", "中華隊", "海力士", "歐力士", "金融時報", "紐約時報",
    "大紀元", "台灣大學", "台灣大道", "東元醫院", "新東陽", "陽明山", "陽明交大", "長榮路", "長榮大學",
    "長榮中學", "全家福", "全家人", "信義區", "信義鄉", "信義路", "建國國中", "建國中學", "建國路", "明華園",
    "大華府", "大甲國小", "大甲溪", "三商巧福", "三星SDI", "三星電子", "三星晶圓", "南港店", "南港展覽館",
    "東華大學", "合歡山", "大同鄉", "三星鄉", "陸海空", "新加坡", "宏碁遊戲", "福壽雙全",
    # (review of 2026-11-17, 12 more hours) a brand, a bank, a project: 鼎泰豐 (泰豐), 大華銀 (UOB: 大華), 台達能源
    # (台達電's subsidiary: 達能)
    "鼎泰豐", "大華銀", "台達能源",
    # words that straddle a name: 「常廣明年」「輝達明晨」「動力泰」「安華東協」「碳中和成」「全台半導體」
    # 「住家登記」「重建大甲」「球星亞」「美國眾議員」「閃耀登場」「巨星雲集」「神基因」「美隆大學」「怡安集團」
    # 「中台灣」「中和大車」
    "明年", "明晨", "輝達", "動力", "東協", "中和", "碳中和", "半導體", "登記", "住家", "重建", "球星",
    "眾議員", "登場", "巨星", "雲集", "基因", "大學", "集團", "台灣", "中餐", "新建設", "門戶", "成長",
    # (review of 2026-11-17) 「從平台端」(台端) 「致員工信」(工信) 「祖國統一」(國統) 「台達能源」(達能)
    # 「中美晶片」(中美晶) 「統一實施」(統一實) 「台中銀髮」(台中銀) 「第一金牌」「第一銅牌」(第一金, 第一銅)
    "平台", "員工", "祖國", "台達", "晶片", "實施", "銀髮", "金牌", "銅牌",
    # (2026-11-17, 12 hours of 2026-11-12 measured after the review fixes) 「積極開發新產品」(新產)
    # 「推進美國建廠」(國建) 「若下台亞股殺血海」(台亞) 「先進光子源」(先進光) 「衛星通訊」(星通) 「聯合利華」
    # (利華, 聯合) 「宏泰人壽」(宏泰, an insurer that is not listed) 「ASIC將大量出貨」(大量)
    "新產品", "建廠", "亞股", "光子", "衛星", "聯合利華", "宏泰人壽", "大量出貨",
})
# Names that are everyday words, places or people's names (measured 2026-11-17: most of their matches in 24 hours were
# something else; the review added the words of 3 characters or more and 光環, 海灣, 神準, and took out 華城, whose
# wrong matches were all 京華城). They count only with the stock's code, its official name, a finance word right
# next to them or another listed name next to them with a finance word near (:func:`_strict_context`); a finance page
# is not enough (「兩岸統一貨幣」「全台預售屋」 in finance sections).
GENERIC_NAMES = frozenset({
    "台南", "全國", "世界", "全台", "聯合", "統一", "冠軍", "全新", "建國", "三星", "創意", "合一", "安心",
    "大洋", "全家", "南亞", "傳奇", "信義", "國產", "幸福", "卓越", "中華", "大台北", "數字", "時報",
    "雲嘉南", "力士", "大甲", "品安", "中台", "大量", "辣椒", "台灣大", "大中", "慶生", "互動", "新興", "無敵",
    "資通", "陸海", "地球", "新建", "新天地", "綠電", "大成", "典範", "創新服務", "大將", "大同", "新門",
    "太醫", "大東", "南港", "大華", "立德", "大山", "京城", "嘉基", "精華", "正道", "中天", "大樹", "雙喜",
    "五福", "星雲", "關中", "鳳凰", "華東",
    "光環", "海灣", "神準", "太空梭", "創業家", "新零售", "地心引力", "尼克森", "第一店", "所羅門", "全國電", "大武山",
    "第一銅", "第一金",
})
_HAN = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
_TAIL = re.compile(r"\s*[|｜]\s*")
# A list of names: 「信驊、創意」「長榮.陽明」「南電/景碩」「緯創 廣達 鴻海」 (one space, half or full width)
_LIST_SEP_BEFORE = re.compile(r"(?:[、，,／/.．‧·及與和跟]|(?<=\S)[ 　])$")
_LIST_SEP_AFTER = re.compile(r"[、，,／/.．‧·及與和跟]|[ 　](?=\S)")
_DASH_TAIL = re.compile(r"\s+[-–—]\s+[^\s，。！？!?、：:]{1,12}$")
_OPEN, _CLOSE = "(（【[〔〈《「", ")）】]〕〉》」"
_INSIDE_BRACKET = re.compile(r"[\sA-Za-z0-9.:：\-、,，/;]*")
_UNIT = re.compile(r"\s*(?:年|元|點|億|萬|千|百|張|股|倍|月|日|號|人|家|名|件|個|多|餘|位|次|台|輛|坪|戶"
                   r"|字|頁|間|座|艘|架|隻|條|項|類|公里|公尺|米|噸|度|分|秒|歲|週|周|天|期|屆|梯|%|％"
                   r"|[KkMm](?![A-Za-z]))")
# An ETF code (00…) is never a count, a year or a month: only an amount or a ratio after it makes it a number
# (「0050元的便當」, not 「0050股價」「00919月配息」「0056年化報酬率」).
_AMOUNT = re.compile(r"\s*(?:元|塊|點|億|萬|千|百|倍|%|％|[KkMm](?![A-Za-z]))")
_NUMBER_BEFORE = re.compile(r"(?:\d[\d,.]*\s*[/\-~～至到:：]\s*|\d[.,]|[$＄])$")
_NUMBER_AFTER = re.compile(r"^(?:[.,]\d|\s*[/\-~～至到:：]\s*\d)")
_EXCHANGE_SUFFIX = re.compile(r"^(?:[.\-](?:TW|TWO|TT)\b|\s?TT\b)", re.IGNORECASE)
_LABEL = re.compile(r"^(?:《[^》]{1,8}》|[^》《\s]{1,6}》)")
_PERIOD = re.compile(r"\s*(?:前|第|今年|去年|明年)?(?:[0-9一二三四]{1,2}(?:季|月|年|週|周)|Q[1-4]|上半年"
                     r"|下半年|全年|前三季|單月|累計)?\s*")
_CODE_LABEL = re.compile(r"(?:股票代號|證券代號|代號|代碼|股號)\s*[:：]?\s*$")
# A finance word right before an everyday-word name counts only across a mark (「焦點股》南亞」「熱門股：統一」
# 「千金股8檔漲停！創意」) or when it is the title 股王／股后 (「新科股后創意」; not 「五股五福」: a district).
_CUE_THEN_MARK = re.compile("(?:" + "|".join(re.escape(c) for c in sorted(FINANCE_CUES, key=len, reverse=True))
                            + r")\s*[》:：／/|｜！!]\s*$|股[王后]\s*$")
# An official name that is also an everyday phrase: a place and an industry (「台灣半導體產值」 is not 台半,
# 「中國鋼鐵」 not 中鋼, 「亞洲航空」 AirAsia, 「全國加油」). It still takes the short name's headlines (台灣半導體 is
# not 台灣), but does not count on its own.
_PLACE = re.compile(r"^(?:台灣|臺灣|中國|亞洲|全球|國際|美國|日本|全國|世界|東亞|大中華)")
_INDUSTRY = frozenset({
    "半導體", "鋼鐵", "鋼鐵結構", "水泥", "塑膠", "塑膠工業", "玻璃", "玻璃工業", "肥料", "航業", "航運", "航空",
    "電器", "化學", "化工", "紡織", "汽車", "人壽", "銀行", "證券", "保險", "食品", "鐵路", "電力", "石化", "造船",
    "光學", "電信", "加油", "加油站", "農林", "製釉", "探針", "砂輪", "人造纖維", "貨櫃運輸", "電視事業", "生醫材料",
})
# The official name without its legal form (「股份有限公司」「(股)公司」「有限公司」), a registry prefix
# (「英屬開曼群島商」) and parentheses (「(開曼)」「(BizLink Holding Inc.)」).
_LEGAL_FORM = re.compile(r"\s*(?:股份有限公司|[(（]股[)）]\s*公司|有限公司|公司)$")
_REGISTRY = re.compile(r"^(?:英屬|美屬)?(?:開曼群島|蓋曼群島|開曼|維京群島|百慕達|薩摩亞|香港|新加坡|馬來西亞"
                       r"|美國|日本|英國|荷蘭|泰國|越南|澳門|納閩|塞席爾|模里西斯)商")
_PARENS = re.compile(r"[(（][^)）]*[)）]")
_MARKET_SUFFIX = re.compile(r"[-*].*$")  # 永冠-KY, 矽力*-KY, 91APP*-KY, 漢康-KY創


def headline(title: str) -> str:
    """The headline part of a title. What follows 「 | 」 is a section, column, author or tags (「| 大台北」
    「| 雲嘉南」「| 縣市長議員選戰」) and is left out, except a long part (:data:`HEADLINE_PART` characters or
    more: a digest's story, 「DIGITIMES Today：… | 韓廠憂心南亞科、華邦電積極導入EUV」). A short 「 - 」 tail
    (自由 「- 臺南市」「- 地產天下」, a blog's name) is left out too."""
    first, *rest = _TAIL.split(title)
    m = _DASH_TAIL.search(first)
    if m and m.start() >= 8:
        first = first[:m.start()].rstrip()
    parts = [first.strip(), *(p.strip() for p in rest if len(re.sub(r"\s+", "", p)) >= HEADLINE_PART)]
    return " | ".join(p for p in parts if p)


def has_han(text: str) -> bool:
    return bool(_HAN.search(text))


def is_finance_page(url: str = "", raw_title: str = "") -> bool:
    """A finance site or section: :data:`FINANCE_DOMAINS`, a finance section by URL, or a title whose tail (after
    「 | 」 or 「 - 」) names a finance section (:data:`FINANCE_SECTIONS`)."""
    if url:
        host = host_of(url)
        if host and any(on_domain(host, d) for d in FINANCE_DOMAINS):
            return True
        try:
            parts = urlsplit(url.strip())
            where = (parts.hostname or "") + parts.path
        except ValueError:
            where = ""
        if where and _FINANCE_PATH.search(where):
            return True
    if raw_title:
        tails = re.split(r"\s*[|｜]\s*|\s+[-–—]\s+", raw_title)[1:]
        for t in tails:
            t = re.sub(r"\s+", "", t)
            if t in FINANCE_SECTIONS:
                return True
    return False


# -- codes ------------------------------------------------------------------------------------------------------
def _bracketed(before: str, after: str) -> bool:
    """The code sits in brackets, possibly with other codes, separators and an exchange suffix: 「(2330)」「（2330、
    2317）」「(TW:2330)」「(2330.TW)」."""
    i = len(before) - 1
    while i >= 0 and _INSIDE_BRACKET.fullmatch(before[i]):
        i -= 1
    if i < 0 or before[i] not in _OPEN or len(before) - 1 - i > 12:
        return False
    j = 0
    while j < len(after) and _INSIDE_BRACKET.fullmatch(after[j]):
        j += 1
    return j < len(after) and after[j] in _CLOSE and j <= 12


def code_mentioned(title: str, code: str, names: Iterable[str] = ()) -> bool:
    """``code`` names the stock in ``title``: with stock context (brackets, the company's name next to it, 「股票代號」,
    an exchange suffix) or, for an ETF code (00…), bare; never a year, an amount, a percentage, a date, a time or part
    of a longer number."""
    if not code:
        return False
    names = [n for n in names if n and has_han(n)]
    etf = code.startswith("00")
    for m in re.finditer(rf"(?<![0-9A-Za-z.$＄]){re.escape(code)}(?![0-9A-Za-z])", title):
        before, after = title[:m.start()], title[m.end():]
        if _NUMBER_BEFORE.search(before) or _NUMBER_AFTER.search(after):
            continue
        b, a = before.rstrip(" -－:：、(（【["), after.lstrip(" -－:：")
        if any(b.endswith(n) or a.startswith(n) for n in names):  # 「2330台積電」 (not 「2000台」)
            return True
        if (_AMOUNT if etf else _UNIT).match(after):
            continue
        if _bracketed(before, after) or _EXCHANGE_SUFFIX.match(after) or _CODE_LABEL.search(before):
            return True
        if etf:
            return True
    return False


# -- names ------------------------------------------------------------------------------------------------------
def core_name(name: str) -> str:
    """The name without the market suffix: 永冠-KY -> 永冠, 91APP*-KY -> 91APP."""
    return _MARKET_SUFFIX.sub("", name) or name


def needs_context(name: str) -> bool:
    """A short or everyday name: two Chinese characters or fewer (the market suffix 「-KY」「*」 not counted), or one of
    :data:`GENERIC_NAMES`."""
    if not has_han(name):
        return False
    return len(core_name(name)) <= 2 or name in GENERIC_NAMES


def official_forms(short: str, official: str) -> tuple[str, ...]:
    """How a headline names a company by its official name (公司名稱): the name without its legal form (統一企業 of
    統一企業股份有限公司, 台灣大哥大, 華電聯網, 台灣大車隊) and, when it starts with the short name, the short name and
    the next two characters (南亞塑膠 of 南亞塑膠工業, 世界先進 of 世界先進積體電路, 全家便利 of 全家便利商店).
    Nothing for a name in Latin letters, one no longer than the short name or one of three characters or fewer
    (GOGOLOOK's official name is 走著瞧, 「wait and see」)."""
    core = _PARENS.sub("", _REGISTRY.sub("", _LEGAL_FORM.sub("", " ".join((official or "").split()))))
    core = re.sub(r"\s+", "", core)
    short = core_name(short or "")
    if len(core) < 4 or not has_han(core) or core == short or not re.fullmatch(r"[㐀-䶿一-鿿豈-﫿A-Za-z0-9]+", core):
        return ()
    out = [core]
    if short and core.startswith(short) and len(core) > len(short) + 2:
        out.append(core[:len(short) + 2])
    return tuple(out)


def everyday_form(form: str) -> bool:
    """An official name that is also an everyday phrase: a place and an industry (台灣半導體, 中國鋼鐵, 亞洲航空,
    全國加油)."""
    m = _PLACE.match(form)
    return bool(m) and form[m.end():] in _INDUSTRY


@functools.lru_cache(maxsize=8192)
def _straddlers(name: str) -> tuple[str, ...]:
    """Words of :data:`WORDS` that can straddle a boundary of ``name`` (share its first or last characters)."""
    out = []
    for w in WORDS:
        if name in w:
            continue
        for k in range(1, min(len(w), len(name))):
            if w.endswith(name[:k]) or w.startswith(name[-k:]):
                out.append(w)
                break
    return tuple(out)


def _occurrences(text: str, word: str) -> list[int]:
    out, i = [], text.find(word)
    while i >= 0:
        out.append(i)
        i = text.find(word, i + 1)
    return out


def free_positions(text: str, name: str, longer: Iterable[str] = (), peers: Collection[str] = ()) -> list[int]:
    """Where ``name`` stands on its own in ``text``: not inside a longer stock or official name (``longer``) or a word
    of :data:`WORDS`, not straddling a word of :data:`WORDS` or another listed name of ``peers`` (「台灣大車隊」:
    台灣大 and 大車隊 overlap), and not inside a column label at the start (「早安世界》」: a label names the column,
    not the story; 「焦點股》南亞」 is 南亞)."""
    starts = _occurrences(text, name)
    if not starts:
        return []
    label = _LABEL.match(text)
    if label:
        starts = [s for s in starts if s >= label.end()]
    n = len(name)
    covers = [w for w in (*longer, *(w for w in WORDS if name in w and w != name)) if w in text]
    spans = [(s, s + len(w)) for w in covers for s in _occurrences(text, w)]
    cross = [(s, s + len(w)) for w in _straddlers(name) if w in text for s in _occurrences(text, w)]
    out = []
    for s in starts:
        e = s + n
        if any(a <= s and e <= b and (b - a) > n for a, b in spans):
            continue
        if any((a < s < b < e) or (s < a < e < b) for a, b in cross):
            continue
        if peers and _overlaps_listed(text, s, e, name, peers):
            continue
        out.append(s)
    return out


def _overlaps_listed(text: str, s: int, e: int, name: str, peers: Collection[str]) -> bool:
    """Another listed name overlaps ``text[s:e]`` without containing it or lying inside it: it starts before the name
    and ends inside it, or starts inside it and ends after it (「台灣大車隊」: 台灣大 and 大車隊). One that is itself
    inside or across a word of :data:`WORDS` does not count (「常廣明年」: 廣明 straddles 明年, so 常廣 stands)."""
    first, longest = _overlap_index(peers)
    for a in range(max(0, s - longest + 1), e):
        if a == s:
            continue
        for p in first.get(text[a], ()):
            b = a + len(p)
            if p == name or not text.startswith(p, a):
                continue
            if ((a < s < b < e) or (s < a < e < b)) and not _in_a_word(text, a, b, p):
                return True
    return False


def _in_a_word(text: str, a: int, b: int, name: str) -> bool:
    """``text[a:b]`` (``name``) lies inside or across a word of :data:`WORDS`."""
    for w in (*(w for w in WORDS if name in w and w != name), *_straddlers(name)):
        if w not in text:
            continue
        for c in _occurrences(text, w):
            d = c + len(w)
            if (c <= a and b <= d) or (c < a < d < b) or (a < c < b < d):
                return True
    return False


_OVERLAP_INDEX: list[tuple[Collection[str], dict[str, list[str]], int]] = []


def _overlap_index(peers: Collection[str]) -> tuple[dict[str, list[str]], int]:
    """Listed names of two characters or more by first character, and the longest length (cached for the last
    ``peers`` collection)."""
    entry = _OVERLAP_INDEX[0] if _OVERLAP_INDEX else None  # read once (request threads share it)
    if entry is None or entry[0] is not peers:
        first: dict[str, list[str]] = {}
        longest = 1
        for p in peers:
            if len(p) >= 2 and has_han(p):
                first.setdefault(p[0], []).append(p)
                longest = max(longest, len(p))
        entry = (peers, first, longest)
        _OVERLAP_INDEX[:] = [entry]
    return entry[1], entry[2]


def _cue_near(text: str, start: int, end: int, window: int | None = None) -> bool:
    """A finance word at most ``window`` characters away from the name (between them, not counting the word itself);
    a period right after the name (「前3季」「10月」「Q3」「明年」) does not count towards the distance:
    「統一前3季EPS」."""
    window = CUE_WINDOW if window is None else window
    period = _PERIOD.match(text, end)
    after_from = period.end() if period else end
    for cue in FINANCE_CUES:
        i = text.find(cue)
        while i >= 0:
            j = i + len(cue)
            if (j <= start and start - j <= window) or (i >= end and i - after_from <= window):
                return True
            i = text.find(cue, i + 1)
    return False


def _cue_adjacent(text: str, start: int, end: int) -> bool:
    """A finance word right after the name (a period and spaces in between are fine: 「統一前3季EPS」「南亞 股價」) or
    right before it across a mark (「焦點股》南亞」「《鋼鐵股》三星」「漲停！創意」) or as the title 股王／股后
    (「新科股后創意」). A finance word right before the name without a mark belongs to the word before (「集團幸福職場」
    「品牌冠軍」「五股五福」), one a character after it to the next word (「大華銀投信」)."""
    period = _PERIOD.match(text, end)
    j = period.end() if period else end
    if any(text.startswith(c, j) for c in FINANCE_CUES):
        return True
    return bool(_CUE_THEN_MARK.search(text, 0, start))


def _listed_with_peer(text: str, start: int, end: int, name: str, peers: Collection[str]) -> bool:
    """Another listed company's name stands right next to the name, as in a list of stocks: 「信驊、創意等逾10檔跌停」
    「聯發科、創意領軍反彈」「長榮.陽明逆風」「緯創 廣達 鴻海大比較」."""
    if not peers:
        return False
    before = _LIST_SEP_BEFORE.search(text[:start])
    after = _LIST_SEP_AFTER.match(text[end:])
    if before:
        left = text[:before.start()]
        if any(left.endswith(p) for p in _peers_ending(left[-1:], peers) if p != name):
            return True
    if after:
        right = text[end + after.end():]
        if any(right.startswith(p) for p in _peers_starting(right[:1], peers) if p != name):
            return True
    return False


def _peers_ending(ch: str, peers: Collection[str]) -> list[str]:
    return [p for p in _peer_index(peers)[1].get(ch, ())]


def _peers_starting(ch: str, peers: Collection[str]) -> list[str]:
    return [p for p in _peer_index(peers)[0].get(ch, ())]


_PEER_INDEX: list[tuple[Collection[str], dict[str, list[str]], dict[str, list[str]]]] = []


def _peer_index(peers: Collection[str]) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Names of two characters or more that are not everyday words, by first and by last character (cached for the
    last ``peers`` collection)."""
    entry = _PEER_INDEX[0] if _PEER_INDEX else None  # read once (request threads share it)
    if entry is None or entry[0] is not peers:
        first: dict[str, list[str]] = {}
        last: dict[str, list[str]] = {}
        for p in peers:
            if len(p) >= 2 and has_han(p) and p not in GENERIC_NAMES:  # 「大同、三星」 are two townships
                first.setdefault(p[0], []).append(p)
                last.setdefault(p[-1], []).append(p)
        entry = (peers, first, last)
        _PEER_INDEX[:] = [entry]
    return entry[1], entry[2]


def _strict_context(text: str, start: int, end: int, name: str, peers: Collection[str]) -> bool:
    """An everyday-word name is the company: a finance word right next to it (:func:`_cue_adjacent`), or another listed
    name next to it with a finance word near (「信驊、創意等逾10檔跌停」; not 「台積電、三星合作」: Samsung)."""
    return _cue_adjacent(text, start, end) or (_listed_with_peer(text, start, end, name, peers)
                                                and _cue_near(text, start, end))


def _latin_positions(text: str, core: str) -> list[int]:
    """Where a Latin-letter name stands as a word, in any case (GOGOLOOK in 「Gogolook第三季EPS」, TPK in
    「TPK-KY 10月營收」)."""
    pattern = r"(?<![A-Za-z0-9])" + re.escape(core) + r"(?![A-Za-z0-9])"
    return [m.start() for m in re.finditer(pattern, text, re.IGNORECASE)]


def relevant(title: str, names: Iterable[str], code: str, *, longer: Iterable[str] = (), url: str = "",
             raw_title: str = "", english: Callable[[str, str], bool] | None = None,
             peers: Collection[str] = (), forms: Iterable[str] = (), own: str = "") -> bool:
    """The headline (after :func:`forliosa.news.normalize.clean_title`) is about this Taiwan stock (module docstring).
    ``names``: its short name and English short names; ``own``: its short name as listed (when in Latin letters,
    GOGOLOOK, it counts in Chinese headlines like a Chinese name; English aliases do not); ``forms``: its official
    name's forms (:func:`official_forms`); ``longer``: other stock and official names that contain one of them;
    ``url`` / ``raw_title`` (the title as published, with its section tail): for :func:`is_finance_page`;
    ``english(name, headline)``: whether an English short name appears as the company (the case rules of
    :func:`forliosa.news.normalize.is_relevant`); ``peers``: every listed company's Chinese name (a short name listed
    next to another one is a stock: 「信驊、創意等」; two that overlap are neither: 「台灣大車隊」)."""
    head = headline(title)
    names = [n for n in names if n]
    longer = list(longer)
    forms = [f for f in forms if f]
    if code_mentioned(head, code, [*names, *forms]):
        return True
    for f in forms:  # the official name: 統一企業, 台灣大哥大 (not an everyday phrase: 台灣半導體)
        if f in head and not everyday_form(f) and free_positions(head, f, [w for w in longer if f in w and w != f]):
            return True
    chinese = has_han(head)
    own_core = core_name(own) if own and not has_han(own) else ""
    finance: bool | None = None
    for n in names:
        strict = False
        if not has_han(n):
            if english is not None and not chinese and english(n, head):
                return True
            # a Chinese headline: only the company's own short name in Latin letters (GOGOLOOK, TPK-KY), never an
            # English alias (APEC, TOP, Alpha, USI there are something else)
            if not chinese or not own_core or core_name(n).casefold() != own_core.casefold():
                continue
            spots = _latin_positions(head, own_core)
            if not spots:
                continue
            if len(own_core) >= LATIN_FREE:
                return True
            size = len(own_core)
        else:
            spots = free_positions(head, n, [w for w in longer if n in w and w != n], peers)
            if not spots:
                continue
            if not needs_context(n):
                return True
            strict = n in GENERIC_NAMES
            size = len(n)
        if strict:
            if any(_strict_context(head, s, s + size, n, peers) for s in spots):
                return True
            continue
        if any(_cue_near(head, s, s + size) or _listed_with_peer(head, s, s + size, n, peers) for s in spots):
            return True
        if finance is None:
            finance = is_finance_page(url, raw_title or title)
        if finance:
            return True
    return False


# -- the catalog's names ------------------------------------------------------------------------------------------
_LONGER: list[tuple[Mapping[str, object], object, frozenset[str], frozenset[str], dict[str, tuple[str, ...]]]] = []


def longer_names(name: str, all_names: Iterable[str]) -> tuple[str, ...]:
    """Other stock names (and Chinese aliases, and official names) that contain ``name``: 聯合再生 for 聯合, 南亞科 for
    南亞, 台灣大車隊 for 台灣大."""
    return tuple(sorted({w for w in all_names if w != name and name in w}))


def catalog_names(master: Mapping[str, object]) -> frozenset[str]:
    """Every Chinese name in the instrument master: Taiwan short names and US companies' Chinese aliases (輝達)."""
    out: set[str] = set()
    for info in master.values():
        for n in (getattr(info, "name", ""), *getattr(info, "aliases", ())):
            if n and has_han(n):
                out.add(n)
    return frozenset(out)


def _master_entry(master: Mapping[str, object], forms: Mapping[str, tuple[str, ...]] | None = None
                  ) -> tuple[frozenset[str], frozenset[str], dict[str, tuple[str, ...]]]:
    """(catalog names, catalog and official names, longer-name cache), cached per master and forms mapping. The entry
    is read once: the stored-headline check at read time (``service.ReadMatch``) shares it across request threads."""
    entry = _LONGER[0] if _LONGER else None
    if entry is None or entry[0] is not master or entry[1] is not forms:  # rebuilt at most hourly
        names = catalog_names(master)
        everything = names | {f for fs in (forms or {}).values() for f in fs}
        entry = (master, forms, names, frozenset(everything), {})
        _LONGER[:] = [entry]
    return entry[2], entry[3], entry[4]


def names_in_master(master: Mapping[str, object]) -> frozenset[str]:
    """:func:`catalog_names`, cached per master."""
    entry = _LONGER[0] if _LONGER else None
    if entry is not None and entry[0] is master:
        return entry[2]
    return _master_entry(master)[0]


def longer_in_master(name: str, master: Mapping[str, object],
                     forms: Mapping[str, tuple[str, ...]] | None = None) -> tuple[str, ...]:
    """:func:`longer_names` over the master's names and the official names of ``forms`` (symbol -> its
    :func:`official_forms`), cached per master and forms."""
    _, everything, cache = _master_entry(master, forms)
    if name not in cache:
        cache[name] = longer_names(name, everything)
    return cache[name]
