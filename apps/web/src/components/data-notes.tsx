import { Link } from "@tanstack/react-router"
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

/** 頁尾的小連結：資料來源與授權（政府資料開放授權條款要求顯名） */
export function SourcesFooter({ className }: { className?: string }) {
  return (
    <p className={cn("mt-12 border-t border-rule pt-3 text-xs text-ink-2", className)}>
      行情與公司資料來自政府開放資料。
      <Link to="/data-sources" className="ml-1 text-ink underline underline-offset-3 hover:decoration-2">
        資料來源與授權
      </Link>
    </p>
  )
}
