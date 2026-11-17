"""``python -m forliosa.news`` — news headlines: refresh now, the takedown blocklist, retention.

    uv run python -m forliosa.news refresh [--symbol 2330.TW …] [--no-ai]
    uv run python -m forliosa.news block udn.com --reason "2026-11-20 來函要求下架"
    uv run python -m forliosa.news unblock udn.com
    uv run python -m forliosa.news blocked
    uv run python -m forliosa.news purge
    uv run python -m forliosa.news searxng-check "台積電" [--language en] [--url http://localhost:8080]
    uv run python -m forliosa.news gdelt-bulk-check [--symbol 2330 --symbol NVDA …] [--feed translation]

``block`` deletes the domain's stored headlines at once (subdomains included); the list also takes
``NEWS_BLOCKED_DOMAINS`` (comma-separated) from the environment. ``searxng-check`` asks our SearXNG once (its
``/healthz``, then one news query) and prints how many results each engine gave and which engines did not answer;
it prints only the instance's scheme, host and port, never a secret, and changes nothing in the database.
``gdelt-bulk-check`` downloads the newest GDELT bulk file of each feed once (:mod:`forliosa.news.gdelt_bulk`) and
prints its size, its rows from Taiwanese sites by site (the English file: also its US and UK outlets' pages), the
headlines that name the given stocks (Taiwan or US) and the US market's headlines (``^US``); it writes nothing.
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
                                                           service.now_utc())
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
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.cmd == "searxng-check":
        return searxng_check(args.query, language=args.language, url=args.url, time_range=args.time_range)
    if args.cmd == "gdelt-bulk-check":
        return gdelt_bulk_check(args.symbol, args.feed or ["translation", "english"])
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
