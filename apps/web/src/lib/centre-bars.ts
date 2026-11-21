import { direction, type Direction } from "@/lib/format"

/** 中線橫條（`components/centre-bars.tsx`）的一條：往哪邊、佔半邊軌道的幾成 */
export interface CentreBar {
  side: Direction
  /** 0–1：這一條的長度 ÷ 半邊軌道；最大的絕對值是 1，持平（0）是 0 */
  share: number
}

/**
 * 以中線為 0 的雙向橫條怎麼量：所有列共用一個比例——最大的絕對值佔滿半邊，其他照比例。
 * 中線固定在正中間：全部上漲的日子橫條都在右半邊、全部下跌都在左半邊，位置本身就說了方向。
 * 全部是 0（或沒有數字）時每一條都是 0，不會除以 0。
 *
 * `scale`：一份清單分成幾欄、每欄各畫一張時，傳整份清單最大的絕對值，各欄的橫條才用同一個比例
 * （市場頁的類股分兩、三欄）。比這幾列自己最大的絕對值小時不用它（橫條不會超出半邊）。
 */
export function centreBars(values: readonly number[], scale?: number): CentreBar[] {
  let max = scale !== undefined && Number.isFinite(scale) ? Math.abs(scale) : 0
  for (const v of values) if (Number.isFinite(v) && Math.abs(v) > max) max = Math.abs(v)
  return values.map((v) => {
    const side = Number.isFinite(v) ? direction(v) : "flat"
    return { side, share: side === "flat" || max === 0 ? 0 : Math.abs(v) / max }
  })
}
