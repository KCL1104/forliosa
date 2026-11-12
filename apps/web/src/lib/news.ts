/**
 * 「新聞報導」的顯示規則（純函式）：
 * - `/news` 同時有官方公告與新聞報導；`category: "media"` 是新聞報導，其他是公告
 * - 每則顯示「媒體・N 小時前」，再來是原標題（連到原文、另開新視窗）；不放圖片、不放內文
 * - Yahoo股市 RSS 的標題要保留「Yahoo股市」與原始媒體（條款要求）
 * - 用到 GDELT 時，清單下方要引用 GDELT（使用條款要求連回 gdeltproject.org）
 */
import type { NewsItem } from "@/api/types"
import { formatDateShort } from "@/lib/format"

export const NEWS_PAGE_SIZE = 8
export const GDELT_URL = "https://www.gdeltproject.org/"

export function isMedia(n: NewsItem): boolean {
  return n.category === "media"
}

/** 官方公告（重大訊息、證交所新聞） */
export function officialNews(items: NewsItem[] | undefined): NewsItem[] {
  return (items ?? []).filter((n) => !isMedia(n))
}

/** 新聞報導，新的在前 */
export function mediaNews(items: NewsItem[] | undefined): NewsItem[] {
  return (items ?? []).filter(isMedia).sort((a, b) => Date.parse(b.published_at) - Date.parse(a.published_at))
}

/** 台北時區的日期（YYYY-MM-DD） */
function taipeiDate(d: Date): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Taipei", year: "numeric", month: "2-digit", day: "2-digit" }).format(d)
}

/** 「剛剛」「12 分鐘前」「3 小時前」「2 天前」；7 天以上或只有日期時顯示「11/3」 */
export function relativeTime(iso: string, now: Date, dateOnly = false): string {
  const t = new Date(iso)
  if (Number.isNaN(t.getTime())) return ""
  if (dateOnly) {
    const day = taipeiDate(t)
    return day === taipeiDate(now) ? "今天" : formatDateShort(day, false)
  }
  const minutes = Math.floor((now.getTime() - t.getTime()) / 60_000)
  if (minutes < 1) return "剛剛"
  if (minutes < 60) return `${minutes} 分鐘前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} 小時前`
  const days = Math.floor(hours / 24)
  if (days < 7) return `${days} 天前`
  return formatDateShort(taipeiDate(t), false)
}

/** 媒體名稱：Yahoo股市 RSS 保留原始媒體與「Yahoo股市」 */
export function outletLabel(n: NewsItem): string {
  const outlet = n.outlet?.trim() || n.source
  if (n.source === "Yahoo股市" && outlet !== "Yahoo股市") return `${outlet}（Yahoo股市）`
  return outlet
}

/** 清單下方的來源說明：用到哪些收集方式（GDELT 必須引用） */
export function newsSourcesUsed(items: NewsItem[]): { gdelt: boolean; others: string[] } {
  const set = new Set(items.map((n) => n.source))
  const others = ["AI 搜尋", "SearXNG", "Yahoo股市", "FinMind"].filter((s) => set.has(s))
  return { gdelt: set.has("GDELT"), others }
}
