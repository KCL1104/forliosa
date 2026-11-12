"""``python -m forliosa.news`` — news headlines: refresh now, the takedown blocklist, retention.

    uv run python -m forliosa.news refresh [--symbol 2330.TW …] [--no-ai]
    uv run python -m forliosa.news block udn.com --reason "2026-11-20 來函要求下架"
    uv run python -m forliosa.news unblock udn.com
    uv run python -m forliosa.news blocked
    uv run python -m forliosa.news purge

``block`` deletes the domain's stored headlines at once (subdomains included); the list also takes
``NEWS_BLOCKED_DOMAINS`` (comma-separated) from the environment.
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
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
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
                  + (f"，暫停的來源 {rep.blocked_sources}" if rep.blocked_sources else ""))
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
