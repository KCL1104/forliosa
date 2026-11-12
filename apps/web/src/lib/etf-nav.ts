import { formatNumber, formatPercent } from "@/lib/format"

/** 走勢要有這麼多個同一天的（收盤、淨值）才畫，和後端 `etf_nav.MIN_POINTS` 相同 */
export const NAV_MIN_POINTS = 20

/**
 * 折溢價的說法：收盤高於淨值是「溢價」、低於是「折價」，四捨五入到 0.00% 時是「平價」。
 * 折溢價不是價格漲跌：不用紅綠、不加 ▲▼，靠文字分辨。
 */
export function premiumParts(p: number | null | undefined): { word: "溢價" | "折價" | "平價"; value: string } | null {
  if (p === null || p === undefined || Number.isNaN(p)) return null
  const value = formatPercent(Math.abs(p), { signed: false })
  if (value === "0.00%") return { word: "平價", value }
  return { word: p > 0 ? "溢價" : "折價", value }
}

export function formatPremium(p: number | null | undefined): string {
  const parts = premiumParts(p)
  if (!parts) return "—"
  return parts.word === "平價" ? "平價" : `${parts.word} ${parts.value}`
}

/** 淨值照官方公布的位數：至少 2 位、最多 4 位小數（101.04、26.4989、10.50） */
export function formatNav(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—"
  const decimals = Math.min(4, Math.max(2, (String(n).split(".")[1] ?? "").length))
  return formatNumber(n, decimals)
}
