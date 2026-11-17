"""``python -m forliosa.news`` — news headlines: refresh now, the takedown blocklist, retention.

    uv run python -m forliosa.news refresh [--symbol 2330.TW …] [--no-ai]
    uv run python -m forliosa.news block udn.com --reason "2026-11-20 來函要求下架"
    uv run python -m forliosa.news unblock udn.com
    uv run python -m forliosa.news blocked
    uv run python -m forliosa.news purge
    uv run python -m forliosa.news searxng-check "台積電" [--language en] [--url http://localhost:8080]
    uv run python -m forliosa.news gdelt-bulk-check [--symbol 2330 --symbol NVDA …] [--feed translation]
    uv run python -m forliosa.news langsearch-refresh
    uv run python -m forliosa.news langsearch-status
    uv run python -m forliosa.news langsearch-smoke

``block`` deletes the domain's stored headlines at once (subdomains included); the list also takes
``NEWS_BLOCKED_DOMAINS`` (comma-separated) from the environment. ``searxng-check`` asks our SearXNG once (its
``/healthz``, then one news query) and prints how many results each engine gave and which engines did not answer;
it prints only the instance's scheme, host and port, never a secret, and changes nothing in the database.
``gdelt-bulk-check`` downloads the newest GDELT bulk file of each feed once (:mod:`forliosa.news.gdelt_bulk`) and
prints its size, its rows from Taiwanese sites by site (the English file: also its US and UK outlets' pages), the
headlines that name the given stocks (Taiwan or US) and the US market's headlines (``^US``); it writes nothing.

LangSearch (:mod:`forliosa.news.langsearch`, only with NEWS_LANGSEARCH_ENABLED and LANGSEARCH_API_KEY):
``langsearch-refresh`` runs one pass now, exactly as the worker's job would (only what is due, inside the day's caps,
nothing while it is paused) and prints the counts; ``langsearch-status`` prints the UTC day's requests, tokens, the
degradation level, the pause and the tiers; ``langsearch-smoke`` sends one request (「"台積電"」, oneDay, count 20)
and passes with 20 results and fewer than 200 tokens — it prints counts only and keeps the worker's rules
(:func:`forliosa.news.langsearch.smoke`): nothing while switched off, paused or past the day's caps, or while a pass
runs; the gap to the last request is waited out; the request and its tokens count in the day's usage; a refusal
(429, 401 / 403, a redirect) stops the worker until 00:00 UTC too. No headline is stored.
"""

from __future__ import annotations

import argparse
import logging
import sys

from forliosa.config import get_settings
from forliosa.db import session_factory
from forliosa.marketdata.service import get_market_data
from forliosa.models import NewsBlockedDomain
from forliosa.news import gdelt_bulk, service
from forliosa.news.searxng import SearxngSource, display_url, engine_refused
from forliosa.news.sources import SourceBlocked, SourceDown


def searxng_check(query: str, *, language: str, url: str | None, time_range: str,
                  source: SearxngSource | None = None) -> int:
    """One health check and one query against SearXNG; per-engine counts on stdout. 0 = answered, 1 = not."""
    settings = get_settings()
    if source is None:
        base = url or settings.searxng_url
        if not base:
            print("SearXNG 已關閉（NEWS_SEARXNG_ENABLED=false 或 NEWS_SEARXNG_URL 為空）")
            return 1
        source = SearxngSource(base, engines=settings.news_searxng_engines,
                               interval=settings.news_searxng_interval_seconds,
                               timeout=settings.news_searxng_timeout_seconds)
    print(f"SearXNG：{display_url(source.base_url)}")
    ok, detail = source.health()
    print(f"健康檢查（/healthz）：{detail}")
    if not ok:
        print("無法使用：確認 SearXNG 服務有在跑、API／worker 和它在同一個私有網路（見 docs/deploy.md）")
        return 1
    params = {"q": query, "format": "json", "categories": "news", "language": language, "time_range": time_range,
              "safesearch": 0, "pageno": 1}
    print(f"查詢：「{query}」 categories=news language={language} time_range={time_range}")
    try:
        ans = source.search(params)
    except SourceBlocked as exc:
        print(f"SearXNG 拒絕查詢：{exc}")
        return 1
    except SourceDown as exc:
        print(f"SearXNG 沒有回應：{exc}")
        return 1
    print(f"結果 {ans.results} 則：可用 {len(ans.items)} 則、沒有可用時間 {ans.no_date} 則、"
          f"搜尋引擎轉址 {ans.redirects} 則（略過）")
    width = max([len(e) for e in (*ans.per_engine, *source.engines, *(e for e, _ in ans.unresponsive))] + [6])
    print("各引擎結果數：")
    reported = {e for e, _ in ans.unresponsive}
    for engine in dict.fromkeys([*source.engines, *ans.per_engine]):
        if engine in reported:
            continue
        print(f"  {engine:<{width}}  {ans.per_engine.get(engine, 0)}")
    if ans.unresponsive:
        print("沒有回應的引擎：")
        for engine, reason in ans.unresponsive:
            kind = "拒絕（worker 會暫停這個引擎）" if engine_refused(reason) else "暫時錯誤"
            print(f"  {engine:<{width}}  {reason}（{kind}）")
    return 0 if ans.results or not ans.unresponsive else 1


