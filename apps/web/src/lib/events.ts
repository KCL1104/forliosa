/**
 * 個股事件與官方公告的顯示規則（總覽與事件分頁共用，純函式）。
 * - `earnings` 是財報公布、`investor_conference` 是法說會（日期是開會當天）
 * - `estimated: true` 只有法定期限的備援：標題去掉「（預估）」，改用「預估」標記
 * - `/news` 現在是官方公告（重大訊息、證交所新聞）；事件裡的 `material_info` 和公告的重大訊息是同一則，合併時去重
 * - 美股的 `sec_filing` 是 SEC 的 8-K／10-Q／10-K（`form`），標題已含表單名稱，連到 sec.gov 原文
 */
import type { InstrumentEvent, NewsCategory, NewsItem } from "@/api/types"

export const EVENT_LABEL: Record<string, string> = {
  ex_dividend: "除息",
  dividend_payment: "股利發放",
  earnings: "財報",
  revenue_release: "營收",
  investor_conference: "法說會",
  material_info: "公告",
  announcement: "公告",
  attention: "注意股",
  disposition: "處置",
  shareholder_meeting: "股東會",
  sec_filing: "SEC 申報",
  trade: "我的交易",
}

/** 美股 SEC 申報的表單名稱（`/A` 是修正版） */
const FORM_LABEL: Record<string, string> = { "10-K": "年報", "10-Q": "季報", "8-K": "重大事件" }

/** 時間軸左欄的類型名稱：SEC 申報依表單（10-K 年報、10-Q 季報、8-K 重大事件），其他依事件類型 */
export function eventLabel(e: { type: string; form?: string | null }): string {
  if (e.type === "sec_filing" && e.form) {
    const amended = e.form.endsWith("/A")
    const base = FORM_LABEL[e.form.replace(/\/A$/, "")]
    if (base) return amended ? `${base}修正` : base
  }
  return EVENT_LABEL[e.type] ?? e.type
}

export const NEWS_CATEGORY_LABEL: Record<NewsCategory, string> = {
  material_info: "重大訊息",
  exchange_news: "證交所公告",
  media: "媒體",
}

/** 公告的發布機關（給「在…查看」的連結說明） */
export function announcementHost(url: string): string {
  if (url.includes("mops.twse.com.tw")) return "公開資訊觀測站"
  if (url.includes("tpex.org.tw")) return "櫃買中心"
  if (url.includes("twse.com.tw")) return "證交所"
  if (url.includes("sec.gov")) return "SEC EDGAR"
  try {
    return new URL(url).hostname.replace(/^www\./, "")
  } catch {
    return "原文"
  }
}

/** 標題去掉「（預估）」：預估改用標記表示 */
export function eventTitle(e: Pick<InstrumentEvent, "title" | "estimated">): string {
  return e.estimated ? e.title.replace(/（預估）$/, "").trim() : e.title
}

export interface TimelineRow extends Omit<InstrumentEvent, "type"> {
  type: InstrumentEvent["type"] | "announcement" | "trade"
  /** 公告的分類（重大訊息、證交所公告、媒體） */
  category?: NewsCategory
}

/**
 * 事件＋公告合併成一條時間軸：公告的重大訊息若已經是事件（同日同標題），把公告的連結補到事件上；
 * 其餘公告（證交所公告、沒被判讀成事件的重大訊息）各成一列。
 */
export function mergeAnnouncements(events: InstrumentEvent[], news: NewsItem[]): TimelineRow[] {
  const rows: TimelineRow[] = events.map((e) => ({ ...e, category: e.type === "material_info" ? "material_info" : undefined }))
  for (const n of news) {
    const date = n.published_at.slice(0, 10)
    const same = rows.find((r) => r.date === date && r.title.trim() === n.title.trim())
    if (same) {
      same.url = same.url ?? n.url
      same.category = n.category ?? same.category
      continue
    }
    rows.push({
      date,
      type: "announcement",
      title: n.title,
      detail: null,
      url: n.url,
      mine: false,
      amount_estimate: null,
      category: n.category ?? "material_info",
      sources: n.sources,
    })
  }
  return rows
}
