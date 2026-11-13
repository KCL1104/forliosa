import { Link } from "@tanstack/react-router"
import { useState } from "react"
import type { MarketOverview } from "@/api/types"
import { Section } from "@/components/section"
import { formatDateShort, formatNumber } from "@/lib/format"

/** 先列這麼多則，其餘按了才展開 */
const FIRST = 6

/**
 * 重大訊息：上市櫃公司當天發布的重大訊息，新的在前。每一列（時間｜公司・主旨）連到那一檔的「事件」分頁。
 * 後端最多給最新的 30 則；當天一共幾則寫在標題旁邊。
 */
export function Announcements({ announcements }: { announcements: NonNullable<MarketOverview["announcements"]> }) {
  const [open, setOpen] = useState(false)
  const { items, total } = announcements
  const shown = open ? items : items.slice(0, FIRST)
  const more = items.length - FIRST
  return (
    <Section
      title="重大訊息"
      titleId="market-announcements"
      aside={
        <span className="num">
          {formatDateShort(announcements.date, false)}・共 {formatNumber(total)} 則{total > items.length && `，列出最新 ${items.length} 則`}
        </span>
      }
      bodyClassName="max-w-[46rem] pt-0"
    >
      <ul>
        {shown.map((a, n) => (
          <li key={`${a.symbol}-${a.time}-${n}`}>
            <Link
              to="/stock/$symbol"
              params={{ symbol: a.symbol }}
              search={{ tab: "events" }}
              className="ruled-row grid min-h-14 grid-cols-[3rem_minmax(0,1fr)] gap-x-3 py-2.5 focus-visible:-outline-offset-2"
            >
              <span className="num pt-0.5 text-sm text-ink-2">{a.time ?? "—"}</span>
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
    </Section>
  )
}
