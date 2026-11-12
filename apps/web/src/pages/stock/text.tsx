import { type SourceNote, toSourceNote } from "@/lib/sources"
import { Fig } from "./tabs/kit"

/** 個股頁的小工具（不是元件）：規則句的數字加粗、後端顯名聲明轉成頁尾的來源 */

const FIGURE = /([+−-]?\d[\d,]*(?:\.\d+)?(?:\s?(?:%|倍|張|元|億|兆|萬|天|個月|次))?)/

/** 後端給的規則句（例如「為什麼」那一行）：把數字標成 600，其他照原文 */
export function withFigures(text: string): React.ReactNode {
  const parts = text.split(FIGURE)
  if (parts.length === 1) return text
  return parts.map((p, i) => (i % 2 === 1 ? <Fig key={i}>{p}</Fig> : p))
}

/**
 * 後端的顯名聲明 → 頁尾的來源：「…依 GDELT 使用條款引用：https://…」這種把網址寫在授權後面的，
 * 拆成授權文字與連結（文字不改寫）。給 `useSourceNote`。
 */
export function sourceNotes(list: readonly string[] | null | undefined): SourceNote[] {
  return (list ?? []).filter(Boolean).map((s) => {
    const n = toSourceNote(s)
    const m = n.licence ? /^(.*?)[：:]\s*(https?:\/\/\S+)$/.exec(n.licence) : null
    return m ? { name: n.name, licence: m[1]!, href: m[2]! } : n
  })
}
