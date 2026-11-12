import { ArrowUpRightIcon } from "lucide-react"
import { useState } from "react"
import { appToday } from "@/api"
import { useEvents } from "@/api/queries"
import type { InstrumentDetail, InstrumentEvent, Position } from "@/api/types"
import { Section } from "@/components/section"
import { RangeChips } from "@/components/segmented"
import { ErrorState } from "@/components/states"
import { Skeleton } from "@/components/ui/skeleton"
import { formatDateShort, formatDaysUntil, formatMoney, formatPrice, formatQuantity } from "@/lib/format"
import { cn } from "@/lib/utils"
import { usePrefs } from "@/stores/prefs"

const LABEL: Record<string, string> = {
  ex_dividend: "除息",
  dividend_payment: "股利發放",
  earnings: "法說會",
  revenue_release: "營收公布",
  material_info: "重大訊息",
  attention: "注意股",
  disposition: "處置",
  shareholder_meeting: "股東會",
  trade: "我的交易",
}

type Row = InstrumentEvent | (Omit<InstrumentEvent, "type"> & { type: "trade" })

/** 事件：過去與接下來的時間軸；「只看我的」包含我的交易與我可領的股利 */
export function EventsTab({ inst, position }: { inst: InstrumentDetail; position: Position | null }) {
  const events = useEvents(inst.symbol)
  const privacy = usePrefs((s) => s.privacyMode)
  const unitPref = usePrefs((s) => s.quantityUnit)
  const [filter, setFilter] = useState<"all" | "mine">("all")
  const today = appToday()
  if (events.isError) return <ErrorState error={events.error} onRetry={() => void events.refetch()} />
  if (!events.data) return <Skeleton className="h-80 w-full rounded-sm" />
  // 我的交易：由部位的標記組成（隱私模式不顯示股數）
  const trades: Row[] = (position?.markers ?? [])
    .filter((m) => m.type === "buy" || m.type === "sell")
    .map((m) => ({
      date: m.date,
      type: "trade" as const,
      title: `${m.type === "buy" ? "買進" : "賣出"} ${privacy || m.quantity === null ? "" : formatQuantity(m.quantity, unitPref, inst.market)} @${formatPrice(m.price, inst.market)}`,
      detail: null,
      url: null,
      mine: true,
      amount_estimate: null,
    }))
  const all: Row[] = [...events.data, ...trades].filter((e) => filter === "all" || e.mine)
  const future = all.filter((e) => e.date >= today).sort((a, b) => a.date.localeCompare(b.date))
  const past = all.filter((e) => e.date < today).sort((a, b) => b.date.localeCompare(a.date)).slice(0, 40)

  return (
    <div className="flex flex-col gap-10">
      <RangeChips
        label="事件篩選"
        value={filter}
        onChange={setFilter}
        options={[
          { value: "all", label: "全部" },
          { value: "mine", label: "只看我的" },
        ]}
      />
      <Section title="接下來" titleId="ev-next">
        <Timeline rows={future} today={today} privacy={privacy} empty="目前沒有已公告的事件。" future />
      </Section>
      <Section title="過去" titleId="ev-past">
        <Timeline rows={past} today={today} privacy={privacy} empty={filter === "mine" ? "沒有你的交易或股利紀錄。" : "沒有過去的事件。"} />
      </Section>
    </div>
  )
}

function Timeline({ rows, today, privacy, empty, future }: { rows: Row[]; today: string; privacy: boolean; empty: string; future?: boolean }) {
  if (rows.length === 0) return <p className="text-md text-ink-2">{empty}</p>
  return (
    <ol className="-mt-3">
      {rows.map((e, i) => (
        <li key={`${e.date}-${e.type}-${e.title}-${i}`} className="grid grid-cols-[92px_1fr] gap-x-4 border-b border-rule py-3 sm:grid-cols-[120px_96px_1fr_auto]">
          <span className="num">
            {formatDateShort(e.date)}
            {future && <span className="block text-xs text-ink-2">{formatDaysUntil(e.date, today)}</span>}
          </span>
          <span className={cn("text-md max-sm:col-start-2 max-sm:row-start-1", e.mine ? "font-medium text-ink" : "text-ink-2")}>{LABEL[e.type] ?? e.type}</span>
          <span className="min-w-0 max-sm:col-start-2">
            {e.url ? (
              <a href={e.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 hover:underline">
                {e.title}
                <ArrowUpRightIcon aria-hidden className="size-3.5 text-ink-2" />
                <span className="sr-only">（另開新視窗）</span>
              </a>
            ) : (
              e.title
            )}
            {e.detail && <span className="block text-sm text-ink-2">{e.detail}</span>}
          </span>
          <span className="num text-right text-md max-sm:col-start-2 max-sm:text-left">
            {e.amount_estimate !== null && e.mine ? <>你可領約 {privacy ? "••••" : formatMoney(e.amount_estimate)}</> : null}
          </span>
        </li>
      ))}
    </ol>
  )
}
