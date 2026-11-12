import { useEffect, useRef, useState } from "react"

/**
 * 時間軸的月份刻度（估值河流圖、殖利率走勢）：每個月第一個資料點當刻度，放不下時每 2／3／6／12 個月一個，
 * 而且對齊日曆（每 3 個月＝1、4、7、10 月；每 6 個月＝1、7 月；每 12 個月＝每年 1 月），
 * 所以不會像 recharts 依間距自動挑選那樣不規則地跳過某個月，也不會在同一個月出現兩個一樣的標籤。
 * 只有一個月的資料時，用頭尾兩天（11/3、11/28）。
 */
export function monthTicks(dates: readonly string[], maxLabels: number): { ticks: string[]; format: (t: string) => string } {
  const firsts: string[] = []
  let prev = ""
  for (const d of dates) {
    const ym = d.slice(0, 7)
    if (ym !== prev) {
      firsts.push(d)
      prev = ym
    }
  }
  if (firsts.length < 2) {
    const ends = dates.length ? [...new Set([dates[0]!, dates.at(-1)!])] : []
    return { ticks: ends, format: (t) => `${Number(t.slice(5, 7))}/${Number(t.slice(8, 10))}` }
  }
  const room = Math.max(2, maxLabels)
  const step = [1, 2, 3, 6, 12, 24].find((s) => firsts.filter((d) => monthIndex(d) % s === 0).length <= room) ?? 24
  const ticks = firsts.filter((d) => monthIndex(d) % step === 0)
  const format = step >= 12 ? (t: string) => t.slice(0, 4) : (t: string) => t.slice(0, 7).replace("-", "/")
  return { ticks, format }
}

/** 從西元 0 年 1 月起算的月數：讓「每 N 個月」對齊 1 月 */
function monthIndex(d: string): number {
  return Number(d.slice(0, 4)) * 12 + Number(d.slice(5, 7)) - 1
}

/** 圖表容器的寬度（ResizeObserver）；量不到時是 0 */
export function useWidth<T extends HTMLElement>() {
  const ref = useRef<T | null>(null)
  const [width, setWidth] = useState(0)
  useEffect(() => {
    const el = ref.current
    if (!el || typeof ResizeObserver !== "function") return
    const ro = new ResizeObserver(([entry]) => setWidth(Math.round(entry!.contentRect.width)))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  return [ref, width] as const
}

/** 一個「2026/09」標籤大約要這麼寬（12px 字＋間距） */
export const MONTH_LABEL_WIDTH = 76
