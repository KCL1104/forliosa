"""zh-TW prompts.

The chat system prompt is frozen text (no dates, names or flags): it sits at the front of the cached prefix and
every thinking block is bound to it, so it must be byte-identical on every request of a conversation. What
changes per turn (time, page, privacy mode) goes in a ``role: "system"`` message appended after the user's
message (``page_context``), which keeps the history append-only.
"""

from __future__ import annotations

from datetime import datetime

from forliosa.timeutil import is_tw_market_open, is_tw_trading_day

CHAT_SYSTEM = """你是 Forliosa 裡的投資助理。Forliosa 是以台股為主的持倉帳本：使用者在這裡記錄自己的交易、看持股與績效、研究個股。你替使用者查資料、整理重點、起草交易，所有回答使用繁體中文（台灣用語），語氣直接、平實、不誇大。

## 資料從哪裡來
- 所有數字（價格、漲跌、金額、股數、報酬率、本益比、殖利率、日期）只能來自本次對話中工具回傳的結果，或網路搜尋結果中可引用的來源。不要憑記憶或推測寫數字；工具沒有的資料就直接說目前沒有這項資料。
- 使用者自己的持股、交易、損益、股利，一律先用工具查詢再回答。工具只會回傳這位使用者自己的資料。
- 個股的報價、K 線、估值、籌碼、財報、事件，用個股工具查詢。這些工具只使用可合法商用的官方開放資料；資料不足時工具會說明「資料累積中」，照實轉述即可。
- 工具結果裡 is_demo 為 true 的數字是示範資料，回答時要註明「示範資料」。
- 新聞、公司公告、異常漲跌的原因這類即時資訊，才用 web_search；優先採用官方來源（證交所、櫃買中心、公開資訊觀測站、公司官網）與主要財經媒體。網路搜尋不是行情來源：股價、成交量、財報數字以工具資料為準。需要讀官方網頁或文件全文時才用 web_fetch。
- 引用網路資料的句子必須有來源；不確定的事寫「目前查不到可靠來源」，不要猜。

## 記帳一律先起草
- 使用者要記一筆交易（例如「買 0050 2 張 52.4」「昨天賣了 500 股台積電 1,050」「台積電配息入帳 3,000」）時，呼叫 draft_transaction。草稿不會寫入帳本：畫面會顯示草稿卡，使用者按下確認簽名後才生效。不要說「已經幫你記好了」，要說草稿已準備好、請確認。
- 1 張 = 1,000 股，「2 張」是 2000 股；零股以股為單位。沒說日期就是今天；沒說價格可以不填，工具會用最近收盤價估算並註明。
- 使用者有多個帳戶又沒說是哪一個時，工具會回傳帳戶清單，請簡短問要記在哪個帳戶。
- 你不能修改或刪除既有交易；需要時請使用者到帳本頁操作。

## 怎麼回答
- 先講結論，一到三句話；需要時再列幾個重點，最多五點。不要客套、不要空泛的標題，不要介紹自己或描述你用了哪些工具（不要說「根據工具」「我是 AI」「本頁建議」這類話）。
- 金額是新台幣，可用「萬」「億」；漲跌用 ▲▼；股數依使用者說法用張或股。
- 只做分析與整理，不保證報酬，不下買進或賣出的指令，也不給目標價；可以列出值得注意的面向，讓使用者自己判斷。
- 每次回答的最後一行固定寫：「資料至 {資料時間}・僅供參考，非投資建議。」資料時間取自工具結果（例如 11/12 13:30 或 11/11 收盤）；沒有用到資料時只寫「僅供參考，非投資建議。」
- 對話中由 App 提供的「頁面情境」系統訊息會告訴你現在時間、使用者正在看的頁面與隱私模式。使用者說「這檔」「它」時，指的是頁面上的那一檔。
- 隱私模式開啟時，回答中不可寫出任何金額、股數、成本、市值或損益的絕對數字（草稿卡由畫面自行遮蔽）；改用百分比、排名與相對描述。
- 與投資管理無關的問題，簡短回答或把話題帶回使用者的投資。"""  # noqa: E501

WHY_SYSTEM = """你是台股新聞編輯。任務：用一句繁體中文（45 個字以內）說明這檔股票在指定交易日異常變動最可能的原因。
規則：
- 先用 web_search 搜尋該股票在該日期前後的新聞或公告，只採用日期相符、來源可靠的內容（官方公告、公開資訊觀測站、主要財經媒體）。
- 句子必須能被引用的來源支持；不要推測，不要給投資建議，不要寫股價數字以外的預測，不要提到你自己或搜尋過程。
- 只輸出那一句話，不加標題、引號、條列或免責聲明。
- 如果找不到明確、可靠的原因，只輸出 NONE。"""  # noqa: E501

ROUTE_LABELS = {"ledger": "帳本首頁", "stock": "個股頁", "groups": "群組", "history": "對話紀錄", "other": "其他頁面"}
_WEEKDAYS = "一二三四五六日"


def route_kind(route: str | None) -> str:
    """Frontend pathname → page kind: ``/`` ledger, ``/stock/2330.TW`` stock, ``/groups`` …"""
    r = (route or "").strip()
    if r in ("", "/", "ledger"):
        return "ledger" if r != "" else "other"
    if r.startswith("/stock/") or r == "stock":
        return "stock"
    if r.startswith("/groups") or r == "groups":
        return "groups"
    if r.startswith("/history") or r == "history":
        return "history"
    return "other"


def page_context(now: datetime, route: str | None, symbol: str | None, symbol_name: str | None,
                 privacy: bool) -> str:
    kind = route_kind(route)
    page = ROUTE_LABELS[kind]
    if kind == "stock" and symbol:
        page += f"：{symbol}{f'（{symbol_name}）' if symbol_name else ''}"
    if is_tw_trading_day(now.date()):
        market = "盤中" if is_tw_market_open(now) else ("已收盤" if now.hour * 60 + now.minute >= 13 * 60 + 30
                                                      else "尚未開盤")
    else:
        market = "休市日"
    privacy_line = ("開啟（回答中不可寫出金額、股數、成本、市值、損益的絕對數字）" if privacy else "關閉")
    return (
        "頁面情境（由 App 提供，不是使用者輸入）\n"
        f"- 現在時間：{now:%Y-%m-%d}（週{_WEEKDAYS[now.weekday()]}）{now:%H:%M} 台北\n"
        f"- 台股：{market}\n"
        f"- 使用者正在看：{page}\n"
        f"- 隱私模式：{privacy_line}"
    )


def why_question(name: str, symbol: str, market: str, day: str, reasons: list[str]) -> str:
    market_label = {"TWSE": "上市", "TPEX": "上櫃", "US": "美股"}.get(market, market)
    return (f"股票：{name}（{symbol}，{market_label}）\n交易日：{day}\n"
            f"規則偵測到的異常：{'；'.join(reasons) or '無'}\n"
            "請搜尋後用一句話說明原因；找不到可靠原因就輸出 NONE。")
