import { ArrowUpRightIcon } from "lucide-react"
import { useState } from "react"
import { appToday } from "@/api"
import { useEvents, useNews } from "@/api/queries"
import type { InstrumentDetail, Position, PositionMarker } from "@/api/types"
import { Section } from "@/components/section"
import { RangeChips } from "@/components/segmented"
import { ErrorState } from "@/components/states"
import { Skeleton } from "@/components/ui/skeleton"
import { announcementHost, eventLabel, eventTitle, mergeAnnouncements, NEWS_CATEGORY_LABEL, type TimelineRow } from "@/lib/events"
import { formatDateShort, formatDaysUntil, formatMoney, formatPrice, formatQuantity } from "@/lib/format"
import { officialNews } from "@/lib/news"
import { cn } from "@/lib/utils"
import { usePrefs } from "@/stores/prefs"
import { Sources } from "./kit"

/**
 * 事件：過去與接下來的時間軸。官方公告（重大訊息、證交所公告）也在這條軸上，標「公告」並連到原文；
 * 法定期限的備援日期標「預估」。「只看我的」包含我的交易（含已出清的）與我可領的股利。
 * 美股：SEC 的 10-K 年報、10-Q 季報、8-K 重大事件，連到 sec.gov 原文。
 */
export function EventsTab({ inst, position, markers }: { inst: InstrumentDetail; position: Position | null; markers?: PositionMarker[] }) {
  const events = useEvents(inst.symbol)
  const news = useNews(inst.symbol)
  const privacy = usePrefs((s) => s.privacyMode)
  const unitPref = usePrefs((s) => s.quantityUnit)
  const [filter, setFilter] = useState<"all" | "mine">("all")
  const today = appToday()
  if (events.isError) return <ErrorState error={events.error} onRetry={() => void events.refetch()} />
  if (!events.data) return <Skeleton className="h-80 w-full rounded-sm" />
  // 我的交易：交易歷史的買賣點（出清後也有；隱私模式不顯示股數）
  const trades: TimelineRow[] = (markers ?? position?.markers ?? [])
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
  // 時間軸只放官方公告；媒體新聞在總覽的「新聞報導」
  const all: TimelineRow[] = [...mergeAnnouncements(events.data, officialNews(news.data)), ...trades].filter((e) => filter === "all" || e.mine)
  const future = all.filter((e) => e.date >= today).sort((a, b) => a.date.localeCompare(b.date))
  const past = all.filter((e) => e.date < today).sort((a, b) => b.date.localeCompare(a.date)).slice(0, 40)
  const sources = [...new Set([...events.data, ...officialNews(news.data)].flatMap((e) => e.sources ?? []))]

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
        <p className="mt-3 text-xs text-ink-2">
          {inst.market === "US"
            ? "美股的申報來自 SEC EDGAR，內容以 sec.gov 原文為準；8-K「營運結果與財務狀況」通常是財報新聞稿。"
            : "財報、營收與法說會用實際公布日；還不知道時以法定期限標「預估」。公告的內容以公開資訊觀測站、證交所原文為準。"}
        </p>
        <Sources items={sources} />
      </Section>
    </div>
  )
}

function Timeline({ rows, today, privacy, empty, future }: { rows: TimelineRow[]; today: string; privacy: boolean; empty: string; future?: boolean }) {
  if (rows.length === 0) return <p className="text-md text-ink-2">{empty}</p>
  return (
    <ol className="-mt-3">
      {rows.map((e, i) => {
        const title = eventTitle(e)
        const announcement = e.type === "announcement" || e.type === "material_info"
        return (
          <li key={`${e.date}-${e.type}-${e.title}-${i}`} className="grid grid-cols-[92px_1fr] gap-x-4 border-b border-rule py-3 sm:grid-cols-[120px_96px_1fr_auto]">
            <span className="num">
              {formatDateShort(e.date)}
              {future && <span className="block text-xs text-ink-2">{formatDaysUntil(e.date, today)}</span>}
            </span>
            <span className={cn("text-md max-sm:col-start-2 max-sm:row-start-1", e.mine ? "font-medium text-ink" : "text-ink-2")}>{eventLabel(e)}</span>
            <span className="min-w-0 max-sm:col-start-2">
              {e.url ? (
                <a href={e.url} target="_blank" rel="noreferrer" className="inline-flex items-baseline gap-1 hover:underline">
                  {title}
                  <ArrowUpRightIcon aria-hidden className="size-3.5 shrink-0 self-center text-ink-2" />
                  <span className="sr-only">（在{announcementHost(e.url)}查看，另開新視窗）</span>
                </a>
              ) : (
                title
              )}
              {e.estimated && (
                <span className="demo-tag ml-2 align-[0.1em]" title="還沒看到實際公布日，先以法定期限顯示">
                  預估
                </span>
              )}
              {(e.detail || (announcement && e.category)) && (
                <span className="block text-sm text-ink-2">
                  {announcement && e.category ? `${NEWS_CATEGORY_LABEL[e.category]}${e.url ? `・${announcementHost(e.url)}` : ""}` : e.detail}
                </span>
              )}
            </span>
            <span className="num text-right text-md max-sm:col-start-2 max-sm:text-left">
              {e.amount_estimate !== null && e.mine ? <>你可領約 {privacy ? "••••" : formatMoney(e.amount_estimate)}</> : null}
            </span>
          </li>
        )
      })}
    </ol>
  )
}
