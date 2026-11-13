import type { AiAction } from "./runner"
import type { AiContext } from "./suggestions"

export { DISCLAIMER } from "./answer-text"

export interface QuickAction {
  key: string
  label: string
  run: AiAction
  code?: string
}

/**
 * 依頁面出現的常用動作（一行文字連結）：只放頁面上沒有、而且這一頁真的能做的事。
 * 「記一筆」在帳本的工具列與個股頁的標題列都有（直接開輸入框），面板不再放第二條會先開一段對話的路；
 * 台股的股利在除息日自動入帳（產品負責人 2026-11-14：只需要記買進）。剩下的只有：持有美股的個股頁「股利入帳」
 * （美股股利沒有來源，要自己記）。其他頁面：沒有。
 */
export function quickActions(ctx: AiContext): QuickAction[] {
  if (ctx.route === "stock" && ctx.stock.market === "US" && ctx.stock.position) {
    return [{ key: "dividend", label: "股利入帳", run: "dividend", code: ctx.stock.code }]
  }
  return []
}

/**
 * 輸入框的提示字，依頁面：帳本給記帳的例子；個股頁用這一檔、單位照市場（台股「張」、美股「股」）；
 * 群組、設定、資料來源、紀錄不給交易的例子，只說可以問什麼。手機的輸入框也用來搜尋股票，句子短一點。
 */
export function composerPlaceholder(ctx: AiContext, variant: "panel" | "screen"): string {
  const screen = variant === "screen"
  if (ctx.route === "ledger") return screen ? "搜尋，或說：買 0050 2 張" : "問問題，或說：買 0050 2 張 52.4"
  if (ctx.route === "stock") {
    const s = ctx.stock
    const trade = s.market === "US" ? `買 ${s.code} 10 股` : `買 ${s.code} 1 張`
    if (screen) return `搜尋，或說：${trade}`
    return s.market === "US" ? `問 ${s.code} 的事，或說：${trade}` : `問${s.name}的事，或說：${trade}`
  }
  return screen ? "搜尋股票或提問" : "問你的持股、股利或任何一檔股票"
}

/** 面板裡的格線列左右延伸到面板邊緣（hover 底色滿版），文字對齊內文（面板 28px／32px、手機 20px 內距） */
export const bleed = { panel: "-mx-7 xl:-ml-8", screen: "-mx-5" } as const
export const bleedPad = { panel: "px-7 xl:pl-8", screen: "px-5" } as const
