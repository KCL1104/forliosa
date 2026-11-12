import { useAttributions } from "@/api/queries"
import { useSourceNote } from "@/hooks/use-source-note"
import { formatDateShort } from "@/lib/format"
import { type SourceNote, toSourceNote } from "@/lib/sources"
import { Fig } from "./tabs/kit"

/** 個股頁的小工具（不是元件）：規則句的數字加粗、後端顯名聲明轉成頁尾的來源、估值序列的期間 */

/**
 * 帶單位的數字（倍、%、張、元、億…）：「近 20 日」這種期間參數不算；「±3%」這種門檻也不算。
 * 數字前的正負號一起加粗。
 */
const FIGURE = /((?<![±\d.,])[+−-]?\d[\d,]*(?:\.\d+)?\s?(?:億元|萬元|%|倍|張|元|億|兆|萬))/

/** 後端給的規則句（例如「為什麼」那一行）：把帶單位的數字標成 600，其他照原文 */
export function withFigures(text: string): React.ReactNode {
  const parts = text.split(FIGURE)
  if (parts.length === 1) return text
  return parts.map((p, i) => (i % 2 === 1 ? <Fig key={i}>{p}</Fig> : p))
}

/**
 * 後端的顯名聲明 → 頁尾的來源：「…依 GDELT 使用條款引用：https://…」這種把網址寫在授權後面的，
 * 拆成授權文字與連結（文字不改寫）。給 `useSourceNote`。
 */
export function sourceNotes(list: readonly (string | null | undefined)[] | null | undefined): SourceNote[] {
  return (list ?? []).filter((s): s is string => !!s).map((s) => {
    const n = toSourceNote(s)
    const m = n.licence ? /^(.*?)[：:]\s*(https?:\/\/\S+)$/.exec(n.licence) : null
    return m ? { name: n.name, licence: m[1]!, href: m[2]! } : n
  })
}

/**
 * 回應本身沒有 `sources` 的資料（月營收、股利、估值序列）：用 `/meta/attributions` 的資料集 key
 * （例如 `shioaji-data/official`、`twse-openapi/ex_dividend`）找出顯名聲明，登記到頁尾。
 * 給 null／false 的 key 不登記（例如這個區塊沒有顯示）。
 */
export function useDatasetSources(keys: readonly (string | null | false | undefined)[]) {
  const wanted = keys.filter((k): k is string => !!k)
  const attributions = useAttributions()
  const datasets = wanted.length ? attributions.data?.datasets : undefined
  useSourceNote(sourceNotes(datasets ? wanted.map((k) => datasets.find((d) => d.key === k)?.attribution) : []))
}

/** 台股的資料集 key 前綴：上市 `twse-openapi`、上櫃 `tpex-openapi`；美股沒有 */
export function twOpenApi(market: string): "twse-openapi" | "tpex-openapi" | null {
  return market === "TWSE" ? "twse-openapi" : market === "TPEX" ? "tpex-openapi" : null
}

/**
 * 估值序列實際涵蓋的期間：滿 4.5 年寫「過去 5 年」，不滿就寫實際的起點「6/1 以來」
 * （商用模式的本益比存檔從 2026-06-01 才開始累積，不能說成 5 年）。跨年時寫年份。
 */
export function valuationSpan(series: readonly { t: string }[], today: string): { label: string; full: boolean } {
  const from = series[0]?.t
  if (!from || Date.parse(today) - Date.parse(from) > 4.5 * 365 * 86_400_000) return { label: "過去 5 年", full: true }
  const day = formatDateShort(from, false)
  return { label: `${from.slice(0, 4) === today.slice(0, 4) ? day : `${from.slice(0, 4)}/${day}`} 以來`, full: false }
}

/** 中文接在期間前：「比過去 5 年」「比 6/1 以來」（數字前留空格） */
export const beforeSpan = (label: string) => (/^\d/.test(label) ? ` ${label}` : label)

/**
 * 事件列的標題不重複類別欄：「除息｜除息 每股 5 元」→「除息｜每股 5 元」、「法說會｜2026Q3 法說會」→「法說會｜2026Q3」。
 * 標題就是類別本身（「股利發放」）時改寫說明；沒有說明就只寫標題、類別欄空著（`kind` 是 null）。
 */
export function withoutKind(title: string, kind: string, detail: string | null): { title: string; kind: string | null } {
  if (title === kind) return detail ? { title: detail, kind } : { title, kind: null }
  if (title.startsWith(kind)) return { title: title.slice(kind.length).trim() || title, kind }
  if (title.endsWith(kind)) return { title: title.slice(0, -kind.length).trim() || title, kind }
  return { title, kind }
}

/** 刻度尺的標籤在兩端時往內對齊（不超出版面）：靠左 0、置中 0.5、靠右 1 */
export const anchorOf = (pos: number): 0 | 0.5 | 1 => (pos < 0.08 ? 0 : pos > 0.92 ? 1 : 0.5)

/** 13px 標籤的大約寬度：中文與全形標點 1em、數字與英文約 0.6em、空白 0.3em */
function labelWidth(text: string): number {
  let em = 0
  for (const ch of text) em += /[⺀-￯]/.test(ch) ? 1 : ch === " " ? 0.3 : 0.6
  return em * 13
}

/** 刻度尺上的兩個標籤（位置 0–1）在寬 `width` px 的尺上會不會疊在一起（中間至少留 12px） */
export function labelsCollide(a: { pos: number; text: string }, b: { pos: number; text: string }, width: number): boolean {
  const range = ({ pos, text }: { pos: number; text: string }) => {
    const w = labelWidth(text)
    const x = pos * width - anchorOf(pos) * w
    return [x, x + w] as const
  }
  const [a1, a2] = range(a)
  const [b1, b2] = range(b)
  return a1 < b2 + 12 && b1 < a2 + 12
}
