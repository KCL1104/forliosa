import { useState } from "react"
import { appToday } from "@/api"
import { useEvents, useNews } from "@/api/queries"
import { useWho } from "@/api/view-as"
import type { InstrumentDetail, Position, PositionMarker } from "@/api/types"
import { Section } from "@/components/section"
import { RangeChips } from "@/components/segmented"
import { ErrorState } from "@/components/states"
import { Skeleton } from "@/components/ui/skeleton"
import { announcementHost, eventLabel, eventTitle, mergeAnnouncements, NEWS_CATEGORY_LABEL, type TimelineRow } from "@/lib/events"
import { formatDaysUntil, formatMoney, formatPrice, formatQuantity } from "@/lib/format"
import { officialNews } from "@/lib/news"
import { cn } from "@/lib/utils"
import { usePrefs } from "@/stores/prefs"
import { useSourceNote } from "@/hooks/use-source-note"
import { sourceNotes, withoutKind } from "../text"
import { DateCell } from "./kit"

/**
 * 事件：過去與接下來的時間軸。官方公告（重大訊息、證交所公告）也在這條軸上，標「公告」並連到原文；
 * 法定期限的備援日期標「預估」。「只看我的」包含我的交易（含已出清的）與我可領的股利
 * （查看別人的資產時寫「只看爸爸的」「爸爸可領約」，不讓查看者誤以為是自己的）。
 * 美股：SEC 的 10-K 年報、10-Q 季報、8-K 重大事件，連到 sec.gov 原文。
 */
export function EventsTab({ inst, position, markers }: { inst: InstrumentDetail; position: Position | null; markers?: PositionMarker[] }) {
  const me = useWho("我")
  const you = useWho("你")
  const events = useEvents(inst.symbol)
  const news = useNews(inst.symbol)
  const privacy = usePrefs((s) => s.privacyMode)
  const unitPref = usePrefs((s) => s.quantityUnit)
  const [filter, setFilter] = useState<"all" | "mine">("all")
  const today = appToday()
  useSourceNote(sourceNotes([...new Set([...(events.data ?? []), ...officialNews(news.data)].flatMap((e) => e.sources ?? []))]))
  if (events.isError) return <ErrorState error={events.error} onRetry={() => void events.refetch()} />
  if (!events.data) return <Skeleton className="h-80 w-full rounded-sm" />
  // 我的交易：交易歷史的買賣點（出清後也有；隱私模式不顯示股數）
  const trades: TimelineRow[] = (markers ?? position?.markers ?? [])
    .filter((m) => m.type === "buy" || m.type === "sell")
    .map((m) => ({
      date: m.date,
      type: "trade" as const,
      title: `${m.type === "buy" ? "買進" : "賣出"}${privacy || m.quantity === null ? "" : ` ${formatQuantity(m.quantity, unitPref, inst.market)}`}，成交價 ${formatPrice(m.price, inst.market)}`,
      detail: null,
      url: null,
      mine: true,
      amount_estimate: null,
    }))
  // 時間軸只放官方公告；媒體新聞在總覽的「新聞報導」
  const all: TimelineRow[] = [...mergeAnnouncements(events.data, officialNews(news.data)), ...trades].filter((e) => filter === "all" || e.mine)
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
          { value: "mine", label: `只看${me}的` },
        ]}
      />
      <Section title="接下來" titleId="ev-next">
        <Timeline rows={future} today={today} privacy={privacy} who={you} empty="目前沒有已公告的事件。" future />
      </Section>
      <Section title="過去" titleId="ev-past">
        <Timeline rows={past} today={today} privacy={privacy} who={you} empty={filter === "mine" ? `沒有${you}的交易或股利紀錄。` : "沒有過去的事件。"} />
      </Section>
    </div>
  )
}

/** `who`：可領股利的主人（「你」，查看模式是授權者的名稱） */
function Timeline({ rows, today, privacy, who, empty, future }: { rows: TimelineRow[]; today: string; privacy: boolean; who: string; empty: string; future?: boolean }) {
  if (rows.length === 0) return <p className="text-md text-ink-2">{empty}</p>
  return (
    <ol className="-mt-3">
      {rows.map((e, i) => {
        // 標題不重複類別欄（「除息｜每股 5 元」）；標題就是類別時改寫說明，下面就不再重複說明
        const { title, kind } = withoutKind(eventTitle(e), eventLabel(e), e.detail)
        const announcement = e.type === "announcement" || e.type === "material_info"
        const amount = e.amount_estimate !== null && e.mine ? `${who}可領約 ${privacy ? "••••" : formatMoney(e.amount_estimate)}` : null
        return (
          <li key={`${e.date}-${e.type}-${e.title}-${i}`} className="grid grid-cols-[5.75rem_minmax(0,1fr)] items-baseline border-b border-rule sm:grid-cols-[7rem_6.5rem_minmax(0,1fr)_auto]">
            <DateCell date={e.date} className="row-span-3 self-stretch py-3 sm:row-span-1" />
            <span className={cn("pt-3 pl-3 text-md sm:pb-3", e.mine ? "font-medium text-ink" : "text-ink-2")}>{kind}</span>
            <span className="min-w-0 pl-3 max-sm:col-start-2 sm:py-3 sm:pl-0">
              {e.url ? (
                // 有原文的列：常駐的淡底線，和沒有連結的列分得出來
                <a href={e.url} target="_blank" rel="noreferrer" className="underline decoration-rule underline-offset-3 hover:decoration-ink">
                  {title}
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
              {((e.detail && e.detail !== title) || (announcement && e.category)) && (
                <span className="block text-sm text-ink-2">
                  {announcement && e.category ? `${NEWS_CATEGORY_LABEL[e.category]}${e.url ? `・${announcementHost(e.url)}` : ""}` : e.detail}
                </span>
              )}
            </span>
            <span className={cn("num pb-3 pl-3 whitespace-nowrap max-sm:col-start-2 sm:py-3 sm:text-right", amount ? "text-md text-ink" : "text-sm text-ink-2")}>
              {amount ?? (future ? formatDaysUntil(e.date, today) : null)}
            </span>
          </li>
        )
      })}
    </ol>
  )
}
