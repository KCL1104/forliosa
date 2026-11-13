import { Link } from "@tanstack/react-router"
import { ChevronDownIcon } from "lucide-react"
import { useId, useState } from "react"
import { SourcesContext, useSources } from "@/hooks/use-source-note"
import { createSourcesStore, groupByLicence, sourceKey } from "@/lib/sources"
import { cn } from "@/lib/utils"

/**
 * 頁尾「資料來源與授權」：一頁一個 `<SourcesProvider>` 包住整頁，最下面放一個 `<SourcesFooter />`；
 * 各區塊用 `useSourceNote(...)`（`@/hooks/use-source-note`）登記自己用到的來源，不再各自寫一段授權文字。
 */
export function SourcesProvider({ children }: { children: React.ReactNode }) {
  const [store] = useState(createSourcesStore)
  return <SourcesContext.Provider value={store}>{children}</SourcesContext.Provider>
}

/**
 * 頁尾的「資料來源與授權」：一頁只出現一次。
 * 收合時是一行 13px 淡墨的揭示按鈕；展開是去重後、依授權分組的格線清單，最後連到完整顯名聲明（/data-sources）。
 * 這一頁沒有登記任何來源（或不在 SourcesProvider 裡）時，只是一個連到聲明頁的小連結。
 */
export function SourcesFooter({ className }: { className?: string }) {
  const notes = useSources()
  const [open, setOpen] = useState(false)
  const panelId = useId()

  if (notes.length === 0) {
    return (
      <p className={cn("mt-12 border-t border-rule text-sm", className)}>
        <Link to="/data-sources" className="inline-flex min-h-11 items-center text-ink-2 underline decoration-ctl underline-offset-3 hover:text-ink hover:decoration-ink">
          資料來源與授權
        </Link>
      </p>
    )
  }

  return (
    <footer className={cn("mt-12 border-t border-rule", className)}>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((v) => !v)}
        className="-ml-1 inline-flex min-h-11 items-center gap-1 rounded-sm px-1 text-sm text-ink-2 hover:text-ink"
      >
        資料來源與授權
        <ChevronDownIcon aria-hidden className={cn("size-4 transition-transform duration-200", open && "rotate-180")} />
      </button>
      <div id={panelId} hidden={!open} className="pb-2">
        {groupByLicence(notes).map(([licence, rows]) => (
          <div key={licence || "-"} className="border-t border-rule first:border-t-0">
            {licence && <p className="pt-3 pb-1 text-sm text-ink-2">{licence}</p>}
            <ul>
              {rows.map((n) => (
                <li key={sourceKey(n)} className="border-b border-rule py-2 text-md last:border-b-0">
                  {n.href ? (
                    <a href={n.href} target="_blank" rel="noreferrer" className="underline decoration-ctl underline-offset-3 hover:decoration-ink">
                      {n.name}
                      <span className="sr-only">（另開新視窗）</span>
                    </a>
                  ) : (
                    n.name
                  )}
                </li>
              ))}
            </ul>
          </div>
        ))}
        <p className="border-t border-rule pt-3 text-sm">
          <Link to="/data-sources" className="text-ink underline underline-offset-3 hover:decoration-2">
            完整顯名聲明
          </Link>
        </p>
      </div>
    </footer>
  )
}
