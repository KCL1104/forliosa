import { BellIcon, BookPlusIcon, CoinsIcon, FileDownIcon } from "lucide-react"
import { useMe } from "@/api/queries"
import type { AiAction } from "./runner"
import type { AiContext } from "./suggestions"

export const DISCLAIMER = "AI 分析僅供參考，不構成投資建議。"

/** 問候：一行，名字太長時省略 */
export function useGreeting(ctx: AiContext): { hello: string; line: string } {
  const me = useMe()
  const name = me.data?.display_name ?? ""
  const hello = name && name.length <= 3 ? `${name}，你好。` : "你好。"
  if (ctx.route === "stock") return { hello, line: `${ctx.stock.name}的事，都可以問我。` }
  return { hello, line: "今天想問什麼？" }
}

/** 依頁面出現的常用動作 */
export function useActions(ctx: AiContext): { key: string; label: string; icon: typeof BookPlusIcon; run: AiAction; code?: string }[] {
  if (ctx.route === "stock") {
    const s = ctx.stock
    return [
      { key: "trade", label: `記一筆 ${s.code}`, icon: BookPlusIcon, run: "trade", code: s.code },
      s.position
        ? { key: "dividend", label: "股利入帳", icon: CoinsIcon, run: "dividend", code: s.code }
        : { key: "alert", label: "到價提醒", icon: BellIcon, run: "alert" },
    ]
  }
  return [
    { key: "trade", label: "記一筆交易", icon: BookPlusIcon, run: "trade" },
    { key: "import", label: "匯入對帳單", icon: FileDownIcon, run: "import" },
    { key: "dividend", label: "股利入帳", icon: CoinsIcon, run: "dividend" },
  ]
}

