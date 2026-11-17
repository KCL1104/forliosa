import { PlainLink } from "@/app/links"
import { ChevronDownIcon } from "lucide-react"
import { useId, useState } from "react"
import { SourcesContext, useSources } from "@/hooks/use-source-note"
import { DISCLAIMER_PATH, DISCLAIMER_TITLE } from "@/lib/disclaimer"
import { createSourcesStore, groupByLicence, sourceKey } from "@/lib/sources"
import { cn } from "@/lib/utils"
import { Disclaimer, disclaimerLink } from "./disclaimer"

/**
 * 頁尾「資料來源與授權」：一頁一個 `<SourcesProvider>` 包住整頁，最下面放一個 `<SourcesFooter />`；
 * 各區塊用 `useSourceNote(...)`（`@/hooks/use-source-note`）登記自己用到的來源，不再各自寫一段授權文字。
 */
export function SourcesProvider({ children }: { children: React.ReactNode }) {
  const [store] = useState(createSourcesStore)
  return <SourcesContext.Provider value={store}>{children}</SourcesContext.Provider>
}

/**
 * 每一頁最下面的頁尾（一頁只出現一次）：一條格線 →
 * 1. 免責的一句（`lib/disclaimer.ts` 的 `short`；13px 淡墨）——Forliosa 只替你整理資訊，不是投資顧問、不提供投資建議；
 * 2. 一列 13px 淡墨的連結：`children`（條款頁放另外兩份文件）、「免責聲明」（`/disclaimer`）、「資料來源與授權」。
 * 「資料來源與授權」：這一頁有登記來源時是揭示按鈕，展開是去重後、依授權分組的格線清單，最後連到完整顯名聲明（/data-sources）；
 * 沒有登記任何來源（或不在 SourcesProvider 裡）時，只是一個連到聲明頁的小連結。
 * `omit`：在那一頁本身時不放連到自己的連結（`/disclaimer` 不放免責的一句與「免責聲明」，`/data-sources` 不放「資料來源與授權」）。
 * 不用路由的 hook：個股頁的測試不掛路由。
 */
export function SourcesFooter({ className, omit, children }: { className?: string; omit?: "disclaimer" | "sources"; children?: React.ReactNode }) {
  const notes = useSources()
  const [open, setOpen] = useState(false)
  const panelId = useId()
  const sources = omit === "sources" ? null : notes.length === 0 ? (
    <PlainLink to="/data-sources" className={disclaimerLink}>
      資料來源與授權
    </PlainLink>
  ) : (
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
  )

  return (
    <footer data-site-footer="" className={cn("mt-12 border-t border-rule", className)}>
      {omit !== "disclaimer" && <Disclaimer className="pt-3" />}
      <div className="flex flex-wrap items-center gap-x-5">
        {children}
        {omit !== "disclaimer" && (
          <PlainLink to={DISCLAIMER_PATH} className={disclaimerLink}>
            {DISCLAIMER_TITLE}
          </PlainLink>
        )}
        {sources}
      </div>
      {notes.length > 0 && omit !== "sources" && (
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
            <PlainLink to="/data-sources" className="text-ink underline underline-offset-3 hover:decoration-2">
              完整顯名聲明
            </PlainLink>
          </p>
        </div>
      )}
    </footer>
  )
}
