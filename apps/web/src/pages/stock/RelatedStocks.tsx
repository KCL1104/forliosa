import { Link } from "@tanstack/react-router"
import { useRelated } from "@/api/queries"
import type { InstrumentDetail, RelatedCard } from "@/api/types"
import { Pct, Price } from "@/components/finance"
import { Section } from "@/components/section"
import { Sparkline } from "@/components/sparkline"
import { Skeleton } from "@/components/ui/skeleton"
import { direction, formatPriceLevel } from "@/lib/format"
import { Sources } from "./tabs/kit"

/**
 * 相關股票（像 Google 財經的「相關股票」列）：最多 4 格，依規則從政府開放資料挑選——
 * 比較基準／富櫃五十成分股、關係企業（法人董事、大股東）、同業（產業別＋市值）；ETF 頁是同指數、同類型的 ETF。
 * 沒有卡片外框：格線分隔，桌機一列 4 格、手機橫向捲動。不到 2 格就不顯示這一列。
 */
export function RelatedStocks({ inst }: { inst: InstrumentDetail }) {
  const related = useRelated(inst.symbol)
  if (related.isLoading) return <Skeleton className="h-40 w-full rounded-sm" />
  const items = related.data?.items ?? []
  if (items.length < 2) return null
  return (
    <Section title="相關股票" titleId="ov-related">
      <ul
        aria-label={`${inst.name}的相關股票`}
        className="-mt-3 flex snap-x snap-mandatory overflow-x-auto overscroll-x-contain sm:grid sm:grid-cols-4 sm:overflow-visible"
      >
        {items.map((c) => (
          // relative：格子裡 sr-only（絕對定位）的文字要留在捲動容器裡，不然手機頁面會被撐寬
          <li key={c.symbol} className="relative w-[44%] min-w-40 shrink-0 snap-start border-r border-rule last:border-r-0 first:*:pl-0 sm:w-auto sm:min-w-0">
            <RelatedCell card={c} />
          </li>
        ))}
      </ul>
      {(related.data?.notes ?? []).map((n) => (
        <p key={n} className="mt-3 text-xs text-ink-2">
          {n}
        </p>
      ))}
      <Sources items={related.data?.sources ?? []} className="mt-1" />
    </Section>
  )
}

function RelatedCell({ card }: { card: RelatedCard }) {
  const values = card.sparkline.map((p) => p.price).filter((v): v is number => v !== null)
  const d = direction(card.change_pct)
  const tone = d === "up" ? "up" : d === "down" ? "down" : "flat"
  const code = card.is_index ? "指數" : card.symbol.split(".")[0]
  const body = (
    <>
      <p className="num text-sm text-ink-2">{code}</p>
      <p className="truncate text-base font-medium" title={card.name}>
        {card.name}
      </p>
      <p className="mt-1 flex flex-wrap items-baseline gap-x-2">
        <span className="num text-base">
          {card.is_index ? (card.close === null ? "—" : formatPriceLevel(card.close)) : <Price value={card.close} market={card.symbol.endsWith(".TWO") ? "TPEX" : "TWSE"} />}
        </span>
        <Pct value={card.change_pct} className="text-md" />
      </p>
      <Sparkline values={values} tone={tone} width={132} height={28} label={`${card.name}近一個月走勢`} className="mt-2 w-full max-w-[132px]" />
      <p className="mt-2 line-clamp-2 text-sm text-ink-2">{card.reason_label}</p>
    </>
  )
  const cls = "block h-full px-3 py-3"
  if (card.is_index) return <div className={cls}>{body}</div>
  return (
    <Link
      to="/stock/$symbol"
      params={{ symbol: card.symbol }}
      className={`${cls} outline-none hover:bg-hov focus-visible:bg-hov focus-visible:ring-2 focus-visible:ring-ink/30`}
    >
      {body}
    </Link>
  )
}
