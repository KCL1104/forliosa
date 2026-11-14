import { useNavigate } from "@tanstack/react-router"
import { Command as CommandPrimitive } from "cmdk"
import { SearchIcon, XIcon } from "lucide-react"
import { useEffect, useState } from "react"
import { useInstrumentSearch } from "@/api/queries"
import type { Instrument } from "@/api/types"
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog"
import { useIsDesktop } from "@/hooks/use-media-query"
import { useVisualViewport } from "@/hooks/use-visual-viewport"
import { MARKET_LABEL, marketTag } from "@/lib/labels"
import { cn } from "@/lib/utils"
import { usePrefs } from "@/stores/prefs"
import { useUi } from "./ui-store"
import { useReadOnly } from "@/api/view-as"


/**
 * ⌘K 全域搜尋（cmdk）：代號或中文股名搜尋商品，也能跳頁與執行常用動作。
 * 清單是文字列：動作與頁面前面不放裝飾圖示（只有輸入框的放大鏡，那是「這裡可以搜尋」）。
 * 依 emil-design-eng：每天用上百次的面板不做開關動畫。
 *
 * 手機（< 1024px，標題列的放大鏡打開）：同一個搜尋，換成滿版的一頁——輸入框在最上面（和標題列同高），
 * 結果往下排、自己捲動。高度跟著看得到的畫面（visual viewport）：螢幕鍵盤打開時，清單的最後一列停在鍵盤上面，
 * 不會被蓋住。右上角是關閉鈕。
 */
export function CommandSearch() {
  const open = useUi((s) => s.searchOpen)
  const setOpen = useUi((s) => s.setSearchOpen)
  const openTradeForm = useUi((s) => s.openTradeForm)
  // 查看別人的資產時是唯讀：不提供記帳
  const readOnly = useReadOnly()
  const togglePrivacy = usePrefs((s) => s.togglePrivacy)
  const navigate = useNavigate()
  const [q, setQ] = useState("")
  const [active, setActive] = useState("")
  const search = useInstrumentSearch(q)
  const sheet = !useIsDesktop()
  const viewport = useVisualViewport()

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
  // 結果是非同步回來的：目前選取的項目不在清單裡時改選第一項，Enter 才一定有作用。
  // 和下面渲染的條件一致（查看模式沒有「記一筆交易」），否則會選到不存在的項目
  const values = [
    ...results.map((i) => i.symbol),
    ...(q.trim() ? [] : [...(readOnly ? [] : ["new-trade"]), "privacy"]),
    ...pages.map((p) => `page:${p.to}`),
  ]
  const selected = values.includes(active) ? active : (values[0] ?? "")

  return (
    <Dialog open={open} onOpenChange={(o) => (o ? setOpen(true) : close())}>
      <DialogContent
        showCloseButton={false}
        className={cn(
          "gap-0 overflow-hidden p-0 duration-0 data-closed:animate-none data-open:animate-none",
          sheet
            ? "top-0 left-0 flex h-dvh max-w-none translate-x-0 translate-y-0 flex-col rounded-none bg-paper ring-0 sm:max-w-none"
            : "top-[12vh] max-w-[calc(100%-2rem)] translate-y-0 sm:max-w-xl",
        )}
        style={sheet && viewport ? { height: viewport.height, top: viewport.top } : undefined}
      >
        <DialogTitle className="sr-only">搜尋股票與功能</DialogTitle>
        <DialogDescription className="sr-only">輸入股票代號或中文名稱，例如 2330 或 台積</DialogDescription>
        <CommandPrimitive shouldFilter={false} loop value={selected} onValueChange={setActive} className={cn("flex flex-col", sheet && "min-h-0 flex-1")} label="搜尋股票與功能">
          <div className={cn("flex shrink-0 items-center border-b", sheet ? "gap-1 pt-[env(safe-area-inset-top,0px)] pr-3 pl-5" : "gap-2.5 px-4")}>
            <SearchIcon className={cn("shrink-0 text-muted-foreground", sheet ? "size-5" : "size-4.5")} aria-hidden />
            <CommandPrimitive.Input
              value={q}
              onValueChange={setQ}
              placeholder={sheet ? "代號或名稱，例如 2330、台積" : "輸入代號或名稱，例如 2330、台積、0050"}
              className={cn("w-full min-w-0 bg-transparent outline-none placeholder:text-muted-foreground", sheet ? "h-[60px] pl-2 text-lg" : "h-13 text-base")}
              enterKeyHint="search"
              autoComplete="off"
              autoCorrect="off"
              spellCheck={false}
            />
            {search.isFetching && <span className="shrink-0 text-sm text-muted-foreground">搜尋中…</span>}
            {sheet && (
              <DialogClose aria-label="關閉搜尋" className="press sel-chip grid size-11 shrink-0 place-items-center rounded-sm text-ink-2">
                <XIcon aria-hidden className="size-[22px]" />
              </DialogClose>
            )}
          </div>
          <CommandPrimitive.List className={cn("scroll-py-2 overflow-y-auto overscroll-contain", sheet ? "min-h-0 flex-1 pb-[max(0.5rem,env(safe-area-inset-bottom,0px))]" : "max-h-[min(60vh,420px)] p-2")}>
            {q.trim() && !search.isFetching && results.length === 0 && (
              <CommandPrimitive.Empty className={cn("py-8 text-md text-muted-foreground", sheet ? "px-5" : "px-3 text-center")}>
                找不到「{q.trim()}」。試試股票代號（2330）、中文簡稱（台積）或美股代號（AAPL）。
              </CommandPrimitive.Empty>
            )}
            {results.length > 0 && (
              <CommandPrimitive.Group heading="股票與 ETF" className={cn(groupClass, sheet && groupSheet)}>
                {results.map((i) => (
                  <CommandPrimitive.Item key={i.symbol} value={i.symbol} onSelect={() => goStock(i)} className={cn(itemClass, sheet && itemSheet)}>
                    <span className="num w-16 shrink-0 text-md font-semibold">{i.code}</span>
                    <span className="min-w-0 flex-1 truncate">{i.name}</span>
                    <span className="shrink-0 text-sm text-muted-foreground">
                      {i.has_quote === false ? marketTag(i) : `${MARKET_LABEL[i.market]}${i.type === "etf" ? "・ETF" : i.industry ? `・${i.industry}` : ""}`}
                    </span>
                  </CommandPrimitive.Item>
                ))}
              </CommandPrimitive.Group>
            )}
            {!q.trim() && (
              <CommandPrimitive.Group heading="常用動作" className={cn(groupClass, sheet && groupSheet)}>
                {!readOnly && (
                  <CommandPrimitive.Item value="new-trade" onSelect={() => { close(); openTradeForm() }} className={cn(itemClass, sheet && itemSheet)}>
                    <span className="flex-1">記一筆交易</span>
                  </CommandPrimitive.Item>
                )}
                <CommandPrimitive.Item value="privacy" onSelect={() => { togglePrivacy(); close() }} className={cn(itemClass, sheet && itemSheet)}>
                  <span className="flex-1">切換隱私模式</span>
                </CommandPrimitive.Item>
              </CommandPrimitive.Group>
            )}
            {pages.length > 0 && (
              <CommandPrimitive.Group heading="前往頁面" className={cn(groupClass, sheet && groupSheet)}>
                {pages.map((p) => (
                  <CommandPrimitive.Item key={p.to} value={`page:${p.to}`} onSelect={() => go(p.to)} className={cn(itemClass, sheet && itemSheet)}>
                    <span className="flex-1">{p.label}</span>
                  </CommandPrimitive.Item>
                ))}
              </CommandPrimitive.Group>
            )}
          </CommandPrimitive.List>
        </CommandPrimitive>
      </DialogContent>
    </Dialog>
  )
}

