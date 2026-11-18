"""``python -m forliosa.reports``: the market reports from the command line (no model call in any of these).

    seed                                  NYSE holidays, macro calendar and US earnings seeds -> the three tables
    status                                mode, this month's spending and tier, the latest runs
    pack --kind K --date YYYY-MM-DD       build a data pack only (prints counts and what is missing; --out writes it)
    data --kind K --date YYYY-MM-DD       the data edition (a past date: a backfill, admins only, never pushed)
    run --kind K --date D [--writer W] --yes   one full AI attempt (gathering, writing, checks); without --yes only
                                          the estimate is printed. W: opus-high | opus-medium | sonnet-high | opus-xhigh
    tables --date YYYY-MM-DD | --promoted  a close edition's tables rebuilt from everything stored now (the AI text
                                          kept, never pushed); --promoted: every former blind-test close whose newer
                                          23:45 / 06:40 tables were left behind by migration 0028
    probe-dates                           when the evening files really change (MI_MARGN, foreign top 20, TAIFEX)

Never prints a key or an environment value (key slots only as ``#4``). Only ``run --yes`` calls a model.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from forliosa.db import session_factory
from forliosa.market_calendar import load_official_calendar
from forliosa.timeutil import TAIPEI, now_taipei


def _default(o: Any) -> Any:
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    return str(o)


def cmd_seed() -> int:
    from forliosa.reports import calendars

    with session_factory()() as db:
        written = calendars.seed(db)
        status = calendars.nyse_status(db, now_taipei().date())
    print(f"寫入：NYSE 休市表 {written['nyse_holidays']} 列、總經行事曆 {written['macro_calendar']} 列、"
          f"美股財報日 {written['us_earnings']} 列")
    print(f"NYSE 表共 {status['rows']} 列，尚未核對 {status['unverified']} 列")
    return 0


def cmd_status() -> int:
    from forliosa.ai.keypool import get_key_pool
    from forliosa.config import get_settings
    from forliosa.models import MarketReportRun
    from forliosa.reports import accounting
    from forliosa.reports import settings as rs
    from forliosa.reports.calls import report_slot

    s = get_settings()
    with session_factory()() as db:
        cfg = rs.config(db, s)
        month = accounting.month_spend(db)
        on = "開" if s.market_reports_enabled else "關"
        print(f"總開關 MARKET_REPORTS_ENABLED：{on}；模式：{rs.mode_of(cfg.mode)}")
        print(f"本月花費 US${month:.2f}／上限 US${s.ai_mreport_monthly_budget_usd:.2f}")
        for kind in ("premarket", "close", "weekly"):
            tier = accounting.tier(db, kind, settings=s)
            writer = rs.apply_tier(rs.chosen_writer(db, kind, s), tier)
            print(f"  {kind}：層級 {tier}，撰寫 {writer.model + ' ' + writer.effort if writer else '只發資料版'}")
        pool = get_key_pool()
        slot = report_slot(pool)
        own = f"#{slot}" if slot is not None else "沒有（共用金鑰池）" if not pool.reserved else "不可用"
        print(f"專用金鑰：{own}")
        runs = list(db.scalars(select(MarketReportRun).order_by(MarketReportRun.started_at.desc()).limit(10)))
        print(f"最近 {len(runs)} 次產生：")
        for r in runs:
            print(f"  {r.id} {r.report_id} {r.variant or '-'} {r.purpose} #{r.attempt} {r.status}/{r.step} "
                  f"{r.tier} US${float(r.cost_usd or 0):.3f} slot {'#' + str(r.key_slot) if r.key_slot else '-'}")
    return 0


def cmd_pack(kind: str, day: date, out: str | None) -> int:
    from forliosa.marketdata.service import get_market_data
    from forliosa.reports import pack

    with session_factory()() as db:
        load_official_calendar(db)
        built = pack.build(db, kind, day, md_=get_market_data())
    print(json.dumps(pack.summary(built), ensure_ascii=False, indent=1, default=_default))
    if out:
        Path(out).write_text(json.dumps({"pack": built.pack, "blocks": built.blocks}, ensure_ascii=False, indent=1,
                                        default=_default), encoding="utf-8")
        print(f"寫到 {out}")
    return 0


WRITERS = {"opus-high": ("claude-opus-5-5", "high"), "opus-medium": ("claude-opus-5-5", "medium"),
           "sonnet-high": ("claude-sonnet-5-5", "high"), "opus-xhigh": ("claude-opus-5-5", "xhigh")}


def cmd_data(kind: str, day: date) -> int:
    from forliosa.marketdata.service import get_market_data
    from forliosa.reports import pipeline

    deps = pipeline.default_deps()
    deps.md = get_market_data()
    with session_factory()() as db:
        load_official_calendar(db)
        report = pipeline.backfill_data(db, kind, day, deps)
        v = pipeline.current(db, report)
        print(f"{report.id}：{report.kind} {report.edition_date}，第 {v.version if v else '?'} 版（資料版），"
              f"{'回補，只有管理員看得到' if report.backfill else report.visibility}")
    return 0


def cmd_run(kind: str, day: date, writer_key: str, yes: bool) -> int:
    from forliosa.config import get_settings
    from forliosa.marketdata.service import get_market_data
    from forliosa.reports import accounting, pipeline
    from forliosa.reports import settings as rs

    model, effort = WRITERS[writer_key]
    est = accounting.EST_MAX_USD[kind]["normal"] * (accounting.XHIGH_FACTOR if effort == "xhigh" else 1)
    print(f"{kind} {day}：撰寫 {model} {effort}，蒐集 {rs.gather_model()[0]}，檢查 {rs.check_model()[0]}；"
          f"預估上限 US${est:.2f}")
    if not yes:
        print("沒有 --yes：只印預估，不呼叫模型。")
        return 0
    if not get_settings().market_reports_enabled:
        print("提醒：MARKET_REPORTS_ENABLED 是關的；這次照樣跑（只有管理員看得到）。")
    deps = pipeline.default_deps()
    deps.md = get_market_data()
    with session_factory()() as db:
        load_official_calendar(db)
        run = pipeline.run_once(db, kind, day, rs.Writer(model, effort), deps)
        print(f"{run.id}：{run.status}/{run.step}，US${float(run.cost_usd or 0):.3f}，"
              f"slot {'#' + str(run.key_slot) if run.key_slot else '-'}{'，' + run.error if run.error else ''}")
    return 0


def cmd_tables(day: date | None, promoted: bool) -> int:
    from forliosa.marketdata.service import get_market_data
    from forliosa.reports import pipeline

    deps = pipeline.default_deps()
    deps.md = get_market_data()
    with session_factory()() as db:
        load_official_calendar(db)
        if promoted:
            todo = pipeline.promoted_closes(db)
        else:
            report = pipeline.report_of(db, "close", day) if day else None
            if report is None or report.current_version_id is None:
                print(f"沒有 {day} 的盤後重點")
                return 1
            todo = [report]
        if not todo:
            print("沒有要重建表格的盤後重點")
        for report in todo:
            v = pipeline.add_tables(db, report, deps.clock().astimezone(TAIPEI), deps)
            print(f"{report.id}：盤後重點 {report.edition_date}，第 {v.version} 版（表格更新）")
    return 0


# -- probe-dates -----------------------------------------------------------------------------------------------------
# (dataset, url, whole file?): the small files are read whole (their newest date); MI_MARGN (≈500 KB, no date field)
# only by a ranged, conditional request for its validators
PROBES = (
    ("twse-openapi/margin", "https://openapi.twse.com.tw/v1/exchangeReport/MI_MARGN", False),
    ("twse-openapi/foreign_top20", "https://openapi.twse.com.tw/v1/fund/MI_QFIIS_sort_20", True),
    ("twse-openapi/turnover", "https://openapi.twse.com.tw/v1/exchangeReport/FMTQIK", True),
    ("taifex-openapi/institutional_general",
     "https://openapi.taifex.com.tw/v1/MarketDataOfMajorInstitutionalTradersGeneralBytheDate", True),
    ("taifex-openapi/put_call_ratio", "https://openapi.taifex.com.tw/v1/PutCallRatio", True),
)
_DATE = re.compile(r'"(?:Date|日期)"\s*:\s*"(\d{7,8})"|^(\d{8}),', re.MULTILINE)


def newest_date(body: bytes) -> str | None:
    """The newest date field in a JSON (ROC or Gregorian) or CSV body; ``None`` without one."""
    found = []
    for m in _DATE.finditer(body.decode("utf-8", "ignore")):
        raw = m.group(1) or m.group(2)
        found.append(f"{int(raw[:3]) + 1911}-{raw[3:5]}-{raw[5:7]}" if len(raw) == 7 else
                     f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}")
    return max(found) if found else None


def cmd_probe_dates() -> int:
    """When the evening files change and which day they carry (memo phase 0): MI_MARGN and MI_QFIIS_sort_20 have no
    date field, so the archive stamps them by the clock (``Archiver.margin_date``); this shows whether the file read in
    the evening already holds that evening's session. Reads the database and the OpenAPIs only (a few small
    conditional requests, no model call). Run it once in the evening (after 21:00) and once the next morning."""
    from forliosa.archive import default_fetcher
    from forliosa.models import DatasetStatus, ForeignHoldingTop20, MarginDaily, TaifexInstitutional

    now = now_taipei()
    print(f"現在 {now:%Y-%m-%d %H:%M}（台北）")
    with session_factory()() as db:
        load_official_calendar(db)
        print("資料庫：")
        margin = db.scalar(select(func.max(MarginDaily.date)).where(MarginDaily.source == "twse-openapi"))
        print(f"  融資融券（上市）最新日期 {margin}")
        print(f"  外資持股前 20 最新日期 {db.scalar(select(func.max(ForeignHoldingTop20.date)))}")
        print(f"  期交所三大法人最新日期 {db.scalar(select(func.max(TaifexInstitutional.trade_date)))}")
        for key in ("twse-openapi/price", "twse-openapi/turnover", "taifex-openapi/institutional_general"):
            row = db.get(DatasetStatus, key)
            if row is not None:
                print(f"  {key}：資料日期 {row.data_date}，抓取 {row.fetched_at.astimezone(TAIPEI):%m/%d %H:%M}")
    print("開放資料（Last-Modified 換成台北時間；檔案內最新的日期）：")
    fetcher = default_fetcher()
    for key, url, whole in PROBES:
        try:
            if whole:
                body, headers = fetcher.fetch(url)
                last_modified = headers.get("last-modified")
            else:
                probe = fetcher.probe(url, first_bytes=1024)
                body, last_modified = probe.head, probe.last_modified
        except Exception as exc:  # unreachable: say so and go on
            status = getattr(exc, "status", None)
            print(f"  {key}：讀不到（{type(exc).__name__}{f' {status}' if status else ''}）")
            continue
        lm = None
        if last_modified:
            try:
                lm = parsedate_to_datetime(last_modified).astimezone(TAIPEI)
            except (TypeError, ValueError):
                lm = None
        newest = newest_date(body) if whole else None
        print(f"  {key}：最後更新 {f'{lm:%m/%d %H:%M}' if lm else '不明'}；"
              f"{'檔案內最新日期 ' + newest if newest else '檔案沒有日期欄'}")
    print("判讀：晚上（21:00 後）跑一次，若融資融券與外資前 20 的最後更新仍是當天清晨，"
          "表示晚上的檔還是前一個交易日的資料：存檔會略過，不把它標成當天（reports.timing 也先用隔天清晨）。"
          "期交所若 21:45 前已更新成當天日期，可以把可用時間提早。")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m forliosa.reports", description="市場報告（只有 run --yes 會呼叫模型）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("seed", help="手動表的初始資料")
    sub.add_parser("status", help="模式、花費、層級、最近的產生紀錄")
    pk = sub.add_parser("pack", help="只建資料包")
    pk.add_argument("--kind", required=True, choices=("premarket", "close", "weekly"))
    pk.add_argument("--date", required=True, type=date.fromisoformat)
    pk.add_argument("--out")
    dt = sub.add_parser("data", help="建資料版（過去的日期＝回補，只有管理員看得到）")
    dt.add_argument("--kind", required=True, choices=("premarket", "close", "weekly"))
    dt.add_argument("--date", required=True, type=date.fromisoformat)
    rn = sub.add_parser("run", help="跑一次完整 AI 流程（要 --yes 才會呼叫模型）")
    rn.add_argument("--kind", required=True, choices=("premarket", "close", "weekly"))
    rn.add_argument("--date", required=True, type=date.fromisoformat)
    rn.add_argument("--writer", default="opus-high", choices=tuple(WRITERS))
    rn.add_argument("--yes", action="store_true")
    tb = sub.add_parser("tables", help="重建盤後重點的表格（不呼叫模型、不推播）")
    which = tb.add_mutually_exclusive_group(required=True)
    which.add_argument("--date", type=date.fromisoformat)
    which.add_argument("--promoted", action="store_true", help="盲測拿掉時留下舊表格的盤後重點")
    sub.add_parser("probe-dates", help="量融資、外資前 20、期交所晚上檔案的日期")
    args = ap.parse_args(argv)
    if args.cmd == "tables":
        return cmd_tables(args.date, args.promoted)
    if args.cmd == "data":
        return cmd_data(args.kind, args.date)
    if args.cmd == "run":
        return cmd_run(args.kind, args.date, args.writer, args.yes)
    if args.cmd == "seed":
        return cmd_seed()
    if args.cmd == "status":
        return cmd_status()
    if args.cmd == "pack":
        return cmd_pack(args.kind, args.date, args.out)
    return cmd_probe_dates()


if __name__ == "__main__":
    sys.exit(main())
