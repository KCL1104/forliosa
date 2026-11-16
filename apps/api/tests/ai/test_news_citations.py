"""產品負責人 2026-11-15: answers built on the stock news tool link the news they use. ``get_news`` returns each
linked headline as a citable ``search_result`` block; a ``search_result_location`` citation becomes a footnote with the
outlet's name, and the turn is checked for uncited news claims like a web search's."""

from __future__ import annotations

from forliosa.services import stock as stock_svc
from tests.ai.conftest import chat
from tests.ai.fake_anthropic import text, tool_use

PCHOME = "https://news.pchome.com.tw/a"
NEWS = [
    {"published_at": "2026-11-11T09:00:00+08:00", "title": "台揚淨值轉負 12/21 終止上市", "category": "media",
     "outlet": "PChome 新聞", "source": "新聞", "url": PCHOME, "sources": ["The GDELT Project"]},
    {"published_at": "2026-11-10T17:30:00+08:00", "title": "公告本公司有價證券終止上市", "category": "material_info",
     "source": "公告", "url": "https://mops.twse.com.tw/mops/web/t05st01", "sources": ["臺灣證券交易所"]},
    {"published_at": "2026-11-09T10:00:00+08:00", "title": "沒有連結的標題", "category": "media", "outlet": "某報",
     "source": "新聞", "url": None, "sources": []},
]


def location(url: str, title: str, cited: str, index: int) -> dict:
    return {"type": "search_result_location", "source": url, "title": title, "cited_text": cited,
            "search_result_index": index, "start_block_index": 0, "end_block_index": 1}


def test_without_links_the_headlines_are_plain_data(client, pool, fake, monkeypatch):
    monkeypatch.setattr(stock_svc, "news", lambda db, md, symbol: [NEWS[2]])
    fake.reply(tool_use("toolu_n", "get_news", {"symbol": "2330"}), stop_reason="tool_use")
    fake.reply(text("好的。"))
    assert chat(client, "最近有什麼新聞？", page={"route": "/stock/2330.TW", "symbol": "2330.TW"})[0] == 200
    content = fake.requests[1]["body"]["messages"][-1]["content"][0]["content"]
    assert isinstance(content, str) and "沒有連結的標題" in content


def test_news_headlines_are_citable_and_footnotes_carry_the_outlet(client, pool, fake, monkeypatch):
    monkeypatch.setattr(stock_svc, "news", lambda db, md, symbol: NEWS)
    fake.reply(tool_use("toolu_n", "get_news", {"symbol": "2330"}), stop_reason="tool_use")
    cite = location(PCHOME, NEWS[0]["title"], "PChome 新聞，11/11 09:00：台揚淨值轉負", 1)
    fake.reply(text("財報顯示每股淨值轉負。", [cite]),
               text("交易所已公告 12/21 下市。"))
    status, events = chat(client, "台揚為什麼跌？", page={"route": "/stock/2330.TW", "symbol": "2330.TW"})
    assert status == 200

    # what the model received: one search_result per linked headline and nothing else (the API rejects a text block
    # beside search results in one tool result); the headline without a link is left out. Neither is from the last
    # 48 hours, so the 公告 comes before the older media headline (``tools.news_for_ai``), each with its time.
    result = fake.requests[1]["body"]["messages"][-1]["content"][0]
    assert result["type"] == "tool_result"
    blocks = result["content"]
    assert [(b["type"], b["source"], b["citations"]) for b in blocks] == [
        ("search_result", "https://mops.twse.com.tw/mops/web/t05st01", {"enabled": True}),
        ("search_result", PCHOME, {"enabled": True})]
    assert blocks[1]["content"] == [{"type": "text", "text": "PChome 新聞，11/11 09:00：台揚淨值轉負 12/21 終止上市"}]
    # a 公告 starts with what kind it is, not the website: 「公開資訊觀測站，…」 was copied into answers (2026-11-16)
    assert blocks[0]["content"][0]["text"].startswith("公司公告，11/10 17:30：")

    # the citation carries the outlet, so 出處 shows 「PChome 新聞」 instead of the host
    cites = [d for n, d in events if n == "citation"]
    assert cites == [{"url": PCHOME, "title": NEWS[0]["title"], "cited_text": "PChome 新聞，11/11 09:00：台揚淨值轉負",
                      "outlet": "PChome 新聞"}]
    # the uncited news-style sentence is flagged, as after a web search
    grounding = [d for n, d in events if n == "grounding"]
    assert grounding and "下市" in grounding[0]["items"][0]["text"]
