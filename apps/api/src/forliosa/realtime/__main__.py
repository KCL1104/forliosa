"""Development helper: send one realtime event from this process, as the worker would.

    uv run python -m forliosa.realtime notify market.closes --market TWSE
    uv run python -m forliosa.realtime notify market.overview

Only with a PostgreSQL ``DATABASE_URL`` (on SQLite another process's hub cannot hear it). Market topics only: they
carry no user data and go to every signed-in page.
"""

from __future__ import annotations

import argparse
import sys

from forliosa.config import get_settings
from forliosa.realtime.capture import notify_now
from forliosa.realtime.events import ALL, event

TOPICS = ("market.closes", "market.overview", "market.reports")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m forliosa.realtime")
    sub = p.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("notify", help="send one market event to every open page")
    n.add_argument("topic", choices=TOPICS)
    n.add_argument("--market", choices=("TWSE", "TPEX", "US"))
    n.add_argument("--date", help="YYYY-MM-DD")
    args = p.parse_args(argv)
    if not get_settings().database_url.startswith("postgresql"):
        print("需要 PostgreSQL 的 DATABASE_URL（SQLite 時其他程序聽不到）", file=sys.stderr)
        return 2
    data = {"market": args.market, "date": args.date} if args.topic == "market.closes" else {}
    notify_now(event(args.topic, data, (ALL,)))
    print("sent", args.topic)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
