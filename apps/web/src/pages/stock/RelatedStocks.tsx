import { Link } from "@tanstack/react-router"
import { useRelated } from "@/api/queries"
import type { InstrumentDetail, RelatedCard } from "@/api/types"
import { Pct } from "@/components/finance"
import { Skeleton } from "@/components/ui/skeleton"
import { useSourceNote } from "@/hooks/use-source-note"
import { formatPrice, formatPriceLevel } from "@/lib/format"
import { QuietSection } from "./tabs/kit"
import { sourceNotes } from "./text"

/**
 * 相關股票（像 Google 財經的「相關股票」列）：最多 4 檔，依規則從政府開放資料挑選——
 * 比較基準／富櫃五十成分股、關係企業（法人董事、大股東）、同業（產業別＋市值）；ETF 頁是同指數、同類型的 ETF。
 * 一盤（寬的時候在事件托盤右邊，4／12 欄）：一檔一列、格線分隔——名稱與代號｜收盤價與漲跌，下面一行挑選的理由。
 * 名稱不截斷（長的 ETF 全名換行）；數字直接寫在列裡，不畫小走勢。不到 2 檔就不顯示這一盤。
 */
export function RelatedStocks({ inst }: { inst: InstrumentDetail }) {
  const related = useRelated(inst.symbol)
  useSourceNote(sourceNotes(related.data?.sources))
  if (related.isLoading)
    return (
      <QuietSection title="相關股票" id="ov-related" className="@4xl:col-span-4">
        <Skeleton className="h-40 w-full rounded-sm" />
      </QuietSection>
    )
  const items = related.data?.items ?? []
  if (items.length < 2) return null
  return (
    <QuietSection title="相關股票" id="ov-related" className="@4xl:col-span-4">
      <ul aria-label={`${inst.name}的相關股票`} className="border-t border-rule">
        {items.map((c) => (
          <li key={c.symbol} className="border-b border-rule last:border-b-0">
            <RelatedRow card={c} />
          </li>
        ))}
      </ul>
      {(related.data?.notes ?? []).map((n) => (
        <p key={n} className="mt-2 text-sm text-ink-2">
          {n}
        </p>
      ))}
    </QuietSection>
  )
}

/** 台股 ETF（含受益憑證）的代號都是 00 開頭：決定升降單位（ETF 50 元以上是 0.05 檔） */
const typeOf = (code: string) => (code.startsWith("00") ? ("etf" as const) : ("stock" as const))

function RelatedRow({ card }: { card: RelatedCard }) {
  const code = card.is_index ? "指數" : card.symbol.split(".")[0]!
  const body = (
    <>
      <span className="min-w-0">
        <span className="font-medium [overflow-wrap:anywhere] text-ink">{card.name}</span>
        <span className="num ml-2 text-sm whitespace-nowrap text-ink-2">{code}</span>
      </span>
      <span className="flex flex-wrap items-baseline justify-end gap-x-2 text-right">
        <span className="num">
          {/* 和報價同一套小數位（214、52.40、1,085）；指數點位四捨五入 */}
          {card.is_index ? (card.close === null ? "—" : formatPriceLevel(card.close)) : formatPrice(card.close, card.symbol.endsWith(".TWO") ? "TPEX" : "TWSE", typeOf(code))}
        </span>
        <Pct value={card.change_pct} className="text-md" />
      </span>
      {card.reason_label && <span className="col-span-2 text-sm text-ink-2">{card.reason_label}</span>}
    </>
  )
  const cls = "grid min-h-11 grid-cols-[minmax(0,1fr)_auto] items-baseline gap-x-3 gap-y-0.5 py-2.5"
  if (card.is_index) return <div className={cls}>{body}</div>
  return (
    <Link
      to="/stock/$symbol"
      params={{ symbol: card.symbol }}
      className={`${cls} -mx-2 rounded-xs px-2 outline-none hover:bg-hov focus-visible:bg-hov focus-visible:ring-2 focus-visible:ring-ink/30`}
    >
      {body}
    </Link>
  )
}
