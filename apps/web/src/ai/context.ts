import { useRouterState } from "@tanstack/react-router"
import {
  useDividends,
  useHoldings,
  useInstrument,
  useOverview,
  usePosition,
  useQuote,
  useSummary,
  useValuation,
  useWhy,
} from "@/api/queries"
import { codeOf, marketOf } from "@/lib/tick"
import type { AiContext } from "./suggestions"

/** 目前路由對應的 AI 情境（只讀資料，資料由各頁共用的快取提供） */
export function useRouteKind(): { kind: "ledger" | "stock" | "groups" | "history" | "other"; symbol: string | null } {
  const pathname = useRouterState({ select: (s) => s.location.pathname })
  if (pathname === "/") return { kind: "ledger", symbol: null }
  const m = /^\/stock\/([^/]+)/.exec(pathname)
  if (m) return { kind: "stock", symbol: decodeURIComponent(m[1]!) }
  if (pathname.startsWith("/groups")) return { kind: "groups", symbol: null }
  if (pathname.startsWith("/history")) return { kind: "history", symbol: null }
  return { kind: "other", symbol: null }
}

export function useAiContext(): AiContext {
  const route = useRouteKind()
  const isLedger = route.kind === "ledger"
  const symbol = route.symbol ?? ""
  // 帳本
  const holdings = useHoldings()
  const summary = useSummary()
  // 個股：不在個股頁時不發請求（hooks 不能條件呼叫，用 enabled 控制）
  const stock = useStockBundle(symbol)

  if (isLedger) return { route: "ledger", ledger: { holdings: holdings.data ?? [], summary: summary.data } }
  if (route.kind === "stock" && symbol) {
    const inst = stock.instrument
    return {
      route: "stock",
      stock: {
        symbol: inst?.symbol ?? symbol,
        code: inst?.code ?? codeOf(symbol),
        name: inst?.name ?? codeOf(symbol),
        market: inst?.market ?? marketOf(symbol),
        type: inst?.type ?? "stock",
        quote: stock.quote,
        overview: stock.overview,
        position: stock.position,
        why: stock.why,
        valuation: stock.valuation,
        dividends: stock.dividends,
      },
    }
  }
  if (route.kind === "groups") return { route: "groups" }
  return { route: "other" }
}

/** 個股頁的資料組合；symbol 為空時不發請求 */
function useStockBundle(symbol: string) {
  const enabled = symbol.length > 0
  const instrument = useInstrument(symbol, enabled)
  const quote = useQuote(symbol, enabled)
  const overview = useOverview(symbol, enabled)
  const position = usePosition(symbol, enabled)
  const why = useWhy(symbol, enabled)
  const valuation = useValuation(symbol, enabled && instrument.data?.type === "stock")
  const dividends = useDividends(symbol, enabled)
  if (!enabled) return {}
  return {
    instrument: instrument.data,
    quote: quote.data,
    overview: overview.data,
    position: position.data,
    why: why.data,
    valuation: valuation.data,
    dividends: dividends.data,
  }
}
