import { Link } from "@tanstack/react-router"
import { useState } from "react"
import type { MarketMover, MarketMovers } from "@/api/types"
import { Pct } from "@/components/finance"
import { Section } from "@/components/section"
import { RangeChips } from "@/components/segmented"
import { formatDateShort, formatNumber, formatPrice, formatVolume } from "@/lib/format"
import { cn } from "@/lib/utils"

type Kind = "gainers" | "losers" | "volume"
const KINDS: { value: Kind; label: string }[] = [
  { value: "gainers", label: "漲幅" },
  { value: "losers", label: "跌幅" },
  { value: "volume", label: "成交量" },
]

/**
 * 排行：上市與上櫃的普通股（不含 ETF），漲幅、跌幅、成交量各前 10。每一列連到個股頁。
 * 寬的時候三張表並排（各自有印好的表頭）；窄的時候上面一排選項，一次看一張。
 */
export function Movers({ movers }: { movers: MarketMovers }) {
  const [kind, setKind] = useState<Kind>("gainers")
  return (
    <Section
      title="排行"
      titleId="market-movers"
      aside={
        <span className="num">
          {formatDateShort(movers.date, false)}・{formatNumber(movers.count)} 檔普通股，不含 ETF
        </span>
      }
      bodyClassName="pt-2 @4xl:pt-3"
    >
      <RangeChips label="排行的種類" value={kind} options={KINDS} onChange={setKind} className="mb-1 @4xl:hidden" />
      <div className="@4xl:grid @4xl:grid-cols-3 @4xl:gap-x-10">
        {KINDS.map((k) => (
          <MoverList key={k.value} kind={k.value} label={k.label} items={movers[k.value]} hiddenWhenNarrow={k.value !== kind} />
        ))}
      </div>
    </Section>
  )
}

function MoverList({ kind, label, items, hiddenWhenNarrow }: { kind: Kind; label: string; items: MarketMover[]; hiddenWhenNarrow: boolean }) {
  const headId = `market-movers-${kind}`
  return (
    <div className={cn("min-w-0", hiddenWhenNarrow && "@max-4xl:hidden")}>
      <div className="form-head flex h-9 items-end justify-between pb-2">
        <span id={headId}>
          <span className="@max-4xl:sr-only">{label}前 10</span>
          <span aria-hidden className="@4xl:hidden">
            名稱
          </span>
        </span>
        <span>{kind === "volume" ? "成交量・漲跌幅" : "收盤價・漲跌幅"}</span>
      </div>
      {items.length === 0 ? (
        <p className="border-b border-rule py-3 text-base text-ink">{kind === "gainers" ? "這一天沒有上漲的股票" : kind === "losers" ? "這一天沒有下跌的股票" : "還沒有資料"}</p>
      ) : (
        <ol aria-labelledby={headId}>
          {items.map((m, n) => (
            <li key={m.symbol}>
              <Link
                to="/stock/$symbol"
                params={{ symbol: m.symbol }}
                className="ruled-row grid h-[60px] grid-cols-[1.25rem_minmax(0,1fr)_auto] content-center items-center gap-x-2 focus-visible:-outline-offset-2"
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
