import { Fragment, useState } from "react"
import type { MarketOverview } from "@/api/types"
import { Pct } from "@/components/finance"
import { Section } from "@/components/section"
import { formatDateShort } from "@/lib/format"
import { cn } from "@/lib/utils"

/** 窄畫面先只列漲最多與跌最多的各幾個 */
const HEAD = 5

/**
 * 類股漲跌：證交所各類股指數當天的漲跌幅，由高到低。
 * 每列是名稱、一條從零軸往右（漲）或往左（跌）的橫條、漲跌幅。橫條用 40% 的漲跌色（比成交量柱的 30% 深一點：這裡的條很細），
 * 方向靠位置與 ▲▼，不只靠顏色；數字是主角，橫條只幫忙看大小。寬的時候排成兩到三欄（一欄讀完接下一欄），
 * 窄的時候先列頭尾各 5 個，按「全部」展開。
 */
export function SectorList({ sectors }: { sectors: NonNullable<MarketOverview["sectors"]> }) {
  const [open, setOpen] = useState(false)
  const items = sectors.items
  const max = Math.max(...items.map((s) => Math.abs(s.change_pct)), 0.0001)
  const collapsible = items.length > HEAD * 2 + 1
  return (
    <Section title="類股" titleId="market-sectors" aside={<span className="num">{formatDateShort(sectors.date, false)}・漲跌幅由高到低</span>} bodyClassName="pt-0">
      <ul className="@2xl:columns-2 @2xl:gap-x-10 @5xl:columns-3">
        {items.map((s, n) => {
          const middle = collapsible && n >= HEAD && n < items.length - HEAD
          const up = s.change_pct > 0
          const flat = s.change_pct === 0
          return (
            <Fragment key={s.index_name}>
              {/* 窄畫面收著的時候：頭 5 個和尾 5 個之間空一格，看得出中間跳過了 */}
              {collapsible && !open && n === items.length - HEAD && (
                <li aria-hidden className="flex h-8 items-center justify-center border-b border-rule text-sm text-ink-2 @2xl:hidden">
                  ⋯
                </li>
              )}
              <li className={cn("grid h-10 break-inside-avoid grid-cols-[8em_minmax(2.5rem,1fr)_4.25rem] items-center gap-x-3 border-b border-rule", middle && !open && "@max-2xl:hidden")}>
                <span className="truncate text-base">{s.name}</span>
                <span aria-hidden className="relative h-2">
                  <span className="absolute -inset-y-1 left-1/2 w-px bg-ctl" />
                  {!flat && (
                    <span
                      className={cn("absolute inset-y-0 rounded-[1px]", up ? "left-1/2 bg-rise/40" : "right-1/2 bg-fall/40")}
                      style={{ width: `${Math.max(1.5, (Math.abs(s.change_pct) / max) * 50)}%` }}
                    />
                  )}
                </span>
                <Pct value={s.change_pct} className="justify-end text-base" />
              </li>
            </Fragment>
          )
        })}
      </ul>
      {collapsible && (
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
          className="mt-1 inline-flex min-h-11 items-center text-sm text-ink-2 underline decoration-ctl underline-offset-3 hover:text-ink hover:decoration-ink @2xl:hidden"
        >
          {open ? "只看漲跌最多的" : `全部 ${items.length} 個類股`}
        </button>
      )}
    </Section>
  )
}
