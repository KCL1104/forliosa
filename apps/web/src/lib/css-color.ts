/**
 * 把 CSS 變數（oklch 等）轉成 canvas 圖表庫能吃的 rgba 字串。
 * lightweight-charts 會自行解析顏色，不支援 oklch，所以用 1×1 canvas 取樣。
 */
let ctx: CanvasRenderingContext2D | null = null

export function cssVarColor(name: string, alpha = 1, el: Element = document.documentElement): string {
  const raw = getComputedStyle(el).getPropertyValue(name).trim()
  if (!raw) return `rgba(0,0,0,${alpha})`
  if (!ctx) {
    const c = document.createElement("canvas")
    c.width = c.height = 1
    ctx = c.getContext("2d", { willReadFrequently: true })
  }
  if (!ctx) return raw
  ctx.clearRect(0, 0, 1, 1)
  ctx.fillStyle = "#000"
  ctx.fillStyle = raw
  ctx.fillRect(0, 0, 1, 1)
  const [r, g, b] = ctx.getImageData(0, 0, 1, 1).data
  return `rgba(${r},${g},${b},${alpha})`
}
