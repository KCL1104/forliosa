"""``python -m forliosa.news`` — news headlines: refresh now, the takedown blocklist, retention.

    uv run python -m forliosa.news refresh [--symbol 2330.TW …] [--no-ai]
    uv run python -m forliosa.news block udn.com --reason "2026-11-20 來函要求下架"
    uv run python -m forliosa.news unblock udn.com
    uv run python -m forliosa.news blocked
    uv run python -m forliosa.news purge
    uv run python -m forliosa.news searxng-check "台積電" [--language en] [--url http://localhost:8080]

``block`` deletes the domain's stored headlines at once (subdomains included); the list also takes
``NEWS_BLOCKED_DOMAINS`` (comma-separated) from the environment. ``searxng-check`` asks our SearXNG once (its
``/healthz``, then one news query) and prints how many results each engine gave and which engines did not answer;
it prints only the instance's scheme, host and port, never a secret, and changes nothing in the database.
"""

from __future__ import annotations

import argparse
import logging
import sys

from forliosa.config import get_settings
from forliosa.db import session_factory
from forliosa.marketdata.service import get_market_data
from forliosa.models import NewsBlockedDomain
from forliosa.news import service
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
    print(f"結果 {ans.results} 則：可用 {len(ans.items)} 則、沒有時間 {ans.no_date} 則、"
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
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.cmd == "searxng-check":
        return searxng_check(args.query, language=args.language, url=args.url, time_range=args.time_range)
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
