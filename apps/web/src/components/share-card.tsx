import { toast } from "sonner"
import { DataNotes } from "@/components/data-notes"
import { Button } from "@/components/ui/button"
import { direction, formatDateShort, toneClass } from "@/lib/format"
import { cn } from "@/lib/utils"
import { glyphPct, type ShareCardData } from "./use-share-card"

/**
 * 分享卡（群組頁與帳本同一張；資料在 `use-share-card.tsx`）：一張印好的聯絡簿紙條（2026-11-20）——印刷線外框、
 * 字標＋日期格、表頭的印刷雙線、明體印刷藍的欄位名稱、大的百分比，下緣一行網址。這是唯一會離開 app 的東西
 * （截圖貼到 LINE）：遮住字標也認得出來，靠印好的表格，不靠顏色。只有百分比，沒有金額。
 * 下面接本月算不出來的原因、Yahoo 參考價那一句（只在需要時）。
 */
export function ShareSlip({ data, className }: { data: ShareCardData; className?: string }) {
  const { cells, noMonth, today, monthNote, referenceNote } = data
  return (
    <div className={cn("max-w-lg", className)}>
      {/* 字級與內距跟著卡片自己的寬度（`@container`）：群組頁 512px、帳本的托盤裡 1440px 時約 470px、iPhone 15 是 321px、
          320px 的手機只有 248px——三格百分比（「▲50.2%」）在任何寬度都不互相蓋到 */}
      <figure className="@container border border-print bg-raised">
        {/* 表頭和下面的格子同一組欄：日期格的直線就是最後一格的分隔線（不會差幾 px） */}
        <div className={cn("form-head grid text-base", noMonth ? "grid-cols-2" : "grid-cols-3")}>
          <span className={cn("self-center py-3 pl-2.5 font-sans text-xl font-bold tracking-[-0.01em] text-ink @min-[22rem]:pl-3 @min-[28rem]:pl-4", !noMonth && "col-span-2")}>Forliosa</span>
          <span className="date-cell num flex items-baseline gap-0 border-e-0 border-l border-rule px-2 py-3 font-sans text-sm @min-[22rem]:px-3 @min-[22rem]:text-base @min-[28rem]:px-4">
            {formatDateShort(today, false)}
            <span className="weekday [font-feature-settings:'halt'_1]">{formatDateShort(today).slice(formatDateShort(today, false).length)}</span>
          </span>
        </div>
        <dl className={cn("grid", noMonth ? "grid-cols-2" : "grid-cols-3")}>
          {cells.map((c, i) => (
            <div key={c.key} className={cn("min-w-0 px-2 pt-4 pb-5 @min-[22rem]:px-3 @min-[28rem]:px-4", i > 0 && "border-l border-rule")}>
              <dt className="print-label text-sm">{c.label}</dt>
              <dd
                className={cn(
                  "num mt-1.5 text-base leading-none font-medium whitespace-nowrap @min-[18rem]:text-xl @min-[22rem]:text-2xl @min-[28rem]:text-3xl",
                  toneClass(direction(c.value)),
                )}
              >
                {c.value === undefined || c.value === null ? "—" : glyphPct(c.value)}
              </dd>
            </div>
          ))}
        </dl>
        <figcaption className="border-t border-rule px-2.5 py-2 text-right text-xs text-ink-2 @min-[22rem]:px-3 @min-[28rem]:px-4">forliosa.trade</figcaption>
      </figure>
      {/* 後端的說明自己就有冒號（「MSFT：還沒有收盤價，…」），前面用一句話接，不再疊一個冒號 */}
      {monthNote && <p className="mt-2 text-base text-ink">{monthNote}</p>}
      {referenceNote && <DataNotes className="mt-2" notes={[referenceNote]} />}
    </div>
  )
}

/** 「複製分享文字」：把「我今天 ▲2.10%，本月 …，總報酬 …（Forliosa 11/12）」放進剪貼簿 */
export function ShareCopyButton({ data, className, size }: { data: ShareCardData; className?: string; size?: "sm" }) {
  return (
    <Button
      variant="outline"
      size={size}
      className={className}
      disabled={!data.ready}
      onClick={() => {
        void navigator.clipboard?.writeText(data.line).then(
          () => toast.success("已複製，可以貼到 LINE"),
          () => toast.error("沒有複製成功", { description: data.line }),
        )
      }}
    >
      複製分享文字
    </Button>
  )
}
