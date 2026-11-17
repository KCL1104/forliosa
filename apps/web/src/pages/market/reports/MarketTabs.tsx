import { useNavigate } from "@tanstack/react-router"
import type { ReportKind } from "@/api/types"

const TABS = [
  { value: "quotes", label: "行情" },
  { value: "reports", label: "報告" },
] as const
export type MarketTab = (typeof TABS)[number]["value"]

/**
 * 市場頁的分頁「行情｜報告」（選取語法 (a)：墨色 700＋2px 墨色底線，和群組、個股的分頁列同一種；sticky 在頂部列下面）。
 * 只在有報告可看的時候出現（`status.available`）；沒有時市場頁和以前一樣，沒有分頁列。
 * 一份報告的頁面（`/market/reports/<id>`）也畫這一列、選在「報告」：按「報告」回到那一種的最新一份。
 */
export function MarketTabs({ tab, kind, detail = false }: { tab: MarketTab; kind?: ReportKind; detail?: boolean }) {
  const navigate = useNavigate()
  const go = (t: MarketTab, focus = false) => {
    void navigate({ to: "/market", search: t === "reports" ? { tab: "reports", kind } : {}, resetScroll: false })
    if (focus) requestAnimationFrame(() => document.getElementById(`market-tab-${t}`)?.focus())
  }
  return (
    <div className="sticky top-(--sticky-top) z-20 -mx-5 mb-6 border-b border-rule bg-paper px-5 md:-mx-8 md:px-8 lg:mx-0 lg:px-0">
      <div role="tablist" aria-label="市場內容" className="flex gap-1">
        {TABS.map((t, i) => {
          const active = t.value === tab
          return (
            <button
              key={t.value}
              type="button"
              role="tab"
              id={`market-tab-${t.value}`}
              aria-selected={active}
              aria-controls="market-tabpanel"
              tabIndex={active ? 0 : -1}
              onKeyDown={(e) => {
                const d = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0
                if (!d) return
                e.preventDefault()
                go(TABS[(i + d + TABS.length) % TABS.length]!.value, true)
              }}
              onClick={() => (!active || detail) && go(t.value)}
              className="sel-tab -mb-px flex h-12 min-w-11 items-center justify-center px-3 text-base text-ink-2"
            >
              {t.label}
            </button>
          )
        })}
      </div>
    </div>
  )
}
