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
 * 依頁面出現的常用動作（一行文字連結）：只放這一頁真的能做的事。
 * 帳本：記一筆交易・匯入對帳單・股利入帳；個股頁：記一筆這一檔（有持股時加股利入帳）；
 * 群組、設定、資料來源、紀錄：沒有。
 */
export function quickActions(ctx: AiContext): QuickAction[] {
  if (ctx.route === "ledger") {
    return [
      { key: "trade", label: "記一筆交易", run: "trade" },
      { key: "import", label: "匯入對帳單", run: "import" },
      { key: "dividend", label: "股利入帳", run: "dividend" },
    ]
  }
  if (ctx.route === "stock") {
    const s = ctx.stock
    // 台股的名稱短（台積電、元大台灣50）；美股名稱長，用代號
    const short = s.market === "US" ? s.code : s.name
    const out: QuickAction[] = [{ key: "trade", label: `記一筆${s.market === "US" ? " " : ""}${short}`, run: "trade", code: s.code }]
    if (s.position) out.push({ key: "dividend", label: "股利入帳", run: "dividend", code: s.code })
    return out
  }
  return []
}
