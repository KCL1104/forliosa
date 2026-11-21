import { Link } from "@tanstack/react-router"
import { useState } from "react"
import type { MarketOverview } from "@/api/types"
import { Tray } from "@/components/tray"
import { formatDateShort, formatNumber } from "@/lib/format"
import { cn } from "@/lib/utils"

/** 先列這麼多則，其餘按了才展開 */
const FIRST = 6

/**
 * 重大訊息：上市櫃公司最新一天發布的重大訊息，新的在前。每一列（時間｜公司・主旨）連到那一檔的「事件」分頁。
 * 後端最多給最新的 30 則；一共幾則寫在托盤的 meta（「11/12・共 428 則」）。
 * 最新的一天是週末或放假日時，後端往前一起列到最後一個交易日（產品負責人 2026-11-15：週日不要只看到週六的幾則）：
 * meta 寫期間（「11/13–11/14・共 N 則」），每一列的時間上面多一行日期。
 */
export function Announcements({ announcements, className }: { announcements: NonNullable<MarketOverview["announcements"]>; className?: string }) {
  const [open, setOpen] = useState(false)
  const { items, total, date, start_date: start } = announcements
  const shown = open ? items : items.slice(0, FIRST)
  const more = items.length - FIRST
  const days = start === date ? formatDateShort(date, false) : `${formatDateShort(start, false)}–${formatDateShort(date, false)}`
  return (
    <Tray title="重大訊息" meta={`${days}・共 ${formatNumber(total)} 則`} className={className} bodyClassName="max-w-[46rem]">
      <ul>
        {shown.map((a, n) => (
          <li key={`${a.symbol}-${a.time}-${n}`}>
            <Link
              to="/stock/$symbol"
              params={{ symbol: a.symbol }}
              search={{ tab: "events" }}
              className={cn(
                "ruled-row grid min-h-14 grid-cols-[3rem_minmax(0,1fr)] gap-x-3 py-2.5 focus-visible:-outline-offset-2",
                n === shown.length - 1 && more <= 0 && "border-b-0",
              )}
            >
              <span className="num pt-0.5 text-sm text-ink-2">
                {start !== date && <span className="block">{formatDateShort(a.date, false)}</span>}
                {a.time ?? "—"}
              </span>
              <span className="min-w-0">
                <span className="flex items-baseline gap-2">
                  <span className="truncate text-base font-medium">{a.name}</span>
                  <span className="num shrink-0 text-sm text-ink-2">{a.code}</span>
                </span>
                <span className="mt-0.5 line-clamp-2 text-base text-ink">{a.title}</span>
              </span>
            </Link>
          </li>
        ))}
      </ul>
      {more > 0 && (
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
          className="mt-1 inline-flex min-h-11 items-center text-sm text-ink-2 underline decoration-ctl underline-offset-3 hover:text-ink hover:decoration-ink"
        >
          {open ? "收起來" : `再看 ${more} 則`}
        </button>
      )}
    </Tray>
  )
}