const PAGES = [
  { to: "/", label: "帳本" },
  { to: "/market", label: "市場" },
  { to: "/groups", label: "群組" },
  { to: "/discussions", label: "討論" },
  { to: "/history", label: "對話紀錄" },
  { to: "/settings", label: "設定" },
] as const

const groupClass = cn(
  "[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:pt-2 [&_[cmdk-group-heading]]:pb-1 [&_[cmdk-group-heading]]:text-sm [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:text-muted-foreground",
)
const itemClass =
  "flex min-h-11 cursor-pointer items-center gap-3 rounded-sm px-2.5 text-base outline-none data-[selected=true]:bg-hov data-[selected=true]:text-ink"
/**
 * 手機：一行一格的格線列（和「問 AI」裡的搜尋結果同一套）——48px 高、17px、左右延伸到畫面邊緣、列與列之間 1px 格線；
 * 選取中的那一列（鍵盤的 Enter 會去的那一筆）是滿版的淡墨底，沒有圓角
 */
const itemSheet = "min-h-12 rounded-none border-b border-rule px-5 text-lg"
const groupSheet = "[&_[cmdk-group-heading]]:border-b [&_[cmdk-group-heading]]:border-rule [&_[cmdk-group-heading]]:px-5 [&_[cmdk-group-heading]]:pt-4 [&_[cmdk-group-heading]]:pb-2 [&_[cmdk-group-heading]]:font-normal"

function isTyping(target: EventTarget | null) {
  const el = target as HTMLElement | null
  return !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable)
}
