import { useNavigate } from "@tanstack/react-router"
import { Command as CommandPrimitive } from "cmdk"
import { CornerDownLeftIcon, EyeOffIcon, HistoryIcon, NotebookTextIcon, PlusIcon, SearchIcon, SettingsIcon, UsersIcon } from "lucide-react"
import { useEffect, useState } from "react"
import { useInstrumentSearch } from "@/api/queries"
import type { Instrument } from "@/api/types"
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog"
import { MARKET_LABEL } from "@/lib/labels"
import { cn } from "@/lib/utils"
import { usePrefs } from "@/stores/prefs"
import { useUi } from "./ui-store"


/**
 * ⌘K 全域搜尋（cmdk）：代號或中文股名搜尋商品，也能跳頁與執行常用動作。
 * 依 emil-design-eng：每天用上百次的面板不做開關動畫。
 */
export function CommandSearch() {
  const open = useUi((s) => s.searchOpen)
  const setOpen = useUi((s) => s.setSearchOpen)
  const openTradeForm = useUi((s) => s.openTradeForm)
  const togglePrivacy = usePrefs((s) => s.togglePrivacy)
  const navigate = useNavigate()
  const [q, setQ] = useState("")
  const [active, setActive] = useState("")
  const search = useInstrumentSearch(q)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.key === "k" || e.key === "K") && (e.metaKey || e.ctrlKey)) {
        e.preventDefault()
        setOpen(!useUi.getState().searchOpen)
      } else if (e.key === "/" && !isTyping(e.target)) {
        e.preventDefault()
        setOpen(true)
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [setOpen])

  const close = () => {
    setOpen(false)
    setQ("")
  }
  const go = (to: string) => {
    close()
    void navigate({ to })
  }
  const goStock = (i: Instrument) => {
    close()
    void navigate({ to: "/stock/$symbol", params: { symbol: i.symbol } })
  }

  const results = search.data ?? []
  const pages = PAGES.filter((p) => !q || p.label.includes(q.trim()))
  // 結果是非同步回來的：目前選取的項目不在清單裡時改選第一項，Enter 才一定有作用
  const values = [
    ...results.map((i) => i.symbol),
    ...(q.trim() ? [] : ["new-trade", "privacy"]),
    ...pages.map((p) => `page:${p.to}`),
  ]
  const selected = values.includes(active) ? active : (values[0] ?? "")

  return (
    <Dialog open={open} onOpenChange={(o) => (o ? setOpen(true) : close())}>
      <DialogContent
        showCloseButton={false}
        className="top-[12vh] max-w-[calc(100%-2rem)] translate-y-0 gap-0 overflow-hidden p-0 duration-0 data-closed:animate-none data-open:animate-none sm:max-w-xl"
      >
        <DialogTitle className="sr-only">搜尋股票與功能</DialogTitle>
        <DialogDescription className="sr-only">輸入股票代號或中文名稱，例如 2330 或 台積</DialogDescription>
        <CommandPrimitive shouldFilter={false} loop value={selected} onValueChange={setActive} className="flex flex-col" label="搜尋股票與功能">
          <div className="flex items-center gap-2.5 border-b px-4">
            <SearchIcon className="size-4.5 shrink-0 text-muted-foreground" aria-hidden />
            <CommandPrimitive.Input
              value={q}
              onValueChange={setQ}
              placeholder="輸入代號或名稱，例如 2330、台積、0050"
              className="h-13 w-full bg-transparent text-base outline-none placeholder:text-muted-foreground"
              enterKeyHint="search"
              autoComplete="off"
              autoCorrect="off"
              spellCheck={false}
            />
            {search.isFetching && <span className="text-xs text-muted-foreground">搜尋中…</span>}
          </div>
          <CommandPrimitive.List className="max-h-[min(60vh,420px)] scroll-py-2 overflow-y-auto overscroll-contain p-2">
            {q.trim() && !search.isFetching && results.length === 0 && (
              <CommandPrimitive.Empty className="px-3 py-8 text-center text-md text-muted-foreground">
                找不到「{q.trim()}」。試試股票代號（2330）、中文簡稱（台積）或美股代號（AAPL）。
              </CommandPrimitive.Empty>
            )}
            {results.length > 0 && (
              <CommandPrimitive.Group heading="股票與 ETF" className={groupClass}>
                {results.map((i) => (
                  <CommandPrimitive.Item key={i.symbol} value={i.symbol} onSelect={() => goStock(i)} className={itemClass}>
                    <span className="num w-16 shrink-0 text-md font-semibold">{i.code}</span>
                    <span className="min-w-0 flex-1 truncate">{i.name}</span>
                    <span className="shrink-0 text-xs text-muted-foreground">
                      {MARKET_LABEL[i.market]}
                      {i.type === "etf" ? "・ETF" : i.industry ? `・${i.industry}` : ""}
                    </span>
                  </CommandPrimitive.Item>
                ))}
              </CommandPrimitive.Group>
            )}
            {!q.trim() && (
              <CommandPrimitive.Group heading="常用動作" className={groupClass}>
                <CommandPrimitive.Item value="new-trade" onSelect={() => { close(); openTradeForm() }} className={itemClass}>
                  <PlusIcon className="size-4 text-muted-foreground" aria-hidden />
                  <span className="flex-1">記一筆交易</span>
                </CommandPrimitive.Item>
                <CommandPrimitive.Item value="privacy" onSelect={() => { togglePrivacy(); close() }} className={itemClass}>
                  <EyeOffIcon className="size-4 text-muted-foreground" aria-hidden />
                  <span className="flex-1">切換隱私模式</span>
                </CommandPrimitive.Item>
              </CommandPrimitive.Group>
            )}
            {pages.length > 0 && (
              <CommandPrimitive.Group heading="前往頁面" className={groupClass}>
                {pages.map((p) => (
                  <CommandPrimitive.Item key={p.to} value={`page:${p.to}`} onSelect={() => go(p.to)} className={itemClass}>
                    <p.icon className="size-4 text-muted-foreground" aria-hidden />
                    <span className="flex-1">{p.label}</span>
                  </CommandPrimitive.Item>
                ))}
              </CommandPrimitive.Group>
            )}
          </CommandPrimitive.List>
          <div className="hidden items-center gap-4 border-t px-4 py-2 text-xs text-muted-foreground sm:flex">
            <span className="inline-flex items-center gap-1">
              <CornerDownLeftIcon className="size-3.5" aria-hidden /> 開啟
            </span>
            <span>↑↓ 選擇</span>
            <span>Esc 關閉</span>
          </div>
        </CommandPrimitive>
      </DialogContent>
    </Dialog>
  )
}

const PAGES = [
  { to: "/", label: "帳本", icon: NotebookTextIcon },
  { to: "/groups", label: "群組", icon: UsersIcon },
  { to: "/history", label: "紀錄", icon: HistoryIcon },
  { to: "/settings", label: "設定", icon: SettingsIcon },
] as const

const groupClass = cn(
  "[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:pt-2 [&_[cmdk-group-heading]]:pb-1 [&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:text-muted-foreground",
)
const itemClass =
  "flex min-h-11 cursor-pointer items-center gap-3 rounded-sm px-2.5 text-base outline-none data-[selected=true]:bg-hov data-[selected=true]:text-ink"

function isTyping(target: EventTarget | null) {
  const el = target as HTMLElement | null
  return !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable)
}