def gdelt_bulk_check(symbols: list[str], feeds: list[str]) -> int:
    """One look at the newest file of each feed; nothing is stored. 0 = every feed answered."""
    from collections import Counter

    from forliosa.news.outlets import host_of, is_taiwan_outlet, is_us_outlet
    from forliosa.news.us_match import market_matches, us_terms

    md = get_market_data()
    queries = {}
    us: dict[str, gdelt_bulk.UsTest] = {service.US_MARKET_KEY: market_matches}
    with session_factory()() as db:
        for s in symbols:
            info = md.instrument(s)
            if info is None:
                continue
            if info.market != "US":
                queries[info.symbol] = service.build_query(db, info, service.now_utc() - service.WINDOW,
                                                           service.now_utc(), md)
            else:
                us[info.symbol] = us_terms(db, info).matches
    fetcher = gdelt_bulk.bulk_fetcher()
    status = 0
    for feed in feeds:
        index_name, suffix = gdelt_bulk.FEEDS[feed]
        try:
            latest = gdelt_bulk.parse_index(fetcher.get_bytes(gdelt_bulk.BASE_URL + index_name).decode())
            if latest is None:
                raise ValueError("索引裡沒有 GKG 檔")
            data = fetcher.get_bytes(f"{gdelt_bulk.BASE_URL}{gdelt_bulk.slot_name(latest)}{suffix}")
        except Exception as exc:
            print(f"{feed}：讀不到（{exc}）")
            status = 1
            continue
        feed_us = us if feed == gdelt_bulk.US_FEED else None
        rows = list(gdelt_bulk.gkg_rows(data, gdelt_bulk.taiwan_or_us_site if feed_us else is_taiwan_outlet))
        taiwan = [r for r in rows if is_taiwan_outlet(r.domain)]
        sites = Counter(r.domain for r in taiwan)
        print(f"{feed}：{gdelt_bulk.slot_name(latest)}（UTC）{len(data) / 1e6:.1f} MB，台灣網站 {len(taiwan)} 則："
              + "、".join(f"{d} {n}" for d, n in sites.most_common(12)))
        if feed_us:
            us_sites = Counter(host_of(r.url) for r in rows if is_us_outlet(r.url))
            print(f"  美國、英國媒體 {sum(us_sites.values())} 則："
                  + "、".join(f"{d} {n}" for d, n in us_sites.most_common(12)))
        for sym, items in gdelt_bulk.match(rows, queries, feed_us).items():
            for it in items:
                print(f"  {sym}  {it.domain}  {it.title[:80]}")
    return status


def langsearch_refresh() -> int:
    from forliosa.news import langsearch

    settings = get_settings()
    if not settings.news_langsearch_enabled:
        print("LangSearch 已關閉（NEWS_LANGSEARCH_ENABLED=false）")
        return 1
    with session_factory()() as db:
        rep = langsearch.refresh_langsearch(db, get_market_data(), settings)
    why = {"off": "已關閉", "no_key": "沒有設定 LANGSEARCH_API_KEY",
           "night": "台北 00:00–08:00 不跑（UTC 日期還是前一天）", "busy": "另一個程序正在跑",
           "paused": "暫停中（langsearch-status 看到幾點）"}
    if rep.skipped:
        print(f"沒有送出請求：{why.get(rep.skipped, rep.skipped)}")
        return 0 if rep.skipped in ("night", "busy", "paused") else 1
    print(f"請求 {rep.requests} 次（{rep.tokens} token），大盤 {rep.topics} 個查詢，個股 {rep.symbols} 檔"
          f"（第一次 {rep.first_fills} 檔），留下 {rep.kept} 則、新增 {rep.stored} 則；"
          f"降級 {rep.level}、今天上限 {rep.cap} 次"
          + (f"；停下：{rep.stopped}" if rep.stopped else "")
          + (f"；剔除 {dict(rep.drops)}" if rep.drops else ""))
    return 0


