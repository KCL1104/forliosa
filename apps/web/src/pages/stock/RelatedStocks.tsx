import { Link } from "@tanstack/react-router"
import { useRelated } from "@/api/queries"
import type { InstrumentDetail, RelatedCard } from "@/api/types"
import { Pct, Price } from "@/components/finance"
import { ScrollRow } from "@/components/scroll-row"
import { Skeleton } from "@/components/ui/skeleton"
import { useSourceNote } from "@/hooks/use-source-note"
import { formatPriceLevel } from "@/lib/format"
import { QuietSection } from "./tabs/kit"
import { sourceNotes } from "./text"

/**
 * 相關股票（像 Google 財經的「相關股票」列）：最多 4 格，依規則從政府開放資料挑選——
 * 比較基準／富櫃五十成分股、關係企業（法人董事、大股東）、同業（產業別＋市值）；ETF 頁是同指數、同類型的 ETF。
 * 一列：格線分隔，桌機 4 格、手機橫向捲動（ScrollRow，後面還有時淡出）。數字直接寫在格子裡，不畫小走勢。
 * 不到 2 格就不顯示這一列。
 */
export function RelatedStocks({ inst }: { inst: InstrumentDetail }) {
  const related = useRelated(inst.symbol)
  useSourceNote(sourceNotes(related.data?.sources))
  if (related.isLoading) return <Skeleton className="h-28 w-full rounded-sm" />
  const items = related.data?.items ?? []
  if (items.length < 2) return null
  return (
    <QuietSection title="相關股票" titleId="ov-related">
      <ScrollRow role="list" aria-label={`${inst.name}的相關股票`} className="snap-x snap-mandatory border-b border-rule sm:grid sm:grid-cols-4">
        {items.map((c) => (
          // relative：格子裡 sr-only（絕對定位）的文字要留在捲動容器裡，不然手機頁面會被撐寬
          <div role="listitem" key={c.symbol} className="relative w-[46%] min-w-40 shrink-0 snap-start border-r border-rule last:border-r-0 first:*:pl-0 sm:w-auto sm:min-w-0">
            <RelatedCell card={c} />
          </div>
        ))}
      </ScrollRow>
      {(related.data?.notes ?? []).map((n) => (
        <p key={n} className="mt-2 text-sm text-ink-2">
          {n}
        </p>
      ))}
    </QuietSection>
  )
}

function RelatedCell({ card }: { card: RelatedCard }) {
  const code = card.is_index ? "指數" : card.symbol.split(".")[0]
  const body = (
    <>
      <p className="flex min-w-0 items-baseline gap-2">
        <span className="num shrink-0 text-sm text-ink-2">{code}</span>
        <span className="truncate font-medium" title={card.name}>
          {card.name}
        </span>
      </p>
      <p className="mt-0.5 flex flex-wrap items-baseline gap-x-2">
        <span className="num">
          {card.is_index ? (card.close === null ? "—" : formatPriceLevel(card.close)) : <Price value={card.close} market={card.symbol.endsWith(".TWO") ? "TPEX" : "TWSE"} />}
        </span>
        <Pct value={card.change_pct} className="text-md" />
      </p>
      <p className="mt-1 line-clamp-2 text-sm text-ink-2">{card.reason_label}</p>
    </>
  )
  const cls = "block h-full py-2.5 pr-3 pl-3"
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
