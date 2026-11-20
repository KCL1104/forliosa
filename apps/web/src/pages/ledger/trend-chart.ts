import { useEffect, useLayoutEffect, useRef, useState } from "react"
import { direction, formatPercent } from "@/lib/format"

/** 總資產走勢（`HeroTrend.tsx`）用的尺寸與小工具。 */

export const TOP = 8
export const AXIS = 22
/** 資產組成：上面留給「估計」括線的高度、橫軸上股利記號那一列 */
export const COMP_TOP = 18
export const COMP_TICKS = 8
/** 滑過時離股利那一天幾 px 以內就對到那一天（股利記號只有 2px 寬） */
export const DIVIDEND_SNAP = 5
export const TICK_FONT = 12
/** 按住後橫向拖超過這麼多 px 才開始逐點看（直向照常捲動頁面） */
export const DRAG_SLOP = 8

/** 12px 的字大約多寬（估計，用來留縱軸刻度的空間） */
export function textWidth(s: string): number {
  let w = 0
  for (const ch of s) w += ch.charCodeAt(0) > 255 ? 12 : /[0-9]/.test(ch) ? 7 : /[.,\s/]/.test(ch) ? 3.6 : 7.6
  return Math.ceil(w)
}

export function useWidth(fallback: number): [React.RefObject<HTMLDivElement | null>, number] {
  const ref = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(fallback)
  // 第一次畫之前先量（不先用猜的寬度畫一次再跳）
  useLayoutEffect(() => {
    const w = Math.floor(ref.current?.clientWidth ?? 0)
    if (w > 0) setWidth(w)
  }, [])
  useEffect(() => {
    const el = ref.current
    if (!el || typeof ResizeObserver === "undefined") return
    const ro = new ResizeObserver(([entry]) => {
      const w = Math.floor(entry!.contentRect.width)
      if (w > 0) setWidth(w)
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  return [ref, width]
}

export const pctText = (r: number) => formatPercent(Math.abs(r), { signed: false, decimals: Math.abs(r) >= 0.1 ? 1 : 2 })

/** 給螢幕報讀器的報酬（不念 ▲▼） */
export function retSpeech(r: number | null): string {
  const d = direction(r)
  return r === null ? "算不出來" : d === "up" ? `上漲 ${pctText(r)}` : d === "down" ? `下跌 ${pctText(r)}` : "持平"
}

/** 一段折線：`idx` 是要畫的點（連續的位置） */
export function pathOf(idx: readonly number[], x: (i: number) => number, y: (i: number) => number): string {
  return idx.map((i, k) => `${k === 0 ? "M" : "L"}${x(i).toFixed(1)} ${y(i).toFixed(1)}`).join("")
}

/**
 * 總資產線（資產組成）：買進、賣出那一天和本金一起垂直跳——先斜到那一天買賣以前的值（`yPre`），再垂直到收盤（`y`）。
 * 沒有買賣的日子兩個值一樣，就是一般的折線。`idx` 是要畫的點（連續的位置）。
 */
export function flowPathOf(idx: readonly number[], x: (i: number) => number, y: (i: number) => number, yPre: (i: number) => number): string {
  return idx
    .map((i, k) => {
      const at = y(i).toFixed(1)
      if (k === 0) return `M${x(i).toFixed(1)} ${at}`
      const pre = yPre(i).toFixed(1)
      return `L${x(i).toFixed(1)} ${pre}${pre === at ? "" : `V${at}`}`
    })
    .join("")
}

export interface Box {
  x0: number
  y0: number
  x1: number
  y1: number
}

/** 線段 (ax, ay)–(bx, by) 有沒有碰到方框（四邊各往外 `pad`）：Liang–Barsky 裁切，碰到一點點也算 */
export function segmentHitsBox(ax: number, ay: number, bx: number, by: number, box: Box, pad: number): boolean {
  const x0 = box.x0 - pad
  const x1 = box.x1 + pad
  const y0 = box.y0 - pad
  const y1 = box.y1 + pad
  const dx = bx - ax
  const dy = by - ay
  let t0 = 0
  let t1 = 1
  for (const [p, q] of [[-dx, ax - x0], [dx, x1 - ax], [-dy, ay - y0], [dy, y1 - ay]] as const) {
    if (p === 0) {
      if (q < 0) return false
      continue
    }
    const t = q / p
    if (p < 0) t0 = Math.max(t0, t)
    else t1 = Math.min(t1, t)
    if (t0 > t1) return false
  }
  return true
}

/** a..b（含）的位置；b < a 是空的 */
export const indexes = (a: number, b: number) => (b < a ? [] : Array.from({ length: b - a + 1 }, (_, k) => a + k))