def langsearch_status() -> int:
    from forliosa.news import langsearch
    from forliosa.timeutil import iso_taipei

    with session_factory()() as db:
        st = langsearch.status(db)
    until = st["paused_until"]
    print(f"LangSearch：{'開' if st['enabled'] else '關'}（{'有' if st['configured'] else '沒有'}可用的設定與金鑰）")
    stopped = f"、今天停下：{st['stopped']}" if st["stopped"] else ""
    print(f"UTC {st['day_utc']}：請求 {st['requests']}／{st['request_cap']} 次、"
          f"token {st['tokens']}／{st['token_cap']}、第一次填入 {st['first_fills']} 檔{stopped}")
    print(f"降級：{st['level']}" + (f"；暫停到 {iso_taipei(until)}" if until is not None else ""))
    if st["warning"]:
        print("警告：回應超過 token 上限（contents 的字數上限沒有生效），今天停用")
    print("分級：" + "、".join(f"{k} {v}" for k, v in st["tiers"].items()))
    ai_stop = f"、今天停下：{st['ai_stopped']}" if st["ai_stopped"] else ""
    print(f"AI（對話、法人觀點、為什麼漲跌）：{'開' if st['ai_enabled'] else '關'}；請求 {st['ai_requests']}／"
          f"{st['ai_request_cap']} 次、token {st['ai_tokens']}／{st['ai_token_cap']}{ai_stop}")
    return 0


