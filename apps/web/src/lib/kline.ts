import type { Candle } from "@/api/types"

export type Interval = "d" | "w" | "m"

/** 日 K 聚合成週 K／月 K */
export function aggregate(candles: Candle[], interval: Interval): Candle[] {
  if (interval === "d") return candles
  const out: Candle[] = []
  const keyOf = (t: string) => {
    if (interval === "m") return t.slice(0, 7)
    const d = new Date(`${t}T00:00:00Z`)
    const monday = new Date(d)
    monday.setUTCDate(d.getUTCDate() - ((d.getUTCDay() + 6) % 7))
    return monday.toISOString().slice(0, 10)
  }
  let cur: Candle | null = null
  let key = ""
  for (const c of candles) {
    const k = keyOf(c.t)
    if (!cur || k !== key) {
      if (cur) out.push(cur)
      cur = { ...c }
      key = k
    } else {
      cur.h = Math.max(cur.h, c.h)
      cur.l = Math.min(cur.l, c.l)
      cur.c = c.c
      cur.v += c.v
    }
  }
  if (cur) out.push(cur)
  return out
}
