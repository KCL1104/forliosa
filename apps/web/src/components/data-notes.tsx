import { cn } from "@/lib/utils"

/**
 * 資料說明（後端的 `notes`，例如「資料累積中：自 2026-11-11 起存檔」）：放在圖表旁，一行淡墨小字。
 * 照後端的原文顯示，不改寫；沒有就不出現。
 */
export function DataNotes({ notes, className }: { notes?: string[] | null; className?: string }) {
  const list = [...new Set((notes ?? []).filter(Boolean))]
  if (list.length === 0) return null
  return (
    <ul className={cn("flex flex-col gap-0.5 text-sm text-ink-2", className)}>
      {list.map((n) => (
        <li key={n}>{n}</li>
      ))}
    </ul>
  )
}

/**
 * 頁尾的「資料來源與授權」搬到 `@/components/sources`（SourcesProvider＋useSourceNote＋SourcesFooter）。
 * 這裡保留同名匯出，舊的匯入不用改；新程式請從 `@/components/sources` 匯入。
 */
export { SourcesFooter } from "./sources"
