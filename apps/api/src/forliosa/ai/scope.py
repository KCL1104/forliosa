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
_FINANCE_WORDS = """
股 債 基金 etf 投資 理財 配息 股利 殖利率 報酬 損益 獲利 虧損 賺 賠 績效 持倉 部位 帳戶 帳本 記帳 交易 買 賣 加碼 減碼
停損 停利 張 價 漲 跌 市值 本益比 淨值 財報 營收 毛利 eps 匯率 利率 利息 複利 年化 通膨 升息 降息 央行 聯準會 大盤 加權
指數 台積 美股 台股 期貨 選擇權 權證 融資 融券 當沖 法人 外資 投信 自營商 定期定額 手續費 稅 除權 除息 填息 forliosa
草稿 自選 群組 資產 存款 貸款 房貸 退休 保險 錢 美元 台幣 薪 預算 財務 金融 經濟 景氣 產業 半導體 公司 銀行 券商 證券
市場 行情 走勢 籌碼 stock invest dividend portfolio market financ trading ticker nasdaq s&p twse tpex
""".split()  # noqa: SIM905 - a long word list reads better as text
_FINANCE = re.compile("|".join([*map(re.escape, _FINANCE_WORDS), _w("fed|dow"), r"k ?線",
                                r"(?<!\d)\d{4,6}(?!\d)"]),  # stock codes (2330, 00878), years, amounts
                      re.IGNORECASE)

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
    ("creative", re.compile(r"(寫|作|創作|編).{0,12}(詩|歌詞|小說|故事|笑話|劇本|情書|文案)|"
                            r"講[個一]*笑話|說[個一]*故事|"
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
