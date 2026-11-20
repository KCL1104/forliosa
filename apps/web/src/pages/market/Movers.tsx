import { Link } from "@tanstack/react-router"
import { useState } from "react"
import type { MarketMover, MarketMovers } from "@/api/types"
import { Pct } from "@/components/finance"
import { RangeChips } from "@/components/segmented"
import { Tray, type TrayTint } from "@/components/tray"
import { formatDateShort, formatNumber, formatPrice, formatVolume } from "@/lib/format"
import { cn } from "@/lib/utils"

type Kind = "gainers" | "losers" | "volume"
const KINDS: { value: Kind; label: string }[] = [
  { value: "gainers", label: "漲幅" },
  { value: "losers", label: "跌幅" },
  { value: "volume", label: "成交量" },
]

/** 一張表的名稱寫實際的列數：跌幅只有 6 檔時是「跌幅前 6」，不是「前 10」；一檔都沒有時只寫種類 */
function moverTitle(label: string, count: number): string {
  return count > 0 ? `${label}前 ${formatNumber(count)}` : label
}

/**
 * 排行：上市與上櫃的普通股（不含 ETF），漲幅、跌幅、成交量各最多 10 檔。每一列連到個股頁。
 * 一盤（托盤）：meta 是日期與範圍（「11/12・16 檔普通股，不含 ETF」）。每張表有印好的表頭，寫表的名稱與實際的列數
 * （「跌幅前 6」）。托盤夠寬（≥ 832px）時三張表並排；窄的時候上面一排選項，一次看一張。
 */
export function Movers({ movers, tint, className }: { movers: MarketMovers; tint?: TrayTint; className?: string }) {
  const [kind, setKind] = useState<Kind>("gainers")
  return (
    <Tray
      title="排行"
      meta={`${formatDateShort(movers.date, false)}・${formatNumber(movers.count)} 檔普通股，不含 ETF`}
      tint={tint}
      className={className}
      bodyClassName="@container"
    >
      <RangeChips label="排行的種類" value={kind} options={KINDS} onChange={setKind} className="mb-1 @[52rem]:hidden" />
      <div className="@[52rem]:grid @[52rem]:grid-cols-3 @[52rem]:gap-x-8">
        {KINDS.map((k) => (
          <MoverList key={k.value} kind={k.value} label={k.label} items={movers[k.value]} hiddenWhenNarrow={k.value !== kind} />
        ))}
      </div>
    </Tray>
  )
}

function MoverList({ kind, label, items, hiddenWhenNarrow }: { kind: Kind; label: string; items: MarketMover[]; hiddenWhenNarrow: boolean }) {
  const headId = `market-movers-${kind}`
  return (
    <div className={cn("min-w-0", hiddenWhenNarrow && "@max-[52rem]:hidden")}>
      <div className="form-head flex h-9 items-end justify-between gap-3 pb-2">
        <span id={headId}>{moverTitle(label, items.length)}</span>
        <span>{kind === "volume" ? "成交量・漲跌幅" : "收盤價・漲跌幅"}</span>
      </div>
      {items.length === 0 ? (
        <p className="py-3 text-base text-ink">{kind === "gainers" ? "沒有上漲的股票" : kind === "losers" ? "沒有下跌的股票" : "還沒有資料"}</p>
      ) : (
        <ol aria-labelledby={headId}>
          {items.map((m, n) => (
            <li key={m.symbol}>
              <Link
                to="/stock/$symbol"
                params={{ symbol: m.symbol }}
                className={cn(
                  "ruled-row grid h-[60px] grid-cols-[1.25rem_minmax(0,1fr)_auto] content-center items-center gap-x-2 focus-visible:-outline-offset-2",
                  n === items.length - 1 && "border-b-0",
                )}
              >
                <span aria-hidden className="num row-span-2 text-sm text-ink-2">
                  {n + 1}
                </span>
                <span className="truncate text-lg leading-6 font-medium">{m.name}</span>
                <span className="num text-right text-lg leading-6">{kind === "volume" ? formatVolume(m.volume, m.market) : formatPrice(m.close, m.market, "stock")}</span>
                <span className="num col-start-2 text-sm leading-5 text-ink-2">{m.code}</span>
                <span className="text-right text-base leading-5">
                  <Pct value={m.change_pct} />
                </span>
              </Link>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}