def langsearch_smoke(client=None, settings=None, *, clock=None, sleep=None) -> int:
    """One request under the worker's rules (:func:`forliosa.news.langsearch.smoke`); counts only."""
    from forliosa.news import langsearch
    from forliosa.timeutil import iso_taipei

    settings = settings or get_settings()
    if not (settings.news_enabled and settings.news_langsearch_enabled):
        print("LangSearch 已關閉（NEWS_ENABLED 或 NEWS_LANGSEARCH_ENABLED 為 false），沒有送出請求")
        return 1
    own = client is None
    if client is None:
        client = langsearch.LangSearchClient.from_settings(settings)
    if client is None:
        print("沒有設定 LANGSEARCH_API_KEY（沙盒：設成 proxy-injected，由 proxy 代入），沒有送出請求")
        return 1
    extra = {k: v for k, v in (("clock", clock), ("sleep", sleep)) if v is not None}
    try:
        with session_factory()() as db:
            res = langsearch.smoke(db, settings, client, **extra)
    finally:
        if own:
            client.close()
    if res.skipped:
        until = f"暫停到 {iso_taipei(res.paused_until)}" if res.paused_until is not None else "暫停中"
        why = {"off": "已關閉", "busy": "worker 正在跑一輪，等它跑完再試",
               "paused": f"{until}（被擋或連不上，langsearch-status 看原因）",
               "requests_cap": "今天（UTC）的請求數已到上限", "tokens_cap": "今天（UTC）的 token 已到上限"}
        print(f"沒有送出請求：{why.get(res.skipped, res.skipped)}")
        return 1
    stopped = {"quota": "碰到額度，worker 也停到下一個 00:00 UTC（台北 08:00）",
               "blocked": "被拒（401／403／轉址），worker 也停到下一個 00:00 UTC",
               "contract": "回應超過 token 上限，今天停用", "unreachable": "連續連不上，整個來源暫停 15 分鐘起"}
    if res.error is not None or res.reply is None:
        print(f"失敗：{res.error}" + (f"；{stopped[res.stopped]}" if res.stopped in stopped else ""))
        return 1
    reply = res.reply
    print(f"HTTP {reply.status}，{res.items} 筆有標題、網址、時間，token {reply.input_tokens}+{reply.output_tokens}，"
          f"{reply.latency:.1f} 秒（算進今天的用量）：{'通過' if res.passed else '不通過（要 20 筆、少於 200 token）'}")
    return 0 if res.passed else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m forliosa.news",
                                     description="新聞報導：更新、下架封鎖清單、清除過期")
    sub = parser.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("refresh", help="立即更新追蹤中的股票（或 --symbol 指定）")
    r.add_argument("--symbol", action="append", help="只更新這些代號（可重複）")
    r.add_argument("--no-ai", action="store_true", help="不用 AI 搜尋補缺")
    b = sub.add_parser("block", help="把網域加入下架封鎖清單，並刪除已存的標題")
    b.add_argument("domain")
    b.add_argument("--reason", default=None, help="例如：2026-11-20 來函要求下架")
    u = sub.add_parser("unblock", help="從封鎖清單移除網域")
    u.add_argument("domain")
    sub.add_parser("blocked", help="列出封鎖清單")
    sub.add_parser("purge", help="刪除超過保存期限的標題")
    c = sub.add_parser("searxng-check", help="SearXNG 健康檢查＋查一次新聞，列出各引擎的結果數（不寫資料庫）")
    c.add_argument("query", help="例如：台積電")
    c.add_argument("--language", default="zh-TW", help="zh-TW（預設）或 en")
    c.add_argument("--time-range", default="week", choices=["day", "week", "month", "year"])
    c.add_argument("--url", default=None, help="SearXNG 網址（預設用 NEWS_SEARXNG_URL）")
    g = sub.add_parser("gdelt-bulk-check",
                       help="下載 GDELT 最新一份整批檔，列出台灣網站與美國、英國媒體的則數，"
                            "點名這些股票的標題與美股市場新聞（不寫資料庫）")
    g.add_argument("--symbol", action="append", default=[], help="比對這些代號（可重複，台股或美股）")
    g.add_argument("--feed", action="append", choices=sorted(gdelt_bulk.FEEDS), help="預設兩種都看")
    sub.add_parser("langsearch-refresh", help="LangSearch：照排程跑一次（只跑到期的，守每天上限）")
    sub.add_parser("langsearch-status", help="LangSearch：今天（UTC）的請求數、token、降級、暫停與分級")
    sub.add_parser("langsearch-smoke", help="LangSearch：照 worker 的規則送一次「台積電」，只印筆數與 token"
                                            "（算進今天的用量；關閉、暫停、到上限時不送）")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.cmd == "searxng-check":
        return searxng_check(args.query, language=args.language, url=args.url, time_range=args.time_range)
    if args.cmd == "gdelt-bulk-check":
        return gdelt_bulk_check(args.symbol, args.feed or ["translation", "english"])
    if args.cmd == "langsearch-refresh":
        return langsearch_refresh()
    if args.cmd == "langsearch-status":
        return langsearch_status()
    if args.cmd == "langsearch-smoke":
        return langsearch_smoke()
    settings = get_settings()
    with session_factory()() as db:
        if args.cmd == "refresh":
            md = get_market_data()
            symbols = None
            if args.symbol:
                symbols = [i.symbol for s in args.symbol if (i := md.instrument(s)) is not None]
            if args.no_ai:
                settings = settings.model_copy(update={"news_ai_enabled": False})
            rep = service.refresh(db, md, settings=settings, symbols=symbols)
            print(f"{rep.symbols} 檔，請求 {rep.fetched}，新增 {rep.stored} 則，AI 搜尋 {rep.ai_searches} 次"
                  + (f"，GDELT 整批檔：台股{'可用' if rep.bulk_ok else '不是最新'}（台灣網站 {rep.bulk_rows} 則）、"
                     f"美股{'可用' if rep.bulk_us_ok else '不是最新'}（美國、英國媒體 {rep.bulk_us_rows} 則）"
                     if "gdelt_bulk" in rep.fetched or rep.bulk_ok or rep.bulk_us_ok else "")
                  + (f"，略過 {rep.skipped}" if rep.skipped else "")
                  + (f"，暫停的來源 {rep.blocked_sources}" if rep.blocked_sources else "")
                  + (f"，暫停的 SearXNG 引擎 {rep.paused_engines}" if rep.paused_engines else ""))
        elif args.cmd == "block":
            n = service.block_domain(db, args.domain, args.reason)
            print(f"已封鎖 {args.domain}，刪除 {n} 則已存標題")
        elif args.cmd == "unblock":
            print("已移除" if service.unblock_domain(db, args.domain) else "不在封鎖清單")
        elif args.cmd == "blocked":
            rows = {r.domain: r for r in db.query(NewsBlockedDomain)}
            for d in service.blocked_domains(db, settings):
                row = rows.get(d)
                origin = f"（{row.reason}）" if row is not None and row.reason else "" if row else "（環境變數）"
                print(f"{d}{origin}")
        elif args.cmd == "purge":
            print(f"刪除 {service.purge(db, settings)} 則過期標題")
    return 0


if __name__ == "__main__":
    sys.exit(main())
