"""Scope pre-check: decline obviously off-topic chat requests without a model call (``AI_SCOPE_PRECHECK``).

The assistant only helps with investing, finance, Taiwan / US stocks, the user's own portfolio and how to use
Forliosa; the full policy is in the system prompt (``prompts.CHAT_SYSTEM``), and the model declines everything
else in one sentence. This check only saves a model call for the clear cases, and is deliberately conservative:
a message is declined only when it matches an off-topic pattern (programming, homework, role-play, creative
writing, translation) **and** contains no finance / portfolio / Forliosa word and no stock-code-like number.
Everything else, including general trivia, goes to the model.
"""

from __future__ import annotations

import re


def _w(alternatives: str) -> str:
    """Whole ASCII words. ``\\b`` does not work here: CJK characters are word characters too (``用python``)."""
    return rf"(?<![a-z0-9])(?:{alternatives})(?![a-z0-9])"


# Any of these means the message may be about money, markets or the app: never declined here (broad on purpose).
_FINANCE = re.compile("|".join([
    r"股", r"債", r"基金", r"etf", r"投資", r"理財", r"配息", r"股利", r"殖利率", r"報酬", r"損益", r"獲利", r"虧損",
    r"賺", r"賠", r"績效", r"持倉", r"部位", r"帳戶", r"帳本", r"記帳", r"交易", r"買", r"賣", r"加碼", r"減碼", r"停損",
    r"停利", r"張", r"價", r"漲", r"跌", r"市值", r"本益比", r"淨值", r"財報", r"營收", r"毛利", r"eps", r"匯率", r"利率",
    r"利息", r"複利", r"年化", r"通膨", r"升息", r"降息", r"央行", r"聯準會", _w("fed"), r"大盤", r"加權", r"指數",
    r"台積", r"美股", r"台股", r"期貨", r"選擇權", r"權證", r"融資", r"融券", r"當沖", r"法人", r"外資", r"投信",
    r"自營商", r"定期定額", r"手續費", r"稅", r"除權", r"除息", r"填息", r"forliosa", r"草稿", r"自選", r"群組", r"資產",
    r"存款", r"貸款", r"房貸", r"退休", r"保險", r"錢", r"美元", r"台幣", r"薪", r"預算", r"財務", r"金融", r"經濟",
    r"景氣", r"產業", r"半導體", r"公司", r"銀行", r"券商", r"證券", r"市場", r"行情", r"走勢", r"k ?線", r"籌碼",
    r"stock", r"invest", r"dividend", r"portfolio", r"market", r"financ", r"trading", r"ticker", r"nasdaq", r"s&p",
    _w("dow"), r"twse", r"tpex", r"(?<!\d)\d{4,6}(?!\d)",  # stock codes (2330, 00878), years, amounts
]), re.IGNORECASE)

_OFF_TOPIC: list[tuple[str, re.Pattern[str]]] = [
    ("code", re.compile(
        r"```|" + _w(r"python|javascript|typescript|java|golang|rust|kotlin|swift|c\+\+|c#|php|ruby|sql|html|css|"
                     r"react|vue|node\.?js|django|flask|docker|kubernetes|linux|bash|powershell|regex") + "|"
        r"(寫|改|修|debug|除錯|優化|重構|解釋).{0,10}(程式|代碼|code|腳本|script|函式|函數|function|爬蟲|網頁|網站|"
        r"app|演算法)|程式碼|語法錯誤|編譯錯誤|stack ?trace|traceback", re.IGNORECASE)),
    ("homework", re.compile(r"作業|功課|習題|考卷|考題|期末考|期中考|學測|指考|作文|讀書心得|小論文|homework",
                            re.IGNORECASE)),
    ("roleplay", re.compile(r"角色扮演|扮演|假裝你是|你現在是一[個位名隻]|role.?play|pretend (?:to be|you are)|"
                            + _w("act as"), re.IGNORECASE)),
    ("creative", re.compile(r"(寫|作|創作|編).{0,12}(詩|歌詞|小說|故事|笑話|劇本|情書|文案)|講[個一]*笑話|說[個一]*故事|"
                            + _w(r"(write|compose) (me )?(a |an )?(poem|story|song|essay|joke)"), re.IGNORECASE)),
    ("translation", re.compile(r"翻譯|translate|英翻中|中翻英|翻成[英中日韓]文", re.IGNORECASE)),
]


def precheck(message: str) -> str | None:
    """The off-topic kind (``code``, ``homework``, ``roleplay``, ``creative``, ``translation``) when the message
    should be declined without asking the model, else ``None``."""
    text = message or ""
    if _FINANCE.search(text):
        return None
    for kind, pattern in _OFF_TOPIC:
        if pattern.search(text):
            return kind
    return None
